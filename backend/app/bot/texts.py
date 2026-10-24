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
    if kind == "created" and order.extras_total_rub:
        text += f"\nОпции: {escape(options_text(order))}. Доплата: {escape(ru(order.extras_total_rub))} ₽."
    return text


def admin_notification(order, client, settings):
    client_name = "@" + client.username if client.username else client.first_name
    product = order.item_title or (urlsplit(order.link).hostname or "Товар")
    lines = [
        f"🆕 <b>Новый заказ {escape(order.public_no)}</b>",
        f"Клиент: {escape(client_name)} · ID {escape(str(client.tg_id))}",
        f'Товар: <a href="{escape(order.link, quote=True)}">{escape(product[:200])}</a>',
        f"Площадка: {escape(platform_label(order.platform))}",
        f"Расчёт: {escape(ru(order.price_cny))} ¥ × {escape(str(order.quantity))} × {escape(ru(order.rate))}"
        f" + комиссия {escape(ru(order.commission_rub))} = {escape(ru(order.total_rub))} ₽",
        f"Тариф: {escape(order.tariff_name)} · ~{escape(ru(order.weight_kg))} кг",
        f"Доставка ориентировочно: {escape(ru(order.delivery_estimate_rub))} ₽",
    ]
    if options_text(order):
        lines.append(f"Опции: {escape(options_text(order))} · доплата {escape(ru(order.extras_total_rub))} ₽")
    if order.track_number:
        lines.append(f"Трек-номер: {escape(order.track_number)}")
    lines.append(f"Комментарий: {escape(order.comment) or '—'}")
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


def welcome(settings):
    return "Добро пожаловать в <b>Taoji Cargo</b>!\nЗдесь можно рассчитать стоимость выкупа, оформить заказ и посмотреть его статус.\n" + f"По вопросам оплаты и доставки — @{escape(settings.manager_username)}."


def help_text(settings):
    return f"Менеджер: @{escape(settings.manager_username)}\nКанал: @{escape(settings.channel_username)}\nУсловия выкупа и доставки уточняйте у менеджера."


APP_TEXT = "Откройте приложение, чтобы рассчитать стоимость и оформить заказ."
ORDERS_TEXT = "Ваши заказы и история статусов — в приложении."
TRACK_USAGE = "Отправьте трек-номер или номер заказа: /track TC-000001"
BUTTON_OPEN = "Открыть приложение"
BUTTON_ORDERS = "Мои заказы"
BUTTON_ORDER = "Открыть заказ"
BUTTON_ADMIN = "Открыть в админке"
BUTTON_CLIENT = "Написать клиенту"
COMMANDS = [("start", "Начать работу"), ("app", "Открыть приложение"), ("orders", "Мои заказы"),
            ("track", "Статус по трек-номеру"), ("help", "Помощь и контакты")]
