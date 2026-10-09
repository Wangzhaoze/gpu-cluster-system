"""Administrator drafts/publication and durable per-member read receipts."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .auth import admin_user, current_user, member_user
from .db import get_db
from .models import Announcement, AnnouncementRead, AuditEvent, User, now
from .schemas import AnnouncementDraft

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


def public_announcement(item: Announcement):
    return {key: getattr(item, key) for key in (
        "id", "title", "body", "created_at", "updated_at", "published_at")}


def event(db, user, action, item):
    db.add(AuditEvent(user_id=user.id, action=action, target_type="announcement", target_id=item.id))


@router.get("")
def list_announcements(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Announcement)
    if user.role == "ADMIN":
        query = query.order_by(Announcement.created_at.desc(), Announcement.id)
    else:
        read = exists().where(AnnouncementRead.announcement_id == Announcement.id, AnnouncementRead.user_id == user.id)
        query = query.where(Announcement.published_at.is_not(None), ~read).order_by(Announcement.published_at, Announcement.id)
    return [public_announcement(item) for item in db.scalars(query)]


@router.post("", status_code=201)
def create_draft(spec: AnnouncementDraft, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = Announcement(**spec.model_dump(), created_by=user.id)
    db.add(item)
    db.flush()
    event(db, user, "announcement.create", item)
    db.commit()
    return public_announcement(item)


def locked_announcement(db, identifier):
    item = db.scalar(select(Announcement).where(Announcement.id == identifier).with_for_update())
    if not item:
        raise HTTPException(404, "公告不存在")
    return item


@router.patch("/{identifier}")
def edit_draft(identifier: str, spec: AnnouncementDraft, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = locked_announcement(db, identifier)
    if item.published_at:
        raise HTTPException(409, "已发布的公告不能修改，请新建公告")
    item.title, item.body = spec.title, spec.body
    event(db, user, "announcement.edit", item)
    db.commit()
    return public_announcement(item)


@router.post("/{identifier}/publish")
def publish(identifier: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = locked_announcement(db, identifier)
    if not item.published_at:
        item.published_at = now()
        event(db, user, "announcement.publish", item)
        db.commit()
    return public_announcement(item)


@router.post("/{identifier}/read")
def mark_read(identifier: str, user: User = Depends(member_user), db: Session = Depends(get_db)):
    # Row lock makes repeated/concurrent tab acknowledgments idempotent.
    item = locked_announcement(db, identifier)
    if not item.published_at:
        raise HTTPException(404, "公告尚未发布")
    if not db.get(AnnouncementRead, (item.id, user.id)):
        db.add(AnnouncementRead(announcement_id=item.id, user_id=user.id))
    db.commit()
    return {"ok": True}
