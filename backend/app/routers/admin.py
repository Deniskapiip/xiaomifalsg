from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Literal
from decimal import Decimal, localcontext

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_types import utcnow
from app.deps import Principal, administrator, owner, session
from app.errors import AppError
from app.models import Order, Tariff, User
from app.schemas import (AdminOrderOut, AdminOrderPage, DashboardOut, NoteIn, SettingsIn, SettingsOut, StatusIn,
                         TariffIn, TariffOut, TrackSetIn)
from app.services.orders import change_note, change_status, change_track, find_order, order_output
from app.services.settings import get_app_settings, save_tariff, settings_output, update_settings
from app.statuses import Status

router = APIRouter(prefix="/admin", tags=["Администрирование"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    now = utcnow()
    midnight = datetime.combine(now.astimezone(ZoneInfo("Europe/Moscow")).date(), time.min, tzinfo=ZoneInfo("Europe/Moscow")).astimezone(timezone.utc)
    grouped = (await db.execute(select(Order.status, func.count()).group_by(Order.status))).all()
    counts = {status.value: 0 for status in Status}
    counts.update(dict(grouped))
    new_today = await db.scalar(select(func.count()).select_from(Order).where(Order.created_at >= midnight))
    stale, stats = None, None
    if principal.role == "owner":
        current = await get_app_settings(db)
        stale = now - current.rate_updated_at > timedelta(hours=24)
        # Exact integer sums. These are order totals, not confirmed revenue/payments.
        amounts = (await db.execute(select(Order.total_rub, Order.commission_rub).where(Order.status != Status.cancelled))).all()
        with localcontext() as context:
            context.prec = 50
            total_rub = sum((Decimal(row[0]) for row in amounts), Decimal(0))
            commission_rub = sum((Decimal(row[1]) for row in amounts), Decimal(0))
        stats = {"orders_total_rub": format(total_rub, "f"), "calculated_commission_rub": format(commission_rub, "f")}
    return DashboardOut(counts=counts, new_today=new_today,
                        requires_action=counts[Status.processing] + counts[Status.at_cn_warehouse],
                        total_orders=sum(counts.values()), rate_stale=stale, stats=stats)


@router.get("/orders", response_model=AdminOrderPage)
async def list_admin_orders(status: Status | None = None, q: str = Query(default="", max_length=2000),
                            limit: int = Query(default=20, ge=1, le=50), offset: int = Query(default=0, ge=0),
                            sort: Literal["newest", "oldest"] = "newest",
                            _principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    query = select(Order).join(User, User.id == Order.user_id)
    if status:
        query = query.where(Order.status == status)
    if q.strip():
        term = q.strip().removeprefix("@")
        query = query.where(or_(Order.public_no.icontains(term, autoescape=True), User.username.icontains(term, autoescape=True), Order.link.icontains(term, autoescape=True)))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    ordering = (Order.created_at.asc(), Order.id.asc()) if sort == "oldest" else (Order.created_at.desc(), Order.id.desc())
    rows = (await db.scalars(query.order_by(*ordering).limit(limit).offset(offset))).all()
    return AdminOrderPage(items=[await order_output(db, row, admin=True, include_events=False) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/orders/{order_id}", response_model=AdminOrderOut)
async def admin_order(order_id: int, _principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    return await order_output(db, await find_order(db, order_id), admin=True)


@router.post("/orders/{order_id}/status", response_model=AdminOrderOut)
async def status_change(request: Request, order_id: int, data: StatusIn,
                        principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        order = await find_order(db, order_id)
        await change_status(db, order, data, principal.user.id, request.app.state.settings)
        return await order_output(db, order, admin=True)


@router.patch("/orders/{order_id}/note", response_model=AdminOrderOut)
async def note_change(request: Request, order_id: int, data: NoteIn,
                      principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        order = await find_order(db, order_id)
        await change_note(db, order, data.note, principal.user.id)
        return await order_output(db, order, admin=True)


@router.post("/orders/{order_id}/tracking", response_model=AdminOrderOut)
async def tracking_change(request: Request, order_id: int, data: TrackSetIn,
                          principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        order = await find_order(db, order_id)
        await change_track(db, order, data, principal.user.id)
        # Сохранили трек — сразу проверяем Добропост, чтобы статус изменился в этом же ответе.
        if order.track_number and request.app.state.settings.order_tracking_enabled \
                and request.app.state.settings.tracking_immediate_refresh:
            from app.services.order_tracking import refresh_order
            try:
                await refresh_order(db, order, request.app.state.settings, fast=True)
            except Exception:  # noqa: BLE001 - сеть не должна мешать сохранению трека
                pass
            await db.refresh(order)
        return await order_output(db, order, admin=True)


@router.post("/orders/{order_id}/tracking/refresh", response_model=AdminOrderOut)
async def tracking_refresh(request: Request, order_id: int,
                           principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    """Ручная проверка трека Добропоста: сразу видно, обновился ли статус заказа."""
    order = await find_order(db, order_id)
    if not order.track_number:
        raise AppError("TRACKING_EMPTY", "У заказа нет трек-номера", 409)
    from app.services.order_tracking import refresh_order
    await refresh_order(db, order, request.app.state.settings)
    await db.refresh(order)
    return await order_output(db, order, admin=True)


@router.post("/tracking/refresh-all")
async def tracking_refresh_all(request: Request,
                               principal: Principal = Depends(administrator), db: AsyncSession = Depends(session)):
    """Проверить все активные заказы с трек-номерами (до 20 за вызов)."""
    from app.services.order_tracking import refresh_order
    orders = (await db.scalars(
        select(Order).where(Order.track_number.is_not(None), Order.track_number != "",
                            Order.status.not_in([Status.delivered.value, Status.cancelled.value]))
        .order_by(Order.tracking_next_check_at, Order.id).limit(20)
    )).all()
    changed = checked = 0
    for order in orders:
        try:
            if await refresh_order(db, order, request.app.state.settings):
                changed += 1
            checked += 1
        except Exception:  # noqa: BLE001 - один заказ не должен ломать остальные
            continue
    return {"checked": checked, "changed": changed, "total": len(orders)}


@router.get("/settings", response_model=SettingsOut)
async def get_settings(_principal: Principal = Depends(owner), db: AsyncSession = Depends(session)):
    return await settings_output(db)


@router.put("/settings", response_model=SettingsOut)
async def put_settings(request: Request, data: SettingsIn, principal: Principal = Depends(owner), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        return await update_settings(db, data, principal.user.id)


@router.get("/tariffs", response_model=list[TariffOut])
async def tariffs(_principal: Principal = Depends(owner), db: AsyncSession = Depends(session)):
    return (await db.scalars(select(Tariff).order_by(Tariff.sort_order, Tariff.id))).all()


@router.post("/tariffs", response_model=TariffOut)
async def create_tariff(request: Request, data: TariffIn, _principal: Principal = Depends(owner), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        return await save_tariff(db, data)


@router.put("/tariffs/{tariff_id}", response_model=TariffOut)
async def edit_tariff(request: Request, tariff_id: int, data: TariffIn, _principal: Principal = Depends(owner), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        return await save_tariff(db, data, tariff_id)
