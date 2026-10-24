from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, localcontext

from sqlalchemy import func, or_, select

from app.db_types import utcnow
from app.errors import AppError
from app.models import NotificationJob, NotificationLog, Order, OrderEvent, OrderItem, User
from app.platforms import identify_platform
from app.schemas import (AdminEventOut, AdminOrderOut, EventOut, NotificationOut, OrderCreate, OrderItemIn,
                         OrderItemOut, OrderOut, StatusIn, TrackSetIn, UserOut)
from app.services.notifications import is_local_preview_order
from app.services.pricing import calculate, rub_per_kg
from app.services.settings import active_tariff, get_app_settings
from app.statuses import Status, requires_confirmation


def normalized_items(data: OrderCreate) -> list[OrderItemIn]:
    """Multi-item order or the legacy single-item payload."""
    if data.items:
        return list(data.items)
    # Legacy fields are already validated Decimals; OrderItemIn expects strings.
    return [OrderItemIn(link=data.link, price_cny=format(data.price_cny, "f"), quantity=data.quantity or 1,
                        item_title=data.item_title, comment=data.comment)]


def item_output(item: OrderItem, rate: Decimal) -> OrderItemOut:
    with localcontext() as context:
        context.prec = 50
        goods = int((item.price_cny * item.quantity * rate).to_integral_value(rounding=ROUND_CEILING))
    return OrderItemOut(id=item.id, position=item.position, link=item.link, platform=item.platform,
                        item_title=item.item_title, price_cny=item.price_cny, quantity=item.quantity,
                        comment=item.comment, goods_rub=goods)


async def find_order(db, order_id: int, user_id: int | None = None):
    query = select(Order).where(Order.id == order_id)
    if user_id is not None:
        query = query.where(Order.user_id == user_id)
    value = await db.scalar(query)
    if value is None:
        raise AppError("NOT_FOUND", "Заказ не найден", 404)
    return value


def normalize_track_query(value: str) -> str:
    return "".join(value.split()).casefold()


async def find_tracked_order(db, number: str, user_id: int | None = None):
    compact = normalize_track_query(number)
    if not compact:
        return None
    query = select(Order).where(or_(
        func.replace(func.lower(func.coalesce(Order.track_number, "")), " ", "") == compact,
        func.replace(func.lower(Order.public_no), " ", "") == compact))
    if user_id is not None:
        query = query.where(Order.user_id == user_id)
    return await db.scalar(query.order_by(Order.created_at.desc(), Order.id.desc()).limit(1))


async def queue_notification(db, event: OrderEvent, recipient_id: int, kind: str):
    if await is_local_preview_order(db, event.order_id):
        return
    db.add(NotificationJob(event_id=event.id, user_id=recipient_id, order_id=event.order_id, kind=kind))


async def queue_review_reminder(db, order: Order, settings):
    """Одно напоминание об отзыве через REVIEW_REMINDER_HOURS после «Доставлен»."""
    if settings is None or not getattr(settings, "review_reminder_enabled", True):
        return
    if await is_local_preview_order(db, order.id):
        return
    exists = await db.scalar(select(NotificationJob.id).where(
        NotificationJob.order_id == order.id, NotificationJob.kind == "review_reminder"))
    if exists is not None:
        return
    event = OrderEvent(order_id=order.id, actor_user_id=None, type="review_reminder",
                       payload={"hours": settings.review_reminder_hours})
    db.add(event)
    await db.flush()
    db.add(NotificationJob(event_id=event.id, user_id=order.user_id, order_id=order.id,
                           kind="review_reminder",
                           next_attempt_at=utcnow() + timedelta(hours=settings.review_reminder_hours)))


