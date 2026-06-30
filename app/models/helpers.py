# =============================================================================
# D. HELPERS
# =============================================================================
from typing import List, Optional
from sqlmodel import Session, select
from app.database import get_session
from app.schemas.Maintennance import (AncestorNode, DescendantNode, FaultType, FaultyEntityStatus)
from app.models.tables import FaultyEntity,MaintenanceCase, Component, Unit, Module, Subsystem, System, Project, Order, Customer
from app.models.base import( EntityType )
from datetime import datetime, timezone


def _get_label(session: Session, entity_type: str, entity_id: int) -> Optional[dict]:
    """Return the human-readable label for any entity."""
    entry = _ENTITY_MODEL_MAP.get(entity_type)
    if not entry:
        return None
    model_cls, _, label_attr = entry
    row = session.get(model_cls, entity_id)
    # print("------------_get_label---------------", row, label_attr)
    if not row or not label_attr:
        return None
    if entity_type != EntityType.CUSTOMER and entity_type != EntityType.ORDER:
        return {
            "part_number": str(getattr(row, label_attr, None)),
            "entity_name": str(getattr(row, "name", None)),
            "serial_number": str(getattr(row, "id", None) if entity_type == EntityType.PROJECT else str(getattr(row, "serial_number", None))),
            }
    elif entity_type == EntityType.CUSTOMER:
        return {
            "part_number": str(getattr(row, "id", None)),
            "entity_name": str(getattr(row, "name", None)),
            "serial_number": str(getattr(row, "id", None)),
            }
    elif entity_type == EntityType.ORDER:
        return {
            "part_number": str(getattr(row, "id", None)),
            "entity_name": str(getattr(row, "order_number", None)),
            "serial_number": str(getattr(row, "id", None)),
            }
    else:
        return {
                "part_number": "default",
                "entity_name": "default",
                "serial_number": "default",
                }

def _resolve_ancestors(session: Session, entity_type: str,entity_id: int) -> List[AncestorNode]:
    """
    Walk UP _EXTENDED_PARENT_MAP from (entity_type, entity_id) until the
    chain ends (Customer or unknown type).  Returns ancestors ordered from
    the direct parent of the given entity up to Customer.
    """
    ancestors: List[AncestorNode] = []
    current_type = entity_type
    current_id   = entity_id

    while current_type in _EXTENDED_PARENT_MAP:

        parent_type, model_cls, fk_attr = _EXTENDED_PARENT_MAP[current_type]
        row = session.get(model_cls, current_id)
        if not row:
            break
        parent_id = getattr(row, fk_attr, None)
        if parent_id is None:
            break
        info:dict = _get_label(session, parent_type, parent_id)
        print("------------info---------------", parent_type, info)

        ancestors.append(
            AncestorNode(entity_type=parent_type, entity_id=parent_id, entity_name = info["entity_name"], entity_PartNumber=info["part_number"], entity_SerialNumber=info["serial_number"])
        )
        current_type = parent_type
        current_id   = parent_id

    return ancestors

def _collect_descendants(
    session:     Session,
    entity_type: str,
    entity_id:   int,
    depth:       int = 0,
) -> List[DescendantNode]:
    """
    Recursively walk DOWN _CHILD_MAP and collect every descendant entity.
    Returns a flat list ordered breadth-first (parent before children).
    """
    result: List[DescendantNode] = []
    if entity_type not in _CHILD_MAP:
        return result                          # leaf node — no children

    child_type, child_model, fk_attr = _CHILD_MAP[entity_type]
