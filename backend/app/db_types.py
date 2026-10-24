from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.types import TypeDecorator


class ExactDecimal(TypeDecorator):
    """SQLite TEXT / PostgreSQL NUMERIC, never a binary float."""
    impl = String
    cache_ok = True

    def __init__(self, precision: int, scale: int, **kwargs):
        self.precision = precision
        self.scale = scale
        super().__init__(**kwargs)

    def __repr__(self):
        return f"ExactDecimal({self.precision}, {self.scale})"

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Numeric(self.precision, self.scale, asdecimal=True))
        return dialect.type_descriptor(String(self.precision + 3))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("Float запрещён для денежных значений")
        value = Decimal(value)
        quantum = Decimal(1).scaleb(-self.scale)
        normalized = value.quantize(quantum)
        if not value.is_finite() or normalized != value or abs(value) >= Decimal(10) ** (self.precision - self.scale):
            raise ValueError("Значение не помещается в точный десятичный тип")
        return normalized if dialect.name == "postgresql" else format(normalized, "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Дата должна содержать часовой пояс")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
