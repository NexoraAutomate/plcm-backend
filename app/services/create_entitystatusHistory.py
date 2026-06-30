from app.models.tables import (EntityStatusHistory)
from sqlmodel import Session
from datetime import datetime, timezone
from app.schemas import schemas

def create_status_history(session: Session, history_data: schemas.EntityStatusHistoryCreate):

    history = EntityStatusHistory(**history_data.model_dump())
    session.add(history)
    session.flush()
    return history