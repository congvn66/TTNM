"""Conservative decimal normalization shared by the real extraction adapters."""

import calendar
import re
from decimal import Decimal, InvalidOperation

NUMBER = re.compile(
    r"(?<![\w/])(?:\(\s*[-+]?\d[\d.,]*\s*\)|[-+]?\d[\d.,]*)(?:\s*%)?(?![\w/])"
)


def canonical_decimal(value: str) -> str:
    """Exact wire form accepted by the evidence contract.

    No exponent, no leading zeros, no ``+`` sign and a single ``0`` for zero:
    ``"+12"`` -> ``"12"``, ``".5"`` -> ``"0.5"``, ``"0.0"`` -> ``"0"``.
    """
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("Non-finite number")
    return format(number, "f") if number else "0"


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


# A period written in a header or sentence: "Q2/25", "Quý 2/2026", "Q3" (no
# year), "6T2026" (six months to date) or a year ("2026", "2026F").
PERIOD = re.compile(
    r"(?i)(?<![\w/])(?:q|quý\s*)(?P<quarter>[1-4])"
    r"(?:\s*[/\-]\s*(?P<quarter_yy>\d{2})(?!\d)|\s*[/\-\s]\s*(?P<quarter_year>(?:19|20)\d{2})(?!\d))?(?!\w)"
    r"|(?<![\w/])(?P<months>\d{1,2})t\s*/?\s*(?P<months_year>(?:19|20)\d{2}|\d{2})(?!\d)"
    r"|(?<![/\d])(?P<year>(?:19|20)\d{2})(?!\d)"
)
_DASHES = {"-", "—", "–"}
# Joins the levels of a table header path: "Doanh thu thuần · Quý 2/2026".
HEADER_JOIN = " · "
_MONTHS_GRANULARITY = {3: "quarter", 6: "half_year", 12: "year"}


def _full_year(digits: str) -> str:
    return digits if len(digits) == 4 else "20" + digits


def _period(match: re.Match, page_year: str | None = None) -> dict | None:
    """Contract period for one PERIOD match; a bare quarter takes page_year when given."""
    if match["quarter"]:
        year = match["quarter_year"] or (match["quarter_yy"] and _full_year(match["quarter_yy"])) or page_year
        if not year:
            return None
        quarter = int(match["quarter"])
        return {"label": f"Q{quarter}/{year}", "start": f"{year}-{(quarter - 1) * 3 + 1:02d}-01", "end": None,
                "granularity": "quarter"}
    if match["months"]:
        months, year = int(match["months"]), _full_year(match["months_year"])
        if not 1 <= months <= 12:
            return None
        last_day = calendar.monthrange(int(year), months)[1]
        return {"label": f"{months}T/{year}", "start": f"{year}-01-01", "end": f"{year}-{months:02d}-{last_day:02d}",
                "granularity": _MONTHS_GRANULARITY.get(months, "unknown")}
    year = match["year"]
    return {"label": year, "start": f"{year}-01-01", "end": f"{year}-12-31", "granularity": "year"}


def period_near(text: str, number_start: int) -> dict | None:
    """Period nearest to a number in free text; a quarter or months period beats a year."""
    found = [(match.start(), _period(match)) for match in PERIOD.finditer(text)]
    found = [(abs(start - number_start), period) for start, period in found if period]
    specific = [item for item in found if item[1]["granularity"] != "year"] or found
    return min(specific, key=lambda item: item[0])[1] if specific else None


def header_period(headers: list[str | None], page_year: str | None = None) -> dict | None:
    """Period a table cell's own headers name, most specific level first.

    headers is the cell's header path, outer to inner (row header, then the
    column header levels); the innermost level that names a period wins.
    """
    for header in reversed([h for h in headers if h]):
        for match in PERIOD.finditer(header):
            period = _period(match, page_year)
            if period:
                return period
    return None


def single_year(text: str) -> str | None:
    """The page's year when exactly one year is written on it."""
    years = {m["year"] for m in PERIOD.finditer(text) if m["year"]}
    return years.pop() if len(years) == 1 else None


def is_value_text(text: str | None) -> bool:
    """A table cell that holds a value: a number that is not a period, or a dash for a missing value."""
    text = (text or "").strip()
    return text in _DASHES or bool(NUMBER.search(PERIOD.sub(" ", text)))
