from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Annotated, Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_serializer, field_validator, model_validator

from app.statuses import Status


def exact_decimal(value):
    if not isinstance(value, str):
        raise ValueError("Передайте десятичное число строкой, например «13.5»")
    value = value.strip().replace(",", ".")
    import re
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) or len(value) > 30:
        raise ValueError("Введите положительное число без экспоненты")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Некорректное число") from None
    if not result.is_finite():
        raise ValueError("Число должно быть конечным")
    return result


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthIn(Input):
    initData: str = Field(max_length=16384)


class TelegramUser(Input):
    model_config = ConfigDict(extra="ignore")
    id: StrictInt = Field(gt=0, le=9223372036854775807)
    first_name: str = Field(max_length=256)
    last_name: str | None = Field(default=None, max_length=256)
    username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,32}$")
    language_code: str | None = Field(default=None, max_length=16)
    allows_write_to_pm: bool = False


class UserOut(Output):
    id: int
    tg_id: int
    username: str | None
    first_name: str
    last_name: str | None
    can_write: bool


class AuthOut(Output):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    role: str


class CalcIn(Input):
    price_cny: Decimal = Field(ge=Decimal("0.01"), le=Decimal("1000000"), max_digits=12, decimal_places=2)
    quantity: StrictInt = Field(ge=1, le=999)
    tariff_id: StrictInt = Field(gt=0)
    weight_kg: Decimal = Field(ge=Decimal("0.01"), le=Decimal("1000"), max_digits=8, decimal_places=3)
    boxes: StrictInt = Field(default=1, ge=1, le=99)
    insurance_enabled: bool = False
    packing_enabled: bool = False
    photo_report_enabled: bool = False
    _decimal_fields = field_validator("price_cny", "weight_kg", mode="before")(exact_decimal)


def safe_order_link(value: str) -> str:
    value = value.strip()
    if any(ord(c) < 32 or c.isspace() for c in value):
        raise ValueError("Ссылка не должна содержать пробелы или управляющие символы")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("Некорректная ссылка") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Нужна полная ссылка http:// или https:// без логина и пароля")
    return value


class OrderItemIn(Input):
    link: str = Field(min_length=1, max_length=2000)
    price_cny: Decimal = Field(ge=Decimal("0.01"), le=Decimal("1000000"), max_digits=12, decimal_places=2)
    quantity: StrictInt = Field(default=1, ge=1, le=999)
    item_title: str = Field(default="", max_length=200)
    comment: str = Field(default="", max_length=500)
    _price = field_validator("price_cny", mode="before")(exact_decimal)

    @field_validator("link")
    @classmethod
    def safe_link(cls, value: str):
        return safe_order_link(value)


def _optional_exact(value):
    return None if value is None else exact_decimal(value)


class OrderCreate(Input):
    # Submitted client totals (and any attempted privileged fields) are ignored.
    model_config = ConfigDict(extra="ignore")
    idempotency_key: UUID
    tariff_id: StrictInt = Field(gt=0)
    weight_kg: Decimal = Field(ge=Decimal("0.01"), le=Decimal("1000"), max_digits=8, decimal_places=3)
    boxes: StrictInt = Field(default=1, ge=1, le=99)
    insurance_enabled: bool = False
    packing_enabled: bool = False
    photo_report_enabled: bool = False
    # Мультизаказ: 1..20 позиций, у каждой своя ссылка, цена, количество, название и комментарий.
    items: list[OrderItemIn] = Field(default_factory=list, max_length=20)
    # Совместимость со старым API: одна позиция отдельными полями.
    link: str | None = Field(default=None, max_length=2000)
    price_cny: Decimal | None = Field(default=None, ge=Decimal("0.01"), le=Decimal("1000000"), max_digits=12, decimal_places=2)
    quantity: StrictInt | None = Field(default=None, ge=1, le=999)
    item_title: str = Field(default="", max_length=200)
    comment: str = Field(default="", max_length=500)
    _decimals = field_validator("weight_kg", "price_cny", mode="before")(_optional_exact)

    @field_validator("link")
    @classmethod
    def safe_link(cls, value):
        return None if value is None else safe_order_link(value)

    @model_validator(mode="after")
    def require_at_least_one_item(self):
        if self.items:
            return self
        if self.link is None or self.price_cny is None:
            raise ValueError("Передайте хотя бы одну ссылку на товар с ценой")
        return self


class TrackSetIn(Input):
    number: str = Field(max_length=64)
    notify: bool = True

    @field_validator("number")
    @classmethod
    def normalize_number(cls, value: str) -> str:
        value = " ".join(value.split())
        if not re.fullmatch(r"[A-Za-z0-9 _-]*", value):
            raise ValueError("Трек-номер может содержать только латинские буквы, цифры, пробелы, «_» и «-»")
        return value


class PriceOut(Output):
    goods_rub: int
    commission_rub: int
    total_rub: int
    delivery_estimate_rub: int
    commission_is_minimum: bool
    insurance_rub: int = 0
    packing_rub: int = 0
    photo_report_rub: int = 0
    extras_total_rub: int = 0
    total_with_extras_rub: int = 0
    @field_serializer("goods_rub", "commission_rub", "total_rub", "delivery_estimate_rub",
                      "insurance_rub", "packing_rub", "photo_report_rub", "extras_total_rub", "total_with_extras_rub")
    def serialize_rubles(self, value: int):
        return str(value)


class CalcOut(PriceOut):
    rate: Decimal
    commission_percent: Decimal
    commission_min_rub: str
    tariff_name: str
    tariff_price_per_kg: Decimal


