"""
Spec 04 — reserve AVAILABLE inventory against Flight → SDLS → hierarchy nodes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, NoReturn, Optional

from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.base import InventoryReservationStatus
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import (
    Flight,
    Inventory,
    InventoryInstance,
    InventoryReservation,
    Module,
    Project,
    Sdls,
    Status,
    Subsystem,
    System,
    Unit,
    User,
)
from app.services.inventory_issuance_service import (
    open_issuance_for_instance,
)
from app.services.inventory_service import (
    find_inventory_group,
    is_component_inventory,
)
from app.services.project_workflow_service import project_status_name

DEFAULT_RESERVATION_DAYS = 30

RESERVABLE_ENTITY_TYPES = frozenset(
    {"system", "subsystem", "module", "unit", "component"}
)


class InventoryReservationError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_item_status_id(session: Session, status_name: str) -> int:
    status = session.exec(
        select(Status).where(
            Status.status_name == status_name,
            Status.status_type == "inventory",
        )
    ).first()
    if not status or status.id is None:
        raise InventoryReservationError(
            f"Required inventory status '{status_name}' is not seeded"
        )
    return int(status.id)


def item_status_name(session: Session, status_id: Optional[int]) -> Optional[str]:
    if status_id is None:
        return None
    status = session.get(Status, status_id)
    return status.status_name if status else None


def assert_project_can_reserve(project: Project) -> None:
    status = project_status_name(project)
    if status != ProjectWorkflowStatus.READY_FOR_INVENTORY.value:
        raise InventoryReservationError(
            "Project must be READY_FOR_INVENTORY to reserve inventory "
            f"(current: {status or 'unknown'})"
        )


def active_reservation_for_instance(
    session: Session, instance_id: int
) -> Optional[InventoryReservation]:
    return session.exec(
        select(InventoryReservation).where(
            InventoryReservation.inventory_instance_id == instance_id,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()


def active_reservations_for_inventory(
    session: Session, inventory_id: int
) -> list[InventoryReservation]:
    return list(
        session.exec(
            select(InventoryReservation).where(
                InventoryReservation.inventory_id == inventory_id,
                InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
            )
        ).all()
    )


def project_reserved_quantity(session: Session, inventory_id: int) -> int:
    """Count of active Spec 04 reservations for an inventory group."""
    rows = active_reservations_for_inventory(session, inventory_id)
    return len(rows)


def is_instance_free_for_project_reserve(
    session: Session, instance: InventoryInstance
) -> bool:
    if instance.id is None:
        return False
    if active_reservation_for_instance(session, int(instance.id)):
        return False
    if open_issuance_for_instance(session, int(instance.id)):
        return False
    current = item_status_name(session, instance.status_id)
    if current in {
        ItemStatus.RESERVED.value,
        ItemStatus.ISSUED.value,
        ItemStatus.INSTALLATION_IN_PROGRESS.value,
        ItemStatus.UNDER_TESTING_REVIEW.value,
        ItemStatus.INSTALLED_VERIFIED.value,
        ItemStatus.SCRAPPED.value,
    }:
        return False
    return True


def _load_hierarchy_entity(
    session: Session, entity_type: str, entity_id: int
) -> Any:
    key = entity_type.strip().lower()
    entry = _ENTITY_MODEL_MAP.get(key)
    if not entry:
        raise InventoryReservationError(f"Unsupported entity type: {entity_type}")
    model, _pk, _label = entry
    entity = session.get(model, entity_id)
    if not entity:
        raise InventoryReservationError(
            f"{entity_type} {entity_id} not found"
        )
    return entity


def _resolve_flight_sdls_for_entity(
    session: Session, entity_type: str, entity: Any
) -> tuple[Flight, Sdls, System]:
    """Walk hierarchy up to System → SDLS → Flight."""
    et = entity_type.strip().lower()
    system: Optional[System] = None

    if et == "system":
        system = entity
    elif et == "subsystem":
        system = session.get(System, entity.system_id)
    elif et == "module":
        sub = session.get(Subsystem, entity.subsystem_id)
        if not sub:
            raise InventoryReservationError("Subsystem parent not found")
        system = session.get(System, sub.system_id)
    elif et == "unit":
        mod = session.get(Module, entity.module_id)
        if not mod:
            raise InventoryReservationError("Module parent not found")
        sub = session.get(Subsystem, mod.subsystem_id)
        if not sub:
            raise InventoryReservationError("Subsystem parent not found")
        system = session.get(System, sub.system_id)
    elif et == "component":
        unit = session.get(Unit, entity.unit_id)
        if not unit:
            raise InventoryReservationError("Unit parent not found")
        mod = session.get(Module, unit.module_id)
        if not mod:
            raise InventoryReservationError("Module parent not found")
        sub = session.get(Subsystem, mod.subsystem_id)
        if not sub:
            raise InventoryReservationError("Subsystem parent not found")
        system = session.get(System, sub.system_id)
    else:
        raise InventoryReservationError(f"Unsupported entity type: {entity_type}")

    if not system:
        raise InventoryReservationError("Could not resolve System parent")
    if not system.sdls_id:
        raise InventoryReservationError(
            "Hierarchy entity is not linked to an SDLS (generate hierarchy first)"
        )
    sdls = session.get(Sdls, system.sdls_id)
    if not sdls:
        raise InventoryReservationError("SDLS not found for hierarchy entity")
    flight = session.get(Flight, sdls.flight_id)
    if not flight:
        raise InventoryReservationError("Flight not found for hierarchy entity")
    return flight, sdls, system


def resolve_inventory_for_entity(
    session: Session,
    *,
    entity_type: str,
    entity: Any,
    part_number: Optional[str] = None,
) -> Inventory:
    name = getattr(entity, "name", None) or ""
    pn = part_number
    if pn is None:
        pn = getattr(entity, "part_number", None)
    group = find_inventory_group(
        session,
        name=str(name),
        inventory_type=entity_type.strip().lower(),
        part_number=pn,
    )
    if not group:
        # Fallback: match by name+type ignoring empty PN on stock that has PN
        group = session.exec(
            select(Inventory).where(
                Inventory.inventory_type == entity_type.strip().lower(),
                col(Inventory.name).ilike(str(name).strip()),
            )
        ).first()
    if not group:
        raise InventoryReservationError(
            f"No inventory stock found for {entity_type} '{name}'"
            + (f" (PN {pn})" if pn else "")
        )
    return group


def pick_free_instance(
    session: Session,
    inventory: Inventory,
    *,
    serial_number: Optional[str] = None,
    instance_id: Optional[int] = None,
) -> Optional[InventoryInstance]:
    if is_component_inventory(inventory.inventory_type):
        return None

    if instance_id is not None:
        inst = session.get(InventoryInstance, instance_id)
        if not inst or inst.inventory_id != inventory.id:
            raise InventoryReservationError("Inventory instance not found in group")
        if not is_instance_free_for_project_reserve(session, inst):
            raise InventoryReservationError(
                "Inventory instance is not available for reservation"
            )
        if serial_number and (inst.serial_number or "").strip().lower() != serial_number.strip().lower():
            raise InventoryReservationError("Serial number does not match instance")
        return inst

    instances = list(
        session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == inventory.id
            )
        ).all()
    )
    if serial_number:
        sn = serial_number.strip().lower()
        match = next(
            (i for i in instances if (i.serial_number or "").strip().lower() == sn),
            None,
        )
        if not match:
            raise InventoryReservationError(
                f"Serial '{serial_number}' not found in inventory"
            )
        if not is_instance_free_for_project_reserve(session, match):
            raise InventoryReservationError(
                f"Serial '{serial_number}' is not available for reservation"
            )
        return match

    for inst in instances:
        if is_instance_free_for_project_reserve(session, inst):
            return inst
    return None


def check_availability(
    session: Session,
    *,
    project_id: int,
    target_entity_type: str,
    target_entity_id: int,
    part_number: Optional[str] = None,
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise InventoryReservationError("Project not found")
    assert_project_can_reserve(project)

    et = target_entity_type.strip().lower()
    if et not in RESERVABLE_ENTITY_TYPES:
        raise InventoryReservationError(f"Unsupported target entity type: {et}")

    entity = _load_hierarchy_entity(session, et, target_entity_id)
    if et == "system" and getattr(entity, "project_id", None) != project_id:
        raise InventoryReservationError("System does not belong to this project")

    flight, sdls, system = _resolve_flight_sdls_for_entity(session, et, entity)
    if flight.project_id != project_id:
        raise InventoryReservationError("Hierarchy entity is not under this project")

    # Prevent double-reserve of same hierarchy node
    existing = session.exec(
        select(InventoryReservation).where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == target_entity_id,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()
    if existing:
        return {
            "available": False,
            "reason": "Hierarchy node already has an active reservation",
            "reservation_id": existing.id,
            "flight_id": flight.id,
            "sdls_id": sdls.id,
            "system_id": system.id,
        }

    inventory = resolve_inventory_for_entity(
        session, entity_type=et, entity=entity, part_number=part_number
    )

    if is_component_inventory(inventory.inventory_type):
        from app.services.inventory_issuance_service import reserved_quantity

        free = max(
            0,
            int(inventory.quantity or 0)
            - reserved_quantity(session, int(inventory.id))
            - project_reserved_quantity(session, int(inventory.id)),
        )
        return {
            "available": free >= 1,
            "free_quantity": free,
            "inventory_id": inventory.id,
            "inventory_name": inventory.name,
            "part_number": inventory.part_number,
            "flight_id": flight.id,
            "sdls_id": sdls.id,
            "system_id": system.id,
            "reason": None if free >= 1 else "No available quantity in stock",
        }

    free_instances = [
        i
        for i in session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == inventory.id
            )
        ).all()
        if is_instance_free_for_project_reserve(session, i)
    ]
    return {
        "available": len(free_instances) >= 1,
        "free_quantity": len(free_instances),
        "inventory_id": inventory.id,
        "inventory_name": inventory.name,
        "part_number": inventory.part_number,
        "serial_numbers": [i.serial_number for i in free_instances if i.serial_number],
        "flight_id": flight.id,
        "sdls_id": sdls.id,
        "system_id": system.id,
        "reason": None if free_instances else "No available serialized units in stock",
    }


def _raise_or_record_shortage(
    session: Session,
    *,
    create_shortage: bool,
    project: Project,
    flight: Flight,
    sdls: Sdls,
    entity: Any,
    entity_type: str,
    entity_id: int,
    actor: User,
    inventory: Optional[Inventory],
    message: str,
) -> NoReturn:
    if not create_shortage:
        raise InventoryReservationError(message)
    from app.services.inventory_shortage_service import (
        InventoryShortageCreated,
        record_shortage_for_reserve,
    )

    shortage = record_shortage_for_reserve(
        session,
        project=project,
        flight=flight,
        sdls=sdls,
        entity=entity,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        inventory=inventory,
    )
    raise InventoryShortageCreated(shortage, message)


def reserve_inventory(
    session: Session,
    project_id: int,
    payload: dict[str, Any],
    *,
    actor: User,
    create_shortage_if_unavailable: bool = True,
) -> InventoryReservation:
    project = session.get(Project, project_id)
    if not project:
        raise InventoryReservationError("Project not found")
    assert_project_can_reserve(project)

    et = str(payload.get("target_entity_type") or "").strip().lower()
    try:
        eid = int(payload["target_entity_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InventoryReservationError(
            "target_entity_type and target_entity_id are required"
        ) from exc
    if et not in RESERVABLE_ENTITY_TYPES:
        raise InventoryReservationError(f"Unsupported target entity type: {et}")

    entity = _load_hierarchy_entity(session, et, eid)
    flight, sdls, system = _resolve_flight_sdls_for_entity(session, et, entity)
    if flight.project_id != project_id:
        raise InventoryReservationError("Hierarchy entity is not under this project")

    # Optional explicit flight/sdls must match resolved
    if payload.get("flight_id") is not None and int(payload["flight_id"]) != flight.id:
        raise InventoryReservationError("flight_id does not match hierarchy entity")
    if payload.get("sdls_id") is not None and int(payload["sdls_id"]) != sdls.id:
        raise InventoryReservationError("sdls_id does not match hierarchy entity")

    existing_node = session.exec(
        select(InventoryReservation).where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == eid,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()
    if existing_node:
        raise InventoryReservationError(
            "Hierarchy node already has an active reservation"
        )

    part_number = payload.get("part_number")
    inventory: Optional[Inventory] = None
    if payload.get("inventory_id"):
        inventory = session.get(Inventory, int(payload["inventory_id"]))
        if not inventory:
            raise InventoryReservationError("Inventory not found")
    else:
        try:
            inventory = resolve_inventory_for_entity(
                session, entity_type=et, entity=entity, part_number=part_number
            )
        except InventoryReservationError as exc:
            if "No inventory stock found" in str(exc):
                _raise_or_record_shortage(
                    session,
                    create_shortage=create_shortage_if_unavailable,
                    project=project,
                    flight=flight,
                    sdls=sdls,
                    entity=entity,
                    entity_type=et,
                    entity_id=eid,
                    actor=actor,
                    inventory=None,
                    message=str(exc),
                )
            raise

    serial_number = payload.get("serial_number")
    instance_id = payload.get("inventory_instance_id")
    instance: Optional[InventoryInstance] = None

    if is_component_inventory(inventory.inventory_type):
        avail = check_availability(
            session,
            project_id=project_id,
            target_entity_type=et,
            target_entity_id=eid,
            part_number=inventory.part_number,
        )
        if not avail["available"]:
            _raise_or_record_shortage(
                session,
                create_shortage=create_shortage_if_unavailable,
                project=project,
                flight=flight,
                sdls=sdls,
                entity=entity,
                entity_type=et,
                entity_id=eid,
                actor=actor,
                inventory=inventory,
                message=avail.get("reason") or "Stock not available",
            )
    else:
        instance = pick_free_instance(
            session,
            inventory,
            serial_number=serial_number,
            instance_id=int(instance_id) if instance_id is not None else None,
        )
        if instance is None:
            _raise_or_record_shortage(
                session,
                create_shortage=create_shortage_if_unavailable,
                project=project,
                flight=flight,
                sdls=sdls,
                entity=entity,
                entity_type=et,
                entity_id=eid,
                actor=actor,
                inventory=inventory,
                message="No available inventory unit to reserve",
            )
        # Double-check no other project holds this instance
        if active_reservation_for_instance(session, int(instance.id)):
            raise InventoryReservationError(
                "Unit is already reserved by another project"
            )

    # Status transition AVAILABLE → RESERVED (treat missing as AVAILABLE)
    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)
    reserved_id = get_item_status_id(session, ItemStatus.RESERVED.value)

    if instance is not None:
        current = item_status_name(session, instance.status_id) or ItemStatus.AVAILABLE.value
        try:
            assert_transition("item", current, ItemStatus.RESERVED.value)
        except ValueError as exc:
            raise InventoryReservationError(str(exc)) from exc
        instance.status_id = reserved_id
        instance.updated_at = _now()
        session.add(instance)
    else:
        current = item_status_name(session, inventory.status_id) or ItemStatus.AVAILABLE.value
        try:
            assert_transition("item", current, ItemStatus.RESERVED.value)
        except ValueError as exc:
            # Component qty groups may already be AVAILABLE with partial reserves
            if current != ItemStatus.AVAILABLE.value and current != ItemStatus.RESERVED.value:
                raise InventoryReservationError(str(exc)) from exc
        if current == ItemStatus.AVAILABLE.value or inventory.status_id is None:
            inventory.status_id = reserved_id
            inventory.updated_at = _now()
            session.add(inventory)

    expires_at = payload.get("expires_at")
    if expires_at is None:
        expires_at = _now() + timedelta(days=DEFAULT_RESERVATION_DAYS)
    elif isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

    reservation = InventoryReservation(
        project_id=project_id,
        flight_id=int(flight.id),
        sdls_id=int(sdls.id),
        target_entity_type=et,
        target_entity_id=eid,
        inventory_id=int(inventory.id),
        inventory_instance_id=int(instance.id) if instance else None,
        reserved_by_user_id=int(actor.id),
        reserved_at=_now(),
        expires_at=expires_at,
        extension_count=0,
        part_number=inventory.part_number
        or getattr(entity, "part_number", None),
        serial_number=(instance.serial_number if instance else serial_number),
        status=InventoryReservationStatus.ACTIVE.value,
        notes=payload.get("notes"),
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def release_reservation(
    session: Session,
    project_id: int,
    reservation_id: int,
    *,
    actor: User,
) -> InventoryReservation:
    reservation = session.get(InventoryReservation, reservation_id)
    if not reservation or reservation.project_id != project_id:
        raise InventoryReservationError("Reservation not found")
    if reservation.status != InventoryReservationStatus.ACTIVE.value:
        raise InventoryReservationError("Reservation is not active")

    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)

    if reservation.inventory_instance_id:
        instance = session.get(InventoryInstance, reservation.inventory_instance_id)
        if instance:
            current = (
                item_status_name(session, instance.status_id)
                or ItemStatus.RESERVED.value
            )
            try:
                assert_transition(
                    "item", current, ItemStatus.AVAILABLE.value
                )
            except ValueError as exc:
                raise InventoryReservationError(str(exc)) from exc
            instance.status_id = available_id
            instance.updated_at = _now()
            session.add(instance)
    else:
        inventory = session.get(Inventory, reservation.inventory_id)
        if inventory:
            # Only flip group back to AVAILABLE if no other active reservations
            others = [
                r
                for r in active_reservations_for_inventory(session, int(inventory.id))
                if r.id != reservation.id
            ]
            if not others:
                current = (
                    item_status_name(session, inventory.status_id)
                    or ItemStatus.RESERVED.value
                )
                if current == ItemStatus.RESERVED.value:
                    try:
                        assert_transition(
                            "item", current, ItemStatus.AVAILABLE.value
                        )
                    except ValueError as exc:
                        raise InventoryReservationError(str(exc)) from exc
                    inventory.status_id = available_id
                    inventory.updated_at = _now()
                    session.add(inventory)

    reservation.status = InventoryReservationStatus.RELEASED.value
    reservation.released_at = _now()
    reservation.released_by_user_id = int(actor.id)
    reservation.updated_at = _now()
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def list_project_reservations(
    session: Session,
    project_id: int,
    *,
    active_only: bool = False,
) -> list[InventoryReservation]:
    query = select(InventoryReservation).where(
        InventoryReservation.project_id == project_id
    )
    if active_only:
        query = query.where(
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value
        )
    query = query.order_by(
        InventoryReservation.reserved_at.desc(), InventoryReservation.id.desc()
    )
    return list(session.exec(query).all())


def reservation_to_dict(reservation: InventoryReservation) -> dict[str, Any]:
    return {
        "id": reservation.id,
        "project_id": reservation.project_id,
        "flight_id": reservation.flight_id,
        "sdls_id": reservation.sdls_id,
        "target_entity_type": reservation.target_entity_type,
        "target_entity_id": reservation.target_entity_id,
        "inventory_id": reservation.inventory_id,
        "inventory_instance_id": reservation.inventory_instance_id,
        "reserved_by_user_id": reservation.reserved_by_user_id,
        "reserved_at": reservation.reserved_at,
        "expires_at": reservation.expires_at,
        "last_reminder_at": reservation.last_reminder_at,
        "extension_count": reservation.extension_count,
        "part_number": reservation.part_number,
        "serial_number": reservation.serial_number,
        "status": reservation.status,
        "released_at": reservation.released_at,
        "released_by_user_id": reservation.released_by_user_id,
        "notes": reservation.notes,
        "flight_code": reservation.flight.code if reservation.flight else None,
        "flight_name": reservation.flight.name if reservation.flight else None,
        "sdls_code": reservation.sdls.code if reservation.sdls else None,
        "sdls_name": reservation.sdls.name if reservation.sdls else None,
        "inventory_name": reservation.inventory.name if reservation.inventory else None,
        "reserved_by_name": (
            (reservation.reserved_by.full_name or reservation.reserved_by.username)
            if reservation.reserved_by
            else None
        ),
    }
