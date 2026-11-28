"""Conservative decimal normalization shared by the real extraction adapters."""

import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

# A number ends at a digit: the "," of "Nhóm 7," and the "." ending a sentence are punctuation.
# (?![.,]\d) keeps a match from stopping inside a longer number: "1.4ppts" is not "1", and
# (?<!\d[.,]) from starting inside one: "1765,28/292,64" is not "64".
NUMBER = re.compile(
    r"(?<![\w/])(?<!\d[.,])(?:\(\s*[-+]?\d(?:[\d.,]*\d)?\s*\)|[-+]?\d(?:[\d.,]*\d)?)(?:\s*%)?(?![\w/])(?![.,]\d)"
)
# Two or more of one separator, each followed by exactly three digits, can only group thousands:
# "140,852,122,738" and "1.357.205" whatever the document's format.
THOUSANDS_ONLY = re.compile(r"\d{1,3}(?P<sep>[.,])\d{3}(?:(?P=sep)\d{3})+")
# Thousands grouped by spaces, "4 968 956 415", or a grouped number OCR split with a space, "52,077, 141,846".
# Spreadsheets print a 13-digit amount as "1430 350 876 514": the first group may have four digits.
_SPACE_GROUPED = re.compile(r"[-+]?\s?(?:\d{1,3}(?: \d{3})+|\d{4}(?: \d{3}){3,})")


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


def decimal_text(raw: str, locale: str | None = None, *, exact: bool = False) -> str:
    """Exact decimal of a printed number, read in the document's number format (locale "vi" or "en").

    Raises ValueError when the text is not one well-formed number in that format, so the
    caller shows it as unsure instead of guessing: with locale "vi", "1,013.545" (an OCR
    slip of "1.013.545") is not read. With no locale, "1.234" is unsure.
    One separator followed by one or two digits can only mark decimals, so "7.0" in a
    Vietnamese report is 7.0; with exact (OCR, where "." is often a misread ",") it must
    be written in the document's format.
    """
    value = re.sub(r"\s+", "", raw).removesuffix("%")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    separators = {c for c in value if c in ".,"}
    if THOUSANDS_ONLY.fullmatch(value.lstrip("+-")):
        value = value.replace(".", "").replace(",", "")
    elif not exact and re.fullmatch(r"[-+]?\d+[.,]\d{1,2}", value):
        value = value.replace(",", ".")
    elif separators and locale in GRAMMAR:
        if not GRAMMAR[locale].fullmatch(value.lstrip("+-")):
            raise ValueError(f"Not a number in the {locale} format")
        thousands, decimal = SEPARATORS[locale]
        value = value.replace(thousands, "").replace(decimal, ".")
    elif len(separators) == 2:
        readers = [name for name, grammar in GRAMMAR.items() if grammar.fullmatch(value.lstrip("+-"))]
        if len(readers) != 1:
            raise ValueError("Invalid decimal")
        thousands, decimal = SEPARATORS[readers[0]]
        value = value.replace(thousands, "").replace(decimal, ".")
    elif separators:
        parts = value.split(separators.pop())
        if len(parts) != 2:
            raise ValueError("Invalid decimal")
        if len(parts[1]) == 3:
            raise ValueError("Ambiguous decimal/thousands separator; configure locale")
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


def joined_number(text: str) -> str:
    """A table cell's text with the spaces inside its one number removed, else the text unchanged.

    "4 968 956 415" (thousands grouped by spaces) and OCR splits of a grouped number,
    "52,077, 141,846" or "20,96 1,264,731", are one number each. Two numbers in one cell
    ("2024 1,200", "15 20") stay as they are.
    """
    stripped = text.strip()
    core = stripped[1:-1].strip() if stripped.startswith("(") and stripped.endswith(")") else stripped
    if " " not in core:
        return text
    if _SPACE_GROUPED.fullmatch(core):
        return stripped.replace(core, core.replace(" ", ""))
    joined = re.sub(r"(?<=[\d.,])\s+(?=[\d.,])", "", core)
    if " " not in joined and THOUSANDS_ONLY.fullmatch(joined.lstrip("+-").rstrip("%")):
        return stripped.replace(core, joined)
    return text


_VI_LETTERS = "aàáảãạăằắẳẵặâầấẩẫậeèéẻẽẹêềếểễệiìíỉĩịoòóỏõọôồốổỗộơờớởỡợuùúủũụưừứửữựyỳýỷỹỵdđ"


def fold(text: str) -> str:
    """text without Vietnamese diacritics, one character for each: positions stay those of text."""
    return "".join("d" if c == "đ" else "D" if c == "Đ" else unicodedata.normalize("NFD", c)[0] for c in text)


_VARIANTS: dict[str, str] = {}
for _letter in _VI_LETTERS:
    _VARIANTS[fold(_letter)] = _VARIANTS.get(fold(_letter), "") + _letter


