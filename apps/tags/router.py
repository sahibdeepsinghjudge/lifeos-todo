from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from apps.tags import service
from apps.tags.schemas import TagCreate, TagResponse, TagUpdate
from core.database import get_db
from core.security import get_current_user

router = APIRouter(prefix="/tags", tags=["Tags"])


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(
    data: TagCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.create_tag(db, current_user.id, data)


@router.get("", response_model=list[TagResponse])
def list_tags(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.list_tags(db, current_user.id)


@router.put("/{id}", response_model=TagResponse)
def update_tag(
    id: int,
    data: TagUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.update_tag(db, current_user.id, id, data)


@router.delete("/{id}")
def delete_tag(
    id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service.delete_tag(db, current_user.id, id)
    return {"detail": "Tag deleted"}
