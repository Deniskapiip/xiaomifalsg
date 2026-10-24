from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import Principal, current_user, session
from app.errors import AppError
from app.models import Order
from app.schemas import OrderCreate, OrderOut, OrderPage, WriteAccessIn
from app.services.orders import create_order, find_order, find_tracked_order, order_output
from app.statuses import TERMINAL

router = APIRouter(tags=["Мои заказы"])


@router.post("/orders", response_model=OrderOut)
async def create(request: Request, data: OrderCreate, principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        order = await create_order(db, data, principal.user, request.app.state.settings)
        return await order_output(db, order)


@router.get("/orders", response_model=OrderPage)
async def list_orders(status_group: Literal["active", "completed"] | None = None,
                      limit: int = Query(default=20, ge=1, le=50), offset: int = Query(default=0, ge=0),
                      principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    query = select(Order).where(Order.user_id == principal.user.id)
    if status_group == "active":
        query = query.where(Order.status.not_in(TERMINAL))
    elif status_group == "completed":
        query = query.where(Order.status.in_(TERMINAL))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).offset(offset))).all()
    return OrderPage(items=[await order_output(db, value, include_events=False) for value in rows], total=total, limit=limit, offset=offset)


@router.get("/track", response_model=OrderOut)
async def track(number: str = Query(min_length=1, max_length=64),
                principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    order = await find_tracked_order(db, number, principal.user.id)
    if order is None:
        raise AppError("NOT_FOUND", "Заказ с таким трек-номером не найден", 404)
    return await order_output(db, order)


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    return await order_output(db, await find_order(db, order_id, principal.user.id))


@router.post("/me/write-access")
async def write_access(request: Request, data: WriteAccessIn, principal: Principal = Depends(current_user), db: AsyncSession = Depends(session)):
    async with request.app.state.write_lock:
        principal.user.can_write = data.allowed
        if data.allowed:
            from app.services.notifications import wake_write_access_jobs
            await wake_write_access_jobs(db, principal.user.id)
        await db.commit()
    return {"ok": True, "can_write": principal.user.can_write}
