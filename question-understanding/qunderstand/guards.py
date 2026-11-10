"""Rules the program applies whatever the AI says.

The baseline test showed that even strong models often pick one meaning of an ambiguous
question without saying so. These checks do not depend on the model.
"""

import copy
import re

from .evidence import EvidenceStore
from .periods import Period, parse_period
from .request import OperandRef, Option, QueryRequest
from .resolver import Resolved
from .text import norm

_RANK_WORDS = re.compile(r"\b(nhieu nhat|manh nhat|tot nhat|cao nhat|lon nhat)\b")
_CHANGE_WORDS = re.compile(r"\b(tang|tang truong|cai thien)\b")
_EXPLICIT_PCT = re.compile(r"%|phan tram|\bty le\b|\btoc do\b|nhanh nhat")
_EXPLICIT_ABS = re.compile(r"so tuyet doi|gia tri tuyet doi|\bso luong\b|\bso tien\b|\bty dong\b|\btrieu dong\b|\bbao nhieu cua hang\b")
_POINT_WORDS = re.compile(r"\bdiem\b|\bdpt\b|ppts?\b")
_RELATIVE_WORDS = re.compile(r"tuong doi")
_PERIOD_WANTED = [(re.compile(r"\b(nua nam|6 thang) nao\b"), 6), (re.compile(r"\bquy nao\b"), 3), (re.compile(r"\bthang nao\b"), 1), (re.compile(r"\bnam nao\b"), 12)]
_STOCK_SERIES = re.compile(r"thue bao|cua hang|du no|ton kho|no vay|tai san|von chu|nhan vien|nhan su|sinh vien|giuong|cong suat")
_PLAIN_PROFIT = re.compile(r"\bloi nhuan\b(?!\s+(gop|rong|thuan|sau|truoc|hoat dong|tu|cua co dong|cong ty me))")
_PROFIT_KIND = re.compile(r"\bloi nhuan\s+(gop|rong|thuan|sau|truoc)\b")
_POINT_IN_TIME_UNITS = re.compile(r"cua hang|giuong|nhan su|nhan vien|sinh vien|ngay|lan|percent|percentage_point|unknown")


def guard_before_resolve(question: str, request: QueryRequest) -> QueryRequest:
    """'Tăng nhiều nhất' has two meanings unless the question names one."""
    if request.intent != "answer" or request.operation != "rank_group":
        return request
    text = norm(question)
    if not request.period and not request.base_period and not request.period_months:
        for pattern, months in _PERIOD_WANTED:
            if pattern.search(text):
                request = copy.deepcopy(request)
                request.period_months = months
                break
    if request.metric_type == "value" or not request.base_period or not request.target_period:
        return request
    if not _RANK_WORDS.search(text) or not _CHANGE_WORDS.search(text):
        return request
    has_pct, has_abs = bool(_EXPLICIT_PCT.search(text)), bool(_EXPLICIT_ABS.search(text))
    if has_pct != has_abs:
        chosen = copy.deepcopy(request)
        chosen.metric_type = "percentage_growth" if has_pct else "absolute"
        return chosen
    by_abs, by_pct = copy.deepcopy(request), copy.deepcopy(request)
    by_abs.metric_type, by_pct.metric_type = "absolute", "percentage_growth"
    return QueryRequest(intent="clarify", question="Bạn muốn so theo số tuyệt đối hay theo tỷ lệ phần trăm?",
                        options=[Option("Theo số tuyệt đối", by_abs), Option("Theo tỷ lệ phần trăm", by_pct)],
                        reason="rank_metric_ambiguous")


def _period_label(store: EvidenceStore, series: str, wanted: Period) -> str | None:
    for item in store.items:
        if item.series == series and item.period and item.period.key() == wanted.key():
            return item.period_text
    return None


def _different_lengths(store: EvidenceStore, resolved: Resolved) -> QueryRequest | None:
    """Quarter against nine months: the numbers subtract, but the answer means nothing. Offer the like-for-like pairs."""
    request = resolved.request
    pair = {o.operand.role: o for o in resolved.operands if o.operand.role in {"base", "target"}}
    if request.operation not in {"diff", "pct_growth"} or len(pair) != 2:
        return None
    base, target = pair["base"], pair["target"]
    base_period, target_period = parse_period(base.operand.period), parse_period(target.operand.period)
    if not base_period or not target_period or base_period.kind == "R" or target_period.kind == "R":
        return None
    if base_period.months == target_period.months:
        return None
    if _POINT_IN_TIME_UNITS.search(target.operand.unit.dimension):
        return None
    refs = {ref.role: ref for ref in request.operands}
    options = []
    for label, role, wanted in (("base", "base", Period(target_period.kind, target_period.number, base_period.year)),
                                ("target", "target", Period(base_period.kind, base_period.number, target_period.year))):
        series = pair[role].evidence.series
        found = _period_label(store, series, wanted) if wanted.year else None
        other = "target" if role == "base" else "base"
        if not found or found == pair[other].operand.period or role not in refs:
            continue
        clone = copy.deepcopy(request)
        for ref in clone.operands:
            if ref.role == role:
                ref.period, ref.evidence = found, None
        options.append(Option(f"So {pair['target'].operand.period if label == 'base' else found} với {found if label == 'base' else pair['base'].operand.period}", clone))
    options.append(Option(f"Vẫn so {target.operand.period} với {base.operand.period}", copy.deepcopy(request)))
    return QueryRequest(intent="clarify", question=f"Hai kỳ dài ngắn khác nhau ({target.operand.period} và {base.operand.period}) nên phép so sánh dễ sai nghĩa. Bạn muốn so thế nào?",
                        options=options, reason="period_length_mismatch")


