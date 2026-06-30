from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.schemas import schemas
from app.routers.auth import require_permission
from app.models.helpers import _generate_Entity_Code
from app.models.tables import FaultyEntity, MaintenanceCase, Component, Unit, Module, Subsystem, System, Project, Order, Customer, User
from app.services.create_entity import New_entity
from app.config.entities import ENTITY_CONFIG
from app.services.update_entity import update_entity_status
entity_config = ENTITY_CONFIG.get("customer")


router = APIRouter()

# ===================== CUSTOMER ENDPOINTS =====================
@router.post("/customers/", response_model=schemas.CustomerRead, tags=["customers"])
def create_customer(customer: schemas.CustomerCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_customers"))):
    db_customer = Customer(**customer.model_dump())
    db_customer.customer_code = _generate_Entity_Code(session, Customer)
    session.add(db_customer)

    session.flush()

    # 1. Create Entity status    2. maintain Status History
    # --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_customer, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
    # --------------------------------------------------------------------------------------------------------------------------------------------

    session.commit()
    session.refresh(db_customer)
    status_name = db_customer.status.status_name if db_customer.status else None
    return schemas.CustomerRead(
        **db_customer.model_dump(),
        status_name=status_name,
    )
    # return db_customer

@router.get("/customers/", response_model=List[schemas.CustomerRead], tags=["customers"])
def list_customers(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_customers"))):
    customers= session.exec(select(Customer).offset(skip).limit(limit)).all()
    result = []
    for customer in customers:
        status_name = customer.status.status_name if customer.status_id else None
        result.append(schemas.CustomerRead(
            **customer.model_dump(),
            status_name=status_name,
        ))
    return result

@router.get("/customers/{customer_id}/", response_model=schemas.CustomerRead, tags=["customers"])
def get_customer(customer_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_customers"))):
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    status_name = customer.status.status_name if customer.status_id else None
    return schemas.CustomerRead(
        **customer.model_dump(),
        status_name=status_name,
    )

@router.put("/customers/{customer_id}/", response_model=schemas.CustomerRead, tags=["customers"])
def update_customer(customer_id: int, customer: schemas.CustomerUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_customers"))):
    db_customer = session.get(Customer, customer_id)
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for k, v in customer.model_dump(exclude_unset=True).items():
        setattr(db_customer, k, v)
    session.add(db_customer)
    session.flush()

 # 1. Create Entity status    2. maintain Status History
    # --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity=db_customer, entity_name = entity_config["display_name"], changed_by_user= current_user.id)

    # --------------------------------------------------------------------------------------------------------------------------------------------
    session.commit()
    session.refresh(db_customer)
    status_name = db_customer.status.status_name if db_customer.status_id else None
    return schemas.CustomerRead(
            **db_customer.model_dump(),
            status_name=status_name,
        )

    # return db_customer

@router.delete("/customers/{customer_id}/", tags=["customers"])
def delete_customer(customer_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_customers"))):
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    session.delete(customer)
    session.commit()
    return {"ok": True}

@router.get("/customers/{customer_id}/orders/", response_model=List[schemas.OrderRead], tags=["customers"])
def list_customer_orders(customer_id: int, session: Session = Depends(get_session)):
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    result = []
    for order in customer.orders:
        status_name = order.status.status_name if order.status else None
        result.append(schemas.OrderRead(
            **order.model_dump(),
            status_name=status_name,
        ))
    return result