"""Timestamp conversion for the older Piper SDK wrappers."""

from decimal import Decimal, InvalidOperation


def as_nanoseconds(value: object, scale: int) -> int:
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite() or decimal < 0:
            raise ValueError("invalid Piper timestamp")
        return int(decimal * scale)
    except (InvalidOperation, TypeError) as error:
        raise ValueError("invalid Piper timestamp") from error
