"""Periods: match 'quý 2', 'Q2/26', '2Q26' and 'Quý 2/2026' to the same thing."""

import re
from dataclasses import dataclass

from .text import deaccent


@dataclass(frozen=True)
class Period:
    """kind: Q quarter, M month, L cumulative months from January, S second half, Y year, A school year (year = first year), R anything else."""

    kind: str
    number: int
    year: int | None = None
    raw: str = ""

    @property
    def months(self) -> int | None:
        return {"Q": 3, "M": 1, "L": self.number, "S": 6, "Y": 12, "A": 12}.get(self.kind)

    def key(self) -> tuple:
        return (self.kind, self.number, self.year) if self.kind != "R" else ("R", self.raw)


def _year(text: str | None) -> int | None:
    if not text:
        return None
    value = int(text)
    return value + 2000 if value < 100 else value


_YEAR = r"(?:[/\s\-]*(?:nam\s*)?(\d{4}|\d{2}))?"
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_PATTERNS: list[tuple[str, str]] = [
    ("A", r"\b(?:nam hoc\s*)?(20\d{2})\s*-\s*20\d{2}\b"),
    ("Q", rf"\b(?:quy|q)\s*([1-4]|iv|iii|ii|i)\b{_YEAR}"),
    ("Q", r"\b([1-4])q(\d{2,4})\b"),
    ("S", rf"\b(?:6\s*(?:thang|t|m)\s*cuoi|nua cuoi|h2)(?:\s*nam)?{_YEAR}"),
    ("L", rf"\bnua dau(?:\s*nam)?{_YEAR}"),
    ("L", rf"\b(6|9|3)\s*(?:thang|t|m)\b(?:\s*dau)?(?:\s*nam)?{_YEAR}"),
    ("L", r"\b(?:luy ke\s*)?(6|9|3)\s*(?:thang|t|m)\s*(?:/\s*)?(\d{4})\b"),
    ("L", r"\bh([1])\b" + _YEAR),
    ("M", rf"\b(?:thang|t)\s*(0?[1-9]|1[0-2])\b{_YEAR}"),
    ("M", r"(?<![\d/])(0?[1-9]|1[0-2])/(20\d{2})\b"),
    ("Y", r"\b(?:ca\s*)?nam\s*(\d{4})[fe]?\b"),
    ("Y", r"\b(?:fy)?(20\d{2})[fe]?\b"),
]


def parse_period(text: str | None) -> Period | None:
    if not text or not text.strip():
        return None
    low = deaccent(text).lower().strip()
    found = find_periods(low)
    if found:
        return found[0]
    return Period("R", 0, None, low)


def find_periods(text: str) -> list[Period]:
    """All periods in a text, in reading order. Overlapping weaker matches are dropped."""
    low = deaccent(text).lower()
    hits: list[tuple[int, int, Period]] = []
    for kind, pattern in _PATTERNS:
        for match in re.finditer(pattern, low):
            groups = match.groups()
            if kind == "Y":
                period = Period("Y", 0, int(groups[0]), match.group(0).strip())
            elif kind == "A":
                period = Period("A", 0, int(groups[0]), match.group(0).strip())
            elif kind == "Q":
                number = _ROMAN.get(groups[0]) or int(groups[0])
                period = Period("Q", number, _year(groups[1] if len(groups) > 1 else None), match.group(0).strip())
            elif kind == "S":
                period = Period("S", 6, _year(groups[0]), match.group(0).strip())
            elif kind == "L" and pattern.startswith(r"\bnua"):
                period = Period("L", 6, _year(groups[0]), match.group(0).strip())
            elif kind == "L":
                months = 6 if pattern.startswith(r"\bh") else int(groups[0])
                period = Period("L", months, _year(groups[1] if len(groups) > 1 else None), match.group(0).strip())
            else:
                period = Period(kind, int(groups[0]), _year(groups[1] if len(groups) > 1 else None), match.group(0).strip())
            hits.append((match.start(), match.end(), period))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    result: list[Period] = []
    last_end = -1
    for start, end, period in hits:
        if start >= last_end:
            result.append(period)
            last_end = end
    return result


def matches(query: Period, candidate: Period) -> bool:
    """A query without a year matches any year of the same period."""
    if query.kind == "R" or candidate.kind == "R":
        return query.raw == candidate.raw and bool(query.raw)
    if query.kind == "Y" and candidate.kind == "A":
        return query.year is None or query.year in {candidate.year, candidate.year + 1}
    if query.kind != candidate.kind or query.number != candidate.number:
        return False
    return query.year is None or candidate.year is None or query.year == candidate.year


def parts_of(period: Period) -> list[Period]:
    """Smaller periods that add up to a cumulative period or a year."""
    if period.kind == "L":
        months = [Period("M", m, period.year) for m in range(1, period.number + 1)]
        quarters = [Period("Q", q, period.year) for q in range(1, period.number // 3 + 1)]
        return quarters + months
    if period.kind == "S":
        return [Period("Q", q, period.year) for q in (3, 4)] + [Period("M", m, period.year) for m in range(7, 13)]
    if period.kind == "Y":
        return [Period("Q", q, period.year) for q in range(1, 5)] + [Period("M", m, period.year) for m in range(1, 13)]
    return []


def shift(period: Period, *, months: int = 0, years: int = 0) -> Period | None:
    """The previous month or quarter, or the same period one year away."""
    year = period.year + years if period.year is not None else None
    if years and period.year is None:
        return None
    number = period.number
    if months:
        if period.kind not in {"M", "Q"}:
            return None
        step = months if period.kind == "M" else months // 3
        limit = 12 if period.kind == "M" else 4
        number += step
        while number < 1:
            number += limit
            year = year - 1 if year is not None else None
        while number > limit:
            number -= limit
            year = year + 1 if year is not None else None
    return Period(period.kind, number, year)


def display(period: Period) -> str:
    year = f"/{period.year}" if period.year else ""
    if period.kind == "Q":
        return f"Quý {period.number}{year}"
    if period.kind == "M":
        return f"Tháng {period.number}{year}"
    if period.kind == "L":
        return f"{period.number} tháng{year}"
    if period.kind == "S":
        return f"6 tháng cuối{year}"
    if period.kind == "Y":
        return f"Năm {period.year}"
    if period.kind == "A":
        return f"Năm học {period.year}-{period.year + 1}"
    return period.raw
