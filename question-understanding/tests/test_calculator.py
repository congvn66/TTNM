from decimal import Decimal as D

from hypothesis import given
from hypothesis import strategies as st

from qunderstand.calculator import DIV_ZERO, ERROR, MISSING, OK, UNIT_MISMATCH, Operand, calculate
from qunderstand.units import parse_unit

MIL = parse_unit("triệu đồng")
BIL = parse_unit("tỷ đồng")
ORD = parse_unit("nghìn đơn")
PCT = parse_unit("%")
TAN = parse_unit("tấn")


def op(key, role, value, unit=MIL, status="valid", label="", period=""):
    return Operand(key, role, None if value is None else D(str(value)), unit, status, label or key, period)


def test_sum_and_conversion():
    result = calculate("sum", [op("a", "item", 100), op("b", "item", 2, BIL)])
    assert (result.status, result.value, result.unit_label) == (OK, 2100, "triệu đồng")


def test_sum_refuses_partial_when_one_is_missing():
    result = calculate("sum", [op("a", "item", 100), op("b", "item", None, status="missing")])
    assert result.status == MISSING and result.value is None and result.problem_keys == ["b"]


def test_error_status_wins_over_missing():
    result = calculate("sum", [op("a", "item", None, status="missing"), op("b", "item", None, status="error")])
    assert result.status == ERROR


def test_zero_is_a_value_not_missing():
    assert calculate("sum", [op("a", "item", 0), op("b", "item", 5)]).value == 5
    assert calculate("lookup", [op("a", "subject", 0)]).value == 0


def test_units_that_do_not_mix():
    assert calculate("sum", [op("a", "item", 1), op("b", "item", 1, ORD)]).status == UNIT_MISMATCH
    assert calculate("diff", [op("t", "target", 1), op("b", "base", 1, PCT)]).status == UNIT_MISMATCH
    assert calculate("pct_growth", [op("t", "target", 1), op("b", "base", 1, ORD)]).status == UNIT_MISMATCH


def test_pct_growth():
    result = calculate("pct_growth", [op("t", "target", 21350), op("b", "base", 18240)])
    assert round(result.value, 2) == D("17.05") and result.extra["absolute_change"] == 3110
    assert calculate("pct_growth", [op("t", "target", 1250), op("b", "base", 0)]).status == DIV_ZERO
    assert calculate("pct_growth", [op("t", "target", 0), op("b", "base", 10)]).value == -100


def test_pct_growth_negative_base_warns():
    result = calculate("pct_growth", [op("t", "target", 50), op("b", "base", -100)])
    assert result.value == 150 and result.warnings


def test_pct_point_diff_requires_percent():
    assert calculate("pct_point_diff", [op("t", "target", 48, PCT), op("b", "base", 40, PCT)]).value == 8
    assert calculate("pct_point_diff", [op("t", "target", 48), op("b", "base", 40)]).status == UNIT_MISMATCH


def test_rank_percentage_excludes_zero_base_and_missing():
    operands = [op("ab", "base", 18240, label="Bắc"), op("at", "target", 21350, label="Bắc"), op("bb", "base", 8120, label="Trung"), op("bt", "target", 9860, label="Trung"),
                op("cb", "base", 0, label="XK"), op("ct", "target", 1250, label="XK"), op("db", "base", None, status="missing", label="Nam"), op("dt", "target", 9, label="Nam")]
    result = calculate("rank_group", operands, {"metric_type": "percentage_growth"})
    assert result.ranking[0]["label"] == "Trung" and result.div_by_zero
    assert {e["label"]: e["reason"] for e in result.excluded} == {"XK": DIV_ZERO, "Nam": MISSING}


def test_rank_absolute_mixed_scale():
    operands = [op("ab", "base", 1, BIL, label="A"), op("at", "target", 3000, MIL, label="A"), op("bb", "base", 100, MIL, label="B"), op("bt", "target", 200, MIL, label="B")]
    result = calculate("rank_group", operands, {"metric_type": "absolute"})
    assert result.ranking[0]["label"] == "A"
    assert result.ranking[0]["metric"] == 2 and result.unit_label == "tỷ đồng"


def test_rank_tie():
    result = calculate("rank_group", [op("a", "item", 5, label="A"), op("b", "item", 5, label="B"), op("c", "item", 1, label="C")], {"metric_type": "value"})
    assert result.is_tie and [r["rank"] for r in result.ranking] == [1, 1, 3]


def test_rank_ascending():
    result = calculate("rank_group", [op("a", "item", 5, label="A"), op("b", "item", 1, label="B")], {"metric_type": "value", "order": "ASC"})
    assert result.ranking[0]["label"] == "B"


def test_rank_all_excluded_reports_reason():
    result = calculate("rank_group", [op("a", "base", 0, label="A"), op("b", "target", 1, label="A")], {"metric_type": "percentage_growth"})
    assert result.status == DIV_ZERO and result.value is None