# EntityType.UNIT:      (EntityType.COMPONENT, Component, "unit_id"),

    # Query all children whose FK matches entity_id
    children = session.exec(
        select(child_model).where(getattr(child_model, fk_attr) == entity_id)
    ).all()

    for child in children:
        child_id = child.id
        child_info = _get_label(session, child_type, child_id)
        parent_info = _get_label(session, entity_type, entity_id)
        result.append(
            DescendantNode(
                entity_type=child_type,
                entity_id=child_id,
                entity_name=child_info["entity_name"],
                entity_PartNumber=child_info["part_number"],
                entity_SerialNumber=child_info["serial_number"],
                parent_ID=entity_id,
                parent_type=entity_type,
                parent_name=parent_info["entity_name"] if parent_info else None,
                depth=depth + 1,
            )
        )
        # Recurse into grandchildren
        result.extend(_collect_descendants(session, child_type, child_id, depth + 1))

    return result

def _create_suspect_fes(
    session:              Session,
    case_id:              int,
    descendants:          List[DescendantNode],
    fault_type:           FaultType,
    parent_faulty_entity_id: int,
    identified_by:        Optional[int],
) -> List[FaultyEntity]:
    """
    Bulk-create one FaultyEntity per descendant with status=UNDER_INSPECTION.
    All rows are linked to parent_faulty_entity_id (the mid-hierarchy FE row).
    Returns the created rows.
    """
    created: List[FaultyEntity] = []

    for desc in descendants:
        fe = FaultyEntity(
            case_id=case_id,
            entity_type=desc.entity_type,
            entity_id=desc.entity_id,
            entity_name= desc.entity_name,
            part_number = desc.entity_PartNumber,
            serial_number= desc.entity_SerialNumber,
            fault_type=fault_type,
            status=FaultyEntityStatus.UNDER_INSPECTION,
            fault_description=f"Suspected — under inspection (parent hierarchy flagged)",
            identified_by=identified_by,
            parent_faulty_entity_id=parent_faulty_entity_id,
            parent_entity_id=desc.parent_ID, 
            parent_entity_type=desc.parent_type,
            depth = desc.depth,

        )
        session.add(fe)
        created.append(fe)
    session.flush()    # assign IDs
    return created

def _clear_healthy_fes(
    session:                  Session,
    case_id:                  int,
    parent_faulty_entity_id:  int,
    confirmed_entity_type:    EntityType,
    confirmed_entity_id:      int,
) -> int:
    """
    After the engineer confirms the exact faulty entity, delete all provisional
    UNDER_INSPECTION faulty-entity rows that belong to sibling subtrees under
    the same parent_faulty_entity_id — EXCEPT the confirmed entity and its
    own ancestors (which should already be CONFIRMED_FAULTY or IDENTIFIED).

    Returns the count of deleted rows.
    """
    # Fetch every UNDER_INSPECTION row under this parent FE
    suspects: List[FaultyEntity] = session.exec(
        select(FaultyEntity).where(
            FaultyEntity.case_id == case_id,
            FaultyEntity.parent_faulty_entity_id == parent_faulty_entity_id,
            FaultyEntity.status == FaultyEntityStatus.UNDER_INSPECTION,
        )
    ).all()

    # Collect the IDs of the confirmed entity and ALL of its descendants
    # (they may have been created as suspects too).
    confirmed_subtree_ids: set = {confirmed_entity_id}
    _collect_confirmed_descendant_ids(
        session, confirmed_entity_type, confirmed_entity_id, confirmed_subtree_ids
    )

    deleted = 0
    for fe in suspects:
        # Keep the row only if this entity is the confirmed fault or its child
        if fe.entity_id in confirmed_subtree_ids and fe.entity_type == confirmed_entity_type:
            # This is the confirmed entity's own suspect row — upgrade it
            fe.status = FaultyEntityStatus.CONFIRMED_FAULTY
            session.add(fe)
            continue

        # Everything else: remove from the database (no history kept)
        if fe.actions:
            # Safety guard: if an action was already logged here, don't delete
            fe.status = FaultyEntityStatus.NO_FAULT_FOUND
            session.add(fe)
        else:
            session.delete(fe)
            deleted += 1

    session.flush()
    return deleted

