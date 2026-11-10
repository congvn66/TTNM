"""Exact number parsing and Vietnamese number display."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class AmbiguousNumber(ValueError):
    """The text can mean two different numbers, such as 1,250 or 1.250."""


def to_decimal(value) -> Decimal | None:
    """Convert a stored value to Decimal. None stays None. Bool and NaN are refused."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, float)):
        result = Decimal(str(value))
    elif isinstance(value, str):
        result = parse_number(value)
    else:
        raise ValueError(f"not a number: {value!r}")
    if not result.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return result


def parse_number(text: str, *, locale: str | None = None) -> Decimal:
    """Parse '21.350', '1,250.50', '12,5', '(1.740)', '-3,2%'.

    locale='vi' reads . as thousands and , as decimal. locale='en' is the reverse.
    Without a locale, a form with one meaning is accepted and '1,250' or '1.250' raises
    AmbiguousNumber, because a silent guess can make a number 1000 times too large.
    """
    raw = (text or "").strip()
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace("%", "").replace("−", "-").replace(" ", "").replace("+", "")
    if cleaned.startswith("-"):
        negative = not negative
        cleaned = cleaned[1:]
    if not re.fullmatch(r"\d[\d.,]*", cleaned) or not cleaned[-1].isdigit():
        raise ValueError(f"not a number: {text!r}")

    dots, commas = cleaned.count("."), cleaned.count(",")
    if dots and commas:
        decimal_sep = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        if cleaned.count(decimal_sep) > 1:
            raise ValueError(f"not a number: {text!r}")
        whole, frac = cleaned.split(decimal_sep)
        _check_groups(whole, thousands_sep, text)
        normal = whole.replace(thousands_sep, "") + "." + frac
    elif dots or commas:
        sep = "." if dots else ","
        parts = cleaned.split(sep)
        grouped = all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3 and parts[0] != "0"
        if len(parts) > 2:
            _check_groups(cleaned, sep, text)
            normal = cleaned.replace(sep, "")
        elif grouped:
            vi_thousands = sep == "."
            en_thousands = sep == ","
            if locale == "vi":
                normal = cleaned.replace(".", "") if vi_thousands else cleaned.replace(",", ".")
            elif locale == "en":
                normal = cleaned.replace(",", "") if en_thousands else cleaned
            else:
                raise AmbiguousNumber(f"ambiguous number: {text!r}")
        else:
            normal = cleaned.replace(sep, ".")
    else:
        normal = cleaned
    try:
        result = Decimal(normal)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    return -result if negative else result


def _check_groups(text: str, sep: str, original: str) -> None:
    parts = text.split(sep)
    if len(parts) > 1 and (not 1 <= len(parts[0]) <= 3 or any(len(p) != 3 for p in parts[1:])):
        raise ValueError(f"not a number: {original!r}")


def fmt(value: Decimal | int | float, places: int = 2) -> str:
    """21350 -> '21.350', 17.0504 -> '17,05', 30 -> '30', -5.5 -> '-5,5'."""
    number = to_decimal(value)
    quantum = Decimal(1).scaleb(-places)
    rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    text = f"{abs(rounded):f}"
    whole, _, frac = text.partition(".")
    groups = f"{int(whole):,}".replace(",", ".")
    frac = frac.rstrip("0")
    return f"{sign}{groups},{frac}" if frac else f"{sign}{groups}"


def as_json_number(value: Decimal | None, places: int = 6):
    """A Decimal as a plain JSON number, or None."""
    if value is None:
        return None
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP).normalize()
    return int(rounded) if rounded == rounded.to_integral_value() else float(rounded)
