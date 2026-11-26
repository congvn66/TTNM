import pytest

from report_qa.api.number_input import AmbiguousNumberError, TypedNumberError, detected_locale, display_number, exact_number, read_typed_number


def test_document_format_is_detected_only_from_numbers_one_format_can_read():
    assert detected_locale(["Doanh thu 1.234.567 tỷ", "12,5%"]) == "vi"
    assert detected_locale(["1,234.5"]) == "en"
    assert detected_locale(["1.234", "26.11.2026", "1.2.3"]) is None
    assert detected_locale(["1.234.567", "1,234,567"]) is None


def test_a_decimal_number_proves_the_format_whose_grammar_alone_reads_it():
    # "6,5" cannot be English (a "," there must be followed by three digits); "21.7" cannot be Vietnamese.
    assert detected_locale(["6,5%", "128,4", "1.234"]) == "vi"
    assert detected_locale(["Doanh thu tăng 128,4."]) == "vi"
    assert detected_locale(["21.7%", "26,200"]) == "en"
    assert detected_locale(["19,0%", "21.7%"]) is None
    assert detected_locale(["Quý 2/2026", "31.12.2023"]) is None


def test_typed_number_uses_the_format_and_reports_ambiguity():
    assert read_typed_number("21.500", "vi") == "21500"
    assert read_typed_number("21.500", "en") == "21.500"
    assert read_typed_number("21,5", None) == "21.5"
    with pytest.raises(AmbiguousNumberError) as error:
        read_typed_number("21.500", None)
    assert error.value.readings == ["21500", "21.500"]
    with pytest.raises(ValueError):
        read_typed_number("abc", None)


def test_display_follows_the_document_format():
    assert display_number("-1234567.25", "vi") == "-1.234.567,25"
    assert display_number("1234567.25", "en") == "1,234,567.25"
    assert display_number("21500", None) == "21500"


@pytest.mark.parametrize("typed, locale", [
    ("18,2.40", "vi"), ("1.234.567,89", "en"), ("21.500,", "vi"), ("21,500,", "en"), ("1e5", "vi"), ("1E5", None),
    ("5%", "vi"), ("1.5.5", "en"), ("1,5,5", "vi"), (".5", "vi"), ("12abc", None), ("１２", None), ("1 234", "vi"),
    ("", None), ("Infinity", None), ("1" * 19, None), ("1.23", "vi"), ("12,5,6", None),
])
def test_a_typed_number_must_be_well_formed_in_the_document_format(typed, locale):
    with pytest.raises(TypedNumberError):
        read_typed_number(typed, locale)


def test_well_formed_typed_numbers_are_read_exactly():
    assert read_typed_number("1.234.567,89", "vi") == "1234567.89"
    assert read_typed_number("1,234,567.89", "en") == "1234567.89"
    assert read_typed_number(" (1.250) ", "vi") == "-1250"
    assert read_typed_number("-0,5", None) == "-0.5"
    assert read_typed_number("007", "en") == "7"
    assert read_typed_number("12,5%", "vi", percent=True) == "12.5"
    assert read_typed_number("1" * 18, None) == "1" * 18
    assert read_typed_number("0.000000000000000000001", "en") == "0.000000000000000000001"


def test_an_exact_decimal_is_held_to_the_same_digit_limit():
    assert exact_number("1234.5") == "1234.5"
    for value in ("1" * 19, "1e5", "1,5"):
        with pytest.raises(TypedNumberError):
            exact_number(value)
