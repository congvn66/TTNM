"""Deterministic domain calculations used by answer workers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable

from .errors import InvariantError
from .types import validate_decimal_text


def decimal_sum(values: Iterable[str]) -> str:
    """Sum exact decimal strings without converting through binary float."""

    total = Decimal("0")
    try:
        for value in values:
            validate_decimal_text(value)
            total += Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvariantError("all operands must be exact decimal strings") from exc
    return format(total, "f")


def growth_rate(previous: str, current: str) -> str | None:
    """Return percent growth, or ``None`` for an undefined zero denominator."""

    try:
        validate_decimal_text(previous)
        validate_decimal_text(current)
        denominator = Decimal(previous)
        numerator = Decimal(current) - denominator
    except (InvalidOperation, ValueError) as exc:
        raise InvariantError("growth operands must be exact decimal strings") from exc
    if denominator == 0:
        return None
    return format((numerator / denominator) * Decimal("100"), "f")
