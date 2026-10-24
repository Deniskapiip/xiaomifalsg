"""Автосмена статусов заказа по трек-номеру Добропоста.

Пока заказ в ручной зоне (оформляется … на складе) статусы ставит владелец.
После «Ожидает оплаты доставки» менеджер добавляет трек-номер Добропоста,
и дальше фоновая задача раз в TRACKING_REFRESH_HOURS часов двигает статус
заказа вперёд по данным официального трекинг-API.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from app.db_types import utcnow
from app.models import Order, OrderEvent
from app.services.tracking import fetch_status
from app.statuses import BY_KEY, Status, TERMINAL

log = logging.getLogger("taoji")

AUTO_ZONE = {
    Status.awaiting_delivery_payment,
    Status.to_cn_customs,
    Status.cn_customs,
    Status.to_ru_customs,
    Status.ru_customs,
    Status.to_recipient,
    Status.delivered,
}


def map_provider_status(raw: str) -> Status | None:
    """Map a DobroPost status phrase to our order status (conservative).

    Реальные русские статусы Добропоста (пример доставленной посылки):
    «Посылка доставлена получателю», «Покинула таможню и передана на доставку по РФ»,
    «Подготовлено к отгрузке в доставку последней мили», «Таможенное оформление посылки завершено»,
    «Начало таможенного оформления», «Поступила на таможню в стране назначения»,
    «На таможне в Китае», «Ожидает оплату», «На складе», «Выкуплен».
    """
    text = (raw or "").lower()
    if any(word in text for word in ("доставлен", "получен", "вручен", "выдан", "delivered")):
        return Status.delivered
    if any(word in text for word in ("передана на доставку", "доставку последней мили", "курьер",
                                     "в пути до получателя", "out for delivery", "left_customs",
                                     "last_mile")):
        return Status.to_recipient
    if "тамож" in text:
        return Status.cn_customs if any(word in text for word in ("кита", "china")) else Status.ru_customs
    if any(word in text for word in ("ожидает оплату", "awaiting_payment")):
        return Status.awaiting_delivery_payment
    if any(word in text for word in ("на складе", "склад", "warehouse", "прибыл")):
        return Status.at_cn_warehouse
    if any(word in text for word in ("выкуп", "куплен", "purchased", "ожидает отправк", "реестр",
                                     "комплектац", "взвешиван")):
        return Status.purchased
    if any(word in text for word in ("оформл", "создан", "принят", "processing")):
        return Status.processing
    return None


def should_advance(current: str, target: Status) -> bool:
    """Статус заказа идёт вперёд по данным Добропоста из любого нетерминального этапа.

    Раньше авто-зона начиналась только с «Ожидает оплаты доставки», но на практике
    менеджер может ввести трек раньше — и клиент должен видеть реальный этап
    («На таможне в России», «В пути до получателя»), а не «Оформляется».
    """
    if current in TERMINAL:
        return False
    if target == Status.cancelled:
        return False
    return BY_KEY[target]["order"] > BY_KEY[current]["order"]


async def refresh_order(db, order: Order, settings, fast: bool = False) -> bool:
    """Check the carrier once; advance the order status when it is safe. Returns True if status changed."""
    hours = max(1, int(settings.tracking_refresh_hours))
    status_text, ok = await fetch_status(order.track_number, settings, fast=fast)
    order.tracking_checked_at = utcnow()
    order.tracking_next_check_at = utcnow() + timedelta(hours=hours)
    changed = False
    if ok and status_text:
        order.tracking_status_text = status_text[:200]
        target = map_provider_status(status_text)
        if target is not None and should_advance(order.status, target):
            previous = order.status
            order.status = target.value
            order.updated_at = utcnow()
            event = OrderEvent(order_id=order.id, actor_user_id=None, type="status_changed",
                               from_status=previous, to_status=target.value,
                               payload={"notify": True, "source": "dobropost",
                                        "provider_status": status_text[:200]})
            db.add(event)
            await db.flush()
            from app.services.orders import queue_notification, queue_review_reminder
            await queue_notification(db, event, order.user_id, target.value)
            if target == Status.delivered:
                await queue_review_reminder(db, order, settings)
            changed = True
            log.info("order_tracking_status order=%s %s->%s", order.id, previous, target.value)
    await db.commit()
    return changed


class OrderTrackingWorker:
    """Раз в минуту проверяет заказы, у которых подошло время проверки трека."""

    def __init__(self, sessions, settings):
        self.sessions, self.settings = sessions, settings

    async def refresh_due(self, limit: int = 10) -> int:
        async with self.sessions() as db:
            ids = list((await db.scalars(
                select(Order.id).where(
                    Order.track_number.is_not(None), Order.track_number != "",
                    Order.status.not_in([Status.delivered.value, Status.cancelled.value]),
                    or_(Order.tracking_next_check_at.is_(None), Order.tracking_next_check_at <= utcnow()),
                ).order_by(Order.tracking_next_check_at, Order.id).limit(limit)
            )).all())
        refreshed = 0
        for order_id in ids:
            async with self.sessions() as db:
                order = await db.get(Order, order_id)
                if order is None or not order.track_number:
                    continue
                try:
                    await refresh_order(db, order, self.settings)
                except Exception as exc:  # noqa: BLE001 - фоновый процесс не падает
                    log.error("order_tracking_error order=%s type=%s", order_id, type(exc).__name__)
                    order.tracking_next_check_at = utcnow() + timedelta(hours=1)
                    await db.commit()
                    continue
                refreshed += 1
        return refreshed

    async def run(self) -> None:
        while True:
            try:
                await self.refresh_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("order_tracking_worker_error type=%s", type(exc).__name__)
            await asyncio.sleep(60)
