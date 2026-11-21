"""Conservative decimal normalization shared by the real extraction adapters."""

import re
from decimal import Decimal, InvalidOperation

NUMBER = re.compile(
    r"(?<![\w/])(?:\(\s*[-+]?\d[\d.,]*\s*\)|[-+]?\d[\d.,]*)(?:\s*%)?(?![\w/])"
)


def decimal_text(raw: str, locale: str | None = None) -> str:
    value = raw.strip().replace(" ", "").removesuffix("%")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    if "," in value and "." in value:
        decimal = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in value or "." in value:
        separator = "," if "," in value else "."
        parts = value.split(separator)
        if locale is None and len(parts) == 2 and len(parts[1]) == 3:
            raise ValueError("Ambiguous decimal/thousands separator; configure locale")
        thousands = "." if locale == "vi" else "," if locale == "en" else None
        if separator == thousands:
            if any(len(p) != 3 for p in parts[1:]):
                raise ValueError("Invalid thousands grouping")
            value = "".join(parts)
        else:
            if len(parts) != 2:
                raise ValueError("Invalid decimal")
            value = ".".join(parts)
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("Non-finite number")
    if negative:
        number = -number
    return format(number, "f") if number else "0"
