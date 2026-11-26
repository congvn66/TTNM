"""Match model quotes to verbatim PDF text and locate them on the page.

A quote is accepted only if it occurs in the extracted page text, either
exactly (ignoring whitespace, case, dash/quote styles) or, for small model
copy errors, by snapping to the page words it was copied from. A snap only
forgives character slips: the page has the quote's words in order, each
equal or one character apart once diacritics are set aside ("thue" ->
"thuế"), with punctuation and spacing free. A swapped word ("trước" for
"sau", "Chi phí" for "Doanh thu") is not a slip, and numbers and polarity
words must be exactly the same, so "tăng 8%" never snaps to "giảm 8%" nor
"2.250" to "1.250". The returned quote is always the document's own text,
never the model's wording.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_FOLD = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "…": "...",
})
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n\s*\n")
_WORD = re.compile(r"\w+")
_TRAILING_PUNCTUATION = re.compile(r"[.,;:!?%)\]”\"']*")
# Words that flip what a sentence claims: direction of change and negation.
POLARITY_WORDS = frozenset({"tăng", "giảm", "sụt", "lãi", "lỗ", "cao", "thấp", "không", "chưa", "chẳng", "chả"})


def _fold(text: str) -> tuple[str, list[int]]:
    """Folded text and, for each folded char, the index of its source char."""
    out: list[str] = []
    index: list[int] = []
    for i, char in enumerate(text):
        if char.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(i)
            continue
        for folded in unicodedata.normalize("NFKC", char).translate(_FOLD).casefold():
            out.append(folded)
            index.append(i)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def _display(text: str) -> str:
    return " ".join(text.split())


def _candidates(text: str):
    """Sentence-sized spans of the page (single sentences, lines and pairs)."""
    spans = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    spans = [(a, b) for a, b in spans if text[a:b].strip()]
    yield from spans
    yield from ((spans[i][0], spans[i + 1][1]) for i in range(len(spans) - 1))
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            yield offset, offset + len(line.rstrip())
        offset += len(line)


def _plain(word: str) -> str:
    """A word without diacritics or case: "Thuế" -> "thue"."""
    return "".join(c for c in unicodedata.normalize("NFD", word.casefold()) if not unicodedata.combining(c)).replace("đ", "d")


_POLARITY_PLAIN = frozenset(map(_plain, POLARITY_WORDS))


def _one_slip(a: str, b: str) -> bool:
    """Equal, or one character substituted, inserted or deleted."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _slip(quoted: str, printed: str) -> bool:
    """A copy slip of one printed word: numbers and polarity words exact, other words one character apart."""
    if quoted[0].isdigit() or printed[0].isdigit():
        return quoted.casefold() == printed.casefold()
    quoted, printed = _plain(quoted), _plain(printed)
    if quoted in _POLARITY_PLAIN or printed in _POLARITY_PLAIN:
        return quoted == printed
    return _one_slip(quoted, printed)


def _snap(page_text: str, quote: str) -> str | None:
    """The page words a quote was copied from with character slips, or None."""
    page_text = unicodedata.normalize("NFC", page_text)
    quoted = _WORD.findall(unicodedata.normalize("NFKC", quote))
    printed = list(_WORD.finditer(page_text))
    for i in range(len(printed) - len(quoted) + 1):
        window = printed[i:i + len(quoted)]
        if quoted and all(_slip(q, p.group()) for q, p in zip(quoted, window)):
            end = _TRAILING_PUNCTUATION.match(page_text, window[-1].end()).end()
            return _display(page_text[window[0].start():end])
    return None


def _closest(page_text: str, folded_quote: str, min_score: float):
    best = None
    for start, end in _candidates(page_text):
        folded_candidate, _ = _fold(page_text[start:end])
        if not folded_candidate or len(folded_candidate) > 3 * len(folded_quote):
            continue
        blocks = SequenceMatcher(None, folded_quote, folded_candidate, autojunk=False).get_matching_blocks()
        score = sum(block.size for block in blocks) / len(folded_quote)
        if score >= min_score and (best is None or (score, start - end) > best[0]):
            best = ((score, start - end), start, end)
    return None if best is None else _display(page_text[best[1]:best[2]])


def _folded_quote(quote) -> str | None:
    if not isinstance(quote, str) or len(quote.strip()) < 4:
        return None
    return _fold(quote.strip().strip('"“”'))[0]


def match_quote(page_text: str, quote: str) -> dict | None:
    """Verbatim page text for a model quote, or None when it is not in the page."""
    folded_quote = _folded_quote(quote)
    if folded_quote is None:
        return None
    folded_page, index = _fold(page_text)
    position = folded_page.find(folded_quote)
    if position >= 0:
        start, end = index[position], index[position + len(folded_quote) - 1] + 1
        return {"quote": _display(page_text[start:end]), "match": "exact"}
    snapped = _snap(page_text, quote)
    return {"quote": snapped, "match": "snapped"} if snapped else None


def suggest_quote(page_text: str, quote: str) -> str | None:
    """Closest real sentence, shown to the model when its quote is rejected."""
    folded_quote = _folded_quote(quote)
    return _closest(page_text, folded_quote, 0.5) if folded_quote else None


def _first_hit(page, rects, quote: str) -> list:
    """Rects of the first hit only: search_for returns every hit's line rects in one flat list."""
    wanted = len(_fold(quote)[0].replace(" ", ""))
    found = 0
    for count, rect in enumerate(rects, 1):
        found += len(_fold(page.get_textbox(rect))[0].replace(" ", ""))
        if found >= wanted:
            return rects[:count]
    return rects


def quote_bbox(pdf_path, page_number: int, quote: str) -> list[float] | None:
    """Normalized [x0, y0, x1, y1] around the quote's first occurrence, if found."""
    import pymupdf

    with pymupdf.open(pdf_path) as pdf:
        if not 1 <= page_number <= pdf.page_count:
            return None
        page = pdf[page_number - 1]
        rects = _first_hit(page, page.search_for(quote), quote)
        words = quote.split()
        if not rects and len(words) > 8:
            head = page.search_for(" ".join(words[:5]))
            tail = page.search_for(" ".join(words[-5:]))
            rects = [head[0], next((r for r in tail if r.y0 >= head[0].y0), tail[-1])] if head and tail else []
        if not rects:
            return None
        width, height = page.rect.width, page.rect.height
        x0 = min(r.x0 for r in rects)
        y0 = min(r.y0 for r in rects)
        x1 = max(r.x1 for r in rects)
        y1 = max(r.y1 for r in rects)
        return [round(max(0, x0 / width), 6), round(max(0, y0 / height), 6),
                round(min(1, x1 / width), 6), round(min(1, y1 / height), 6)]