def test_share_converts_units():
    result = calculate("share", [op("a", "numerator", 42290), op("b", "numerator", 49880), op("g", "denominator", 220, BIL)])
    assert round(result.value, 1) == D("41.9")
    assert calculate("share", [op("a", "numerator", 1), op("g", "denominator", 0)]).status == DIV_ZERO


def test_apply_rate():
    assert calculate("apply_rate", [op("b", "base", 17420), op("r", "rate", 31, PCT)]).value == D("5400.20")
    assert calculate("apply_rate", [op("b", "base", 21350), op("r", "rate", 8, PCT)], {"mode": "add"}).value == 23058
    assert calculate("apply_rate", [op("b", "base", 1), op("r", "rate", 8)]).status == UNIT_MISMATCH


def test_ratio_scales_label():
    result = calculate("ratio", [op("r", "numerator", 17420), op("a", "denominator", 110, ORD)])
    assert round(result.value, 2) == D("158.36") and result.unit_label == "nghìn đồng/đơn"
    assert calculate("ratio", [op("r", "numerator", 1), op("a", "denominator", 0, ORD)]).status == DIV_ZERO


def test_bad_inputs_do_not_raise():
    assert calculate("nope", [op("a", "item", 1)]).status == "invalid_request"
    assert calculate("sum", []).status == "invalid_request"
    assert calculate("pct_growth", [op("t", "target", 1)]).status == "invalid_request"
    assert calculate("rank_group", [op("a", "item", 1)], {"metric_type": "nope"}).status == "invalid_request"


numbers = st.decimals(min_value=-10**12, max_value=10**12, places=2, allow_nan=False, allow_infinity=False)


@given(st.lists(numbers, min_size=1, max_size=20))
def test_sum_matches_python_sum(values):
    assert calculate("sum", [op(str(i), "item", v) for i, v in enumerate(values)]).value == sum(values)


@given(numbers, numbers)
def test_diff_antisymmetric(a, b):
    assert calculate("diff", [op("t", "target", a), op("b", "base", b)]).value == -calculate("diff", [op("t", "target", b), op("b", "base", a)]).value


@given(numbers, numbers)
def test_pct_growth_never_raises(a, b):
    result = calculate("pct_growth", [op("t", "target", a), op("b", "base", b)])
    assert (result.status == DIV_ZERO) == (b == 0)
    if b > 0:
        assert (result.value > 0) == (a > b)


@given(st.lists(numbers, min_size=1, max_size=12), st.sampled_from(["DESC", "ASC"]))
def test_rank_is_sorted_with_valid_positions(values, order):
    result = calculate("rank_group", [op(str(i), "item", v, label=str(i)) for i, v in enumerate(values)], {"metric_type": "value", "order": order})
    metrics = [r["metric"] for r in result.ranking]
    assert metrics == sorted(metrics, reverse=order == "DESC")
    assert result.ranking[0]["rank"] == 1 and len(result.ranking) == len(values)


@given(numbers, st.sampled_from(["triệu đồng", "tỷ đồng", "nghìn đồng"]))
def test_scale_does_not_change_growth(value, label):
    unit = parse_unit(label)
    base = calculate("pct_growth", [op("t", "target", value), op("b", "base", 7)])
    scaled = calculate("pct_growth", [op("t", "target", value * unit.factor), op("b", "base", 7 * unit.factor)])
    assert round(base.value, 6) == round(scaled.value, 6)


def test_output_unit_converts_or_refuses():
    assert calculate("lookup", [op("a", "subject", 50000, TAN)], {"output_unit": "nghìn tấn"}).value == 50
    refused = calculate("lookup", [op("a", "subject", 100, BIL)], {"output_unit": "USD"})
    assert refused.status == "unit_mismatch" and refused.value is None


def test_percent_of_two_periods_cannot_be_added():
    first, second = op("a", "item", 80, PCT, label="Tỷ lệ", period="T1"), op("b", "item", 75, PCT, label="Tỷ lệ", period="T2")
    assert calculate("sum", [first, second]).status == "unit_mismatch"


def test_percent_shares_of_one_period_can_be_added():
    first, second = op("a", "item", 30, PCT, label="Tỷ trọng - A", period="T1"), op("b", "item", 20, PCT, label="Tỷ trọng - B", period="T1")
    assert calculate("sum", [first, second]).value == 50


def test_rank_by_percent_leaves_out_a_negative_base():
    rows = [op("a", "base", -80, MIL, label="A"), op("b", "target", 120, MIL, label="A"), op("c", "base", 100, MIL, label="B"), op("d", "target", 110, MIL, label="B")]
    result = calculate("rank_group", rows, {"metric_type": "percentage_growth"})
    assert result.ranking[0]["label"] == "B" and result.excluded == [{"label": "A", "reason": "negative_base"}]
