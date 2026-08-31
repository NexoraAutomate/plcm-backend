"""Signed inventory label lifecycle and scan resolution services."""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from app.auth import SECRET_KEY, is_inventory_manager
from app.models.base import InventoryLabelStatus
from app.models.tables import (
    EntityStatusHistory,
    Inventory,
    InventoryInstance,
    InventoryIssuanceEvent,
    InventoryLabel,
    InventoryLabelPrintEvent,
    InventoryLabelScanEvent,
    MaintenanceLog,
    FaultyEntity,
    MaintenanceAction,
    Status,
    User,
)
from app.services.inventory_issuance_service import user_can_access_inventory
from app.services.app_definitions_service import inventory_label_code_type
from app.utils.datetimes import to_api_utc
from app.services.workflow_audit_service import write_workflow_audit


LABEL_PREFIX = "PLCM1"
BARCODE_PREFIX = "PLCB"
LABEL_SIGNATURE_VERSION = "v1"
ACTIVE = InventoryLabelStatus.ACTIVE.value


class InventoryLabelError(ValueError):
    """Expected validation failure for a label operation."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(value: Optional[datetime]) -> bool:
    """Compare DB timestamps safely when the driver returns naive datetimes."""
    expiry = to_api_utc(value)
    return expiry is not None and expiry <= _now()


def _sign(label_id: str) -> str:
    digest = hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"{LABEL_SIGNATURE_VERSION}:{label_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def signed_payload(label_id: str) -> str:
    return f"{LABEL_PREFIX}.{label_id}.{_sign(label_id)}"


def _base36(value: int) -> str:
    if value < 0:
        raise ValueError("Base-36 values cannot be negative")
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(alphabet[remainder])
    return "".join(reversed(digits))


def _from_base36(value: str) -> int:
    return int(value, 36)


def _barcode_sign(value: str) -> str:
    digest = hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"{LABEL_SIGNATURE_VERSION}:barcode:{value}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest[:8]).decode("ascii").rstrip("=")


def barcode_payload(label_id: str, numeric_id: Optional[int]) -> str:
    """Return a short signed barcode payload suitable for high-volume labels."""
    if numeric_id is None:
        return signed_payload(label_id)
    compact_id = _base36(int(numeric_id))
    return f"{BARCODE_PREFIX}.{compact_id}.{_barcode_sign(compact_id)}"


def parse_signed_payload(payload: str) -> tuple[str, bool]:
    parts = (payload or "").strip().split(".")
    if len(parts) != 3 or parts[0] != LABEL_PREFIX or not parts[1] or not parts[2]:
        return "", False
    expected = _sign(parts[1])
    return parts[1], hmac.compare_digest(parts[2], expected)


def parse_barcode_payload(payload: str) -> tuple[Optional[int], bool]:
    parts = (payload or "").strip().split(".")
    if len(parts) != 3 or parts[0] != BARCODE_PREFIX or not parts[1] or not parts[2]:
        return None, False
    try:
        numeric_id = _from_base36(parts[1])
    except ValueError:
        return None, False
    return numeric_id, hmac.compare_digest(parts[2], _barcode_sign(parts[1]))


def _scan_fingerprint(payload: str) -> str:
    return hashlib.sha256((payload or "").encode("utf-8")).hexdigest()


def _serial_for_target(
    session: Session,
    inventory: Inventory,
    *,
    instance_id: Optional[int],
    requested_serial: Optional[str],
) -> tuple[Optional[InventoryInstance], Optional[str]]:
    instance: Optional[InventoryInstance] = None
    serial = (requested_serial or "").strip() or None
    if instance_id is not None:
        instance = session.get(InventoryInstance, instance_id)
        if not instance or instance.inventory_id != inventory.id:
            raise InventoryLabelError("Inventory instance does not belong to this inventory item")
        serial = (instance.serial_number or instance.original_serial_number or "").strip() or None
    elif serial:
        instance = session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == inventory.id,
                or_(
                    InventoryInstance.serial_number == serial,
                    InventoryInstance.original_serial_number == serial,
                ),
            )
        ).first()
        if not instance:
            raise InventoryLabelError("Serial number was not found in this inventory item")
    else:
        raise InventoryLabelError("An inventory instance is required")
    return instance, serial


def _active_for_target(
    session: Session,
    *,
    inventory_id: int,
    instance_id: Optional[int],
    serial: Optional[str],
) -> Optional[InventoryLabel]:
    stmt = select(InventoryLabel).where(
        InventoryLabel.status == ACTIVE,
        InventoryLabel.inventory_id == inventory_id,
    )
    if instance_id is not None:
        stmt = stmt.where(InventoryLabel.inventory_instance_id == instance_id)
    elif serial:
        stmt = stmt.where(
            InventoryLabel.inventory_instance_id.is_(None),
            InventoryLabel.serial_number == serial,
        )
    else:
        stmt = stmt.where(
            InventoryLabel.inventory_instance_id.is_(None),
            InventoryLabel.serial_number.is_(None),
        )
    return session.exec(stmt).first()


def label_to_dict(session: Session, label: InventoryLabel) -> dict[str, Any]:
    inventory = session.get(Inventory, label.inventory_id)
    return {
        "id": int(label.id),
        "label_id": label.label_id,
        "signed_payload": signed_payload(label.label_id),
        "barcode_payload": barcode_payload(label.label_id, label.id),
        "inventory_id": label.inventory_id,
        "inventory_instance_id": label.inventory_instance_id,
        "serial_number": label.serial_number,
        "inventory_name": inventory.name if inventory else None,
        "part_number": inventory.part_number if inventory else None,
        "label_type": label.label_type,
        "status": label.status,
        "print_count": label.print_count,
        "first_printed_at": label.first_printed_at,
        "last_printed_at": label.last_printed_at,
        "created_at": label.created_at,
        "updated_at": label.updated_at,
    }


def generate_labels(
    session: Session,
    *,
    targets: Iterable[dict[str, Any]],
    label_type: str,
    actor: User,
) -> list[InventoryLabel]:
    if label_type not in {"qr", "barcode", "both"}:
        raise InventoryLabelError("Label type must be qr, barcode, or both")

    labels: list[InventoryLabel] = []
    seen_targets: set[tuple[int, Optional[int], Optional[str]]] = set()
    for target in targets:
        inventory_id = int(target["inventory_id"])
        inventory = session.get(Inventory, inventory_id)
        if not inventory:
            raise InventoryLabelError(f"Inventory {inventory_id} was not found")
        if _is_expired(inventory.shelf_life_expires_at):
            raise InventoryLabelError("Expired inventory cannot receive a new label")
        instance, serial = _serial_for_target(
            session,
            inventory,
            instance_id=target.get("inventory_instance_id"),
            requested_serial=target.get("serial_number"),
        )
        key = (inventory_id, instance.id if instance else None, serial)
        if key in seen_targets:
            continue
        seen_targets.add(key)
        existing = _active_for_target(
            session,
            inventory_id=inventory_id,
            instance_id=instance.id if instance else None,
            serial=serial,
        )
        if existing:
            if existing.label_type != label_type:
                existing.label_type = label_type
                existing.updated_at = _now()
                session.add(existing)
            labels.append(existing)
            continue

        now = _now()
        label = InventoryLabel(
            label_id=uuid.uuid4().hex,
            inventory_id=inventory_id,
            inventory_instance_id=instance.id if instance else None,
            serial_number=serial,
            label_type=label_type,
            status=ACTIVE,
            signature_version=LABEL_SIGNATURE_VERSION,
            activated_at=now,
            activated_by_id=actor.id,
            created_at=now,
            updated_at=now,
        )
        session.add(label)
        session.flush()
        write_workflow_audit(
            session,
            action="LABEL_GENERATED",
            entity_type="inventory_label",
            entity_id=label.label_id,
            actor=actor,
            old_value=None,
            new_value={
                "inventory_id": inventory_id,
                "inventory_instance_id": instance.id if instance else None,
                "serial_number": serial,
                "label_type": label_type,
            },
        )
        labels.append(label)
    return labels


def ensure_inventory_labels(
    session: Session,
    inventory: Inventory,
    *,
    actor: User,
    label_type: Optional[str] = None,
) -> list[InventoryLabel]:
    """Create one durable label for every current stock unit."""
    if inventory.id is None:
        return []
    label_type = label_type or inventory_label_code_type(session)

    instances = session.exec(
        select(InventoryInstance)
        .where(InventoryInstance.inventory_id == int(inventory.id))
        .order_by(InventoryInstance.id)
    ).all()
    targets = [
        {
            "inventory_id": int(inventory.id),
            "inventory_instance_id": instance.id,
            "serial_number": instance.serial_number,
        }
        for instance in instances
        if instance.id is not None
    ]

    if not targets:
        return []
    return generate_labels(
        session,
        targets=targets,
        label_type=label_type,
        actor=actor,
    )


def print_labels(
    session: Session,
    *,
    label_ids: Iterable[str],
    label_format: str,
    quantity: int,
    reason: Optional[str],
    actor: User,
) -> list[InventoryLabelPrintEvent]:
    if quantity < 1:
        raise InventoryLabelError("Print quantity must be at least one")
    ids = list(dict.fromkeys(str(value).strip() for value in label_ids if value))
    if not ids:
        raise InventoryLabelError("At least one label is required")

    events: list[InventoryLabelPrintEvent] = []
    for label_id in ids:
        label = session.exec(
            select(InventoryLabel).where(InventoryLabel.label_id == label_id)
        ).first()
        if not label:
            raise InventoryLabelError(f"Label {label_id} was not found")
        if label.status != ACTIVE:
            raise InventoryLabelError(f"Label {label_id} is {label.status} and cannot be printed")
        if not user_can_access_inventory(
            session,
            actor,
            label.inventory_id,
            is_manager=is_inventory_manager(actor),
        ):
            raise InventoryLabelError("You are not allowed to print this inventory label")
        if label.print_count > 0 and not (reason or "").strip():
            raise InventoryLabelError("A reason is required when reprinting a label")

        now = _now()
        first = label.print_count == 0
        label.print_count += quantity
        label.first_printed_at = label.first_printed_at or now
        label.last_printed_at = now
        label.updated_at = now
        event = InventoryLabelPrintEvent(
            label_id=label.label_id,
            user_id=int(actor.id),
            printed_at=now,
            reason=(reason or "").strip() or None,
            label_type=label.label_type,
            label_format=label_format.strip(),
            quantity=quantity,
            is_first_print=first,
        )
        session.add(label)
        session.add(event)
        write_workflow_audit(
            session,
            action="LABEL_PRINTED" if first else "LABEL_REPRINTED",
            entity_type="inventory_label",
            entity_id=label.label_id,
            actor=actor,
            new_value={
                "quantity": quantity,
                "label_format": label_format,
                "is_first_print": first,
                "reason": (reason or "").strip() or None,
            },
        )
        events.append(event)
    session.flush()
    return events


def list_history(session: Session, label_id: str) -> tuple[InventoryLabel, list[InventoryLabelPrintEvent], list[InventoryLabelScanEvent]]:
    label = session.exec(
        select(InventoryLabel).where(InventoryLabel.label_id == label_id)
    ).first()
    if not label:
        raise InventoryLabelError("Label not found")
    prints = list(
        session.exec(
            select(InventoryLabelPrintEvent)
            .where(InventoryLabelPrintEvent.label_id == label_id)
            .order_by(InventoryLabelPrintEvent.printed_at.desc())
        ).all()
    )
    scans = list(
        session.exec(
            select(InventoryLabelScanEvent)
            .where(InventoryLabelScanEvent.label_id == label_id)
            .order_by(InventoryLabelScanEvent.scanned_at.desc())
        ).all()
    )
    return label, prints, scans


def _record_scan(
    session: Session,
    *,
    label_id: Optional[str],
    actor: User,
    payload: str,
    source: str,
    location: Optional[str],
    valid: bool,
    suspicious: bool,
    reason: Optional[str],
) -> InventoryLabelScanEvent:
    event = InventoryLabelScanEvent(
        label_id=label_id,
        user_id=int(actor.id),
        scanned_at=_now(),
        location=(location or "").strip() or None,
        source=(source or "web").strip()[:32],
        valid=valid,
        suspicious=suspicious,
        reason=reason,
        payload_fingerprint=_scan_fingerprint(payload),
    )
    session.add(event)
    session.flush()
    return event


def _serialize(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def _hierarchy_for_inventory(session: Session, inventory: Inventory) -> dict[str, Any] | None:
    if inventory.entity_id is None or inventory.inventory_type == "component" and not inventory.entity_id:
        return None
    try:
        from app.models.helpers import _collect_descendants, _resolve_ancestors

        entity_type = inventory.inventory_type
        ancestors = _resolve_ancestors(session, entity_type, int(inventory.entity_id))
        descendants = _collect_descendants(session, entity_type, int(inventory.entity_id))
        return {
            "entity_type": entity_type,
            "entity_id": int(inventory.entity_id),
            "ancestors": [_serialize(item) for item in ancestors],
            "descendants": [_serialize(item) for item in descendants],
        }
    except (KeyError, TypeError, ValueError):
        return None


def resolve_scan(
    session: Session,
    *,
    payload: str,
    actor: User,
    location: Optional[str],
    source: str,
) -> dict[str, Any]:
    compact_id, compact_signature_valid = parse_barcode_payload(payload)
    is_compact_barcode = compact_id is not None or payload.strip().startswith(f"{BARCODE_PREFIX}.")
    if is_compact_barcode:
        signature_valid = compact_signature_valid
        label_id = ""
        label = session.get(InventoryLabel, compact_id) if signature_valid else None
        if label:
            label_id = label.label_id
    else:
        label_id, signature_valid = parse_signed_payload(payload)
        label = None
    if not signature_valid:
        _record_scan(
            session,
            label_id=None,
            actor=actor,
            payload=payload,
            source=source,
            location=location,
            valid=False,
            suspicious=True,
            reason="Invalid label signature",
        )
        write_workflow_audit(
            session,
            action="LABEL_SUSPICIOUS_SCAN",
            entity_type="inventory_label",
            entity_id=label_id or "unknown",
            actor=actor,
            remarks="Invalid label signature",
            new_value={"payload_fingerprint": _scan_fingerprint(payload)},
        )
        return {
            "valid": False,
            "status": "invalid",
            "message": "This label code is invalid or has been altered.",
        }

    if label is None:
        label = session.exec(
            select(InventoryLabel).where(InventoryLabel.label_id == label_id)
        ).first()
    if not label:
        _record_scan(
            session,
            label_id=None,
            actor=actor,
            payload=payload,
            source=source,
            location=location,
            valid=False,
            suspicious=True,
            reason="Unassigned label ID",
        )
        write_workflow_audit(
            session,
            action="LABEL_SUSPICIOUS_SCAN",
            entity_type="inventory_label",
            entity_id=label_id,
            actor=actor,
            remarks="Signed label ID is not assigned",
            new_value={"payload_fingerprint": _scan_fingerprint(payload)},
        )
        return {
            "valid": False,
            "status": "unassigned",
            "message": "This signed label is not assigned to inventory.",
        }

    inventory = session.get(Inventory, label.inventory_id)
    instance = (
        session.get(InventoryInstance, label.inventory_instance_id)
        if label.inventory_instance_id
        else None
    )
    if instance:
        current_serial = (instance.serial_number or instance.original_serial_number or "").strip()
    else:
        current_serial = (inventory.serial_number or "").strip() if inventory else ""
    if not inventory or (
        label.inventory_instance_id is not None
        and (not instance or instance.inventory_id != inventory.id)
    ) or (label.serial_number and label.serial_number != current_serial):
        reason = "Label assignment conflicts with inventory records"
        _record_scan(
            session,
            label_id=label_id,
            actor=actor,
            payload=payload,
            source=source,
            location=location,
            valid=False,
            suspicious=True,
            reason=reason,
        )
        write_workflow_audit(
            session,
            action="LABEL_SUSPICIOUS_SCAN",
            entity_type="inventory_label",
            entity_id=label_id,
            actor=actor,
            remarks=reason,
            new_value={
                "inventory_id": label.inventory_id,
                "inventory_instance_id": label.inventory_instance_id,
            },
        )
        return {
            "valid": False,
            "status": "duplicate",
            "message": "This label has a conflicting inventory assignment.",
        }
    if not user_can_access_inventory(
        session, actor, inventory.id, is_manager=is_inventory_manager(actor)
    ):
        _record_scan(
            session,
            label_id=label_id,
            actor=actor,
            payload=payload,
            source=source,
            location=location,
            valid=False,
            suspicious=False,
            reason="Access denied",
        )
        return {
            "valid": False,
            "status": "forbidden",
            "message": "You are not authorized to view this inventory record.",
        }
    if label.status != ACTIVE:
        _record_scan(
            session,
            label_id=label_id,
            actor=actor,
            payload=payload,
            source=source,
            location=location,
            valid=False,
            suspicious=True,
            reason=f"Label is {label.status}",
        )
        return {
            "valid": False,
            "status": label.status,
            "message": f"This label is {label.status} and cannot be used.",
        }
    if _is_expired(inventory.shelf_life_expires_at):
        _record_scan(
            session,
            label_id=label_id,
            actor=actor,
            payload=payload,
            source=source,
            location=location,
            valid=False,
            suspicious=False,
            reason="Inventory shelf life has expired",
        )
        return {
            "valid": False,
            "status": "expired",
            "message": "This label belongs to inventory whose shelf life has expired.",
        }

    current_location = (
        (instance.location if instance else None) or inventory.location or ""
    ).strip()
    warnings: list[str] = []
    if location and current_location and location.strip().lower() != current_location.lower():
        warnings.append(
            f"Scan location '{location.strip()}' differs from recorded location '{current_location}'."
        )
    recent_scans = list(
        session.exec(
            select(InventoryLabelScanEvent)
            .where(
                InventoryLabelScanEvent.label_id == label_id,
                InventoryLabelScanEvent.valid == True,  # noqa: E712
                InventoryLabelScanEvent.scanned_at >= _now() - timedelta(minutes=15),
            )
            .order_by(InventoryLabelScanEvent.scanned_at.desc())
        ).all()
    )
    if any(
        scan.location
        and location
        and scan.location.strip().lower() != location.strip().lower()
        for scan in recent_scans
    ):
        warnings.append("The same label was recently scanned from another location.")
    suspicious = bool(warnings)
    _record_scan(
        session,
        label_id=label_id,
        actor=actor,
        payload=payload,
        source=source,
        location=location,
        valid=True,
        suspicious=suspicious,
        reason="; ".join(warnings) if warnings else None,
    )

    print_events = list(
        session.exec(
            select(InventoryLabelPrintEvent)
            .where(InventoryLabelPrintEvent.label_id == label_id)
            .order_by(InventoryLabelPrintEvent.printed_at.desc())
        ).all()
    )
    issuance_events = list(
        session.exec(
            select(InventoryIssuanceEvent).where(
                InventoryIssuanceEvent.inventory_id == inventory.id,
                *(
                    [InventoryIssuanceEvent.inventory_instance_id == instance.id]
                    if instance
                    else []
                ),
            ).order_by(InventoryIssuanceEvent.created_at.desc())
        ).all()
    )
    build_history: list[dict[str, Any]] = []
    maintenance_history: list[dict[str, Any]] = []
    if inventory.entity_id:
        status_rows = list(
            session.exec(
                select(EntityStatusHistory).where(
                    EntityStatusHistory.entity_id == inventory.entity_id
                ).order_by(EntityStatusHistory.changed_at.desc())
            ).all()
        )
        build_history = [_serialize(item) for item in status_rows]
        maintenance_rows = list(
            session.exec(
                select(MaintenanceLog).where(
                    MaintenanceLog.entity_id == inventory.entity_id
                ).order_by(MaintenanceLog.performed_at.desc())
            ).all()
        )
        maintenance_history = [_serialize(item) for item in maintenance_rows]
        faulty_rows = list(
            session.exec(
                select(FaultyEntity).where(FaultyEntity.entity_id == inventory.entity_id)
            ).all()
        )
        for faulty in faulty_rows:
            maintenance_history.append(
                {"record_type": "fault", **_serialize(faulty)}
            )
            if faulty.id:
                action_rows = list(
                    session.exec(
                        select(MaintenanceAction).where(
                            MaintenanceAction.faulty_entity_id == faulty.id
                        ).order_by(MaintenanceAction.performed_at.desc())
                    ).all()
                )
                maintenance_history.extend(
                    {"record_type": "maintenance_action", **_serialize(item)}
                    for item in action_rows
                )

    stock_history = [
        {
            "event_type": "stock_received",
            "inventory_id": inventory.id,
            "inventory_instance_id": instance.id if instance else None,
            "serial_number": label.serial_number,
            "created_at": inventory.added_date,
        }
    ] + [_serialize(item) for item in issuance_events]
    ownership_history = [
        {
            "location": instance.location if instance else inventory.location,
            "holder_user_id": instance.holder_user_id if instance else inventory.holder_user_id,
            "recorded_at": instance.updated_at if instance else inventory.updated_at,
            "source": "current_inventory",
        }
    ]
    ownership_history.extend(
        {
            "location": scan.location,
            "user_id": scan.user_id,
            "recorded_at": scan.scanned_at,
            "source": "label_scan",
        }
        for scan in recent_scans
    )
    write_workflow_audit(
        session,
        action="LABEL_SUSPICIOUS_SCAN" if suspicious else "LABEL_SCANNED",
        entity_type="inventory_label",
        entity_id=label_id,
        actor=actor,
        new_value={"warnings": warnings, "location": location, "source": source},
    )
    session.flush()
    inventory_data = inventory.model_dump()
    inventory_status = session.get(Status, inventory.status_id) if inventory.status_id else None
    instance_data = instance.model_dump() if instance else None
    if instance_data is not None and instance.status_id:
        instance_status = session.get(Status, instance.status_id)
        instance_data["status_name"] = instance_status.status_name if instance_status else None
    inventory_data["status_name"] = inventory_status.status_name if inventory_status else None
    return {
        "valid": True,
        "status": "active",
        "message": "Label resolved successfully.",
        "warnings": warnings,
        "label": label_to_dict(session, label),
        "inventory": {
            **inventory_data,
            "instance": instance_data,
        },
        "stock_history": stock_history,
        "build_history": build_history,
        "maintenance_history": maintenance_history,
        "ownership_location_history": ownership_history,
        "hierarchy": _hierarchy_for_inventory(session, inventory),
        "print_history": [_serialize(item) for item in print_events],
    }


def deactivate_label(session: Session, label_id: str, *, actor: User, reason: str) -> InventoryLabel:
    label = session.exec(
        select(InventoryLabel).where(InventoryLabel.label_id == label_id)
    ).first()
    if not label:
        raise InventoryLabelError("Label not found")
    now = _now()
    label.status = InventoryLabelStatus.DEACTIVATED.value
    label.deactivated_at = now
    label.deactivated_by_id = actor.id
    label.updated_at = now
    session.add(label)
    write_workflow_audit(
        session,
        action="LABEL_DEACTIVATED",
        entity_type="inventory_label",
        entity_id=label_id,
        actor=actor,
        remarks=reason.strip(),
        old_value={"status": ACTIVE},
        new_value={"status": label.status},
    )
    session.flush()
    return label


def replace_label(
    session: Session,
    label_id: str,
    *,
    actor: User,
    reason: str,
    label_type: str,
) -> tuple[InventoryLabel, InventoryLabel]:
    old = session.exec(
        select(InventoryLabel).where(InventoryLabel.label_id == label_id)
    ).first()
    if not old:
        raise InventoryLabelError("Label not found")
    if old.status != ACTIVE:
        raise InventoryLabelError("Only an active label can be replaced")
    old.status = InventoryLabelStatus.REPLACED.value
    old.deactivated_at = _now()
    old.deactivated_by_id = actor.id
    old.updated_at = _now()
    session.add(old)
    session.flush()
    new = generate_labels(
        session,
        targets=[
            {
                "inventory_id": old.inventory_id,
                "inventory_instance_id": old.inventory_instance_id,
                "serial_number": old.serial_number,
            }
        ],
        label_type=label_type,
        actor=actor,
    )
    if not new:
        raise InventoryLabelError("Replacement label could not be generated")
    replacement = new[0]
    old.replacement_label_id = replacement.label_id
    old.updated_at = _now()
    session.add(old)
    write_workflow_audit(
        session,
        action="LABEL_REPLACED",
        entity_type="inventory_label",
        entity_id=label_id,
        actor=actor,
        remarks=reason.strip(),
        old_value={"status": ACTIVE},
        new_value={"status": old.status, "replacement_label_id": replacement.label_id},
    )
    session.flush()
    return old, replacement