def _negative_base(resolved: Resolved) -> QueryRequest | None:
    """From a loss to a profit, a percent change has no clear meaning. The absolute change does."""
    request = resolved.request
    if request.operation != "pct_growth":
        return None
    base = next((o.operand for o in resolved.operands if o.operand.role == "base"), None)
    if base is None or base.value is None or base.value >= 0:
        return None
    absolute, percent = copy.deepcopy(request), copy.deepcopy(request)
    absolute.operation = "diff"
    return QueryRequest(intent="clarify", question=f"Kỳ gốc ({base.period}) là số âm nên phần trăm thay đổi không có ý nghĩa rõ ràng. Bạn muốn xem gì?",
                        options=[Option("Xem mức chênh lệch tuyệt đối", absolute), Option("Vẫn tính phần trăm", percent)], reason="negative_base")


def _unnamed_profit(question: str, resolved: Resolved) -> QueryRequest | None:
    """The question says only 'lợi nhuận' and a model picked one kind of profit. Ask the user to confirm the kind."""
    if not _PLAIN_PROFIT.search(norm(question)):
        return None
    kinds = sorted({o.operand.label.partition(" - ")[0] for o in resolved.operands if _PROFIT_KIND.search(norm(o.operand.label))})
    if not kinds:
        return None
    return QueryRequest(intent="clarify", question=f"Câu hỏi chỉ ghi “lợi nhuận”. Bạn muốn xem {', '.join(kinds)} phải không?",
                        options=[Option(f"Đúng, xem {', '.join(kinds)}", copy.deepcopy(resolved.request))], reason="profit_kind_not_named")


def _stock_added_over_time(resolved: Resolved) -> QueryRequest | None:
    """Subscribers or debt at the end of each quarter are counted again each quarter, so a sum over time means nothing."""
    request = resolved.request
    numbers = [o for o in resolved.operands if o.operand.value is not None]
    if request.operation != "sum" or len({o.operand.period for o in numbers}) < 2 or not all(_STOCK_SERIES.search(norm(o.operand.label)) for o in numbers):
        return None
    options = []
    for item in numbers:
        options.append(Option(f"Xem {item.operand.period}", QueryRequest(intent="answer", operation="lookup", operands=[OperandRef("subject", item.operand.label, item.operand.period)])))
    return QueryRequest(intent="clarify", question=f"“{numbers[0].operand.label}” là số tại một thời điểm nên cộng qua các kỳ sẽ đếm lặp. Bạn muốn xem kỳ nào?",
                        options=options, reason="stock_added_over_time")


def guard_after_resolve(question: str, resolved: Resolved, store: EvidenceStore) -> QueryRequest | None:
    """Questions that look answerable but mix unlike things. Returns a clarify request, or None."""
    for found in (_different_lengths(store, resolved), _negative_base(resolved), _unnamed_profit(question, resolved), _stock_added_over_time(resolved)):
        if found is not None:
            return found
    request = resolved.request
    if request.operation not in {"pct_growth", "pct_point_diff", "diff"}:
        return None
    pair = [o.operand for o in resolved.operands if o.operand.role in {"base", "target"}]
    if len(pair) != 2 or any(o.unit.dimension != "percent" for o in pair):
        return None
    text = norm(question)
    if _POINT_WORDS.search(text):
        request.operation = "pct_point_diff"
        return None
    if _RELATIVE_WORDS.search(text):
        request.operation = "pct_growth"
        return None
    if request.operation == "pct_growth" and "phan tram" not in text and "%" not in text:
        request.operation = "pct_point_diff"
        return None
    if request.operation == "diff" or ("phan tram" not in text and "%" not in text):
        request.operation = "pct_point_diff"
        return None
    by_points, by_relative = copy.deepcopy(request), copy.deepcopy(request)
    by_points.operation, by_relative.operation = "pct_point_diff", "pct_growth"
    return QueryRequest(intent="clarify", question="Chỉ số này đã là phần trăm. Bạn muốn xem chênh lệch theo điểm phần trăm hay mức tăng tương đối?",
                        options=[Option("Theo điểm phần trăm", by_points), Option("Theo mức tăng tương đối", by_relative)],
                        reason="percent_change_ambiguous")
