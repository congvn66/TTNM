"""Read a number the user typed, in the number format of the document.

A document's number format is PDF_NUMBER_LOCALE when it is set, as for
extraction; otherwise it is the format the document's own printed numbers
show without doubt; otherwise it is unknown.

A typed number must be a well-formed number in that format: digits, then
optionally thousands separators each followed by exactly three digits, then
optionally one decimal separator followed by digits. A sign or brackets
("(5)" is -5) may surround it, and a "%" may follow it only when the number
is a percentage. Exponents, other characters and more than
MAX_SIGNIFICANT_DIGITS significant digits are refused. The PDF extraction
reads printed text with its own, more tolerant parser (decimal_text).
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

from report_qa.application.numeric_extraction import NUMBER
from report_qa.domain.types import validate_decimal_text


LOCALES = ("vi", "en")
# Above this the Decimal arithmetic of the answers (28 digits) starts to round.
MAX_SIGNIFICANT_DIGITS = 18
SEPARATORS = {"vi": (".", ","), "en": (",", ".")}  # (thousands, decimal)
EXAMPLES = {"vi": "21.500 hoặc 21,5", "en": "21,500 hoặc 21.5", None: "21500 hoặc 21,5"}
# Printed numbers that only one format can read: "1.234.567" or "1.234,5"
# is Vietnamese, "1,234,567" or "1,234.5" is English. "1.234" proves nothing.
_PROOF = {
    "vi": re.compile(r"\d{1,3}(?:\.\d{3}){2,}|\d{1,3}(?:\.\d{3})+,\d+"),
    "en": re.compile(r"\d{1,3}(?:,\d{3}){2,}|\d{1,3}(?:,\d{3})+\.\d+"),
}
_GRAMMAR = {
    locale: re.compile(rf"(?P<whole>[0-9]{{1,3}}(?:{re.escape(thousands)}[0-9]{{3}})+|[0-9]+)(?:{re.escape(decimal)}(?P<fraction>[0-9]+))?")
    for locale, (thousands, decimal) in SEPARATORS.items()
}

_EXPONENT = re.compile(r"[0-9][eE][-+]?[0-9]")


class TypedNumberError(ValueError):
    """The typed text is not one number; ``message`` says why, for the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AmbiguousNumberError(ValueError):
    def __init__(self, readings: list[str]) -> None:
        super().__init__("Ambiguous decimal/thousands separator")
        self.readings = readings


def document_number_locale(extraction: dict[str, Any]) -> str | None:
    configured = os.getenv("PDF_NUMBER_LOCALE") or None
    if configured is not None:
        return configured
    raw_texts = (item.get("raw_text") for item in (extraction.get("evidence_batch") or {}).get("evidences", []))
    return detected_locale(raw_texts)


def detected_locale(raw_texts: Iterable[str | None]) -> str | None:
    found = set()
    for text in raw_texts:
        for match in NUMBER.finditer(text or ""):
            token = match.group().strip("()+-% ")
            found.update(locale for locale, proof in _PROOF.items() if proof.fullmatch(token))
    return found.pop() if len(found) == 1 else None


def decimal_separator(locale: str | None) -> str | None:
    return SEPARATORS[locale][1] if locale in SEPARATORS else None


def read_typed_number(text: str, locale: str | None, *, percent: bool = False) -> str:
    """The exact decimal string for ``text`` ("21.500" -> "21500" in a vi document).

    ``percent`` says whether the number is a percentage, so that "5%" may be
    typed. With no known format the input is read both ways: readings that
    differ raise AmbiguousNumberError ("21.500" is 21500 or 21.5); otherwise
    the one number is used ("21,5" can only be 21.5).
    """
    body, negative = _split_sign(text.strip(), percent)
    if locale in SEPARATORS:
        value = _read(body, locale)
        if value is None:
            raise TypedNumberError(_format_message(text, locale))
    else:
        readings = list(dict.fromkeys(value for candidate in LOCALES if (value := _read(body, candidate)) is not None))
        if len(readings) > 1:
            raise AmbiguousNumberError([_signed(value, negative) for value in readings])
        if not readings:
            raise TypedNumberError(_format_message(text, None))
        value = readings[0]
    return _signed(value, negative)


def exact_number(value: str) -> str:
    """A number sent as an exact decimal string ("1234.5"), held to the same digit limit."""
    try:
        validate_decimal_text(value)
    except Exception as exc:
        raise TypedNumberError("Giá trị phải là chuỗi thập phân chính xác, ví dụ 58 hoặc 58.25.") from exc
    _check_digits(value)
    return value


def display_number(value: str, locale: str | None) -> str:
    """The exact decimal string as the document prints numbers: "21500" -> "21.500" for vi."""
    if locale not in LOCALES:
        return value
    sign, digits = ("-", value[1:]) if value.startswith("-") else ("", value)
    whole, _, fraction = digits.partition(".")
    thousands, decimal = SEPARATORS[locale]
    grouped = f"{int(whole):,}".replace(",", thousands)
    return sign + grouped + (decimal + fraction if fraction else "")


def _split_sign(text: str, percent: bool) -> tuple[str, bool]:
    if not text:
        raise TypedNumberError("Hãy nhập một số.")
    if _EXPONENT.search(text):
        raise TypedNumberError("Không dùng dạng số mũ (ví dụ 1e5); hãy nhập đủ các chữ số.")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    elif text[0] in "+-":
        negative, text = text[0] == "-", text[1:].strip()
    if text.endswith("%"):
        if not percent:
            raise TypedNumberError("Số liệu này không phải tỷ lệ phần trăm; hãy nhập số không có dấu %.")
        text = text[:-1].rstrip()
    return text, negative


def _read(body: str, locale: str) -> str | None:
    match = _GRAMMAR[locale].fullmatch(body)
    if match is None:
        return None
    whole = match["whole"].replace(SEPARATORS[locale][0], "").lstrip("0") or "0"
    fraction = match["fraction"]
    value = f"{whole}.{fraction}" if fraction else whole
    _check_digits(value)
    return value


def _check_digits(value: str) -> None:
    if len(value.lstrip("-").replace(".", "").lstrip("0")) > MAX_SIGNIFICANT_DIGITS:
        raise TypedNumberError(f"Số có quá nhiều chữ số; tối đa {MAX_SIGNIFICANT_DIGITS} chữ số có nghĩa.")


def _signed(value: str, negative: bool) -> str:
    return "-" + value if negative and value.strip("0.") else value


def _format_message(text: str, locale: str | None) -> str:
    rule = {
        "vi": "tài liệu này dùng dấu chấm ngăn hàng nghìn và dấu phẩy thập phân",
        "en": "tài liệu này dùng dấu phẩy ngăn hàng nghìn và dấu chấm thập phân",
        None: "mỗi nhóm sau dấu ngăn hàng nghìn phải có đúng 3 chữ số và chỉ có một dấu thập phân",
    }[locale]
    return f"Không đọc được \"{text}\" thành một số: {rule}. Ví dụ hợp lệ: {EXAMPLES[locale]}."
