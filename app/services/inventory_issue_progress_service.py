"""Spec 07 — 24h after issue, auto-set item status to INSTALLATION_IN_PROGRESS."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_status import ItemStatus
from app.models.tables import Inventory, InventoryInstance, InventoryIssuance
from app.services.inventory_issuance_service import OPEN_STATUS
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit
from app.services.inventory_reservation_service import (
    get_item_status_id,
    item_status_name,
)


DEFAULT_PROGRESS_HOURS = 24


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def issue_progress_hours() -> int:
    return max(1, _env_int("ISSUE_PROGRESS_HOURS", DEFAULT_PROGRESS_HOURS))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_issue_progress(session: Session) -> dict[str, Any]:
    """Flip ISSUED items to INSTALLATION_IN_PROGRESS once the timer elapses."""
    hours = issue_progress_hours()
    rows = list(
        session.exec(
            select(InventoryIssuance).where(
                InventoryIssuance.status == OPEN_STATUS,
            )
        ).all()
    )
    flipped = 0
    skipped = 0
    examined = 0
    now = _now()
    cutoff = now - timedelta(hours=hours)
    progress_id = get_item_status_id(session, ItemStatus.INSTALLATION_IN_PROGRESS.value)

    for issuance in rows:
        issued_at = _aware(issuance.issued_at) if issuance.issued_at else None
        if issued_at is None or issued_at > cutoff:
            continue
        examined += 1
        instance = None
        if issuance.inventory_instance_id:
            instance = session.get(InventoryInstance, issuance.inventory_instance_id)
        inventory = session.get(Inventory, issuance.inventory_id)
        current = (issuance.item_lifecycle_status or "").strip().upper()
        if instance is not None:
            current = (
                item_status_name(session, instance.status_id) or current or ItemStatus.ISSUED.value
            )
        elif inventory is not None:
            current = (
                item_status_name(session, inventory.status_id) or current or ItemStatus.ISSUED.value
            )
        if current != ItemStatus.ISSUED.value:
            skipped += 1
            continue
        try:
            assert_transition(
                "item",
                ItemStatus.ISSUED.value,
                ItemStatus.INSTALLATION_IN_PROGRESS.value,
                actor_role=None,
            )
        except ValueError:
            skipped += 1
            continue
        if instance is not None:
            instance.status_id = progress_id
            instance.updated_at = now
            session.add(instance)
        if inventory is not None:
            inventory.status_id = progress_id
            inventory.updated_at = now
            session.add(inventory)
        issuance.item_lifecycle_status = ItemStatus.INSTALLATION_IN_PROGRESS.value
        session.add(issuance)
        write_workflow_audit(
            session,
            action=WorkflowAuditAction.INSTALLATION_IN_PROGRESS,
            entity_type="inventory_issuance",
            entity_id=int(issuance.id),
            system=True,
            project_id=issuance.project_id,
            old_value={"status": ItemStatus.ISSUED.value},
            new_value={"status": ItemStatus.INSTALLATION_IN_PROGRESS.value},
            remarks="Automatic 24h issue progress",
        )
        flipped += 1

    if flipped:
        session.commit()
    return {"flipped": flipped, "skipped": skipped, "examined": examined}
