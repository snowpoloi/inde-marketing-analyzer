from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def as_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
        return parsed if parsed.is_finite() else Decimal(default)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return default


def as_date(value: Any, fallback: date | None = None) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    if fallback:
        return fallback
    return datetime.now(timezone.utc).date()


def as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.now(timezone.utc)


def dec_to_float(value: Any) -> float:
    return float(value or 0)