def _collect_confirmed_descendant_ids(
    session:     Session,
    entity_type: str,
    entity_id:   int,
    id_set:      set,
) -> None:
    """Recursively gather entity_ids of the confirmed entity's subtree."""
    if entity_type not in _CHILD_MAP:
        return
    child_type, child_model, fk_attr = _CHILD_MAP[entity_type]
    children = session.exec(
        select(child_model).where(getattr(child_model, fk_attr) == entity_id)
    ).all()
    for child in children:
        id_set.add(child.id)
        _collect_confirmed_descendant_ids(session, child_type, child.id, id_set)


# =============================================================================
# CASCADE FAULT HELPER
# =============================================================================
# Entity type → (parent entity type, SQLModel class, FK attribute name)
# Used by the cascade endpoint to walk the hierarchy upward.
# =============================================================================


_PARENT_MAP: dict = {
    EntityType.COMPONENT: (EntityType.UNIT,      Component, "unit_id"),
    EntityType.UNIT:      (EntityType.MODULE,    Unit,       "module_id"),
    EntityType.MODULE:    (EntityType.SUBSYSTEM, Module,     "subsystem_id"),
    EntityType.SUBSYSTEM: (EntityType.SYSTEM,    Subsystem,  "system_id"),
    EntityType.SYSTEM:    (EntityType.PROJECT,   System,     "project_id"),
    EntityType.PROJECT:   (EntityType.ORDER,     Project,     "order_id"),
    EntityType.ORDER:     (EntityType.CUSTOMER,  Order,       "customer_id"),
}

def _cascade_fault_up(
    session:          Session,
    case_id:          int,
    root_entity_type: EntityType,
    root_entity_id:   int,
    fault_type:       FaultType,
    fault_description: Optional[str],
    identified_by:    Optional[int],
) -> List[FaultyEntity]:
    """
    Starting from root_entity, walk UP _PARENT_MAP and create one
    FaultyEntity per ancestor level. Returns all created rows (root first).
    The parent_faulty_entity_id chain is set so the tree is queryable.
    """
    created: List[FaultyEntity] = []
    current_type = root_entity_type
    current_id   = root_entity_id
    parent_fe_id: Optional[int] = None

    while True:
        is_root = (len(created) == 0)
        fe = FaultyEntity(
            case_id=case_id,
            entity_type=current_type,
            entity_id=current_id,
            fault_type=fault_type,
            fault_description=(
                fault_description if is_root
                else f"Cascaded from {root_entity_type} id={root_entity_id}"
            ),
            status=(
                FaultyEntityStatus.CONFIRMED_FAULTY if is_root
                else FaultyEntityStatus.IDENTIFIED
            ),
            parent_faulty_entity_id=parent_fe_id,
            identified_by=identified_by,
        )
        session.add(fe)
        session.flush()               # populate fe.id before next iteration
        created.append(fe)
        parent_fe_id = fe.id

        if current_type not in _PARENT_MAP:
            break                     # reached the top of the hierarchy
        parent_type, model_cls, fk_attr = _PARENT_MAP[current_type]
        row = session.get(model_cls, current_id)
        if not row:
            break                     # parent entity not found — stop cascade
        current_id   = getattr(row, fk_attr)
        current_type = parent_type

    session.commit()
    return created

# =============================================================================
# C. CHILD MAP  (mirrors _PARENT_MAP downward)
# =============================================================================
# Maps entity_type  →  (child entity_type, SQLModel class, FK attr on child)
#
# Example: a MODULE has many UNITs; Unit.module_id is the FK.
# Adapt the FK attribute names to your actual model definitions.

from typing import Dict, Tuple, Any

