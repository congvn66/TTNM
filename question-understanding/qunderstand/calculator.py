"""All arithmetic. No AI, no network, no store access. Same input gives the same output."""

from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from .units import UNKNOWN, Unit, convert, parse_unit, scaled_money_label

OPERATIONS = {"lookup", "sum", "diff", "pct_growth", "pct_point_diff", "rank_group", "share", "apply_rate", "ratio"}

OK = "ok"
MISSING = "missing_data"
ERROR = "extraction_error"
DIV_ZERO = "div_by_zero"
UNIT_MISMATCH = "unit_mismatch"
BAD_REQUEST = "invalid_request"
NEGATIVE_BASE = "negative_base"


@dataclass(frozen=True)
class Operand:
    """One input number. role: target, base, item, numerator, denominator, rate."""

    param_key: str
    role: str
    value: Decimal | None
    unit: Unit = UNKNOWN
    data_status: str = "valid"
    label: str = ""
    period: str = ""
    is_estimate: bool = False
    text: str | None = None


@dataclass
class CalcResult:
    status: str
    value: Decimal | None = None
    unit_label: str = ""
    formula: str = ""
    ranking: list[dict] = field(default_factory=list)
    is_tie: bool = False
    excluded: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problem_keys: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def div_by_zero(self) -> bool:
        return self.status == DIV_ZERO or any(e.get("reason") == DIV_ZERO for e in self.excluded)


def _unusable(operands: list[Operand]) -> CalcResult | None:
    missing = [o for o in operands if o.data_status == "missing" or (o.value is None and o.data_status == "valid" and o.text is None)]
    errors = [o for o in operands if o.data_status == "error"]
    if errors:
        return CalcResult(ERROR, problem_keys=[o.param_key for o in errors])
    if missing:
        return CalcResult(MISSING, problem_keys=[o.param_key for o in missing])
    return None


def _common_unit(operands: list[Operand]) -> Unit | None:
    """The first operand's unit if all operands can be converted to it. None means they cannot."""
    first = operands[0].unit
    for operand in operands[1:]:
        if operand.unit.dimension == "unknown" and first.dimension == "unknown":
            continue
        if not first.compatible(operand.unit):
            return None
    return first


def _in_unit(operand: Operand, unit: Unit) -> Decimal:
    return operand.value if unit.dimension == "unknown" else convert(operand.value, operand.unit, unit)


def _by_role(operands: list[Operand], role: str) -> list[Operand]:
    return [o for o in operands if o.role == role]


def _one(operands: list[Operand], role: str) -> Operand | None:
    found = _by_role(operands, role)
    return found[0] if len(found) == 1 else None


def _mismatch(operands: list[Operand]) -> CalcResult:
    labels = ", ".join(sorted({o.unit.label or "không rõ" for o in operands}))
    return CalcResult(UNIT_MISMATCH, problem_keys=[o.param_key for o in operands], extra={"units": labels})


def calculate(operation: str, operands: list[Operand], args: dict | None = None) -> CalcResult:
    args = args or {}
    handler = _HANDLERS.get(operation)
    if handler is None:
        return CalcResult(BAD_REQUEST, extra={"detail": f"unknown operation {operation!r}"})
    if not operands:
        return CalcResult(BAD_REQUEST, extra={"detail": "no operands"})
    if operation != "lookup" and any(o.text is not None for o in operands):
        return CalcResult(BAD_REQUEST, extra={"detail": "text evidence cannot be used in arithmetic"})
    with localcontext() as ctx:
        ctx.prec = 40
        return _to_output_unit(handler(operands, args), args.get("output_unit"))


def _to_output_unit(result: CalcResult, label: str | None) -> CalcResult:
    """The question asked for a unit. Convert when the units are the same kind. Otherwise say so and give no number."""
    if not label or result.status != OK or result.value is None or result.ranking:
        return result
    source, wanted = parse_unit(result.unit_label), parse_unit(label)
    if source.dimension == wanted.dimension and source.dimension in {"percent", "percentage_point"}:
        return result
    if not source.compatible(wanted):
        return CalcResult(UNIT_MISMATCH, extra={"units": f"{result.unit_label or 'không rõ'}, {label}"})
    result.value = convert(result.value, source, wanted)
    result.unit_label = label
    return result


def _lookup(operands, _args):
    numbers = [o for o in operands if o.text is None]
    bad = _unusable(numbers)
    if bad:
        return bad
    if len(numbers) == 1:
        return CalcResult(OK, value=numbers[0].value, unit_label=numbers[0].unit.label)
    return CalcResult(OK)


