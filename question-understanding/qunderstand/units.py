"""Units: which values can be combined, and how to convert them."""

import re
from dataclasses import dataclass
from decimal import Decimal

from .text import norm

_SCALES = {"nghin ty": Decimal(10) ** 12, "ngan ty": Decimal(10) ** 12, "ty": Decimal(10) ** 9, "trieu": Decimal(10) ** 6,
           "nghin": Decimal(10) ** 3, "ngan": Decimal(10) ** 3, "tram": Decimal(100)}
_MONEY = {"dong": "đồng", "vnd": "đồng", "vnđ": "đồng", "usd": "USD"}


@dataclass(frozen=True)
class Unit:
    """dimension is what is counted; factor converts one unit to the base of the dimension."""

    dimension: str
    factor: Decimal
    label: str
    noun: str = ""

    def compatible(self, other: "Unit") -> bool:
        return self.dimension == other.dimension and self.dimension not in {"unknown", "text"}


UNKNOWN = Unit("unknown", Decimal(1), "")


def parse_unit(label: str | None) -> Unit:
    if not label or not label.strip():
        return UNKNOWN
    text = norm(label)
    if text == "text":
        return Unit("text", Decimal(1), label)
    if "diem" in text and ("%" in text or "phan tram" in text):
        return Unit("percentage_point", Decimal(1), label)
    if text in {"%", "phan tram"} or text.endswith(" %"):
        return Unit("percent", Decimal(1), label)
    factor = Decimal(1)
    rest = text
    scale_words = 0
    for word, scale in _SCALES.items():
        if re.match(rf"{word}\b", rest):
            factor, rest = scale, rest[len(word):].strip()
            scale_words = len(word.split())
            break
    rest = _MONEY.get(rest, rest)
    if not rest:
        return Unit("đồng", factor, label, "đồng")
    noun = rest if rest in _MONEY.values() else " ".join(label.split()[scale_words:])
    return Unit(rest, factor, label, noun)


def convert(value: Decimal, source: Unit, target: Unit) -> Decimal:
    if not source.compatible(target):
        raise ValueError(f"cannot convert {source.label!r} to {target.label!r}")
    return value * source.factor / target.factor


def scaled_money_label(value: Decimal, dimension: str, per: str | None = None) -> tuple[Decimal, str]:
    """Pick a readable scale for a base-unit value, e.g. 158363 đồng/đơn -> 158,36 nghìn đồng/đơn."""
    size = abs(value)
    for name, scale in (("nghìn tỷ", Decimal(10) ** 12), ("tỷ", Decimal(10) ** 9), ("triệu", Decimal(10) ** 6), ("nghìn", Decimal(10) ** 3)):
        if size >= scale:
            label = f"{name} {dimension}"
            return value / scale, f"{label}/{per}" if per else label
    return value, f"{dimension}/{per}" if per else dimension
