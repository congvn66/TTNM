from decimal import Decimal as D

import pytest

from qunderstand.numbers import AmbiguousNumber, fmt, parse_number, to_decimal
from qunderstand.periods import find_periods, matches, parse_period, shift
from qunderstand.units import convert, parse_unit


@pytest.mark.parametrize("text,value", [("12,5", "12.5"), ("1,250.50", "1250.50"), ("2.010,75", "2010.75"), ("(1.740,5)", "-1740.5"), ("-3,2%", "-3.2"), ("0,5", "0.5"), ("1.234.567", "1234567"), ("+18,7%", "18.7"), ("1000", "1000")])
def test_parse_number(text, value):
    assert parse_number(text) == D(value)


@pytest.mark.parametrize("text", ["1,250", "1.250", "21.350", "113,607"])
def test_ambiguous_number_is_refused_without_locale(text):
    with pytest.raises(AmbiguousNumber):
        parse_number(text)


def test_locale_resolves_ambiguity():
    assert parse_number("21.350", locale="vi") == 21350
    assert parse_number("113,607", locale="en") == 113607
    assert parse_number("1,250", locale="vi") == D("1.250")


@pytest.mark.parametrize("text", ["", "abc", "1,2,3", "12.34.56", "1,", "--5", "n/a", "—"])
def test_bad_numbers_raise(text):
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), [], {}])
def test_to_decimal_rejects(value):
    with pytest.raises(ValueError):
        to_decimal(value)


def test_fmt():
    assert (fmt(21350), fmt(D("17.0504")), fmt(30), fmt(-5.5), fmt(0), fmt(D("1234.5"))) == ("21.350", "17,05", "30", "-5,5", "0", "1.234,5")


def test_units():
    assert convert(D(2), parse_unit("tỷ đồng"), parse_unit("triệu đồng")) == 2000
    assert convert(D(1), parse_unit("nghìn tỷ đồng"), parse_unit("tỷ đồng")) == 1000
    assert parse_unit("VND").compatible(parse_unit("tỷ VND"))
    assert not parse_unit("triệu đồng").compatible(parse_unit("nghìn đơn"))
    assert not parse_unit("%").compatible(parse_unit("điểm phần trăm"))
    assert not parse_unit(None).compatible(parse_unit(None))
    assert parse_unit("nghìn tấn").compatible(parse_unit("triệu tấn"))
    with pytest.raises(ValueError):
        convert(D(1), parse_unit("đơn"), parse_unit("tấn"))


@pytest.mark.parametrize("text,kind,number,year", [("Quý 1/2026", "Q", 1, 2026), ("Q2/26", "Q", 2, 2026), ("2Q26", "Q", 2, 2026), ("quy 3", "Q", 3, None), ("Tháng 6/2026", "M", 6, 2026), ("T4", "M", 4, None), ("9 tháng 2025", "L", 9, 2025), ("9M2025", "L", 9, 2025), ("6T/2026", "L", 6, 2026), ("Năm 2026", "Y", 0, 2026), ("2026F", "Y", 0, 2026), ("Cuối quý 2/2026", "Q", 2, 2026)])
def test_parse_period(text, kind, number, year):
    period = parse_period(text)
    assert (period.kind, period.number, period.year) == (kind, number, year)


def test_period_matching():
    assert matches(parse_period("quý 2"), parse_period("Quý 2/2026"))
    assert not matches(parse_period("quý 2/2025"), parse_period("Quý 2/2026"))
    assert not matches(parse_period("quý 2"), parse_period("Tháng 2/2026"))


def test_shift_crosses_year():
    assert shift(parse_period("Tháng 1/2026"), months=-1).key() == ("M", 12, 2025)
    assert shift(parse_period("Quý 1/2026"), months=-3).key() == ("Q", 4, 2025)
    assert shift(parse_period("Quý 2/2026"), years=-1).key() == ("Q", 2, 2025)


def test_find_periods_in_order():
    found = find_periods("doanh thu quy 2 so voi quy 1 va thang 5/2026")
    assert [p.key() for p in found] == [("Q", 2, None), ("Q", 1, None), ("M", 5, 2026)]
    assert find_periods("cong ty trong nam") == []


@pytest.mark.parametrize("label,kind,number,year", [("Quý IV/2025", "Q", 4, 2025), ("Q3-2025", "Q", 3, 2025), ("Quý 2 năm 2026", "Q", 2, 2026), ("03/2026", "M", 3, 2026),
                                                    ("6T/2026", "L", 6, 2026), ("H1 2026", "L", 6, 2026), ("FY2025", "Y", 0, 2025), ("Năm học 2025-2026", "A", 0, 2025)])
def test_messy_period_labels(label, kind, number, year):
    period = parse_period(label)
    assert (period.kind, period.number, period.year) == (kind, number, year)


def test_calendar_year_matches_two_school_years():
    year, first, second = parse_period("năm 2025"), parse_period("Năm học 2024-2025"), parse_period("Năm học 2025-2026")
    assert matches(year, first) and matches(year, second) and not matches(year, parse_period("Năm học 2026-2027"))


def test_second_half_is_not_first_half():
    first, second = parse_period("6 tháng đầu năm 2025"), parse_period("6 tháng cuối năm 2025")
    assert (second.kind, second.year) == ("S", 2025) and not matches(first, second) and not matches(second, first)
    assert matches(first, parse_period("nửa đầu năm 2025")) and matches(second, parse_period("H2 2025"))