def _sum(operands, _args):
    bad = _unusable(operands)
    if bad:
        return bad
    unit = _common_unit(operands)
    if unit is None:
        return _mismatch(operands)
    if unit.dimension == "percent" and len(operands) > 1:
        same_period = len({o.period for o in operands}) == 1
        same_metric = len({o.label.partition(" - ")[0] for o in operands}) == 1
        if not (same_period and same_metric):
            return CalcResult(UNIT_MISMATCH, problem_keys=[o.param_key for o in operands], extra={"units": "tỷ lệ % của nhiều kỳ hoặc nhiều chỉ tiêu không cộng được"})
    total = sum((_in_unit(o, unit) for o in operands), Decimal(0))
    return CalcResult(OK, value=total, unit_label=unit.label, formula=" + ".join(o.param_key for o in operands))


def _pair(operands):
    target, base = _one(operands, "target"), _one(operands, "base")
    if target is None or base is None:
        return None, None, CalcResult(BAD_REQUEST, extra={"detail": "needs one target and one base"})
    return target, base, _unusable([base, target])


def _diff(operands, _args):
    target, base, bad = _pair(operands)
    if bad:
        return bad
    unit = _common_unit([target, base])
    if unit is None:
        return _mismatch([target, base])
    value = _in_unit(target, unit) - _in_unit(base, unit)
    label = "điểm phần trăm" if unit.dimension == "percent" else unit.label
    return CalcResult(OK, value=value, unit_label=label, formula=f"{target.param_key} - {base.param_key}")


def _pct_growth(operands, _args):
    target, base, bad = _pair(operands)
    if bad:
        return bad
    unit = _common_unit([target, base])
    if unit is None:
        return _mismatch([target, base])
    base_value = _in_unit(base, unit)
    if base_value == 0:
        return CalcResult(DIV_ZERO, problem_keys=[base.param_key])
    change = _in_unit(target, unit) - base_value
    result = CalcResult(OK, value=change / abs(base_value) * 100, unit_label="%",
                        formula=f"(({target.param_key} - {base.param_key}) / |{base.param_key}|) * 100",
                        extra={"absolute_change": change, "absolute_unit": unit.label})
    if base_value < 0:
        result.warnings.append("Kỳ gốc là số âm nên phần trăm thay đổi cần được đọc cẩn thận.")
    return result


def _pct_point_diff(operands, _args):
    target, base, bad = _pair(operands)
    if bad:
        return bad
    allowed = {"percent", "percentage_point"}
    if target.unit.dimension not in allowed or base.unit.dimension not in allowed:
        return _mismatch([target, base])
    return CalcResult(OK, value=target.value - base.value, unit_label="điểm phần trăm",
                      formula=f"{target.param_key} - {base.param_key}")


def _rank_group(operands, args):
    metric = args.get("metric_type", "value")
    descending = str(args.get("order", "DESC")).upper() != "ASC"
    rows, excluded = [], []
    if metric == "value":
        items = _by_role(operands, "item")
        if not items:
            return CalcResult(BAD_REQUEST, extra={"detail": "rank needs item operands"})
        unit = _common_unit([o for o in items if o.value is not None] or items)
        if unit is None:
            return _mismatch(items)
        for item in items:
            bad = _unusable([item])
            if bad:
                excluded.append({"label": item.label, "period": item.period, "reason": bad.status})
            else:
                rows.append({"label": item.label, "period": item.period, "metric": _in_unit(item, unit)})
        out_unit = unit.label
    elif metric in {"absolute", "percentage_growth"}:
        names = list(dict.fromkeys(o.label for o in operands))
        out_unit = "%"
        for name in names:
            base = next((o for o in operands if o.label == name and o.role == "base"), None)
            target = next((o for o in operands if o.label == name and o.role == "target"), None)
            if base is None or target is None:
                excluded.append({"label": name, "reason": MISSING})
                continue
            bad = _unusable([base, target])
            if bad:
                excluded.append({"label": name, "reason": bad.status})
                continue
            unit = _common_unit([base, target])
            if unit is None:
                excluded.append({"label": name, "reason": UNIT_MISMATCH})
                continue
            base_value, target_value = _in_unit(base, unit), _in_unit(target, unit)
            change = target_value - base_value
            if metric == "absolute":
                out_unit = unit.label
                rows.append({"label": name, "metric": change * unit.factor, "base_val": base_value, "target_val": target_value, "unit": unit})
            elif base_value == 0:
                excluded.append({"label": name, "reason": DIV_ZERO})
            elif base_value < 0:
                excluded.append({"label": name, "reason": NEGATIVE_BASE})
            else:
                rows.append({"label": name, "metric": change / abs(base_value) * 100, "base_val": base_value, "target_val": target_value, "unit": unit})
        if metric == "absolute" and rows:
            units = {r["unit"].dimension for r in rows}
            if len(units) > 1:
                return CalcResult(UNIT_MISMATCH, extra={"units": ", ".join(sorted(units))})
            display = rows[0]["unit"]
            for row in rows:
                row["metric"] = row["metric"] / display.factor
            out_unit = display.label
    else:
        return CalcResult(BAD_REQUEST, extra={"detail": f"unknown metric_type {metric!r}"})
    if not rows:
        reasons = {e["reason"] for e in excluded}
        status = DIV_ZERO if reasons == {DIV_ZERO} else (next(iter(reasons)) if len(reasons) == 1 else MISSING)
        return CalcResult(status, excluded=excluded)
    rows.sort(key=lambda r: r["metric"], reverse=descending)
    position = 0
    previous = None
    for index, row in enumerate(rows):
        if row["metric"] != previous:
            position = index + 1
            previous = row["metric"]
        row["rank"] = position
        row.pop("unit", None)
    leaders = [r for r in rows if r["rank"] == 1]
    return CalcResult(OK, value=rows[0]["metric"], unit_label=out_unit, ranking=rows, is_tie=len(leaders) > 1, excluded=excluded)


