from app.models.tables import (Entity)
from sqlmodel import Field
from datetime import datetime, timezone
from app.schemas import schemas
from app.services.create_entitystatusHistory import create_status_history


def New_entity(session, entity:any, entity_name:str, changed_by_user: int) -> Entity:

    entity_data=schemas.EntityCreate(
            name=f"{entity_name}-{entity.id}",
            display_name=f"{entity_name}-{entity.id}",
            entity_type=entity_name,
            entity_pk=entity.id,
            status_id=entity.status_id
        )


    db_entity = Entity(**entity_data.model_dump())
    session.add(db_entity)
    session.flush()

    if entity.status_id is not None:
        create_status_history(
            session=session,
            history_data=schemas.EntityStatusHistoryCreate(
                entity_id=db_entity.id,
                status_id=entity.status_id,
                changed_by=changed_by_user
            )
        )
    return db_entity