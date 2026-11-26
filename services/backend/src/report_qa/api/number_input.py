"""Read a number the user typed, in the number format of the document.

A document's number format is PDF_NUMBER_LOCALE when it is set; otherwise
it is the format its page text proves (detected_locale), the same rule the
extraction reads the printed numbers with; otherwise it is unknown.

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
from functools import lru_cache
from typing import Any

from report_qa.application.numeric_extraction import GRAMMAR, SEPARATORS, detected_locale
from report_qa.domain.types import validate_decimal_text

from .user_messages import NUMBER_INPUT_MESSAGES


LOCALES = ("vi", "en")
# Above this the Decimal arithmetic of the answers (28 digits) starts to round.
MAX_SIGNIFICANT_DIGITS = 18
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
    return _page_text_locale(tuple(page.get("text") or "" for page in extraction.get("pages", [])))


# Page text never changes within a reading, and detecting the format of a
# large document takes about 0.1 s, so the result is kept per page text.
@lru_cache(maxsize=16)
def _page_text_locale(page_texts: tuple[str, ...]) -> str | None:
    return detected_locale(page_texts)


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
        raise TypedNumberError(NUMBER_INPUT_MESSAGES["not_exact"]) from exc
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
        raise TypedNumberError(NUMBER_INPUT_MESSAGES["empty"])
    if _EXPONENT.search(text):
        raise TypedNumberError(NUMBER_INPUT_MESSAGES["exponent"])
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    elif text[0] in "+-":
        negative, text = text[0] == "-", text[1:].strip()
    if text.endswith("%"):
        if not percent:
            raise TypedNumberError(NUMBER_INPUT_MESSAGES["percent"])
        text = text[:-1].rstrip()
    return text, negative


def _read(body: str, locale: str) -> str | None:
    match = GRAMMAR[locale].fullmatch(body)
    if match is None:
        return None
    whole = match["whole"].replace(SEPARATORS[locale][0], "").lstrip("0") or "0"
    fraction = match["fraction"]
    value = f"{whole}.{fraction}" if fraction else whole
    _check_digits(value)
    return value


def _check_digits(value: str) -> None:
    if len(value.lstrip("-").replace(".", "").lstrip("0")) > MAX_SIGNIFICANT_DIGITS:
        raise TypedNumberError(NUMBER_INPUT_MESSAGES["too_many_digits"].format(limit=MAX_SIGNIFICANT_DIGITS))


def _signed(value: str, negative: bool) -> str:
    return "-" + value if negative and value.strip("0.") else value


def _format_message(text: str, locale: str | None) -> str:
    return NUMBER_INPUT_MESSAGES[f"format_{locale or 'unknown'}"].format(text=text)
