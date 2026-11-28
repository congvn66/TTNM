"""Where each bar of a bar chart is, so a chart value can point at its own label.

DePlot gives a chart's values but no places. Here the chart image itself is
read: bars are blocks of one strong colour standing on a common baseline,
the legend's small squares give each colour its series, bars group left to
right into categories, and the number printed above a bar (read by OCR) ties
the bar to a value. Anything that does not add up (a colour with no legend
square, a category count that differs from DePlot's) leaves that value
without a place, and the caller keeps its old fallback.
"""

from __future__ import annotations

import io
from typing import Any

# A hue counts as a series colour when it covers at least this share of the image.
_MIN_HUE_SHARE = 0.002
_HUE_WINDOW = 6


def find_bar_marks(png: bytes, box: list[float], categories: list[str], series: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """{(category, series): {"label": page box, "bar": page box, "text": "38"}} for one rendered chart crop.

    box is the crop's place on the page (normalised x0, y0, x1, y1). Returns {}
    when the image is not a bar chart this can read.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return {}
    image = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    strong = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 60)
    histogram = np.bincount(hsv[:, :, 0][strong], minlength=180)
    floor = max(500, _MIN_HUE_SHARE * height * width)
    peaks = [h for h in range(180) if histogram[h] > floor and histogram[h] == histogram[max(0, h - _HUE_WINDOW):h + _HUE_WINDOW + 1].max()]
    bars, swatches = [], []
    for hue in peaks:
        mask = (strong & (np.abs(hsv[:, :, 0].astype(int) - hue) <= _HUE_WINDOW)).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if area < 0.6 * w * h or w < 4:
                continue  # not a filled block
            square = abs(w - h) <= max(3, 0.2 * max(w, h)) and h < 0.08 * height
            (swatches if square else bars).append({"hue": hue, "x": x, "y": y, "w": w, "h": h})
    bars = [bar for bar in bars if bar["h"] >= 0.02 * height]
    if not bars:
        return {}
    baseline = max(bar["y"] + bar["h"] for bar in bars)
    bars = [bar for bar in bars if abs(bar["y"] + bar["h"] - baseline) <= max(4, 0.01 * height)]

    # Series: the legend squares, read like text; one square per series colour.
    swatches.sort(key=lambda item: (round(item["y"] / max(1, 0.03 * height)), item["x"]))
    legend = list(dict.fromkeys(item["hue"] for item in swatches))
    if len(legend) != len(series) or set(legend) != {bar["hue"] for bar in bars}:
        return {}
    series_of = {hue: series[index] for index, hue in enumerate(legend)}

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
        return {}

    labels = _printed_numbers(image)
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
            marks[(category, series_of[bar["hue"]])] = {
                "bar": to_page(bar["x"], bar["y"], bar["x"] + bar["w"], bar["y"] + bar["h"]),
                "label": to_page(label["x"], label["y"], label["x"] + label["w"], label["y"] + label["h"]) if label else None,
                "text": label["text"] if label else None,
            }
    return marks


def _printed_numbers(image) -> list[dict[str, Any]]:
    """Numbers printed on the chart, with their boxes in image pixels (OCR at 2x)."""
    try:
        import cv2
        import pytesseract
    except ImportError:
        return []
    large = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(large, config="--psm 11 -c tessedit_char_whitelist=0123456789.,", output_type=pytesseract.Output.DICT)
    words = []
    for index, text in enumerate(data["text"]):
        text = str(text).strip().strip(".,")
        if text and any(ch.isdigit() for ch in text):
            words.append({"text": text, "x": data["left"][index] / 2, "y": data["top"][index] / 2,
                          "w": data["width"][index] / 2, "h": data["height"][index] / 2})
    return words
