from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.tags.models import Tag, Taggable
from apps.tags.schemas import TagCreate, TagUpdate


def create_tag(db: Session, user_id: int, data: TagCreate) -> Tag:
    existing = db.execute(
        select(Tag).where(Tag.user_id == user_id, Tag.name == data.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="A tag with this name already exists. Please choose a different name.")

    tag = Tag(user_id=user_id, name=data.name, color=data.color)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def list_tags(db: Session, user_id: int) -> list[Tag]:
    result = db.execute(select(Tag).where(Tag.user_id == user_id))
    return list(result.scalars().all())


def update_tag(db: Session, user_id: int, tag_id: int, data: TagUpdate) -> Tag:
    tag = db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
    ).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="We couldn't find the requested tag. It may have been deleted.")

    if data.name is not None:
        # Check for duplicate name when renaming
        duplicate = db.execute(
            select(Tag).where(
                Tag.user_id == user_id, Tag.name == data.name, Tag.id != tag_id
            )
        ).scalar_one_or_none()
        if duplicate:
            raise HTTPException(
                status_code=400, detail="A tag with this name already exists. Please choose a different name."
            )
        tag.name = data.name

    if data.color is not None:
        tag.color = data.color

    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, user_id: int, tag_id: int) -> None:
    tag = db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
    ).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="We couldn't find the requested tag. It may have been deleted.")

    # Delete all taggable entries referencing this tag
    db.execute(
        Taggable.__table__.delete().where(Taggable.tag_id == tag_id)
    )
    db.delete(tag)
    db.commit()


def get_or_create_tag(
    db: Session, user_id: int, name: str, color: str = "#3b82f6"
) -> Tag:
    tag = db.execute(
        select(Tag).where(Tag.user_id == user_id, Tag.name == name)
    ).scalar_one_or_none()
    if tag:
        return tag

    tag = Tag(user_id=user_id, name=name, color=color)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag
