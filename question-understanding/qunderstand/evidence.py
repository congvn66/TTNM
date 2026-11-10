"""The list of numbers from a report, in the format of data_design.pdf (EVIDENCES)."""

import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from .numbers import AmbiguousNumber, to_decimal
from .periods import Period, matches, parse_period
from .text import deaccent, norm, tokens
from .units import Unit, parse_unit

DATA_STATUS = {"valid", "missing", "error"}
VERIFICATION_STATUS = {"unverified", "verified", "edited"}
SOURCE_TYPE = {"text_paragraph", "table_cell", "chart_bar", "chart_line"}
EXTRACTION = {"direct_label", "axis_estimation", "none"}


class StoreError(ValueError):
    """The store cannot be trusted. The message lists every problem."""


@dataclass(frozen=True)
class Evidence:
    code: str
    source_type: str
    extraction_method: str
    location: dict
    series: str
    period_text: str
    unit: Unit
    raw_value: Decimal | None
    current_value: Decimal | None
    text_content: str | None
    data_status: str
    verification_status: str
    period: Period | None = None
    revises: str | None = None

    @property
    def page(self) -> int | None:
        return self.location.get("page")

    @property
    def is_estimate(self) -> bool:
        return self.extraction_method == "axis_estimation"

    @property
    def is_text(self) -> bool:
        return self.source_type == "text_paragraph" and self.current_value is None


@dataclass
class EvidenceStore:
    document_code: str
    file_name: str
    page_count: int
    items: list[Evidence]
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.by_code = {e.code: e for e in self.items}

    def catalog(self) -> list[dict]:
        """What the AI may see: names only, never a value, so it cannot calculate or copy a number."""
        seen = {}
        for item in self.items:
            key = (item.series, item.period_text, item.unit.label)
            seen.setdefault(key, {"series": item.series, "period": item.period_text, "unit": item.unit.label,
                                  "kind": "text" if item.is_text else "number"})
        return list(seen.values())

    def series_names(self) -> list[str]:
        return sorted({e.series for e in self.items if e.series})

    def find_series(self, hint: str) -> list[str]:
        """Series names that match a hint. Exact match wins. Otherwise every hint word must appear."""
        target = norm(hint)
        exact = [s for s in self.series_names() if norm(s) == target]
        if exact:
            return exact
        wanted = set(tokens(hint))
        if not wanted:
            return []
        names = [s for s in self.series_names() if wanted <= set(tokens(s))]
        if "nghia" not in wanted:
            names = [s for s in names if not norm(s).startswith("dinh nghia")]
        return names

    def in_series(self, series: str) -> list[Evidence]:
        return [e for e in self.items if e.series == series]

    def lookup(self, series: str, period: Period | None) -> list[Evidence]:
        items = self.in_series(series)
        if period is None:
            return items
        return [e for e in items if e.period is None and not e.period_text or (e.period is not None and matches(period, e.period))]


def _load_item(raw: dict, index: int, problems: list[str]) -> Evidence | None:
    label = raw.get("evidence_code") or f"#{index}"
    before = len(problems)
    for key, allowed in (("source_type", SOURCE_TYPE), ("extraction_method", EXTRACTION), ("data_status", DATA_STATUS),
                         ("verification_status", VERIFICATION_STATUS)):
        if raw.get(key) not in allowed:
            problems.append(f"{label}: {key} = {raw.get(key)!r} is not one of {sorted(allowed)}")
    if not raw.get("evidence_code"):
        problems.append(f"{label}: evidence_code is empty")
    location = raw.get("location")
    if not isinstance(location, dict) or not isinstance(location.get("page"), int) or isinstance(location.get("page"), bool) or location.get("page") < 1:
        problems.append(f"{label}: location.page must be a positive integer")
    values = {}
    for key in ("raw_value", "current_value"):
        try:
            values[key] = to_decimal(raw.get(key))
        except AmbiguousNumber:
            problems.append(f"{label}: {key} = {raw.get(key)!r} can mean two numbers. Send a JSON number.")
        except ValueError:
            problems.append(f"{label}: {key} = {raw.get(key)!r} is not a number")
    status = raw.get("data_status")
    if len(problems) == before:
        is_text = raw.get("source_type") == "text_paragraph" and raw.get("text_content")
        if status == "valid" and values["current_value"] is None and not is_text:
            problems.append(f"{label}: data_status is valid but current_value is null")
        if status == "missing" and values["current_value"] is not None:
            problems.append(f"{label}: data_status is missing but current_value has a value. Use null, not 0.")
    if len(problems) != before:
        return None
    return Evidence(
        code=raw["evidence_code"], source_type=raw["source_type"], extraction_method=raw["extraction_method"],
        location=location, series=(raw.get("series_name") or "").strip(), period_text=(raw.get("time_period") or "").strip(),
        unit=parse_unit(raw.get("unit")), raw_value=values["raw_value"], current_value=values["current_value"],
        text_content=raw.get("text_content"), data_status=status, verification_status=raw["verification_status"],
        period=parse_period(raw.get("time_period")), revises=(location.get("meta") or {}).get("revises"),
    )


def _name_quality(name: str) -> tuple:
    has_accents = deaccent(name) != name
    return (has_accents, not name.isupper(), name[:1].isupper(), name != name.title(), name)


def _merge_series_names(items: list[Evidence]) -> list[Evidence]:
    """A PDF step writes one name many ways: 'DOANH THU THUẦN ', 'Doanh thu  thuần', 'Doanh thu thuan'. They are one series."""
    groups: dict[str, set[str]] = {}
    for item in items:
        groups.setdefault(norm(item.series), set()).add(re.sub(r"\s+", " ", unicodedata.normalize("NFC", item.series)).strip())
    best = {key: max(names, key=_name_quality) for key, names in groups.items()}
    best = {key: name[:1].upper() + name[1:] for key, name in best.items()}
    return [replace(item, series=best[norm(item.series)]) for item in items]


def store_from_dict(data: dict) -> EvidenceStore:
    problems: list[str] = []
    for key in ("document_code", "evidences"):
        if key not in data:
            problems.append(f"missing field: {key}")
    if problems:
        raise StoreError("; ".join(problems))
    items, seen = [], set()
    for index, raw in enumerate(data["evidences"]):
        if not isinstance(raw, dict):
            problems.append(f"#{index}: not an object")
            continue
        item = _load_item(raw, index, problems)
        if item is None:
            continue
        if item.code in seen:
            problems.append(f"{item.code}: duplicate evidence_code")
        seen.add(item.code)
        items.append(item)
    for item in items:
        if item.revises and item.revises not in seen:
            problems.append(f"{item.code}: revises unknown evidence {item.revises}")
    if problems:
        raise StoreError(f"{len(problems)} problem(s): " + "; ".join(problems[:20]))
    return EvidenceStore(data["document_code"], data.get("file_name", ""), data.get("page_count", 0), _merge_series_names(items))


def load_store(path: str | Path) -> EvidenceStore:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoreError(f"{path}: not valid JSON: {exc}") from exc
    return store_from_dict(data)
