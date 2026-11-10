"""Find the exact numbers a request needs, or say precisely why that is not possible."""

import copy
from dataclasses import dataclass, field

from .calculator import Operand
from .evidence import Evidence, EvidenceStore
from .numbers import fmt
from .periods import matches, parse_period, parts_of
from .request import OperandRef, Option, QueryRequest
from .units import parse_unit
from .text import norm, tokens

NOT_FOUND = "not_found"
CONFLICT = "source_conflict"
CLARIFY = "needs_clarification"


@dataclass
class ResolvedOperand:
    operand: Operand
    evidence: Evidence


@dataclass
class Resolved:
    request: QueryRequest
    operands: list[ResolvedOperand]
    context: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Stop:
    """Resolution ended without numbers to calculate on."""

    status: str
    message: str
    options: list[Option] = field(default_factory=list)
    related: list[str] = field(default_factory=list)


def param_key(evidence: Evidence) -> str:
    return evidence.code.removeprefix("EVD_")


def _to_operand(role: str, evidence: Evidence) -> ResolvedOperand:
    value = evidence.current_value
    operand = Operand(param_key=param_key(evidence), role=role, value=value, unit=evidence.unit, data_status=evidence.data_status,
                      label=evidence.series, period=evidence.period_text, is_estimate=evidence.is_estimate,
                      text=evidence.text_content if evidence.is_text else None)
    return ResolvedOperand(operand, evidence)


def related_series(store: EvidenceStore, hint: str, limit: int = 5) -> list[str]:
    wanted = set(tokens(hint))
    scored = [(len(wanted & set(tokens(name))), name) for name in store.series_names()]
    return [name for score, name in sorted(scored, key=lambda x: (-x[0], x[1])) if score][:limit]


def _swap_series(request: QueryRequest, hint: str, name: str) -> QueryRequest:
    clone = copy.deepcopy(request)
    for operand in clone.operands:
        if operand.series == hint:
            operand.series = name
    clone.group_series = [name if g == hint else g for g in clone.group_series]
    return clone


def _series(store: EvidenceStore, hint: str, request: QueryRequest, period_text: str | None = None) -> str | Stop:
    found = store.find_series(hint)
    if len(found) == 1:
        return found[0]
    period = parse_period(period_text)
    if len(found) > 1 and period is not None:
        having = [name for name in found if store.lookup(name, period)]
        if not having:
            return Stop(NOT_FOUND, f"Báo cáo không có “{hint}” cho {period_text}.", related=found[:3])
        if len(having) == 1:
            return having[0]
        found = having
    if not found:
        related = related_series(store, hint)
        return Stop(NOT_FOUND, f"Báo cáo không có chỉ tiêu “{hint}”.", related=related)
    return Stop(CLARIFY, f"“{hint}” có nhiều chỉ tiêu phù hợp. Bạn muốn xem chỉ tiêu nào?",
                options=[Option(name, _swap_series(request, hint, name)) for name in found])


def _swap_period(request: QueryRequest, ref: OperandRef, period_text: str) -> QueryRequest:
    clone = copy.deepcopy(request)
    if ref not in request.operands:  # a ranking keeps its periods on the request, not on operands
        field_name = {"item": "period", "base": "base_period", "target": "target_period"}[ref.role]
        setattr(clone, field_name, period_text)
        return clone
    index = request.operands.index(ref)
    old = ref.period
    for position, operand in enumerate(clone.operands):
        if position == index or (operand.series == ref.series and operand.period == old):
            operand.period = period_text
    return clone


