# 2️⃣ Service: Update Entity Status
# This updates current status in the entity table.

from app.models.tables import (Entity)
from sqlmodel import Session, select
from typing import Optional
from fastapi import HTTPException
from app.services.create_entitystatusHistory import create_status_history
from app.schemas import schemas



def update_entity_status(session: Session, entity:any, entity_name: Optional[str], changed_by_user: int):

    updated_entity = session.exec(
        select(Entity).where(
            Entity.entity_type == entity_name,
            Entity.entity_pk == entity.id
        )
    ).first()
    if not entity:
        raise HTTPException(status_code=404, detail = "Entity Record not found")
        return None
    print("updated_entity",updated_entity)
    updated_entity.status_id = entity.status_id

    session.add(updated_entity)
    session.flush()

    if entity.status_id is not None:
        create_status_history(
            session=session,
            history_data=schemas.EntityStatusHistoryCreate(
                entity_id=updated_entity.id,
                status_id=updated_entity.status_id,
                changed_by=changed_by_user
            )
        )
    return updated_entity