async def create_order(db, data: OrderCreate, user: User, settings):
    existing = await db.scalar(select(Order).where(Order.idempotency_key == str(data.idempotency_key)))
    if existing is not None:
        if existing.user_id != user.id:
            raise AppError("IDEMPOTENCY_CONFLICT", "Ключ оформления уже использован. Повторите оформление с новым ключом.", 409)
        return existing
    count = await db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id, Order.created_at >= utcnow() - timedelta(hours=1)))
    if count >= 10:
        raise AppError("ORDER_RATE_LIMITED", "Можно оформить не более 10 заказов за час. Подождите перед новым заказом.", 429)
    tariff = await active_tariff(db, data.tariff_id)
    current = await get_app_settings(db)
    price_per_kg_rub = rub_per_kg(tariff.price_per_kg, tariff.price_currency, current.rate_cny_rub)
    insurance_enabled = data.insurance_enabled and tariff.insurance_available
    items = normalized_items(data)
    total_cny = sum((Decimal(item.price_cny) * item.quantity for item in items), Decimal(0))
    first = items[0]
    prices = calculate(total_cny, 1, current.rate_cny_rub, current.commission_percent,
                       current.commission_min_rub, price_per_kg_rub, data.weight_kg,
                       insurance_enabled=insurance_enabled, packing_enabled=data.packing_enabled,
                       photo_report_enabled=data.photo_report_enabled, insurance_percent=settings.insurance_percent,
                       packing_fee_rub=settings.packing_fee_rub, photo_report_fee_rub=settings.photo_report_fee_rub,
                       boxes=data.boxes)
    order = Order(user_id=user.id, idempotency_key=str(data.idempotency_key), link=first.link,
                  platform=identify_platform(first.link).value, item_title=first.item_title, price_cny=total_cny,
                  quantity=1, comment=first.comment, tariff_id=tariff.id, tariff_name=tariff.name,
                  tariff_price_per_kg=price_per_kg_rub, tariff_price_currency=tariff.price_currency,
                  tariff_price_value=tariff.price_per_kg, rate=current.rate_cny_rub,
                  commission_percent=current.commission_percent, commission_min_rub=current.commission_min_rub,
                  weight_kg=data.weight_kg, boxes=data.boxes, goods_rub=prices.goods_rub,
                  commission_rub=prices.commission_rub, total_rub=prices.total_rub,
                  delivery_estimate_rub=prices.delivery_estimate_rub, status=Status.processing,
                  insurance_enabled=insurance_enabled, packing_enabled=data.packing_enabled,
                  photo_report_enabled=data.photo_report_enabled, insurance_rub=prices.insurance_rub,
                  packing_rub=prices.packing_rub, photo_report_rub=prices.photo_report_rub,
                  extras_total_rub=prices.extras_total_rub, total_with_extras_rub=prices.total_with_extras_rub)
    db.add(order)
    await db.flush()
    order.public_no = f"TC-{order.id:06d}"
    for position, item in enumerate(items):
        db.add(OrderItem(order_id=order.id, position=position, link=item.link,
                         platform=identify_platform(item.link).value, item_title=item.item_title,
                         price_cny=item.price_cny, quantity=item.quantity, comment=item.comment))
    local_preview = settings.dev_mode and user.tg_id == settings.dev_user_tg_id
    payload = {"options": {"insurance": insurance_enabled, "packing": data.packing_enabled,
                           "photo_report": data.photo_report_enabled},
               "extras_total_rub": str(prices.extras_total_rub), "boxes": data.boxes,
               "tariff_price_currency": tariff.price_currency,
               "tariff_price_value": str(tariff.price_per_kg),
               "items": len(items), "items_total_cny": str(total_cny)}
    if local_preview:
        payload["local_preview"] = True
    event = OrderEvent(order_id=order.id, actor_user_id=user.id, type="created", to_status=Status.processing,
                       payload=payload)
    db.add(event)
    await db.flush()
    if not local_preview:
        await queue_notification(db, event, user.id, "created")
        for tg_id in sorted(settings.owner_id_set | settings.manager_id_set):
            recipient = await db.scalar(select(User).where(User.tg_id == tg_id))
            if recipient is None:
                recipient = User(tg_id=tg_id, first_name="Администратор", can_write=False)
                db.add(recipient)
                await db.flush()
            await queue_notification(db, event, recipient.id, "admin_created")
    await db.commit()
    return order


