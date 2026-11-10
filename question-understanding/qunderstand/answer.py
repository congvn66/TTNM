"""Write the final Vietnamese answer from computed values. The AI writes none of these numbers."""

from .calculator import DIV_ZERO, ERROR, MISSING, OK, UNIT_MISMATCH, CalcResult
from .numbers import fmt
from .resolver import ResolvedOperand

LABELS = {"lookup": "tra cứu", "sum": "tổng", "diff": "hiệu", "pct_growth": "phần trăm thay đổi", "pct_point_diff": "chênh lệch điểm phần trăm",
          "rank_group": "xếp hạng", "share": "tỷ trọng", "apply_rate": "áp tỷ lệ", "ratio": "tỷ số"}


def _with_unit(value, unit: str) -> str:
    text = fmt(value)
    if not unit:
        return text
    return f"{text}%" if unit == "%" else f"{text} {unit}"


def _name(item: ResolvedOperand) -> str:
    op = item.operand
    return f"{op.label}, {op.period}" if op.period else op.label


def _pages(items: list[ResolvedOperand]) -> str:
    pages = sorted({i.evidence.page for i in items if i.evidence.page})
    return f" (trang {', '.join(map(str, pages))})" if pages else ""


def _estimate_note(items: list[ResolvedOperand]) -> str:
    return " Số đọc từ biểu đồ là số ước lượng theo trục." if any(i.operand.is_estimate for i in items) else ""


def _inputs(items: list[ResolvedOperand], roles=None) -> str:
    used = [i for i in items if roles is None or i.operand.role in roles]
    return ", ".join(f"{_name(i)}: {_with_unit(i.operand.value, i.operand.unit.label)}" for i in used)


def formula_display(operation: str, items: list[ResolvedOperand], result: CalcResult, args: dict) -> str:
    get = lambda role: [i.operand for i in items if i.operand.role == role]
    if result.status != OK:
        return ""
    show = lambda o: fmt(o.value)
    if operation in {"pct_growth"}:
        target, base = get("target")[0], get("base")[0]
        return f"(({show(target)} - {show(base)}) / {fmt(abs(base.value))}) × 100 = {fmt(result.value)}%"
    if operation in {"diff", "pct_point_diff"}:
        target, base = get("target")[0], get("base")[0]
        return f"{show(target)} - {show(base)} = {_with_unit(result.value, result.unit_label)}"
    if operation == "sum":
        return " + ".join(show(i.operand) for i in items) + f" = {_with_unit(result.value, result.unit_label)}"
    if operation == "share":
        top = " + ".join(f"{show(o)} {o.unit.label}" for o in get("numerator"))
        bottom = " + ".join(f"{show(o)} {o.unit.label}" for o in get("denominator"))
        return f"({top}) / ({bottom}) × 100 = {fmt(result.value)}%"
    if operation == "ratio":
        top = " + ".join(f"{show(o)} {o.unit.label}" for o in get("numerator"))
        bottom = " + ".join(f"{show(o)} {o.unit.label}" for o in get("denominator"))
        return f"({top}) / ({bottom}) = {_with_unit(result.value, result.unit_label)}"
    if operation == "apply_rate":
        base, rate = get("base")[0], get("rate")[0]
        if args.get("mode") == "add":
            return f"{show(base)} × (1 + {show(rate)}%) = {_with_unit(result.value, result.unit_label)}"
        return f"{show(base)} × {show(rate)}% = {_with_unit(result.value, result.unit_label)}"
    if operation == "rank_group" and args.get("metric_type") == "percentage_growth":
        return "((kỳ sau - kỳ gốc) / kỳ gốc) × 100"
    if operation == "rank_group" and args.get("metric_type") == "absolute":
        return "kỳ sau - kỳ gốc"
    return ""