class TariffIn(Input):
    name: str = Field(min_length=1, max_length=100)
    price_per_kg: Decimal = Field(ge=Decimal("0"), lt=Decimal("10000000000"), max_digits=12, decimal_places=2)
    price_currency: Literal["rub", "cny"] = "rub"
    insurance_available: bool = False
    eta_text: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    is_active: bool = False
    sort_order: StrictInt = Field(default=0, ge=0, le=10000)
    _price = field_validator("price_per_kg", mode="before")(exact_decimal)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Название не должно быть пустым")
        return value.strip()

    @model_validator(mode="after")
    def active_price(self):
        if self.is_active and self.price_per_kg <= 0:
            raise ValueError("У активного тарифа цена должна быть больше нуля")
        return self


class TariffOut(Output):
    id: int
    name: str
    price_per_kg: Decimal
    price_currency: str
    insurance_available: bool
    eta_text: str
    description: str
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class StatusOut(Output):
    key: str
    name: str
    icon: str
    stage: int | None
    order: int
    terminal: bool


class ConfigOut(Output):
    rate_cny_rub: Decimal
    rate_updated_at: datetime
    commission_percent: Decimal
    commission_min_rub: str
    insurance_percent: Decimal
    packing_fee_rub: str
    photo_report_fee_rub: str
    contacts: dict[str, str]
    statuses: list[StatusOut]
    tariffs: list[TariffOut]


class EventOut(Output):
    id: int
    type: str
    from_status: str | None
    to_status: str | None
    payload: dict
    created_at: datetime


class AdminEventOut(EventOut):
    actor_user_id: int | None
    actor: UserOut | None = None


class OrderItemOut(Output):
    id: int
    position: int
    link: str
    platform: str
    item_title: str
    price_cny: Decimal
    quantity: int
    comment: str
    goods_rub: int = 0
    @field_serializer("goods_rub")
    def serialize_item_goods(self, value: int):
        return str(value)


class OrderOut(Output):
    id: int
    public_no: str
    link: str
    platform: str
    item_title: str
    price_cny: Decimal
    quantity: int
    comment: str
    tariff_id: int
    tariff_name: str
    tariff_price_per_kg: Decimal
    tariff_price_currency: str = "rub"
    tariff_price_value: Decimal = Decimal("0")
    rate: Decimal
    commission_percent: Decimal
    commission_min_rub: int
    weight_kg: Decimal
    boxes: int = 1
    goods_rub: int
    commission_rub: int
    total_rub: int
    delivery_estimate_rub: int
    delivery_final_rub: int | None
    insurance_enabled: bool = False
    packing_enabled: bool = False
    photo_report_enabled: bool = False
    insurance_rub: int = 0
    packing_rub: int = 0
    photo_report_rub: int = 0
    extras_total_rub: int = 0
    total_with_extras_rub: int = 0
    track_number: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut] = Field(default_factory=list)
    events: list[EventOut] = Field(default_factory=list)
    @field_serializer("commission_min_rub", "goods_rub", "commission_rub", "total_rub", "delivery_estimate_rub", "delivery_final_rub",
                      "insurance_rub", "packing_rub", "photo_report_rub", "extras_total_rub", "total_with_extras_rub")
    def serialize_rubles(self, value):
        return None if value is None else str(value)


class NotificationOut(Output):
    user_id: int
    kind: str
    ok: bool
    error: str | None
    created_at: datetime


class AdminOrderOut(OrderOut):
    user_id: int
    manager_note: str
    client: UserOut
    events: list[AdminEventOut] = Field(default_factory=list)
    notifications: list[NotificationOut] = Field(default_factory=list)
    notification_warning: bool = False


class OrderPage(Output):
    items: list[OrderOut]
    total: int
    limit: int
    offset: int


class AdminOrderPage(Output):
    items: list[AdminOrderOut]
    total: int
    limit: int
    offset: int


class StatusIn(Input):
    status: Status
    delivery_amount_rub: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,14}$")
    notify: bool = True
    confirmed: bool = False
    # Причина отмены для менеджера: сохраняется в истории заказа и в уведомлении клиенту.
    reason: str | None = Field(default=None, max_length=500)
    @model_validator(mode="after")
    def require_delivery(self):
        if self.status == Status.awaiting_delivery_payment and self.delivery_amount_rub is None:
            raise ValueError("Укажите целую положительную сумму доставки в рублях")
        if self.status != Status.awaiting_delivery_payment and self.delivery_amount_rub is not None:
            raise ValueError("Сумма доставки задаётся при статусе «Ожидает оплату доставки»")
        return self


class NoteIn(Input):
    note: str = Field(max_length=2000)


class WriteAccessIn(Input):
    allowed: bool


class SettingsIn(Input):
    rate_cny_rub: Decimal = Field(gt=Decimal("0"), lt=Decimal("100000000"), max_digits=12, decimal_places=4)
    commission_percent: Decimal = Field(ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2)
    commission_min_rub: str = Field(pattern=r"^(0|[1-9][0-9]{0,14})$")
    _decimals = field_validator("rate_cny_rub", "commission_percent", mode="before")(exact_decimal)


class RateHistoryOut(Output):
    id: int
    old_rate: Decimal
    new_rate: Decimal
    changed_by: int
    changed_by_user: UserOut | None = None
    changed_at: datetime


class SettingsOut(Output):
    rate_cny_rub: Decimal
    commission_percent: Decimal
    commission_min_rub: str
    rate_updated_at: datetime
    rate_updated_by: int | None
    rate_history: list[RateHistoryOut]


class DashboardOut(Output):
    counts: dict[str, int]
    new_today: int
    requires_action: int
    total_orders: int
    rate_stale: bool | None
    stats: dict[str, str] | None
