"""
Entity List — master catalog of allowed entity names and categories (hierarchy levels).

The `hierarchy` table stores Entity List entries as a flat catalog keyed by
(name, hierarchy_type). Parent/child tree structure is defined per configuration
(or installed hardware), not in the Entity List itself.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models.tables import Hierarchy

ENTITY_LIST_LEVELS = frozenset({"system", "subsystem", "module", "unit", "component"})


class EntityListError(ValueError):
    pass


def list_entity_list_entries(
    session: Session,
    *,
    hierarchy_type: str | None = None,
    parent_id: int | None = None,
) -> list[Hierarchy]:
    query = select(Hierarchy).order_by(Hierarchy.hierarchy_type, Hierarchy.name)
    if hierarchy_type:
        query = query.where(Hierarchy.hierarchy_type == hierarchy_type)
    if parent_id is not None:
        query = query.where(Hierarchy.parent_id == parent_id)
    return list(session.exec(query).all())


def _normalize_name(value: str) -> str:
    return value.strip()


def find_entity_list_entry(
    session: Session,
    *,
    name: str,
    hierarchy_type: str,
    parent_name: str | None = None,
    parent_id: int | None = None,
) -> Hierarchy | None:
    """Return a catalog row matching name + level.

    parent_name / parent_id are accepted for call-site compatibility but are not
    used: Entity List is a flat catalog; configuration trees choose parent/child.
    """
    del parent_name, parent_id  # unused — flat catalog
    level = hierarchy_type.strip().lower()
    if level not in ENTITY_LIST_LEVELS:
        return None

    normalized_name = _normalize_name(name)
    if not normalized_name:
        return None

    entries = list_entity_list_entries(session, hierarchy_type=level)
    for entry in entries:
        if entry.name.strip().lower() == normalized_name.lower():
            return entry
    return None


def require_entity_list_name(
    session: Session,
    *,
    name: str,
    hierarchy_type: str,
    parent_name: str | None = None,
    parent_id: int | None = None,
) -> Hierarchy:
    entry = find_entity_list_entry(
        session,
        name=name,
        hierarchy_type=hierarchy_type,
        parent_name=parent_name,
        parent_id=parent_id,
    )
    if entry is None:
        level = hierarchy_type.strip().lower()
        detail = (
            f"'{name.strip()}' is not a registered {level}. "
            "Add it in Settings → Definitions → Entity List."
        )
        raise EntityListError(detail)
    return entry


def validate_config_nodes_entity_list(
    session: Session, nodes: list[dict[str, Any]]
) -> None:
    """Ensure every template node name exists in the Entity List for its level."""
    for index, node in enumerate(nodes):
        level = str(node.get("level", "")).strip().lower()
        name = str(node.get("name", "")).strip()
        if level not in ENTITY_LIST_LEVELS or not name:
            continue

        try:
            require_entity_list_name(
                session,
                name=name,
                hierarchy_type=level,
            )
        except EntityListError as exc:
            raise EntityListError(f"Node[{index}]: {exc}") from exc


def validate_inventory_entity_name(
    session: Session, *, name: str, inventory_type: str
) -> None:
    require_entity_list_name(
        session,
        name=name,
        hierarchy_type=inventory_type.strip().lower(),
    )


def _parent_level(level: str) -> str | None:
    mapping = {
        "subsystem": "system",
        "module": "subsystem",
        "unit": "module",
        "component": "unit",
    }
    return mapping.get(level)


def validate_hardware_entity_name(
    session: Session,
    *,
    name: str,
    entity_type: str,
    parent_name: str | None = None,
    parent_id: int | None = None,
) -> None:
    # Catalog check is name + type only; parent comes from the install tree.
    del parent_name, parent_id
    require_entity_list_name(
        session,
        name=name,
        hierarchy_type=entity_type.strip().lower(),
    )


def enrich_hierarchy_reads(session: Session, entries: list[Hierarchy]) -> list[dict]:
    """Attach parent_name for API responses."""
    parent_ids = {e.parent_id for e in entries if e.parent_id is not None}
    name_by_id: dict[int, str] = {}
    if parent_ids:
        parents = list(
            session.exec(select(Hierarchy).where(Hierarchy.id.in_(parent_ids))).all()
        )
        name_by_id = {p.id: p.name for p in parents if p.id is not None}

    result: list[dict] = []
    for entry in entries:
        data = entry.model_dump()
        pid = entry.parent_id
        data["parent_name"] = name_by_id.get(pid) if pid is not None else None
        result.append(data)
    return result
