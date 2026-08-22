"""
Spec 01 — hierarchy configuration CRUD service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func
from sqlmodel import Session, select

from app.domain.hierarchy_config import (
    CONFIG_RULE_NOTES_DEFAULT,
    DEFAULT_PRODUCT_TYPE_DEFS,
    PARENT_TEMPLATE_LEVEL,
    TEMPLATE_NODE_LEVELS,
    HierarchyConfigLevel,
)
from app.models.tables import (
    Hierarchy,
    HierarchyConfigNode,
    HierarchyConfigProductType,
    HierarchyConfiguration,
    User,
)
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit
from app.services.entity_list_service import validate_config_nodes_entity_list, EntityListError


class HierarchyConfigError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_unique_configuration_name(
    session: Session,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    """Reject duplicate configuration names (case-insensitive, trimmed)."""
    needle = name.strip().lower()
    if not needle:
        return
    stmt = select(HierarchyConfiguration).where(
        func.lower(HierarchyConfiguration.name) == needle
    )
    if exclude_id is not None:
        stmt = stmt.where(HierarchyConfiguration.id != exclude_id)
    existing = session.exec(stmt).first()
    if existing:
        raise HierarchyConfigError(
            f"Configuration name '{name.strip()}' already exists"
        )


def get_configuration(session: Session, config_id: int) -> HierarchyConfiguration | None:
    return session.get(HierarchyConfiguration, config_id)


def list_configurations(
    session: Session, *, available_only: bool = False
) -> list[HierarchyConfiguration]:
    query = select(HierarchyConfiguration).order_by(HierarchyConfiguration.name)
    if available_only:
        query = query.where(HierarchyConfiguration.is_available.is_(True))
    return list(session.exec(query).all())


def _validate_product_types(product_types: list[dict[str, Any]]) -> None:
    if not product_types:
        raise HierarchyConfigError("At least one product type is required")
    codes = [str(pt.get("code", "")).strip() for pt in product_types]
    if any(not c for c in codes):
        raise HierarchyConfigError("Product type code is required")
    if len(codes) != len(set(codes)):
        raise HierarchyConfigError("Product type codes must be unique within a configuration")


def _validate_nodes(session: Session, nodes: list[dict[str, Any]]) -> None:
    allowed = {level.value for level in TEMPLATE_NODE_LEVELS}
    keys: set[str] = set()
    for index, node in enumerate(nodes):
        level = str(node.get("level", "")).strip().lower()
        name = str(node.get("name", "")).strip()
        if level not in allowed:
            raise HierarchyConfigError(
                f"Node[{index}] level must be one of: {', '.join(sorted(allowed))}"
            )
        if not name:
            raise HierarchyConfigError(f"Node[{index}] name is required")
        client_key = str(node.get("client_key") or f"n{index}").strip()
        if client_key in keys:
            raise HierarchyConfigError(f"Duplicate client_key: {client_key}")
        keys.add(client_key)

    # Parent level rules
    by_key = {
        str(n.get("client_key") or f"n{i}").strip(): n for i, n in enumerate(nodes)
    }
    for index, node in enumerate(nodes):
        level = HierarchyConfigLevel(str(node.get("level")).strip().lower())
        expected_parent = PARENT_TEMPLATE_LEVEL[level]
        parent_key = node.get("parent_client_key")
        if expected_parent is None:
            if parent_key:
                raise HierarchyConfigError(
                    f"Node[{index}] ({level.value}) must not have a parent"
                )
            continue
        if not parent_key:
            raise HierarchyConfigError(
                f"Node[{index}] ({level.value}) requires parent_client_key"
            )
        parent = by_key.get(str(parent_key).strip())
        if parent is None:
            raise HierarchyConfigError(
                f"Node[{index}] parent_client_key '{parent_key}' not found"
            )
        parent_level = str(parent.get("level", "")).strip().lower()
        if parent_level != expected_parent.value:
            raise HierarchyConfigError(
                f"Node[{index}] parent must be {expected_parent.value}, got {parent_level}"
            )

    try:
        validate_config_nodes_entity_list(session, nodes)
    except EntityListError as exc:
        raise HierarchyConfigError(str(exc)) from exc


def _replace_children(
    session: Session,
    config: HierarchyConfiguration,
    product_types: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> None:
    assert config.id is not None
    from sqlalchemy import update

    # Break self-FK, then delete children via SQL (avoids stale ORM collections)
    session.exec(
        update(HierarchyConfigNode)
        .where(HierarchyConfigNode.configuration_id == config.id)
        .values(parent_id=None)
    )
    session.exec(
        delete(HierarchyConfigNode).where(
            HierarchyConfigNode.configuration_id == config.id
        )
    )
    session.exec(
        delete(HierarchyConfigProductType).where(
            HierarchyConfigProductType.configuration_id == config.id
        )
    )
    session.expire(config, ["nodes", "product_types"])
    session.flush()

    for index, pt in enumerate(product_types):
        session.add(
            HierarchyConfigProductType(
                configuration_id=config.id,
                code=str(pt["code"]).strip(),
                name=str(pt.get("name") or pt["code"]).strip(),
                description=pt.get("description"),
                sort_order=int(pt.get("sort_order", index)),
            )
        )

    level_rank = {level.value: i for i, level in enumerate(TEMPLATE_NODE_LEVELS)}
    ordered = sorted(
        enumerate(nodes),
        key=lambda pair: level_rank.get(str(pair[1].get("level", "")).lower(), 99),
    )
    key_to_id: dict[str, int] = {}
    for index, node in ordered:
        client_key = str(node.get("client_key") or f"n{index}").strip()
        parent_id = None
        parent_key = node.get("parent_client_key")
        if parent_key:
            parent_id = key_to_id.get(str(parent_key).strip())
            if parent_id is None:
                raise HierarchyConfigError(
                    f"Parent '{parent_key}' must be created before child '{client_key}'"
                )
        db_node = HierarchyConfigNode(
            configuration_id=config.id,
            level=str(node["level"]).strip().lower(),
            name=str(node["name"]).strip(),
            description=node.get("description"),
            abbreviation=node.get("abbreviation"),
            sort_order=int(node.get("sort_order", index)),
            client_key=client_key,
            parent_id=parent_id,
        )
        session.add(db_node)
        session.flush()
        key_to_id[client_key] = int(db_node.id)


def create_configuration(
    session: Session,
    payload: dict[str, Any],
    *,
    actor: Optional[User] = None,
) -> HierarchyConfiguration:
    code = str(payload.get("code", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not code:
        raise HierarchyConfigError("code is required")
    if not name:
        raise HierarchyConfigError("name is required")

    existing = session.exec(
        select(HierarchyConfiguration).where(HierarchyConfiguration.code == code)
    ).first()
    if existing:
        raise HierarchyConfigError(f"Configuration code '{code}' already exists")

    _assert_unique_configuration_name(session, name)

    product_types = list(payload.get("product_types") or [])
    nodes = list(payload.get("nodes") or [])
    _validate_product_types(product_types)
    _validate_nodes(session, nodes)

    config = HierarchyConfiguration(
        code=code,
        name=name,
        description=payload.get("description"),
        notes=payload.get("notes") or CONFIG_RULE_NOTES_DEFAULT,
        is_available=bool(payload.get("is_available", True)),
        version=1,
        created_by_id=actor.id if actor else None,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(config)
    session.flush()
    _replace_children(session, config, product_types, nodes)
    session.commit()
    session.refresh(config)
    return config


def update_configuration(
    session: Session,
    config_id: int,
    payload: dict[str, Any],
    *,
    actor: Optional[User] = None,
) -> HierarchyConfiguration:
    config = get_configuration(session, config_id)
    if not config:
        raise HierarchyConfigError("Configuration not found")

    if "code" in payload and payload["code"] is not None:
        new_code = str(payload["code"]).strip()
        if new_code and new_code != config.code:
            clash = session.exec(
                select(HierarchyConfiguration).where(
                    HierarchyConfiguration.code == new_code,
                    HierarchyConfiguration.id != config_id,
                )
            ).first()
            if clash:
                raise HierarchyConfigError(f"Configuration code '{new_code}' already exists")
            config.code = new_code

    if "name" in payload and payload["name"] is not None:
        name = str(payload["name"]).strip()
        if not name:
            raise HierarchyConfigError("name cannot be empty")
        if name.lower() != (config.name or "").strip().lower():
            _assert_unique_configuration_name(
                session, name, exclude_id=config_id
            )
        config.name = name
    if "description" in payload:
        config.description = payload["description"]
    if "notes" in payload:
        config.notes = payload["notes"]
    if "is_available" in payload and payload["is_available"] is not None:
        config.is_available = bool(payload["is_available"])

    replace_children = "product_types" in payload or "nodes" in payload
    if replace_children:
        product_types = list(
            payload["product_types"]
            if "product_types" in payload
            else [
                {
                    "code": pt.code,
                    "name": pt.name,
                    "description": pt.description,
                    "sort_order": pt.sort_order,
                }
                for pt in config.product_types
            ]
        )
        nodes = list(
            payload["nodes"]
            if "nodes" in payload
            else [
                {
                    "client_key": n.client_key or f"id-{n.id}",
                    "parent_client_key": next(
                        (
                            (p.client_key or f"id-{p.id}")
                            for p in config.nodes
                            if p.id == n.parent_id
                        ),
                        None,
                    ),
                    "level": n.level,
                    "name": n.name,
                    "description": n.description,
                    "abbreviation": n.abbreviation,
                    "sort_order": n.sort_order,
                }
                for n in config.nodes
            ]
        )
        _validate_product_types(product_types)
        _validate_nodes(session, nodes)
        _replace_children(session, config, product_types, nodes)

    config.version = int(config.version or 1) + 1
    config.updated_at = _now()
    session.add(config)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.MODIFIED,
        entity_type="hierarchy_configuration",
        entity_id=int(config.id),
        actor=actor,
        new_value={"code": config.code, "name": config.name, "version": config.version},
    )
    session.commit()
    session.refresh(config)
    return config


def set_available(
    session: Session, config_id: int, is_available: bool
) -> HierarchyConfiguration:
    config = get_configuration(session, config_id)
    if not config:
        raise HierarchyConfigError("Configuration not found")
    config.is_available = is_available
    config.version = int(config.version or 1) + 1
    config.updated_at = _now()
    session.add(config)
    session.commit()
    session.refresh(config)
    return config


def delete_configuration(
    session: Session, config_id: int, *, hard: bool = False, actor: Optional[User] = None
) -> None:
    """
    Soft-retire by default (is_available=False).
    Hard delete removes the row and clears project / CR references.
    """
    from sqlalchemy import update

    from app.models.tables import ConfigChangeRequest, Project

    config = get_configuration(session, config_id)
    if not config:
        raise HierarchyConfigError("Configuration not found")
    if not hard:
        soft_retire_configuration(session, config_id)
        return

    session.exec(
        update(Project)
        .where(Project.hierarchy_config_id == config_id)
        .values(hierarchy_config_id=None)
    )
    session.exec(
        update(ConfigChangeRequest)
        .where(ConfigChangeRequest.target_hierarchy_config_id == config_id)
        .values(target_hierarchy_config_id=None)
    )
    session.exec(
        update(HierarchyConfigNode)
        .where(HierarchyConfigNode.configuration_id == config_id)
        .values(parent_id=None)
    )
    session.exec(
        delete(HierarchyConfigNode).where(
            HierarchyConfigNode.configuration_id == config_id
        )
    )
    session.exec(
        delete(HierarchyConfigProductType).where(
            HierarchyConfigProductType.configuration_id == config_id
        )
    )
    session.expire(config, ["nodes", "product_types"])
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.DELETED,
        entity_type="hierarchy_configuration",
        entity_id=int(config.id),
        actor=actor,
        old_value={"code": config.code, "name": config.name},
    )
    session.delete(config)
    session.commit()


def soft_retire_configuration(session: Session, config_id: int) -> HierarchyConfiguration:
    return set_available(session, config_id, False)


def configuration_to_dict(config: HierarchyConfiguration) -> dict[str, Any]:
    nodes = sorted(config.nodes or [], key=lambda n: (n.level, n.sort_order, n.id or 0))
    id_to_key = {n.id: (n.client_key or f"id-{n.id}") for n in nodes}
    return {
        "id": config.id,
        "code": config.code,
        "name": config.name,
        "description": config.description,
        "notes": config.notes,
        "is_available": config.is_available,
        "version": config.version,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
        "created_by_id": config.created_by_id,
        "product_types": [
            {
                "id": pt.id,
                "code": pt.code,
                "name": pt.name,
                "description": pt.description,
                "sort_order": pt.sort_order,
            }
            for pt in sorted(
                config.product_types or [], key=lambda p: (p.sort_order, p.id or 0)
            )
        ],
        "nodes": [
            {
                "id": n.id,
                "client_key": n.client_key or f"id-{n.id}",
                "parent_id": n.parent_id,
                "parent_client_key": id_to_key.get(n.parent_id) if n.parent_id else None,
                "level": n.level,
                "name": n.name,
                "description": n.description,
                "abbreviation": n.abbreviation,
                "sort_order": n.sort_order,
            }
            for n in nodes
        ],
    }


def _catalog_rows_to_nodes(rows: list[Hierarchy]) -> list[dict[str, Any]]:
    allowed = {level.value for level in TEMPLATE_NODE_LEVELS}
    catalog = [row for row in rows if (row.hierarchy_type or "").strip().lower() in allowed]
    ids = {row.id for row in catalog if row.id is not None}
    nodes: list[dict[str, Any]] = []
    for row in catalog:
        if row.id is None or not (row.name or "").strip():
            continue
        level = row.hierarchy_type.strip().lower()
        parent_key = None
        if level != HierarchyConfigLevel.SYSTEM.value:
            if row.parent_id is None or row.parent_id not in ids:
                continue
            parent_key = f"cat-{row.parent_id}"
        nodes.append(
            {
                "client_key": f"cat-{row.id}",
                "parent_client_key": parent_key,
                "level": level,
                "name": row.name.strip(),
                "description": row.description,
                "abbreviation": row.abbreviation,
                "sort_order": int(row.id),
            }
        )
    return nodes


def import_catalog_into_empty_configs(session: Session) -> int:
    """Legacy helper — no longer auto-creates configurations on startup.

    Kept for optional/manual migration use. Returns 0 (no-op) so empty Admin
    config lists stay empty until configurations are created deliberately.
    """
    return 0
