from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.statuses import BY_KEY


def ru(value) -> str:
    text = format(value, "f") if hasattr(value, "as_tuple") else str(value)
    whole, separator, fraction = text.partition(".")
    whole = f"{int(whole):,}".replace(",", "\u00a0")
    fraction = fraction.rstrip("0")
    return whole + ("," + fraction if fraction else "")


PLATFORM_LABELS = {
    "poizon": "Poizon / Dewu",
    "goofish": "Xianyu / Goofish",
    "taobao": "Taobao",
    "tmall": "Tmall",
    "1688": "1688",
    "pinduoduo": "Pinduoduo",
}


def platform_label(platform) -> str:
    return PLATFORM_LABELS.get(str(platform), "Не определена")


def options_text(order) -> str:
    items = []
    if order.insurance_enabled:
        items.append(f"страховка {ru(order.insurance_rub)} ₽")
    if order.packing_enabled:
        items.append(f"упаковка {ru(order.packing_rub)} ₽")
    if order.photo_report_enabled:
        items.append(f"фотоотчёт {ru(order.photo_report_rub)} ₽")
    return ", ".join(items)


CLIENT_TEXTS = {
    "created": "🆕 Заказ {no} принят. Менеджер @{manager} свяжется с вами для подтверждения и оплаты выкупа.",
    "processing": "📝 Заказ {no}: оформляется.",
    "purchased": "🛍 Заказ {no} выкуплен.",
    "to_cn_warehouse": "🚚 Заказ {no} в пути на наш склад в Китае.",
    "at_cn_warehouse": "📦 Заказ {no} прибыл на склад в Китае.",
    "awaiting_delivery_payment": "💳 Заказ {no}: ожидает оплату доставки. Сумма: {sum} ₽. Напишите менеджеру @{manager} для оплаты.",
    "to_cn_customs": "🛫 Заказ {no} в пути на таможню Китая.",
    "cn_customs": "🛃 Заказ {no} проходит таможню в Китае.",
    "to_ru_customs": "🚛 Заказ {no} в пути на таможню России.",
    "ru_customs": "🏛 Заказ {no} на таможне в России.",
    "to_recipient": "🚚 Заказ {no} в пути до получателя.",
    "delivered": "✅ Заказ {no} доставлен.",
    "cancelled": "❌ Заказ {no} отменён. Вопросы — @{manager}.",
    "tracking": "📦 Заказ {no}: трек-номер {track}.",
}


def client_notification(kind, order, event, settings):
    amount = event.payload.get("delivery_amount_rub", "0")
    track = event.payload.get("track_number") or "—"
    text = CLIENT_TEXTS[kind].format(no=escape(order.public_no), manager=escape(settings.manager_username),
                                     sum=escape(ru(int(amount))), track=escape(track))
    if kind == "created":
        count = event.payload.get("items")
        if isinstance(count, int) and count > 1:
            text += f"\nПозиций в заказе: {count}."
    if kind == "created" and order.extras_total_rub:
        text += f"\nОпции: {escape(options_text(order))}. Доплата: {escape(ru(order.extras_total_rub))} ₽."
    if kind == "cancelled":
        reason = event.payload.get("cancel_reason")
        if isinstance(reason, str) and reason:
            text += f"\nПричина: {escape(reason)}"
    if kind == "delivered":
        text += f"\nПоделитесь впечатлением: @{escape(settings.review_username)}"
    return text


