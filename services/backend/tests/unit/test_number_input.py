import pytest

from report_qa.api.number_input import AmbiguousNumberError, TypedNumberError, detected_locale, document_number_locale, display_number, exact_number, read_typed_number


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
    # A clear majority wins over a few slips, as in a broker report with one "44,4%".
    assert detected_locale(["13.7%", "82.7%", "49.0%", "6.2", "18.6", "27.8", "8.3", "3.4", "5.9", "1.8", "21.5", "44,4%"]) == "en"
    assert detected_locale(["6.2", "18.6", "27.8", "44,4%", "4,4"]) is None
    assert detected_locale(["Quý 2/2026", "31.12.2023"]) is None


def test_a_document_has_the_format_its_page_text_proves_as_its_extraction_uses(monkeypatch):
    monkeypatch.delenv("PDF_NUMBER_LOCALE", raising=False)
    extraction = {"pages": [{"page": 1, "text": "Chi phi 6,5% doanh thu"}], "evidence_batch": {"evidences": []}}
    assert document_number_locale(extraction) == "vi"
    monkeypatch.setenv("PDF_NUMBER_LOCALE", "en")
    assert document_number_locale(extraction) == "en"


def test_a_documents_format_is_read_from_its_page_text_once(monkeypatch):
    from uuid import uuid4

    from report_qa.api import number_input

    monkeypatch.delenv("PDF_NUMBER_LOCALE", raising=False)
    calls = []
    monkeypatch.setattr(number_input, "detected_locale", lambda texts: calls.append(1) or "vi")
    extraction = {"pages": [{"page": 1, "text": f"Chi phi 6,5% {uuid4()}"}]}
    assert [document_number_locale(extraction) for _ in range(3)] == ["vi"] * 3
    assert len(calls) == 1


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
    ("18,2.40", "vi"), ("21.500,", "vi"), ("21,500,", "en"), ("1e5", "vi"), ("1E5", None),
    ("5%", "vi"), ("1.5.5", "en"), ("1,5,5", "vi"), (".5", "vi"), ("12abc", None), ("１２", None), ("1 234", "vi"),
    ("", None), ("Infinity", None), ("1" * 19, None), ("12,5,6", None),
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


def test_a_number_in_the_other_format_is_read_when_it_has_one_meaning() -> None:
    assert read_typed_number("30.42", "vi") == "30.42"
    assert read_typed_number("30,42", "en") == "30.42"
    assert read_typed_number("1,234,567", "vi") == "1234567"
    assert read_typed_number("1.234.567,89", "en") == "1234567.89"


def test_the_document_format_wins_when_both_formats_read_the_text() -> None:
    assert read_typed_number("21.500", "vi") == "21500"
    assert read_typed_number("21.500", "en") == "21.500"