_CHILD_MAP: Dict[str, Tuple[str, Any, str]] = {
    EntityType.SYSTEM:    (EntityType.SUBSYSTEM, Subsystem, "system_id"),
    EntityType.SUBSYSTEM: (EntityType.MODULE,    Module,    "subsystem_id"),
    EntityType.MODULE:    (EntityType.UNIT,      Unit,      "module_id"),
    EntityType.UNIT:      (EntityType.COMPONENT, Component, "unit_id"),
    # but typically a project-level fault wouldn't trigger suspect-children.
    EntityType.PROJECT:   (EntityType.SYSTEM,    System,    "project_id"),
}

# Map each entity type to its SQLModel class and the attribute used as its
# human-readable label (name, part_number, serial_number, etc.).  Adjust to your schema.
_ENTITY_MODEL_MAP: Dict[str, Tuple[Any, str, Optional[str]]] = {
    # (SQLModelClass, pk_attr, label_attr)
    EntityType.COMPONENT: (Component, "id", "part_number"),
    EntityType.UNIT:      (Unit,      "id", "part_number"),
    EntityType.MODULE:    (Module,    "id", "part_number"),
    EntityType.SUBSYSTEM: (Subsystem, "id", "part_number"),
    EntityType.SYSTEM:    (System,    "id", "part_number"),
    EntityType.PROJECT:   (Project,   "id", "name"),
    EntityType.ORDER:     (Order,     "id", "order_number"),
    EntityType.CUSTOMER:  (Customer,  "id", "name"),
}

# Parent map extended upward beyond Project (Project → Order → Customer).
# Add your actual FK attribute names.
_EXTENDED_PARENT_MAP: Dict[str, Tuple[str, Any, str]] = {
    **_PARENT_MAP,
    EntityType.PROJECT:  (EntityType.ORDER,    Project,     "order_id"),
    EntityType.ORDER:    (EntityType.CUSTOMER, Order, "customer_id"),
}

# SR/part-number lookup:  maps entity_type → (SQLModelClass, PN_attr)
# A single SRU must be unique within each entity type (enforced by your schema).
_SR_SEARCH_MODELS: List[Tuple[str, Any, str]] = [
    (EntityType.COMPONENT, Component, "part_number"),
    (EntityType.UNIT,      Unit,      "part_number"),
    (EntityType.MODULE,    Module,    "part_number"),
    (EntityType.SUBSYSTEM, Subsystem, "part_number"),
    (EntityType.SYSTEM,    System,    "part_number"),
    # Add more if Project / Order also carry part numbers.
]


# =============================================================================
# HELPER — Case Number Generator
# =============================================================================

def _generate_case_number(session: Session) -> str:
    """
    Produces sequential, year-scoped case numbers: MC-2024-0001
    Guaranteed unique within the year by counting existing cases.
    """
    year = datetime.now(timezone.utc).year
    prefix = f"MC-{year}-"

    latest_case = session.exec(select(MaintenanceCase).order_by(MaintenanceCase.id.desc())).first()
    if latest_case:
        next_id = latest_case.id + 1
    else:
        next_id = 1

    case_number = f"MC-{year}-{next_id:04d}"

    return case_number

year = datetime.now(timezone.utc).year

from app.models.tables import * 
ENTITY_PREFIXES = {
    
    Customer: "CUST",
    Order: f"ORD-{year}",
    Project: "PROJ",
    MaintenanceCase: "MC",
    System: "SYS",
    Subsystem: "SUB",
    Module: "MOD",
    Unit: "UNIT",
    Component: "COMP",
}

# # ====================================
def _generate_Entity_Code(session: Session, model) -> str:
    """
    Produces sequential, year-scoped case numbers: MC-2024-0001
    Guaranteed unique within the year by counting existing cases.
    """
    prefix = ENTITY_PREFIXES[model]
    print("prefix",prefix)

    latest_case = session.exec(select(model).order_by(model.id.desc())).first()
    print("latest_case",latest_case)
    if latest_case:
        entity_code = latest_case.id + 1
    else:
        entity_code = 1

    return f"{prefix}-{entity_code:03d}"