def _rank_text(result: CalcResult, args: dict) -> str:
    metric = args.get("metric_type", "value")
    leaders = [r for r in result.ranking if r["rank"] == 1]
    def name(row):
        return row["label"] if not (metric == "value" and len({r["label"] for r in result.ranking}) == 1) else row["period"]
    names = " và ".join(name(r) for r in leaders)
    direction = "cao nhất" if args.get("order", "DESC") == "DESC" else "thấp nhất"
    value = _with_unit(leaders[0]["metric"], result.unit_label)
    if metric == "percentage_growth":
        lead = f"{names} tăng nhanh nhất theo tỷ lệ, {value}" if args.get("order", "DESC") == "DESC" else f"{names} có tỷ lệ tăng thấp nhất, {value}"
    elif metric == "absolute":
        lead = f"{names} tăng nhiều nhất theo số tuyệt đối, {value}" if args.get("order", "DESC") == "DESC" else f"{names} tăng ít nhất theo số tuyệt đối, {value}"
    else:
        lead = f"{names} {direction}, {value}"
    if result.is_tie:
        lead += " (đồng hạng)"
    others = [r for r in result.ranking if r["rank"] != 1][:4]
    tail = "; ".join(f"{name(r)} {_with_unit(r['metric'], result.unit_label)}" for r in others)
    return f"{lead}. Các mục còn lại: {tail}." if tail else f"{lead}."


def answer_text(operation: str, items: list[ResolvedOperand], result: CalcResult, args: dict, warnings: list[str]) -> str:
    notes = list(warnings) + list(result.warnings)
    pages = _pages(items)
    if result.status == MISSING:
        keys = set(result.problem_keys)
        names = [_name(i) for i in items if i.operand.param_key in keys]
        body = f"Báo cáo chưa có số liệu cho {', '.join(names)}, nên không trả lời được.{pages}" if names else f"Báo cáo chưa có đủ số liệu để trả lời.{pages}"
        body += " Giá trị thiếu không được coi là 0."
    elif result.status == ERROR:
        keys = set(result.problem_keys)
        names = [_name(i) for i in items if i.operand.param_key in keys]
        body = f"Không đọc được số liệu {', '.join(names) or 'cần dùng'}, nên chưa trả lời được. Hãy kiểm tra lại nguồn.{pages}"
    elif result.status == DIV_ZERO:
        body = f"Không tính được phần trăm vì kỳ gốc bằng 0. {_inputs(items)}.{pages}"
    elif result.status == UNIT_MISMATCH:
        units = result.extra.get("units", "")
        body = f"Không tính được vì các số có đơn vị không tương thích ({units}). {_inputs(items)}.{pages}"
    elif result.status != OK:
        body = "Chưa xử lý được yêu cầu này."
    elif operation == "lookup":
        parts = []
        for item in items:
            op = item.operand
            if op.text is not None:
                parts.append(f"{op.label}: {op.text}")
            elif op.value is None:
                parts.append(f"{_name(item)}: chưa có số liệu")
            else:
                prefix = "khoảng " if op.is_estimate else ""
                parts.append(f"{_name(item)}: {prefix}{_with_unit(op.value, op.unit.label)}")
        body = "; ".join(parts) + pages + "."
        if args.get("output_unit") and result.value is not None:
            body += f" Theo đơn vị bạn hỏi: {_with_unit(result.value, result.unit_label)}."
    elif operation == "rank_group":
        body = _rank_text(result, args) + (f" Nguồn{pages}." if pages else "")
    else:
        change = result.extra.get("absolute_change")
        extra = f" ({'+' if change > 0 else ''}{_with_unit(change, result.extra.get('absolute_unit', ''))})" if change is not None else ""
        sign = "+" if operation in {"pct_growth", "pct_point_diff", "diff"} and result.value > 0 else ""
        body = f"{LABELS[operation].capitalize()}: {sign}{_with_unit(result.value, result.unit_label)}{extra}. Số đầu vào: {_inputs(items)}{pages}."
    if result.status == OK:
        body += _estimate_note(items)
    excluded = [e for e in result.excluded]
    if excluded:
        reasons = {DIV_ZERO: "kỳ gốc bằng 0", MISSING: "thiếu số liệu", ERROR: "đọc lỗi", UNIT_MISMATCH: "khác đơn vị", "negative_base": "kỳ gốc là số âm"}
        body += " Không xếp hạng: " + ", ".join(f"{e['label']} ({reasons.get(e['reason'], e['reason'])})" for e in excluded) + "."
    if notes:
        body += " " + " ".join(notes)
    return body
