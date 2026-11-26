"""Read a number the user typed, in the number format of the document.

The server is the only place that reads typed numbers, with the same parser
the extraction uses (``decimal_text``). A document's number format is
PDF_NUMBER_LOCALE when it is set, as for extraction; otherwise it is the
format the document's own printed numbers show without doubt; otherwise it is
unknown.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

from report_qa.application.numeric_extraction import NUMBER, decimal_text


LOCALES = ("vi", "en")
# Printed numbers that only one format can read: "1.234.567" or "1.234,5"
# is Vietnamese, "1,234,567" or "1,234.5" is English. "1.234" proves nothing.
_PROOF = {
    "vi": re.compile(r"\d{1,3}(?:\.\d{3}){2,}|\d{1,3}(?:\.\d{3})+,\d+"),
    "en": re.compile(r"\d{1,3}(?:,\d{3}){2,}|\d{1,3}(?:,\d{3})+\.\d+"),
}


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


def read_typed_number(text: str, locale: str | None) -> str:
    """The exact decimal string for ``text``; ValueError when it is not a number.

    With no known format the input is read both ways. Readings that differ
    raise AmbiguousNumberError ("21.500" is 21500 or 21.5); otherwise the one
    number is used ("21,5" can only be 21.5).
    """
    if locale is not None:
        return decimal_text(text, locale)
    readings = []
    for candidate in LOCALES:
        try:
            value = decimal_text(text, candidate)
        except ValueError:
            continue
        if value not in readings:
            readings.append(value)
    if len(readings) > 1:
        raise AmbiguousNumberError(readings)
    if not readings:
        raise ValueError("Invalid decimal")
    return readings[0]


def display_number(value: str, locale: str | None) -> str:
    """The exact decimal string as the document prints numbers: "21500" -> "21.500" for vi."""
    if locale not in LOCALES:
        return value
    sign, digits = ("-", value[1:]) if value.startswith("-") else ("", value)
    whole, _, fraction = digits.partition(".")
    thousands, decimal = (".", ",") if locale == "vi" else (",", ".")
    grouped = f"{int(whole):,}".replace(",", thousands)
    return sign + grouped + (decimal + fraction if fraction else "")