def _pick(store: EvidenceStore, series: str, ref: OperandRef, request: QueryRequest, warnings: list[str]) -> Evidence | Stop:
    """One evidence for a series and period, handling revisions, source conflicts and unknown years."""
    pinned = ref.evidence or request.pins.get(f"{series}|{ref.period or ''}")
    if pinned:
        chosen = store.by_code.get(pinned)
        if chosen is None:
            return Stop(NOT_FOUND, f"Không có số liệu mã {pinned}.")
        return chosen
    period = parse_period(ref.period)
    items = store.lookup(series, period)
    if not items:
        available = sorted({e.period_text for e in store.in_series(series) if e.period_text})
        where = f" cho {ref.period}" if ref.period else ""
        have = f" Báo cáo chỉ có: {', '.join(available)}." if available else ""
        return Stop(NOT_FOUND, f"Báo cáo không có “{series}”{where}.{have}", related=[series])

    numbers = [e for e in items if not e.is_text]
    if period is None and len({e.period_text for e in numbers}) > 1:
        choices = sorted({e.period_text for e in numbers})
        return Stop(CLARIFY, f"“{series}” có nhiều kỳ. Bạn muốn xem kỳ nào?",
                    options=[Option(text, _swap_period(request, ref, text)) for text in choices])
    school_years = {e.period.year for e in items if e.period and e.period.kind == "A"}
    if period is not None and period.kind == "Y" and len(school_years) > 1:
        choices = sorted({e.period_text for e in items})
        return Stop(CLARIFY, f"“{ref.period}” có thể là nhiều năm học. Bạn muốn xem năm học nào?",
                    options=[Option(text, _swap_period(request, ref, text)) for text in choices])
    if period is not None and period.year is None:
        years = sorted({e.period.year for e in items if e.period and e.period.year})
        if len(years) > 1:
            choices = sorted({e.period_text for e in items})
            return Stop(CLARIFY, f"“{ref.period}” có ở nhiều năm. Bạn muốn xem năm nào?",
                        options=[Option(text, _swap_period(request, ref, text)) for text in choices])

    revised = {e.revises for e in items if e.revises}
    if revised:
        for item in items:
            if item.code in revised:
                warnings.append(f"Dùng số đã điều chỉnh thay cho số sơ bộ {fmt(item.current_value)} {item.unit.label}.".replace("  ", " "))
        items = [e for e in items if e.code not in revised]

    dimensions = {e.unit.dimension for e in items if e.current_value is not None}
    if len(dimensions) > 1:
        wanted = parse_unit(request.output_unit)
        fitting = [e for e in items if e.unit.compatible(wanted)]
        if not fitting:
            usable = [e for e in items if e.data_status == "valid"]
            return Stop(CLARIFY, f"“{series}”, {ref.period or items[0].period_text} có ở nhiều đơn vị. Bạn muốn dùng đơn vị nào?",
                        options=[Option(e.unit.label, _pin(request, ref, e)) for e in usable])
        items = fitting

    def key(item: Evidence):
        if item.current_value is None:
            return ("none", item.data_status)
        return ("value", item.current_value * item.unit.factor, item.unit.dimension)

    if len({key(e) for e in items}) > 1:
        usable = [e for e in items if e.data_status == "valid"]
        if len(usable) == 1:
            return usable[0]
        lines = "; ".join(_source_text(e) for e in usable)
        return Stop(CONFLICT, f"Báo cáo ghi hai số khác nhau cho “{series}”, {ref.period or items[0].period_text}: {lines}. Bạn muốn dùng số nào?",
                    options=[Option(_source_text(e), _pin(request, ref, e)) for e in usable])
    return sorted(items, key=lambda e: (e.extraction_method != "direct_label", e.code))[0]


def _source_text(evidence: Evidence) -> str:
    kinds = {"text_paragraph": "văn bản", "table_cell": "bảng", "chart_bar": "biểu đồ cột", "chart_line": "biểu đồ đường"}
    value = fmt(evidence.current_value) if evidence.current_value is not None else "không có"
    return f"{value} {evidence.unit.label} ({kinds[evidence.source_type]}, trang {evidence.page})".replace("  ", " ")


def _pin(request: QueryRequest, ref: OperandRef, evidence: Evidence) -> QueryRequest:
    clone = copy.deepcopy(request)
    if ref in request.operands:
        clone.operands[request.operands.index(ref)].evidence = evidence.code
    else:
        clone.pins[f"{evidence.series}|{ref.period or ''}"] = evidence.code
    return clone


