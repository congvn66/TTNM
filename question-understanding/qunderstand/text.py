"""Text normalization shared by matching code."""

import re
import unicodedata


def deaccent(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def norm(text: str) -> str:
    """Lowercase, no diacritics, single spaces, punctuation removed except % and /."""
    text = deaccent(text or "").lower()
    text = re.sub(r"[^\w%/+.,-]+", " ", text)
    text = re.sub(r"(?<!\d)[.,]|[.,](?!\d)", " ", text)
    text = re.sub(r"(?<![\w%])-|-(?![\w%])", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s\-/]+", norm(text)) if t]
