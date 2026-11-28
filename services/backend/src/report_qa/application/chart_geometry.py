"""Where each bar of a bar chart is, so a chart value can point at its own label.

DePlot gives a chart's values but no places. Here the chart image itself is
read: bars are blocks of one strong colour standing on a common baseline,
the legend's small squares give each colour its series (a one-series chart
needs no legend), bars group left to right into categories, and the number
printed above a bar ties the bar to a value. The tick numbers beside the
plot give each side's axis scale, so a bar's height can be turned into a
second, independent reading of its value. Anything that does not add up (a
colour with no legend square, a category count that differs from DePlot's,
ticks that are not evenly spaced) leaves that value without a place or a
reading, and the caller keeps its old fallback.
"""

from __future__ import annotations

import io
import math
import re
from typing import Any

# A hue counts as a series colour when it covers at least this share of the image.
_MIN_HUE_SHARE = 0.002
_HUE_WINDOW = 6


def read_chart_image(png: bytes, box: list[float], categories: list[str], series: list[str], words=None, rows=None) -> dict[str, Any]:
    """What the chart image itself shows: {"shape", "marks", "axes", "names", "legend", "right_line"}.

    shape is "pie" for a round chart (a pie or a ring), else None. marks is
    {(category, series): {"label", "bar", "text", "estimate"}}: the bar and
    its printed number as page boxes, and the value its height shows on its
    axis (None without a linear axis). axes is {"left": axis, "right": axis}
    with each axis {"low", "high", "linear", ...} or None. names maps a
    DePlot category to the label printed under its bars, when the words
    include text (a vector chart). words are the chart's printed words in
    image pixels (from the PDF for a vector chart); without them the image
    is read by OCR, which reads numbers only.

    With a right axis, legend lists the legend entries that name their axis
    ("Biên lợi nhuận gộp (trục phải)") as {"text", "side"} in reading
    order, and right_line gives, for each of the rows category positions
    left to right, the point of the line drawn there read on the right axis
    ({"value", "box"}, or None where no single point is seen).
    """
    empty = {"shape": None, "marks": {}, "axes": {"left": None, "right": None}, "names": {}, "legend": [], "right_line": None}
    try:
        import cv2  # noqa: F401
        import numpy as np
        from PIL import Image
    except ImportError:
        return empty
    image = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    if _is_round(image):
        return {**empty, "shape": "pie"}
    bars, swatches = _blocks(image)
    words = _printed_numbers(image) if words is None else words
    height, width = image.shape[:2]
    axes = {
        "left": _axis(words, lambda w: w["x"] + w["w"] <= min((b["x"] for b in bars), default=0.3 * width) + 2),
        "right": _axis(words, lambda w: w["x"] >= max((b["x"] + b["w"] for b in bars), default=0.7 * width) - 2),
    }
    for axis in axes.values():
        if axis and axis["linear"]:
            # Ticks OCR missed still lie on the scale: the whole image height is its reach.
            axis["reach"] = sorted((axis["intercept"], axis["intercept"] + axis["slope"] * height))
    marks, slots = _marks(image, box, bars, swatches, categories, series, words, axes)
    names = {}
    centres = [sum(bar["x"] + bar["w"] / 2 for bar in slot) / len(slot) for slot in slots]
    for index, (category, slot) in enumerate(zip(categories, slots)):
        # A label may be wider than its bars, but never reaches half way to the next group.
        room = 0.5 * min([abs(centres[index] - c) for c in centres[:index] + centres[index + 1:]] or [width])
        name = _label_under(slot, words, height, room)
        if name:
            names[category] = name
    legend, right_line = [], None
    if axes["right"]:
        legend = _legend(image, words)
        xs = _category_xs(words, rows or len(categories), axes, height, slots)
        if axes["right"]["linear"] and xs:
            to_page = lambda x0, y0, x1, y1: [box[0] + x0 / width * (box[2] - box[0]), box[1] + y0 / height * (box[3] - box[1]),  # noqa: E731
                                              box[0] + x1 / width * (box[2] - box[0]), box[1] + y1 / height * (box[3] - box[1])]
            right_line = [_line_point(image, x, axes["right"], {bar["hue"][0] for bar in bars}, to_page) for x in xs]
    return {"shape": None, "marks": marks, "axes": axes, "names": names if len(names) == len(categories) else {},
            "legend": legend, "right_line": right_line}


