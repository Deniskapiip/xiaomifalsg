from enum import StrEnum


class Status(StrEnum):
    processing = "processing"
    purchased = "purchased"
    to_cn_warehouse = "to_cn_warehouse"
    at_cn_warehouse = "at_cn_warehouse"
    awaiting_delivery_payment = "awaiting_delivery_payment"
    to_cn_customs = "to_cn_customs"
    cn_customs = "cn_customs"
    to_ru_customs = "to_ru_customs"
    ru_customs = "ru_customs"
    to_recipient = "to_recipient"
    delivered = "delivered"
    cancelled = "cancelled"


STATUSES = [
    {"key": Status.processing, "name": "Оформляется", "icon": "📝", "stage": 1},
    {"key": Status.purchased, "name": "Выкуплен", "icon": "🛍", "stage": 2},
    {"key": Status.to_cn_warehouse, "name": "В пути на склад в Китае", "icon": "🚚", "stage": 3},
    {"key": Status.at_cn_warehouse, "name": "На складе", "icon": "📦", "stage": 3},
    {"key": Status.awaiting_delivery_payment, "name": "Ожидает оплату доставки", "icon": "💳", "stage": 3},
    {"key": Status.to_cn_customs, "name": "В пути на таможню Китая", "icon": "🛫", "stage": 4},
    {"key": Status.cn_customs, "name": "Проходит таможню в Китае", "icon": "🛃", "stage": 4},
    {"key": Status.to_ru_customs, "name": "В пути на таможню в России", "icon": "🚛", "stage": 4},
    {"key": Status.ru_customs, "name": "На таможне в России", "icon": "🏛", "stage": 4},
    {"key": Status.to_recipient, "name": "В пути до получателя", "icon": "🚚", "stage": 4},
    {"key": Status.delivered, "name": "Доставлен", "icon": "✅", "stage": 4},
    {"key": Status.cancelled, "name": "Отменён", "icon": "❌", "stage": None},
]
TERMINAL = {Status.delivered, Status.cancelled}
BY_KEY = {row["key"]: {**row, "order": index, "terminal": row["key"] in TERMINAL} for index, row in enumerate(STATUSES)}


def requires_confirmation(old: str, new: str) -> bool:
    return new == Status.cancelled or (old != Status.cancelled and new != Status.cancelled and BY_KEY[new]["order"] < BY_KEY[old]["order"])