def _loose(words: str) -> str:
    """Pattern for words written with any diacritics or none: OCR drops and swaps them ("Quy", "thắng", "Téng")."""
    return r"\s+".join("".join(f"[{_VARIANTS[c]}]" if c in _VARIANTS else re.escape(c) for c in fold(word))
                       for word in words.split())


# A period written in a header or sentence: "Q2/25", "Quý 2/2026", "Quý II/2026", "Quý III năm 2025",
# "Q3" (no year), "6T2026", "6 tháng đầu năm 2026" or "Lũy kế 9 tháng năm 2025" (months to date),
# "H1/2026", a month ("tháng 3/2026", "tháng 10 năm 2025", "tháng 6") or a year ("2026", "2026F").
# Words are read with or without diacritics.
_QUY, _THANG, _NAM, _DAU = (_loose(word) for word in ("quý", "tháng", "năm", "đầu"))
PERIOD = re.compile(
    rf"(?i)(?<![\w/])(?:q|{_QUY}\s*)(?P<quarter>[1-4]|iv|i{{1,3}})"
    rf"(?:\s*[/\-.]\s*(?P<quarter_yy>\d{{2}})(?!\d)|(?:\s*[/\-.\s]|\s+{_NAM})\s*(?P<quarter_year>(?:19|20)\d{{2}})(?!\d))?(?!\w)"
    rf"|(?<![\w/])(?P<months>\d{{1,2}})(?:t\s*/?\s*|\s*{_THANG}\s*(?:(?:{_DAU}\s+)?{_NAM}\s*)?(?=(?:19|20)\d{{2}}))"
    rf"(?P<months_year>(?:19|20)\d{{2}}|\d{{2}})(?!\d)"
    r"|(?<![\w/])h(?P<half>[12])(?:\s*[/\-\s]\s*(?P<half_year>(?:19|20)\d{2}|\d{2})(?!\d))?(?!\w)"
    rf"|(?<![\w/]){_THANG}\s*(?P<month>\d{{1,2}})(?:(?:\s*[/\-]\s*|\s+{_NAM}\s+)(?P<month_year>(?:19|20)\d{{2}}))?(?![\d/])"
    r"|(?<![/\d])(?P<year>(?:19|20)\d{2})(?!\d)"
)
# A date ("31/12/2023", "31-12-2023") or a month of a year ("3/2026").
DATE = re.compile(
    r"(?<![\w/.,])(?:\d{1,2}(?P<sep>[/.\-])\d{1,2}(?P=sep)(?:19|20)?\d{2}|\d{1,2}/(?:19|20)\d{2})(?![\w/.,])"
)
# A reference to a figure or table of the document: "Biểu đồ 2", "Bảng 1", "Hình 3". OCR drops
# accents ("Bang 3"); only a capital keeps that apart from "bằng 6,5%" typed without accents.
REFERENCE = re.compile(
    r"\b(?:(?i:biểu đồ|bảng|hình|sơ đồ|phụ lục|figure|fig\.?|table|chart)|Bieu do|BIEU DO|Bang|BANG|Hinh|HINH)\s*\d+(?!\w)"
)
# Digits to dial, not amounts: "(+84) 24-7303-5333", "024-7303-5333", "(+84 28) 7300 7000",
# "Tel: 024 3942 9396", "Ext: 1044".
CONTACT = re.compile(
    r"\(?\+\d{1,3}(?:\s+\d{1,3})?\)?(?:[\s.\-()]*\d{2,5}){2,}|(?<![\w.,])\d{2,4}(?:-\d{3,4}){2,}(?!\w)"
    r"|(?i:\b(?:tel|fax|điện thoại|đt|hotline|phone|mobile)\b\.?\s*:?\s*[\d\s()+.\-]{6,}|\bext\b\.?\s*:?\s*\d+)"
)
# The number of an official paper, "Nghị quyết 68-NQ/TW", "Thông tư 200/2014-TT-BTC", "96/2020/TT-BTC".
CODE = re.compile(r"(?<![\w/])\d+(?:/\d+)*(?:[/\-][A-ZĐ]{1,6})+(?!\w)")
_UPPER = "A-Z" + _VI_LETTERS.upper()
# A number that names a thing rather than counts it: "Điều 14", "khoản 2", "TK 1283", "lần 14",
# "ngày 20", "Tầng 3", an address "Số 55", "số 55, đường K2" or "470 Đồng Văn Cống,",
# "Chuẩn mực kế toán số 16", a tax or company code "MST: 0100779340", a note "V.01",
# and "(2)" in "hai (2) điều kiện".
IDENTIFIER = re.compile(
    r"(?i:(?<!\w)(?:mst|mã số thuế|ma so thue|mã số doanh nghiệp|mã số dn)\s*[:.]?\s*\d[\d.\s\-]*\d)"
    rf"|(?<![\w.,/])\d{{1,4}}(?=(?:\s+[{_UPPER}][^\s\d,;:.]*){{2,5}}\s*[,\-–])"
    r"|(?i:(?<!\w)(?:điều|dieu|đieu|khoản|khoan|chương|chuong|tk|tài khoản|tai khoan|lần thứ|lần|lan|ngày|ngay"
    r"|article|clause|chapter)"
    r"\W{0,2}\d+(?:[.,]\d+)*)"
    r"|(?<![\w.])(?:Tầng|TẦNG|Số|SỐ|So|SO)(?:/No)?\s*[:.]?\s*\d+"
    r"|(?i:(?<!\w)số\s+\d+\s*[,\-]?\s*(?:đường|phố|ngõ|ngách|hẻm|phường|quận|lô))"
    r"|(?i:(?<!\w)(?:chuẩn mực|thông tư|nghị định|nghị quyết|quyết định|công văn|văn bản|luật)[^\d;:.]{0,40}?\bsố\s+\d+)"
    r"|(?<![\w.,])0\d{3,}(?![\w.,])"
    r"|(?<![\w.])[IVX]{1,4}\.\d{1,2}[a-z]?(?!\w)"
    r"|\(\s*\d{1,2}\s*\)"
)
# A list marker that numbers the points of a text: "1) BHX mở mới…", "(2) Doanh thu…", and
# "1." only at the start of a text ("tăng 5. Doanh thu…" ends a sentence with an amount).
_LIST_MARKER = re.compile(r"(?:^|(?<=[\s:;.]))\(?\d{1,2}\)(?=\s+(?P<next>\w))|^\s*\d{1,2}\.(?=\s+(?P<first>\w))")
# A length of time counted in periods: "4 quý", "3 năm", "6 tháng", "52 tuần" (not "6 năm 2026").
DURATION = re.compile(
    rf"(?i)(?<![\w/.,])\d{{1,3}}\s*(?:{_NAM}|{_QUY}|{_THANG}|{_loose('tuần')})(?!\w)(?!\s*(?:19|20)\d{{2}})"
)
# A table label that starts with its number in a list: "1. Vốn góp…", "17.Lợi nhuận…", "a) Trả trước…",
# "IV. Hàng tồn kho", and as OCR reads them: "8 Chi phí bán hàng", "1 0. Lợi nhuận", "] 11. Thu nhập".
_NUMBERED_LABEL = re.compile(
    r"^[^\w(]*(?:\(?\d{1,2}(?:\s\d)?[.)]|[IVXivx]{1,4}[.)]|[a-zđ]\))\s*[^\W\d_]"
    r"|^[^\w(]*\d{1,2}(?:\s\d)?\s+[^\W\d_]+\s+[^\W\d_]"
)
# A note reference in a "Thuyết minh" column: "V.01", "VI.9", "IV.2a".
NOTE_REF = re.compile(r"(?i)^\s*[IVX]{1,4}\s?\.\s?\d{1,2}[a-z]?\s*$")
# A label followed by its value in one cell: "Tổng cộng 2.370.750", "Biên lãi gộp 24,6%".
_LABEL_THEN_VALUE = re.compile(r"\s\(?[-+]?\d{1,3}(?:[.,]\d+)+\)?\s*%?\s*$")
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
    quantities; nor are phone numbers, the numbers of official papers,
    identifiers ("Điều 14", "Số 55", "V.01") and list markers ("1) BHX…").
    Positions are those of text.
    """
    blanked = list(text)
    spans = [m.span() for pattern in (PERIOD, DATE, DURATION, REFERENCE, CONTACT, CODE, IDENTIFIER) for m in pattern.finditer(text)]
    spans += [m.span() for m in _LIST_MARKER.finditer(text) if (m["next"] or m["first"])[0].isupper()]
    for start, end in spans:
        blanked[start:end] = " " * (end - start)
    return list(NUMBER.finditer("".join(blanked)))


def is_note_ref(text: str | None) -> bool:
    return bool(NOTE_REF.match(text or ""))


def is_value_text(text: str | None) -> bool:
    """A table cell that holds a value: a number that is not a period, or a dash for a missing value.

    A label is not a value even when it holds a number: "1. Vốn góp…" (a numbered row),
    "V.01" (a note), "Thấp/Cao 52 tuần", "TK 1283". A label may end with its value
    when the value is written in full: "Tổng cộng 2.370.750".
    """
    text = (text or "").strip()
    if text in _DASHES:
        return True
    if _NUMBERED_LABEL.match(text) or NOTE_REF.match(text):
        return False
    rest = PERIOD.sub(lambda m: " " * len(m.group()), text)
    match = NUMBER.search(rest)
    if not match:
        return False
    if any(c.isalpha() for c in rest[:match.start()]):
        return bool(_LABEL_THEN_VALUE.search(rest))
    return True
