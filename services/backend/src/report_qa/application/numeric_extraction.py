"""Conservative decimal normalization shared by the real extraction adapters."""

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation

# A number ends at a digit: the "," of "Nhóm 7," and the "." ending a sentence are punctuation.
NUMBER = re.compile(
    r"(?<![\w/])(?:\(\s*[-+]?\d(?:[\d.,]*\d)?\s*\)|[-+]?\d(?:[\d.,]*\d)?)(?:\s*%)?(?![\w/])"
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


# A period written in a header or sentence: "Q2/25", "Quý 2/2026", "Quý II/2026", "Q3" (no
# year), "6T2026" or "6 tháng đầu năm 2026" (six months to date), "H1/2026",
# a month ("tháng 3/2026", "tháng 6") or a year ("2026", "2026F").
PERIOD = re.compile(
    r"(?i)(?<![\w/])(?:q|quý\s*)(?P<quarter>[1-4]|iv|i{1,3})"
    r"(?:\s*[/\-]\s*(?P<quarter_yy>\d{2})(?!\d)|\s*[/\-\s]\s*(?P<quarter_year>(?:19|20)\d{2})(?!\d))?(?!\w)"
    r"|(?<![\w/])(?P<months>\d{1,2})(?:t\s*/?|\s*tháng\s+đầu\s+năm)\s*(?P<months_year>(?:19|20)\d{2}|\d{2})(?!\d)"
    r"|(?<![\w/])h(?P<half>[12])(?:\s*[/\-\s]\s*(?P<half_year>(?:19|20)\d{2}|\d{2})(?!\d))?(?!\w)"
    r"|(?<![\w/])tháng\s*(?P<month>\d{1,2})(?:\s*[/\-]\s*(?P<month_year>(?:19|20)\d{2}))?(?![\d/])"
    r"|(?<![/\d])(?P<year>(?:19|20)\d{2})(?!\d)"
)
# A date ("31/12/2023", "31-12-2023") or a month of a year ("3/2026").
DATE = re.compile(
    r"(?<![\w/.,])(?:\d{1,2}(?P<sep>[/.\-])\d{1,2}(?P=sep)(?:19|20)?\d{2}|\d{1,2}/(?:19|20)\d{2})(?![\w/.,])"
)
# A reference to a figure or table of the document: "Biểu đồ 2", "Bảng 1", "Hình 3".
REFERENCE = re.compile(r"(?i)\b(?:biểu đồ|bảng|hình|sơ đồ|phụ lục|figure|fig\.?|table|chart)\s*\d+(?!\w)")
# A length of time counted in periods: "4 quý", "3 năm", "6 tháng" (not "6 năm 2026").
DURATION = re.compile(r"(?i)(?<![\w/.,])\d{1,3}\s*(?:năm|quý|tháng)(?!\w)(?!\s*(?:19|20)\d{2})")
_DASHES = {"-", "—", "–"}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
# Joins the levels of a table header path: "Doanh thu thuần · Quý 2/2026".
HEADER_JOIN = " · "
_MONTHS_GRANULARITY = {3: "quarter", 6: "half_year", 12: "year"}


def _full_year(digits: str) -> str:
    return digits if len(digits) == 4 else "20" + digits


def _period(match: re.Match, page_year: str | None = None) -> dict | None:
    """Contract period for one PERIOD match; a bare quarter, half or month takes page_year when given."""
    if match["half"]:
        year = (match["half_year"] and _full_year(match["half_year"])) or page_year
        if not year:
            return None
        first = match["half"] == "1"
        return {"label": f"H{match['half']}/{year}", "start": f"{year}-{'01' if first else '07'}-01",
                "end": f"{year}-{'06-30' if first else '12-31'}", "granularity": "half_year"}
    if match["month"]:
        month, year = int(match["month"]), match["month_year"] or page_year
        if not (1 <= month <= 12 and year):
            return None
        last_day = calendar.monthrange(int(year), month)[1]
        return {"label": f"T{month}/{year}", "start": f"{year}-{month:02d}-01", "end": f"{year}-{month:02d}-{last_day:02d}",
                "granularity": "month"}
    if match["quarter"]:
        year = match["quarter_year"] or (match["quarter_yy"] and _full_year(match["quarter_yy"])) or page_year
        if not year:
            return None
        quarter = _ROMAN.get(match["quarter"].casefold()) or int(match["quarter"])
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


def period_span(period: dict | None) -> tuple[date, date] | None:
    """First and last day a contract period covers; None when it has no start."""
    if not period or not period.get("start"):
        return None
    start = date.fromisoformat(period["start"])
    if period.get("end"):
        return start, date.fromisoformat(period["end"])
    if period.get("granularity") == "quarter":
        last_month = start.month + 2
        return start, date(start.year, last_month, calendar.monthrange(start.year, last_month)[1])
    return None


def asked_periods(text: str) -> list[tuple[date, date]]:
    """Spans of the periods a question names with their year ("quý 2/2025", "6T2026", "năm 2026").

    "cùng kỳ" (the same period a year earlier) adds each of them a year back.
    """
    spans = [span for match in PERIOD.finditer(text) if (span := period_span(_period(match)))]
    if "cùng kỳ" in text.casefold():
        spans += [(_year_back(a), _year_back(b)) for a, b in spans]
    return spans


def _year_back(day: date) -> date:
    return day.replace(year=day.year - 1, day=min(day.day, calendar.monthrange(day.year - 1, day.month)[1]))


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

SEPARATORS = {"vi": (".", ","), "en": (",", ".")}  # (thousands, decimal)
LOCALE_MAJORITY = 10  # proofs of one format per proof of the other before that format wins
# A well-formed number in one format: digits, optional thousands groups of three, optional decimals.
GRAMMAR = {
    locale: re.compile(rf"(?P<whole>[0-9]{{1,3}}(?:{re.escape(thousands)}[0-9]{{3}})+|[0-9]+)(?:{re.escape(decimal)}(?P<fraction>[0-9]+))?")
    for locale, (thousands, decimal) in SEPARATORS.items()
}


def detected_locale(texts) -> str | None:
    """The number format that printed quantities prove, when they prove exactly one.

    A printed number proves a format when that format's grammar reads it and
    the other's does not: "1.234.567", "1.234,5" and "6,5" are Vietnamese,
    "1,234,567", "1,234.5" and "6.5" are English. "1.234" and "2026" prove
    nothing. When a document proves both, one format wins only when it has at
    least LOCALE_MAJORITY times the proofs of the other: writers slip ("44,4%"
    in an English-style report), and a few slips must not make every
    "3,722" in the report unreadable. A closer split has no one format.
    """
    counts = dict.fromkeys(GRAMMAR, 0)
    for text in texts:
        for match in quantities(text or ""):
            token = match.group().strip("()+-% ")
            readers = [locale for locale, grammar in GRAMMAR.items() if grammar.fullmatch(token)]
            if len(readers) == 1:
                counts[readers[0]] += 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    (winner, most), (_, other) = ranked[0], ranked[1]
    if not most:
        return None
    return winner if other == 0 or most >= LOCALE_MAJORITY * other else None


def single_year(text: str) -> str | None:
    """The page's year when exactly one year is written on it, alone or in a period ("quý 1/2026")."""
    years = {_full_year(year) for m in PERIOD.finditer(text)
             for year in (m["year"], m["quarter_year"], m["quarter_yy"], m["months_year"], m["half_year"], m["month_year"])
             if year}
    return years.pop() if len(years) == 1 else None


def quantities(text: str) -> list[re.Match]:
    """NUMBER matches that state a quantity.

    Digits glued to letters or slashes ("Q3", "H1", "6T") are never NUMBER
    matches; periods, dates and durations ("quý 2/2026", "31/12/2023",
    "4 quý") are labels of time and "Biểu đồ 2" is the name of a figure, not
    quantities. Positions are those of text.
    """
    blanked = list(text)
    for pattern in (PERIOD, DATE, DURATION, REFERENCE):
        for match in pattern.finditer(text):
            blanked[match.start():match.end()] = " " * (match.end() - match.start())
    return list(NUMBER.finditer("".join(blanked)))


def is_value_text(text: str | None) -> bool:
    """A table cell that holds a value: a number that is not a period, or a dash for a missing value."""
    text = (text or "").strip()
    return text in _DASHES or bool(NUMBER.search(PERIOD.sub(" ", text)))
