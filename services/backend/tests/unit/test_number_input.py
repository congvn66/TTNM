import pytest

from report_qa.api.number_input import AmbiguousNumberError, detected_locale, display_number, read_typed_number


def test_document_format_is_detected_only_from_numbers_one_format_can_read():
    assert detected_locale(["Doanh thu 1.234.567 tỷ", "12,5%"]) == "vi"
    assert detected_locale(["1,234.5"]) == "en"
    assert detected_locale(["1.234", "26.11.2026", "1.2.3"]) is None
    assert detected_locale(["1.234.567", "1,234,567"]) is None


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