def find_bar_marks(png: bytes, box: list[float], categories: list[str], series: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """{(category, series): {"label": page box, "bar": page box, "text": "38"}} for one rendered chart crop.

    box is the crop's place on the page (normalised x0, y0, x1, y1). Returns {}
    when the image is not a bar chart this can read.
    """
    return read_chart_image(png, box, categories, series)["marks"]


def _is_round(image) -> bool:
    """A pie or a ring: the coloured area's outline is a large circle, which no bar chart has."""
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    coloured = ((hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 60)).astype(np.uint8)
    # Slices are drawn with thin white borders between them.
    closed = cv2.morphologyEx(coloured, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return False
    biggest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(biggest)
    (_, _), radius = cv2.minEnclosingCircle(biggest)
    return area >= 0.12 * height * width and area >= 0.8 * math.pi * radius * radius


def _blocks(image):
    """Filled blocks of one strong colour: bars standing on the common baseline, and legend squares."""
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    strong = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 60)
    histogram = np.bincount(hsv[:, :, 0][strong], minlength=180)
    floor = max(500, _MIN_HUE_SHARE * height * width)
    peaks = [h for h in range(180) if histogram[h] > floor and histogram[h] == histogram[max(0, h - _HUE_WINDOW):h + _HUE_WINDOW + 1].max()]
    blocks = []
    for hue in peaks:
        same_hue = strong & (np.abs(hsv[:, :, 0].astype(int) - hue) <= _HUE_WINDOW)
        # Two series can share a hue in different shades (navy and steel blue): split by brightness too.
        shades = np.bincount(hsv[:, :, 2][same_hue] // 16, minlength=16)
        levels = [v for v in range(16) if shades[v] > floor and shades[v] == shades[max(0, v - 2):v + 3].max()]
        for level in levels:
            mask = (same_hue & (np.abs(hsv[:, :, 2].astype(int) // 16 - level) <= 2)).astype(np.uint8)
            count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            for index in range(1, count):
                x, y, w, h, area = (int(v) for v in stats[index])
                if area < 0.6 * w * h or w < 4:
                    continue  # not a filled block
                square = abs(w - h) <= max(3, 0.2 * max(w, h)) and h < 0.08 * height
                blocks.append({"hue": (hue, level), "x": x, "y": y, "w": w, "h": h, "square": square})
    tall = [b for b in blocks if not b["square"] and b["h"] >= 0.02 * height]
    if not tall:
        return [], [b for b in blocks if b["square"]]
    # The baseline is where most blocks end (a wide legend mark under the plot is not on it).
    tolerance = max(4, 0.01 * height)
    bottoms = [b["y"] + b["h"] for b in tall]
    baseline = max(bottoms, key=lambda y: (sum(abs(other - y) <= tolerance for other in bottoms), y))
    # A short bar can be as wide as it is tall; it still stands on the baseline, which a legend square does not.
    on_base = lambda b: abs(b["y"] + b["h"] - baseline) <= tolerance  # noqa: E731
    bars = [b for b in blocks if on_base(b) and b["h"] >= 0.02 * height]
    return bars, [b for b in blocks if b["square"] and not on_base(b)]


def _marks(image, box, bars, swatches, categories, series, words, axes):
    """Each bar's marks, and the bars of each category left to right ([] when they do not add up)."""
    height, width = image.shape[:2]
    if not bars:
        return {}, []

    # Series: the legend squares, read like text; one square per series colour.
    swatches.sort(key=lambda item: (round(item["y"] / max(1, 0.03 * height)), item["x"]))
    legend = list(dict.fromkeys(item["hue"] for item in swatches))
    hues = {bar["hue"] for bar in bars}
    if len(legend) == len(series) and set(legend) == hues:
        series_of = {hue: series[index] for index, hue in enumerate(legend)}
    elif len(hues) == 1 and len(legend) <= 1:
        # One bar colour: the one series, or the one series not on the right axis (the other is the line).
        left = series if len(series) == 1 else [name for name in series if axis_side(name) != "right"]
        if len(left) != 1:
            return {}, []
        series_of = {hues.pop(): left[0]}
    else:
        return {}, []

    # Categories: bars grouped by the gaps between them, left to right.
    bars.sort(key=lambda bar: bar["x"])
    # Bars of one category touch or nearly touch; categories are a clear gap apart.
    widths = sorted(bar["w"] for bar in bars)
    gap = max(4, 0.5 * widths[len(widths) // 2])
    slots: list[list[dict]] = [[bars[0]]]
    for bar in bars[1:]:
        previous = slots[-1][-1]
        if bar["x"] - (previous["x"] + previous["w"]) > gap:
            slots.append([bar])
        else:
            slots[-1].append(bar)
    if len(slots) != len(categories):
        return {}, []

    labels = [word for word in words if any(ch.isdigit() for ch in word["text"])]
    marks = {}
    for category, slot in zip(categories, slots):
        for bar in slot:
            centre = bar["x"] + bar["w"] / 2
            above = [word for word in labels
                     if word["y"] + word["h"] <= bar["y"] + 3 and bar["y"] - (word["y"] + word["h"]) < 0.06 * height
                     and abs(word["x"] + word["w"] / 2 - centre) < bar["w"] / 2 + 4]
            label = min(above, key=lambda word: bar["y"] - (word["y"] + word["h"]), default=None)
            to_page = lambda x0, y0, x1, y1: [box[0] + x0 / width * (box[2] - box[0]), box[1] + y0 / height * (box[3] - box[1]),
                                              box[0] + x1 / width * (box[2] - box[0]), box[1] + y1 / height * (box[3] - box[1])]
            name = series_of[bar["hue"]]
            axis = axes["right" if axis_side(name) == "right" else "left"]
            marks[(category, name)] = {
                "bar": to_page(bar["x"], bar["y"], bar["x"] + bar["w"], bar["y"] + bar["h"]),
                "label": to_page(label["x"], label["y"], label["x"] + label["w"], label["y"] + label["h"]) if label else None,
                "text": label["text"] if label else None,
                "estimate": axis["intercept"] + axis["slope"] * bar["y"] if axis and axis["linear"] else None,
            }
    return marks, slots


def _label_under(slot, words, height, room):
    """The category name printed under a group of bars: the phrases centred under it, line by line.

    Reading stops at a line in another type size or after a wider gap
    ("#1" ranks, the source note), so only the label itself is taken.
    """
    base = max(bar["y"] + bar["h"] for bar in slot)
    middle = (min(bar["x"] for bar in slot) + max(bar["x"] + bar["w"] for bar in slot)) / 2
    band = sorted((w for w in words if base - 2 <= w["y"] < base + 0.2 * height), key=lambda w: w["y"])
    lines: list[list[dict]] = []
    for word in band:
        if lines and word["y"] - lines[-1][0]["y"] <= 0.5 * lines[-1][0]["h"]:
            lines[-1].append(word)
        else:
            lines.append([word])
    picked, size, bottom = [], None, None
    for line in lines:
        phrases: list[list[dict]] = []
        for word in sorted(line, key=lambda w: w["x"]):
            if phrases and word["x"] - (phrases[-1][-1]["x"] + phrases[-1][-1]["w"]) <= 0.6 * word["h"]:
                phrases[-1].append(word)
            else:
                phrases.append([word])
        centre = lambda phrase: (phrase[0]["x"] + phrase[-1]["x"] + phrase[-1]["w"]) / 2
        mine = sorted((p for p in phrases if abs(centre(p) - middle) <= room), key=lambda p: abs(centre(p) - middle))
        if not mine:
            if picked:
                break
            continue
        phrase = mine[0]
        top = min(w["y"] for w in phrase)
        if picked and (abs(phrase[0]["h"] - size) > 0.25 * size or top - bottom > 0.6 * size):
            break
        picked.append(phrase)
        size = size or phrase[0]["h"]
        bottom = max(w["y"] + w["h"] for w in phrase)
    text = " ".join(w["text"] for phrase in picked for w in phrase)
    return text if any(ch.isalpha() for ch in text) else None


def _ocr(image, config, lang="eng", left=0):
    """OCR words of an image at 2x, with boxes in the image's pixels shifted by left."""
    import cv2
    import pytesseract

    large = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(large, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    return [{"text": str(text).strip(), "x": left + data["left"][i] / 2, "y": data["top"][i] / 2,
             "w": data["width"][i] / 2, "h": data["height"][i] / 2}
            for i, text in enumerate(data["text"]) if str(text).strip()]


def _printed_numbers(image) -> list[dict[str, Any]]:
    """Numbers printed on the chart, with their boxes in image pixels (OCR at 2x).

    The two side strips are read again as text blocks: sparse reading of a
    whole scanned chart misses most tick numbers (S2 found 18, 12, 10 of
    10…24), while a strip holding only the ticks reads them all.
    """
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return []
    digits = "-c tessedit_char_whitelist=0123456789.,"
    words = _ocr(image, "--psm 11 " + digits)
    width = image.shape[1]
    strip = int(0.13 * width)
    for left, part in ((0, image[:, :strip]), (width - strip, image[:, width - strip:])):
        for word in _ocr(part, "--psm 6 " + digits, left=left):
            if not any(_overlap(word, other) for other in words):
                words.append(word)
    out = []
    for word in words:
        text = word["text"].strip(".,")
        if text and any(ch.isdigit() for ch in text):
            out.append({**word, "text": text})
    return out


def _overlap(a, b) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def _legend(image, words) -> list[dict[str, str]]:
    """Legend entries that name their axis, in reading order: [{"text", "side"}].

    A vector chart's words carry the text; a picture is read with the
    Vietnamese OCR model.
    """
    if not any(sum(ch.isalpha() for ch in w["text"]) >= 2 for w in words):
        try:
            words = _ocr(image, "--psm 11", lang="vie")
        except Exception:  # noqa: BLE001  no Vietnamese model or no OCR: no legend
            return []
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (w["y"] + w["h"] / 2, w["x"])):
        if lines and abs(word["y"] + word["h"] / 2 - (lines[-1][0]["y"] + lines[-1][0]["h"] / 2)) <= 0.5 * word["h"]:
            lines[-1].append(word)
        else:
            lines.append([word])
    entries = []
    for line in lines:
        phrases: list[list[dict]] = []
        for word in sorted(line, key=lambda w: w["x"]):
            if phrases and word["x"] - (phrases[-1][-1]["x"] + phrases[-1][-1]["w"]) <= 1.5 * word["h"]:
                phrases[-1].append(word)
            else:
                phrases.append([word])
        for phrase in phrases:
            # Drop what OCR made of the legend's colour mark ("1M", "—") before the name.
            while phrase and sum(ch.isalpha() for ch in phrase[0]["text"]) < 2:
                phrase = phrase[1:]
            text = " ".join(w["text"] for w in phrase)
            side = axis_side(text) if phrase else None
            if side:
                entries.append({"text": text, "side": side})
    return entries


def _category_xs(words, count, axes, height, slots):
    """Where each category sits across the plot, left to right: its label under the axis, else its bars."""
    known = [axis for axis in axes.values() if axis]
    bottom = max(axis["bottom"] for axis in known)
    left = axes["left"]["x1"] if axes["left"] else 0
    right = axes["right"]["x0"] if axes["right"] else float("inf")
    under = [w for w in words if bottom - 0.02 * height <= w["y"] + w["h"] / 2 <= bottom + 0.1 * height
             and left < w["x"] + w["w"] / 2 < right]
    lines: list[list[dict]] = []
    for word in sorted(under, key=lambda w: w["y"]):
        # Chained to the last word: a scan's skew lets a row of labels drift down across the page.
        if lines and abs(word["y"] - lines[-1][-1]["y"]) <= 0.5 * word["h"]:
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        if len(line) == count:
            return sorted(w["x"] + w["w"] / 2 for w in line)
    if len(slots) == count:
        return [sum(bar["x"] + bar["w"] / 2 for bar in slot) / len(slot) for slot in slots]
    return None


def _line_point(image, x, axis, bar_hues, to_page):
    """The line's point above x, read on the axis: the middle of the line's ink in a thin column.

    Ink is dark grey or black, or a strong colour no bar has. A column with
    ink far apart (two lines, or a line and a label) gives no point.
    """
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    step = (axis["bottom"] - axis["top"]) / 10
    # Above the lowest tick's line: the axis line itself is ink too.
    top, bottom = max(0, int(axis["top"] - step)), min(height, int(axis["bottom"] - 3))
    rows = []
    for half in (2, 5):  # a thin column first; a wider one where the line ends just beside the label's centre
        left, right = max(0, int(x) - half), min(width, int(x) + half + 1)
        hsv = cv2.cvtColor(np.ascontiguousarray(image[top:bottom, left:right]), cv2.COLOR_RGB2HSV).astype(int)
        hue_free = np.ones(hsv.shape[:2], bool)
        for hue in bar_hues:
            hue_free &= np.abs(hsv[:, :, 0] - hue) > _HUE_WINDOW
        ink = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] < 110)) | ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 60) & hue_free)
        rows = np.nonzero(ink.any(axis=1))[0]
        if len(rows):
            break
    if not len(rows) or rows.max() - rows.min() > 0.12 * (bottom - top):
        return None
    y = top + float(np.median(rows))
    return {"value": axis["intercept"] + axis["slope"] * y, "box": to_page(x - 6, y - 6, x + 6, y + 6)}


def axis_side(series: str) -> str | None:
    """The axis a series name says it is read on: "Biên EBITDA (%, phải)" is on the right."""
    text = series.casefold()
    if re.search(r"\bph(ải|ai)\b|\bright\b|\brhs\b|\(p\)", text):
        return "right"
    if re.search(r"\btr(ái|ai)\b|\bleft\b|\blhs\b|\(t\)", text):
        return "left"
    return None


_THOUSANDS_DOT = re.compile(r"-?\d{1,3}(\.\d{3})+(,\d+)?")
_THOUSANDS_COMMA = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d+)?")


def tick_value(text: str) -> float | None:
    """A printed tick or label as a number: "2.500" and "2,500" are 2500, "45%" is 45, "-" is 0."""
    text = text.strip().replace("\u2212", "-").removesuffix("%").strip()
    if text in {"-", "\u2013"}:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    if _THOUSANDS_DOT.fullmatch(text):
        text = text.replace(".", "").replace(",", ".")
    elif _THOUSANDS_COMMA.fullmatch(text):
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def _axis(words, beside):
    """One side's tick numbers: the most words sharing an edge, with values falling as they go down.

    linear is True when the ticks are evenly spaced (one misread tick may be
    left out); a value can then be read from a height. Otherwise only the
    range is known (e.g. ticks rounded to "1%, 1%, 2%").
    """
    ticks = [(word, tick_value(word["text"])) for word in words if beside(word)]
    ticks = [(word, value) for word, value in ticks if value is not None]
    best = []
    # Ticks share an edge: usually the one next to the plot, sometimes the other.
    for line in (lambda w: w["x"], lambda w: w["x"] + w["w"]):
        for word, _ in ticks:
            group = [(w, v) for w, v in ticks if abs(line(w) - line(word)) <= 4]
            if len(group) > len(best):
                best = group
    rows = {}
    for word, value in best:
        rows.setdefault(round(word["y"] + word["h"] / 2), value)
    points = sorted(rows.items())
    if len(points) < 3:
        return None
    values = [value for _, value in points]
    axis = {"low": min(values), "high": max(values), "linear": False, "slope": None, "intercept": None,
            "top": points[0][0], "bottom": points[-1][0],
            "x0": min(w["x"] for w, _ in best), "x1": max(w["x"] + w["w"] for w, _ in best)}
    fit = _line(points)
    # OCR misreads a tick now and then ("180" for 150): leave one out, or two when six or more are read.
    if fit is None and len(points) >= 5:
        fit = next((f for f in (_line(points[:i] + points[i + 1:]) for i in range(len(points))) if f), None)
    if fit is None and len(points) >= 6:
        fit = next((f for f in (_line([p for k, p in enumerate(points) if k not in (i, j)])
                                for i in range(len(points)) for j in range(i + 1, len(points))) if f), None)
    if fit:
        # The range is that of the ticks on the scale, not of a misread one left out.
        kept = [v for y, v in points if abs(fit[1] + fit[0] * y - v) <= 0.02 * (max(values) - min(values))] or values
        axis.update(linear=True, slope=fit[0], intercept=fit[1], low=min(kept), high=max(kept))
    return axis


def _line(points):
    """(slope, intercept) of value = intercept + slope * y when every tick lies on it, else None."""
    count = len(points)
    mean_y = sum(y for y, _ in points) / count
    mean_v = sum(v for _, v in points) / count
    spread = sum((y - mean_y) ** 2 for y, _ in points)
    if spread == 0:
        return None
    slope = sum((y - mean_y) * (v - mean_v) for y, v in points) / spread
    intercept = mean_v - slope * mean_y
    span = max(v for _, v in points) - min(v for _, v in points)
    if slope >= 0 or span <= 0:
        return None  # values must grow upwards
    if any(abs(intercept + slope * y - v) > 0.02 * span for y, v in points):
        return None
    return slope, intercept
