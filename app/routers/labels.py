"""Inventory label generation, printing, scanning, and compromise workflow."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth import check_permission, is_inventory_manager
from app.database import get_session
from app.models.base import InventoryLabelStatus
from app.models.tables import (
    Inventory,
    InventoryLabel,
    InventoryLabelPrintEvent,
    User,
)
from app.routers.auth import get_current_user, require_permission
from app.schemas import schemas
from app.services.inventory_issuance_service import user_can_access_inventory
from app.services.inventory_label_service import (
    InventoryLabelError,
    deactivate_label,
    generate_labels,
    ensure_inventory_labels,
    label_to_dict,
    list_history,
    print_labels,
    replace_label,
    resolve_scan,
)
from app.services.app_definitions_service import inventory_label_code_type
from app.services.workflow_audit_service import write_workflow_audit


router = APIRouter(prefix="/labels", tags=["inventory-labels"])


def _require_label_permission(user: User, permission: str) -> None:
    if is_inventory_manager(user) or check_permission(user, permission):
        return
    raise HTTPException(status_code=403, detail="You are not allowed to manage inventory labels")


def _commit_error(session: Session, exc: Exception) -> None:
    session.rollback()
    if isinstance(exc, InventoryLabelError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, IntegrityError):
        raise HTTPException(
            status_code=409,
            detail="The label assignment conflicts with another active label.",
        ) from exc
    raise exc


@router.post(
    "/generate",
    response_model=list[schemas.InventoryLabelRead],
    status_code=status.HTTP_201_CREATED,
)
def generate_inventory_labels(
    body: schemas.InventoryLabelGenerateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _require_label_permission(current_user, "inventory.label.generate")
    try:
        labels = generate_labels(
            session,
            targets=[target.model_dump() for target in body.targets],
            label_type=inventory_label_code_type(session),
            actor=current_user,
        )
        session.commit()
        return [label_to_dict(session, label) for label in labels]
    except (InventoryLabelError, IntegrityError) as exc:
        _commit_error(session, exc)


@router.post(
    "/generate-all",
    response_model=list[schemas.InventoryLabelRead],
    status_code=status.HTTP_201_CREATED,
)
def generate_all_inventory_labels(
    body: schemas.InventoryLabelGenerateAllRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Ensure one durable label exists for every current inventory stock unit."""
    _require_label_permission(current_user, "inventory.label.generate")
    if not is_inventory_manager(current_user):
        raise HTTPException(
            status_code=403,
            detail="Only inventory managers can generate labels for all inventory",
        )
    try:
        labels: list[InventoryLabel] = []
        selected_type = inventory_label_code_type(session)
        inventories = session.exec(select(Inventory).order_by(Inventory.id)).all()
        for inventory in inventories:
            labels.extend(
                ensure_inventory_labels(
                    session,
                    inventory,
                    actor=current_user,
                    label_type=selected_type,
                )
            )
        session.commit()
        return [label_to_dict(session, label) for label in labels]
    except (InventoryLabelError, IntegrityError) as exc:
        _commit_error(session, exc)


@router.get("/", response_model=list[schemas.InventoryLabelRead])
def list_inventory_labels(
    inventory_id: Optional[int] = Query(None),
    inventory_instance_id: Optional[int] = Query(None),
    include_inactive: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    stmt = select(InventoryLabel)
    if inventory_id is not None:
        stmt = stmt.where(InventoryLabel.inventory_id == inventory_id)
    if inventory_instance_id is not None:
        stmt = stmt.where(InventoryLabel.inventory_instance_id == inventory_instance_id)
    if not include_inactive:
        stmt = stmt.where(InventoryLabel.status == InventoryLabelStatus.ACTIVE.value)
    rows = list(session.exec(stmt.order_by(InventoryLabel.created_at.desc())).all())
    visible: list[dict] = []
    for label in rows:
        if user_can_access_inventory(
            session,
            current_user,
            label.inventory_id,
            is_manager=is_inventory_manager(current_user),
        ):
            visible.append(label_to_dict(session, label))
    return visible


@router.post("/print", response_model=list[schemas.InventoryLabelPrintEventRead])
def print_inventory_labels(
    body: schemas.InventoryLabelPrintRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _require_label_permission(current_user, "inventory.label.print")
    try:
        events = print_labels(
            session,
            label_ids=body.label_ids,
            label_format=inventory_label_code_type(session),
            quantity=body.quantity,
            reason=body.reason,
            actor=current_user,
        )
        session.commit()
        return events
    except (InventoryLabelError, IntegrityError) as exc:
        _commit_error(session, exc)


@router.get("/{label_id}/history", response_model=schemas.InventoryLabelHistoryRead)
def inventory_label_history(
    label_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    try:
        label, prints, scans = list_history(session, label_id)
        if not user_can_access_inventory(
            session,
            current_user,
            label.inventory_id,
            is_manager=is_inventory_manager(current_user),
        ):
            raise InventoryLabelError("You are not allowed to view this label")
        return {
            "label": label_to_dict(session, label),
            "print_events": prints,
            "scan_events": scans,
        }
    except InventoryLabelError as exc:
        _commit_error(session, exc)


@router.post("/scan", response_model=schemas.InventoryLabelScanResponse)
def scan_inventory_label(
    body: schemas.InventoryLabelScanRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    try:
        result = resolve_scan(
            session,
            payload=body.payload,
            actor=current_user,
            location=body.location,
            source=body.source,
        )
        session.commit()
        return result
    except InventoryLabelError as exc:
        _commit_error(session, exc)


@router.post("/{label_id}/deactivate", response_model=schemas.InventoryLabelRead)
def deactivate_inventory_label(
    label_id: str,
    body: schemas.InventoryLabelActionRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _require_label_permission(current_user, "inventory.label.manage")
    try:
        label = deactivate_label(session, label_id, actor=current_user, reason=body.reason)
        session.commit()
        return label_to_dict(session, label)
    except InventoryLabelError as exc:
        _commit_error(session, exc)


@router.post("/{label_id}/investigate", response_model=schemas.InventoryLabelRead)
def investigate_inventory_label(
    label_id: str,
    body: schemas.InventoryLabelActionRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _require_label_permission(current_user, "inventory.label.manage")
    try:
        label = session.exec(
            select(InventoryLabel).where(InventoryLabel.label_id == label_id)
        ).first()
        if not label:
            raise InventoryLabelError("Label not found")
        old_status = label.status
        label.status = InventoryLabelStatus.INVESTIGATION.value
        session.add(label)
        write_workflow_audit(
            session,
            action="LABEL_INVESTIGATION_STARTED",
            entity_type="inventory_label",
            entity_id=label_id,
            actor=current_user,
            remarks=body.reason.strip(),
            old_value={"status": old_status},
            new_value={"status": label.status},
        )
        session.commit()
        return label_to_dict(session, label)
    except InventoryLabelError as exc:
        _commit_error(session, exc)


@router.post("/{label_id}/replace", response_model=list[schemas.InventoryLabelRead])
def replace_inventory_label(
    label_id: str,
    body: schemas.InventoryLabelReplaceRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _require_label_permission(current_user, "inventory.label.manage")
    try:
        old, replacement = replace_label(
            session,
            label_id,
            actor=current_user,
            reason=body.reason,
            label_type=inventory_label_code_type(session),
        )
        session.commit()
        return [label_to_dict(session, old), label_to_dict(session, replacement)]
    except (InventoryLabelError, IntegrityError) as exc:
        _commit_error(session, exc)
