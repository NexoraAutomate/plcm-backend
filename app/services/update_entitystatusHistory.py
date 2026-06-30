# 2️⃣ Service: Update Entity Status
# This updates current status in the entity table.

from app.models.tables import (EntityStatusHistory)
from sqlmodel import Session, select


def update_entity_status(
    session: Session,
    entity_id: int,
    new_status_id: int,
    changed_by: int
):

    entity = session.exec(
        select(EntityStatusHistory).where(
            EntityStatusHistory.entity_id == entity_id,
            EntityStatusHistory.status_id == new_status_id
        )
    ).first()

    if not entity:
        return None

    entity.status_id = new_status_id

    session.add(entity)
    session.commit()
    session.refresh(entity)

    return entity