def _share(operands, _args):
    numerators, denominators = _by_role(operands, "numerator"), _by_role(operands, "denominator")
    if not numerators or not denominators:
        return CalcResult(BAD_REQUEST, extra={"detail": "share needs numerator and denominator"})
    bad = _unusable(numerators + denominators)
    if bad:
        return bad
    unit = _common_unit(numerators + denominators)
    if unit is None:
        return _mismatch(numerators + denominators)
    bottom = sum((_in_unit(o, unit) for o in denominators), Decimal(0))
    if bottom == 0:
        return CalcResult(DIV_ZERO, problem_keys=[o.param_key for o in denominators])
    top = sum((_in_unit(o, unit) for o in numerators), Decimal(0))
    return CalcResult(OK, value=top / bottom * 100, unit_label="%",
                      formula=f"({' + '.join(o.param_key for o in numerators)}) / ({' + '.join(o.param_key for o in denominators)}) * 100")


def _apply_rate(operands, args):
    base, rate = _one(operands, "base"), _one(operands, "rate")
    if base is None or rate is None:
        return CalcResult(BAD_REQUEST, extra={"detail": "apply_rate needs one base and one rate"})
    bad = _unusable([base, rate])
    if bad:
        return bad
    if rate.unit.dimension != "percent":
        return _mismatch([base, rate])
    fraction = rate.value / 100
    if args.get("mode") == "add":
        return CalcResult(OK, value=base.value * (1 + fraction), unit_label=base.unit.label,
                          formula=f"{base.param_key} * (1 + {rate.param_key} / 100)")
    return CalcResult(OK, value=base.value * fraction, unit_label=base.unit.label, formula=f"{base.param_key} * {rate.param_key} / 100")


def _ratio(operands, _args):
    numerators, denominators = _by_role(operands, "numerator"), _by_role(operands, "denominator")
    if not numerators or not denominators:
        return CalcResult(BAD_REQUEST, extra={"detail": "ratio needs numerator and denominator"})
    bad = _unusable(numerators + denominators)
    if bad:
        return bad
    top_unit, bottom_unit = _common_unit(numerators), _common_unit(denominators)
    if top_unit is None or bottom_unit is None:
        return _mismatch(numerators + denominators)
    bottom = sum((o.value * o.unit.factor for o in denominators), Decimal(0))
    if bottom == 0:
        return CalcResult(DIV_ZERO, problem_keys=[o.param_key for o in denominators])
    top = sum((o.value * o.unit.factor for o in numerators), Decimal(0))
    raw = top / bottom
    if top_unit.dimension == bottom_unit.dimension:
        return CalcResult(OK, value=raw, unit_label="lần", formula=f"{'+'.join(o.param_key for o in numerators)} / {'+'.join(o.param_key for o in denominators)}")
    value, label = scaled_money_label(raw, top_unit.noun or top_unit.dimension, bottom_unit.noun or bottom_unit.dimension)
    return CalcResult(OK, value=value, unit_label=label, formula=f"({'+'.join(o.param_key for o in numerators)}) / ({'+'.join(o.param_key for o in denominators)})",
                      extra={"base_value": raw})


_HANDLERS = {"lookup": _lookup, "sum": _sum, "diff": _diff, "pct_growth": _pct_growth, "pct_point_diff": _pct_point_diff,
             "rank_group": _rank_group, "share": _share, "apply_rate": _apply_rate, "ratio": _ratio}
assert set(_HANDLERS) == OPERATIONS