async def change_status(db, order: Order, data: StatusIn, actor_id: int, settings=None):
    if requires_confirmation(order.status, data.status) and not data.confirmed:
        raise AppError("CONFIRMATION_REQUIRED", "Подтвердите откат статуса или отмену заказа", 409)
    previous = order.status
    order.status = data.status.value
    order.updated_at = utcnow()
    event = OrderEvent(order_id=order.id, actor_user_id=actor_id, type="status_changed", from_status=previous,
                       to_status=data.status.value, payload={"notify": data.notify})
    if data.status == Status.awaiting_delivery_payment:
        old_amount = order.delivery_final_rub
        order.delivery_final_rub = int(data.delivery_amount_rub)
        event.payload = {"notify": data.notify, "delivery_amount_rub": str(order.delivery_final_rub)}
        db.add(OrderEvent(order_id=order.id, actor_user_id=actor_id, type="delivery_amount_set",
                          from_status=previous, to_status=data.status.value,
                          payload={"old_amount_rub": None if old_amount is None else str(old_amount),
                                   "delivery_amount_rub": str(order.delivery_final_rub)}))
    if data.status == Status.cancelled:
        reason = " ".join((data.reason or "").split())[:500]
        if reason:
            event.payload = {**event.payload, "cancel_reason": reason}
    db.add(event)
    await db.flush()
    if data.notify:
        await queue_notification(db, event, order.user_id, data.status.value)
        if data.status == Status.delivered:
            await queue_review_reminder(db, order, settings)
    await db.commit()
    return order


async def change_note(db, order: Order, note: str, actor_id: int):
    order.manager_note = note
    order.updated_at = utcnow()
    db.add(OrderEvent(order_id=order.id, actor_user_id=actor_id, type="note", payload={"note": note}))
    await db.commit()


async def change_track(db, order: Order, data: TrackSetIn, actor_id: int):
    number = " ".join(data.number.split())
    order.track_number = number or None
    order.tracking_status_text = ""
    order.tracking_checked_at = None
    # Новый номер проверяем сразу (в течение минуты), очистка снимает расписание.
    order.tracking_next_check_at = utcnow() if number else None
    order.updated_at = utcnow()
    event = OrderEvent(order_id=order.id, actor_user_id=actor_id, type="tracking",
                       payload={"track_number": number})
    db.add(event)
    await db.flush()
    if data.notify:
        await queue_notification(db, event, order.user_id, "tracking")
    await db.commit()
    return order


async def order_output(db, order: Order, admin: bool = False, include_events: bool = True):
    # Do not touch the lazy ORM relationship: in async SQLAlchemy it would raise
    # MissingGreenlet. Build the schema from columns and attach items explicitly.
    data = {name: getattr(order, name) for name in OrderOut.model_fields if name not in {"items", "events"}}
    result = OrderOut(**data)
    rows = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)
                             .order_by(OrderItem.position, OrderItem.id))).all()
    result.items = [item_output(row, order.rate) for row in rows]
    events = []
    if include_events:
        query = select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.created_at, OrderEvent.id)
        if not admin:
            query = query.where(OrderEvent.type.not_in(["note", "review_reminder"]))
        events = (await db.scalars(query)).all()
    if not admin:
        result.events = [EventOut.model_validate(event) for event in events]
        return result
    user_ids = {order.user_id} | {event.actor_user_id for event in events if event.actor_user_id is not None}
    users = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
    users_by_id = {user.id: UserOut.model_validate(user) for user in users}
    logs = (await db.scalars(select(NotificationLog).where(NotificationLog.order_id == order.id).order_by(NotificationLog.created_at, NotificationLog.id))).all()
    client_kinds = {}
    for log in logs:
        if log.user_id == order.user_id and log.kind != "admin_created":
            client_kinds[log.kind] = log.ok
    return AdminOrderOut(**result.model_dump(mode="python"), user_id=order.user_id, manager_note=order.manager_note,
                          client=users_by_id[order.user_id], notifications=[NotificationOut.model_validate(x) for x in logs],
                          notification_warning=any(not ok for ok in client_kinds.values())).model_copy(
                              update={"events": [AdminEventOut.model_validate(x).model_copy(
                                  update={"actor": users_by_id.get(x.actor_user_id)}) for x in events]})