def admin_notification(order, client, settings, items=None):
    client_name = "@" + client.username if client.username else client.first_name
    lines = [
        f"🆕 <b>Новый заказ {escape(order.public_no)}</b>",
        f"Клиент: {escape(client_name)} · ID {escape(str(client.tg_id))}",
    ]
    if items:
        lines.append(f"Позиций: {len(items)}")
        for index, item in enumerate(items, start=1):
            title = item.item_title or (urlsplit(item.link).hostname or "Товар")
            lines.append(f'{index}. <a href="{escape(item.link, quote=True)}">{escape(title[:120])}</a>')
            lines.append(f"   {escape(ru(item.price_cny))} ¥ × {item.quantity} · {escape(platform_label(item.platform))}")
        lines.append(f"Товар: {escape(ru(order.price_cny))} ¥ · комиссия {escape(ru(order.commission_rub))}"
                     f" = {escape(ru(order.total_rub))} ₽")
    else:
        product = order.item_title or (urlsplit(order.link).hostname or "Товар")
        lines.append(f'Товар: <a href="{escape(order.link, quote=True)}">{escape(product[:200])}</a>')
        lines.append(f"Площадка: {escape(platform_label(order.platform))}")
        lines.append(f"Расчёт: {escape(ru(order.price_cny))} ¥ × {escape(str(order.quantity))} × {escape(ru(order.rate))}"
                     f" + комиссия {escape(ru(order.commission_rub))} = {escape(ru(order.total_rub))} ₽")
    lines.append(f"Тариф: {escape(order.tariff_name)} · ~{escape(ru(order.weight_kg))} кг")
    lines.append(f"Доставка ориентировочно: {escape(ru(order.delivery_estimate_rub))} ₽")
    if options_text(order):
        lines.append(f"Опции: {escape(options_text(order))} · доплата {escape(ru(order.extras_total_rub))} ₽")
    if order.track_number:
        lines.append(f"Трек-номер: {escape(order.track_number)}")
    comments = [item.comment for item in (items or []) if item.comment]
    if comments:
        lines.append(f"Комментарий: {escape('; '.join(comments)[:500])}")
    elif order.comment:
        lines.append(f"Комментарий: {escape(order.comment)}")
    return "\n".join(lines)


def track_status(order) -> str:
    status = BY_KEY.get(order.status)
    status_name = f"{status['icon']} {status['name']}" if status else str(order.status)
    updated = order.updated_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M МСК")
    return (
        f"📦 <b>Заказ {escape(order.public_no)}</b>\n"
        f"Статус: {escape(status_name)}\n"
        f"Площадка: {escape(platform_label(order.platform))}\n"
        f"Обновлён: {escape(updated)}\n"
        f"Трек-номер: {escape(order.track_number or '—')}"
    )


def track_not_found(number: str) -> str:
    return f"Заказ «{escape(number)}» не найден. Проверьте номер или откройте /orders."


def _track_datetime(value) -> str:
    return value.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M МСК") if value else "—"


def external_tracking_status(link, settings) -> str:
    status = link.status_text or "ожидает первого обновления"
    checked = _track_datetime(link.last_checked_at) if link.last_checked_at else "ещё не проверяли"
    next_at = _track_datetime(link.next_check_at)
    return (
        f"📦 <b>Трек {escape(link.track_number)}</b>\n"
        f"Статус: {escape(status)}\n"
        f"Обновлено: {escape(checked)}\n"
        f"Следующее обновление: {escape(next_at)} (каждые {settings.tracking_refresh_hours} ч)\n"
        "Трек сохранён: статус обновляется автоматически, смотреть можно в приложении."
    )


def external_tracking_update(link) -> str:
    return f"🔄 <b>Трек {escape(link.track_number)}</b>\nНовый статус: {escape(link.status_text)}"


def welcome(settings):
    return "Добро пожаловать в <b>Taoji Cargo</b>!\nЗдесь можно рассчитать стоимость выкупа, оформить заказ и посмотреть его статус.\n" + f"По вопросам оплаты и доставки — @{escape(settings.manager_username)}."


def help_text(settings):
    return f"Менеджер: @{escape(settings.manager_username)}\nКанал: @{escape(settings.channel_username)}\nУсловия выкупа и доставки уточняйте у менеджера."


APP_TEXT = "Откройте приложение, чтобы рассчитать стоимость и оформить заказ."
ORDERS_TEXT = "Ваши заказы и история статусов — в приложении."
TRACK_USAGE = ("Отправьте трек-номер или номер заказа: /track TC-000001.\n"
               "Трек-номер Добропоста сохранится в приложении и будет обновляться каждые 6 часов.")
BUTTON_OPEN = "Открыть приложение"
BUTTON_ORDERS = "Мои заказы"
BUTTON_ORDER = "Открыть заказ"
BUTTON_ADMIN = "Открыть в админке"
BUTTON_CLIENT = "Написать клиенту"
BUTTON_REVIEW = "Оставить отзыв"
COMMANDS = [("start", "Начать работу"), ("app", "Открыть приложение"), ("orders", "Мои заказы"),
            ("track", "Статус по трек-номеру"), ("help", "Помощь и контакты")]
