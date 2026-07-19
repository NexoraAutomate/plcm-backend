from typing import List
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Order, User)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.create_entitystatusHistory import create_status_history
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.routers.auth import require_permission
from app.services.pagination import paginated_query
from app.models.helpers import _generate_Entity_Code

entity_config = ENTITY_CONFIG.get("order")

router = APIRouter()
# ===================== ORDER ENDPOINTS =====================

@router.post("/orders/", response_model=schemas.OrderRead, tags=["orders"])
def create_order(order: schemas.OrderCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_orders"))):
    db_order = Order(**order.model_dump())
    db_order.order_number = _generate_Entity_Code(session, Order)
    session.add(db_order)
    session.flush()

# 1. Create Entity status    2. maintain Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_order, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------
    session.commit()
    session.refresh(db_order)
    # Attach status_name for response
    status_name = db_order.status.status_name if db_order.status else None
    return schemas.OrderRead(
        **db_order.model_dump(),
        status_name=status_name,
    )

@router.get("/orders/", response_model=List[schemas.OrderRead], tags=["orders"])
def list_orders(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_orders")),
):
    def to_read(order: Order) -> schemas.OrderRead:
        status_name = order.status.status_name if order.status else None
        return schemas.OrderRead(
            **order.model_dump(),
            status_name=status_name,
        )

    return paginated_query(
        session,
        Order,
        skip,
        limit,
        response,
        transform=to_read,
        sort_by=sort_by,
        sort_order=sort_order,
    )

@router.get("/orders/{order_id}/", response_model=schemas.OrderRead, tags=["orders"])
def get_order(order_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_orders"))):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    status_name = order.status.status_name if order.status else None
    return schemas.OrderRead(
        **order.model_dump(),
        status_name=status_name,
    )

@router.put("/orders/{order_id}/", response_model=schemas.OrderRead, tags=["orders"])
def update_order(order_id: int, order: schemas.OrderUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_orders"))):
    db_order = session.get(Order, order_id)
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")
    for k, v in order.model_dump(exclude_unset=True).items():
        setattr(db_order, k, v)
    session.add(db_order)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_order, entity_name = entity_config["display_name"],changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------
    session.commit()
    session.refresh(db_order)
    status_name = db_order.status.status_name if db_order.status else None
    return schemas.OrderRead(
        **db_order.model_dump(),
        status_name=status_name,
    )

@router.delete("/orders/{order_id}/", tags=["orders"])
def delete_order(order_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_orders"))):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    session.delete(order)
    session.commit()
    return {"ok": True}

@router.get("/orders/{order_id}/projects/", response_model=List[schemas.ProjectRead], tags=["orders"])
def list_order_projects(order_id: int, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order.projects
