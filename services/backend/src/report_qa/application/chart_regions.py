"""Which pictures on a page are charts worth offering for reading, and the caption each one has.

Layout detection lists every picture: logos in the page header, side tabs,
photos. It also hands captions to the wrong picture (a header logo got the
caption of the chart under it, one chart got the captions of two). Here a
picture is kept only when it is large enough to hold a chart and shows
text (axis ticks, labels, a caption), and its caption is the "Hình N" /
"Biểu đồ N" line nearest above it (else below it) in its own column.
"""

from __future__ import annotations

import re
from typing import Any

# Smallest chart, as a share of the page: header logos are ~4% of the page high, side tabs ~4% wide.
_MIN_WIDTH = 0.15
_MIN_HEIGHT = 0.07
_MIN_AREA = 0.015
_CAPTION = re.compile(r"(hình|biểu đồ|đồ thị|sơ đồ|figure|fig\.|chart|exhibit)\s*\d+", re.IGNORECASE)
# "Hình 4:" / "Biểu đồ 1." is a caption wherever it stands on a line; "như Hình 3 cho thấy" is not.
_CAPTION_FORM = re.compile(_CAPTION.pattern + r"\s*[:.]", re.IGNORECASE)


def chart_candidates(pdf, charts: list[dict[str, Any]], *, read_image_text=None) -> list[dict[str, Any]]:
    """The chart regions worth offering, each with the caption found on the page.

    read_image_text(page, rect) returns the words OCR reads in a picture; it
    is used only for a picture with no PDF text and no caption.
    """
    import pymupdf

    read_image_text = read_image_text or _ocr_words
    kept = []
    for region in charts:
        x0, y0, x1, y1 = region["bbox"]
        if x1 - x0 < _MIN_WIDTH or y1 - y0 < _MIN_HEIGHT or (x1 - x0) * (y1 - y0) < _MIN_AREA:
            continue
        page = pdf[region["page_number"] - 1]
        width, height = page.rect.width, page.rect.height
        rect = pymupdf.Rect(x0 * width, y0 * height, x1 * width, y1 * height)
        caption = caption_near(page, rect)
        if not caption and not _shows_text(page, rect, read_image_text):
            continue  # a photo or a decoration
        old = region.get("text") or ""
        # Layout's own "Hình N" caption is dropped when the page's text puts no such caption near the
        # picture (a header logo got the caption of the chart under it). A scan has no text to check.
        text = caption or ("" if _CAPTION.match(old) and page.get_text().strip() else old)
        kept.append({**region, "text": text})
    return kept


def caption_near(page, rect) -> str:
    """The "Hình N: …" text nearest the picture: above it first, else below, overlapping its column."""
    height = page.rect.height
    best, best_distance = "", None
    for box, text in captions(page):
        overlap = min(box.x1, rect.x1) - max(box.x0, rect.x0)
        if overlap < 0.3 * min(box.width, rect.width):
            continue
        # A layout box often takes in the chart's own title line, so a caption may overlap its top.
        if rect.y0 - 0.12 * height <= box.y1 <= rect.y0 + 0.3 * rect.height and box.y0 < rect.y0 + 0.3 * rect.height:
            distance = abs(rect.y0 - box.y1)
        elif rect.y1 - 0.3 * rect.height <= box.y0 <= rect.y1 + 0.08 * height:
            distance = abs(box.y0 - rect.y1) + 0.5 * height  # below counts only when nothing is above
        else:
            continue
        if best_distance is None or distance < best_distance:
            best, best_distance = text, distance
    return best


def captions(page):
    """Every figure caption on the page as (box, text), read from words so side-by-side captions stay apart.

    A caption starts with "Hình 3", "Biểu đồ 1"… at the start of a line,
    after a wide gap or as "Hình 3:" (not "như Hình 3 cho thấy"), runs right to
    the next caption on the line, and goes on over the next lines of its
    column while they follow closely in the same type size.
    """
    import pymupdf

    lines: list[list[tuple]] = []
    for word in sorted(page.get_text("words"), key=lambda w: (w[1], w[0])):
        if lines and abs(word[1] - lines[-1][0][1]) <= 0.5 * (word[3] - word[1]):
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda w: w[0])
    starts = {}
    for number, line in enumerate(lines):
        for index, word in enumerate(line):
            size = word[3] - word[1]
            text = " ".join(w[4] for w in line[index:index + 3])
            if _CAPTION.match(text) and (index == 0 or word[0] - line[index - 1][2] > 2 * size or _CAPTION_FORM.match(text)):
                starts.setdefault(number, []).append(index)
    found = []
    for number, indexes in starts.items():
        line = lines[number]
        for k, index in enumerate(indexes):
            first = line[index]
            size = first[3] - first[1]
            left = first[0]
            right = line[indexes[k + 1]][0] if k + 1 < len(indexes) else page.rect.width
            parts = [w for w in line[index:] if w[0] < right]
            bottom = max(w[3] for w in parts)
            for following in lines[number + 1:number + 3]:
                column = [w for w in following if left - size <= w[0] < right]
                if (
                    not column
                    or column[0][1] - bottom > 0.6 * size
                    or abs((column[0][3] - column[0][1]) - size) > 0.2 * size
                    or abs(column[0][0] - left) > 2 * size
                    or _CAPTION.match(" ".join(w[4] for w in column[:3]))
                    or sum(any(ch.isdigit() for ch in w[4]) for w in column) * 2 > len(column)
                ):
                    break
                parts += column
                bottom = max(w[3] for w in column)
            box = pymupdf.Rect(min(w[0] for w in parts), min(w[1] for w in parts), max(w[2] for w in parts), bottom)
            found.append((box, " ".join(w[4] for w in parts)))
    return found


def _shows_text(page, rect, read_image_text) -> bool:
    if not page.get_text().strip():
        return True  # a scanned page: its text is in the picture, and Docling already read it as a figure
    if len(page.get_text("words", clip=rect)) >= 3:
        return True
    return len(read_image_text(page, rect)) >= 3


def _ocr_words(page, rect) -> list[str]:
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError:
        return ["?"] * 3  # cannot tell: keep the picture
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=rect, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        text = pytesseract.image_to_string(image, config="--psm 11")
    except Exception:  # noqa: BLE001  OCR missing at run time: keep the picture
        return ["?"] * 3
    return [word for word in text.split() if any(ch.isalnum() for ch in word)]