def _expand_cumulative(store: EvidenceStore, series: str, ref: OperandRef) -> list[Evidence] | None:
    """'6 tháng' with no direct number: use quarters or months that fully cover it."""
    period = parse_period(ref.period)
    if period is None or period.kind not in {"L", "Y"}:
        return None
    for kind, count in (("Q", period.number // 3 if period.kind == "L" else 4), ("M", period.number if period.kind == "L" else 12)):
        wanted = [p for p in parts_of(period) if p.kind == kind][:count]
        found = []
        for part in wanted:
            items = [e for e in store.in_series(series) if e.period and matches(part, e.period)]
            if len(items) != 1:
                found = None
                break
            found.append(items[0])
        if found:
            return found
    return None


def _context(store: EvidenceStore, operands: list[ResolvedOperand]) -> list[Evidence]:
    """Definition paragraphs that explain a metric used in this answer."""
    names = [set(tokens(o.evidence.series)) for o in operands]
    result = []
    for item in store.items:
        if not item.is_text or not norm(item.series).startswith("dinh nghia"):
            continue
        topic = set(tokens(item.series)) - {"dinh", "nghia"}
        if topic and any(topic <= name for name in names):
            result.append(item)
    return result


def _rank_operands(store: EvidenceStore, request: QueryRequest, warnings: list[str]) -> list[ResolvedOperand] | Stop:
    hints = request.group_series or [o.series for o in request.operands]
    series_names: list[str] = []
    for hint in hints:
        found = store.find_series(hint)
        if not found:
            return Stop(NOT_FOUND, f"Báo cáo không có chỉ tiêu “{hint}”.", related=related_series(store, hint))
        series_names.extend(n for n in found if n not in series_names)
    metric = request.metric_type or ("value" if not request.base_period else None)
    result: list[ResolvedOperand] = []
    if metric == "value":
        if len(series_names) == 1 and not request.period:
            numbers = [item for item in store.in_series(series_names[0]) if not item.is_text]
            lengths = sorted({item.period.months for item in numbers if item.period and item.period.months})
            if request.period_months:
                numbers = [item for item in numbers if item.period and item.period.months == request.period_months]
            elif len(lengths) > 1:
                options = []
                for months in lengths:
                    clone = copy.deepcopy(request)
                    clone.period_months = months
                    options.append(Option(f"So các kỳ {months} tháng", clone))
                return Stop(CLARIFY, f"“{series_names[0]}” có các kỳ dài ngắn khác nhau nên không xếp chung được. Bạn muốn so các kỳ nào?", options=options)
            if not numbers:
                return Stop(NOT_FOUND, f"Báo cáo không có kỳ {request.period_months} tháng cho “{series_names[0]}”.")
            return [_to_operand("item", item) for item in numbers]
        for name in series_names:
            pick = _pick(store, name, OperandRef("item", name, request.period), request, warnings)
            if isinstance(pick, Stop):
                if pick.status == NOT_FOUND and len(series_names) > 1:
                    continue
                return pick
            result.append(_to_operand("item", pick))
        return result or Stop(NOT_FOUND, "Báo cáo không có số liệu cho kỳ này.")
    for name in series_names:
        for role, period_text in (("base", request.base_period), ("target", request.target_period)):
            pick = _pick(store, name, OperandRef(role, name, period_text), request, warnings)
            if isinstance(pick, Stop):
                if pick.status == NOT_FOUND:
                    continue
                return pick
            result.append(_to_operand(role, pick))
    return result or Stop(NOT_FOUND, "Báo cáo không có số liệu cho các kỳ này.")


def resolve(store: EvidenceStore, request: QueryRequest) -> Resolved | Stop:
    warnings: list[str] = []
    if request.operation == "rank_group":
        built = _rank_operands(store, request, warnings)
        if isinstance(built, Stop):
            return built
        return Resolved(request, built, _context(store, built), warnings)

    built: list[ResolvedOperand] = []
    for ref in request.operands:
        name = _series(store, ref.series, request, ref.period)
        if isinstance(name, Stop):
            return name
        pick = _pick(store, name, ref, request, warnings)
        if isinstance(pick, Stop):
            if pick.status == NOT_FOUND and request.operation in {"sum", "share", "ratio"}:
                parts = _expand_cumulative(store, name, ref)
                if parts:
                    role = "item" if ref.role == "subject" else ref.role
                    built.extend(_to_operand(role, item) for item in parts)
                    continue
            return pick
        built.append(_to_operand(ref.role, pick))
    seen, unique = set(), []
    for item in built:
        identity = (item.evidence.code, item.operand.role)
        if identity not in seen:
            seen.add(identity)
            unique.append(item)
    return Resolved(request, unique, _context(store, unique), warnings)
