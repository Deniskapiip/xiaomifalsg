import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_types import utcnow
from app.deps import Principal, current_user, session
from app.errors import AppError
from app.models import TrackingLink
from app.schemas import TrackingIn, TrackingOut
from app.services.tracking import COOLDOWN_MINUTES, refresh_link_by_id

router = APIRouter(prefix="/tracking", tags=["Трекинг"])


async def _own_link(db, link_id: int, user_id: int) -> TrackingLink:
    link = await db.get(TrackingLink, link_id)
    if link is None or link.user_id != user_id:
        raise AppError("NOT_FOUND", "Трек-номер не найден", 404)
    return link


@router.get("", response_model=list[TrackingOut])
async def list_tracking(principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    rows = (await db.scalars(select(TrackingLink).where(TrackingLink.user_id == principal.user.id)
                             .order_by(TrackingLink.created_at.desc(), TrackingLink.id.desc()))).all()
    return list(rows)


@router.post("", response_model=TrackingOut)
async def add_tracking(request: Request, data: TrackingIn,
                       principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    settings = request.app.state.settings
    async with request.app.state.write_lock:
        existing = await db.scalar(select(TrackingLink).where(
            TrackingLink.user_id == principal.user.id, TrackingLink.provider == "dobropost",
            TrackingLink.track_number == data.track_number))
        if existing is not None:
            return existing
        link = TrackingLink(user_id=principal.user.id, track_number=data.track_number)
        db.add(link)
        await db.commit()
        await db.refresh(link)
        link_id = link.id
    # Не задерживаем ответ: статус подтянется фоновой проверкой.
    asyncio.create_task(refresh_link_by_id(request.app.state.sessions, link_id, settings))
    return link


@router.delete("/{link_id}")
async def delete_tracking(request: Request, link_id: int,
                          principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        link = await _own_link(db, link_id, principal.user.id)
        await db.delete(link)
        await db.commit()
    return {"ok": True}


@router.post("/{link_id}/refresh", response_model=TrackingOut)
async def refresh_tracking(request: Request, link_id: int,
                           principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    link = await _own_link(db, link_id, principal.user.id)
    if link.last_checked_at is not None:
        elapsed = (utcnow() - link.last_checked_at).total_seconds()
        if elapsed < COOLDOWN_MINUTES * 60:
            raise AppError("TRACKING_COOLDOWN",
                           f"Статус обновляли недавно. Повторите через {COOLDOWN_MINUTES} минут.", 429)
    refreshed = await refresh_link_by_id(request.app.state.sessions, link_id, request.app.state.settings)
    if refreshed is None:
        raise AppError("NOT_FOUND", "Трек-номер не найден", 404)
    return refreshed
