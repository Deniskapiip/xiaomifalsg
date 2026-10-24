from decimal import Decimal
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, false, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db_types import ExactDecimal, UTCDateTime, utcnow
from app.statuses import Status


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32))
    first_name: Mapped[str] = mapped_column(String(256))
    last_name: Mapped[str | None] = mapped_column(String(256))
    language_code: Mapped[str | None] = mapped_column(String(16))
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_settings_row"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    rate_cny_rub: Mapped[Decimal] = mapped_column(ExactDecimal(12, 4))
    commission_percent: Mapped[Decimal] = mapped_column(ExactDecimal(5, 2))
    commission_min_rub: Mapped[int] = mapped_column(BigInteger)
    rate_updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    rate_updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class RateHistory(Base):
    __tablename__ = "rate_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    old_rate: Mapped[Decimal] = mapped_column(ExactDecimal(12, 4))
    new_rate: Mapped[Decimal] = mapped_column(ExactDecimal(12, 4))
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Tariff(Base):
    __tablename__ = "tariffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price_per_kg: Mapped[Decimal] = mapped_column(ExactDecimal(12, 2))
    price_on_request: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    price_currency: Mapped[str] = mapped_column(String(3), default="rub", server_default=text("'rub'"))
    insurance_available: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    eta_text: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(1000), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_track_number", "track_number"),
        Index("ix_orders_tracking_next_check", "tracking_next_check_at"),
        CheckConstraint("quantity >= 1 AND quantity <= 999", name="order_quantity_bounds"),
        CheckConstraint("status IN (" + ",".join(repr(s.value) for s in Status) + ")", name="order_status_values"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_no: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    link: Mapped[str] = mapped_column(String(2000))
    platform: Mapped[str] = mapped_column(String(20))
    item_title: Mapped[str] = mapped_column(String(200), default="")
    price_cny: Mapped[Decimal] = mapped_column(ExactDecimal(12, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(500), default="")
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    tariff_name: Mapped[str] = mapped_column(String(100))
    tariff_price_per_kg: Mapped[Decimal] = mapped_column(ExactDecimal(12, 2))
    tariff_price_currency: Mapped[str] = mapped_column(String(3), default="rub", server_default=text("'rub'"))
    tariff_price_value: Mapped[Decimal] = mapped_column(ExactDecimal(12, 2), server_default=text("0"))
    rate: Mapped[Decimal] = mapped_column(ExactDecimal(12, 4))
    commission_percent: Mapped[Decimal] = mapped_column(ExactDecimal(5, 2))
    commission_min_rub: Mapped[int] = mapped_column(BigInteger)
    weight_kg: Mapped[Decimal] = mapped_column(ExactDecimal(8, 3))
    goods_rub: Mapped[int] = mapped_column(BigInteger)
    commission_rub: Mapped[int] = mapped_column(BigInteger)
    total_rub: Mapped[int] = mapped_column(BigInteger)
    delivery_estimate_rub: Mapped[int] = mapped_column(BigInteger)
    delivery_final_rub: Mapped[int | None] = mapped_column(BigInteger)
    boxes: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    insurance_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    packing_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    photo_report_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    insurance_rub: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    packing_rub: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    photo_report_rub: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    extras_total_rub: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    total_with_extras_rub: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    track_number: Mapped[str | None] = mapped_column(String(64))
    tracking_status_text: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    tracking_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tracking_next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manager_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default=Status.processing)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order",
                                                    cascade="all, delete-orphan", order_by="OrderItem.position")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_order_position", "order_id", "position"),
        CheckConstraint("quantity >= 1 AND quantity <= 999", name="order_item_quantity_bounds"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    link: Mapped[str] = mapped_column(String(2000))
    platform: Mapped[str] = mapped_column(String(20))
    item_title: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    price_cny: Mapped[Decimal] = mapped_column(ExactDecimal(12, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    comment: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"))
    order: Mapped[Order] = relationship("Order", back_populates="items")


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class NotificationLog(Base):
    __tablename__ = "notifications_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "kind", name="unique_notification_event_recipient"),
        Index("ix_notification_jobs_due", "state", "next_attempt_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("order_events.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    kind: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class TrackingLink(Base):
    """Внешний трек-номер (например, Добропост), который клиент отслеживает сам."""
    __tablename__ = "tracking_links"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "track_number", name="unique_tracking_link"),
        Index("ix_tracking_links_due", "next_check_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20), default="dobropost", server_default=text("'dobropost'"))
    track_number: Mapped[str] = mapped_column(String(64))
    status_text: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    ok: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_check_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, server_default=text("CURRENT_TIMESTAMP"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
