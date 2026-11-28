"""Read one requested image with DePlot, then inspect label/axis provenance.

The visual checker sees the source crop and the unchanged DePlot table. Its
assessment is model-based, not a human confirmation; uncertain values remain
ambiguous. Stored raw outputs support later review and correction.
"""

import base64
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from report_qa.api import session_storage
from report_qa.api.ai_provider import _json_from_content
from report_qa.application.deplot_reading import (
    _native_label,
    parse_table,
    predict_chart,
)
from report_qa.application.chart_geometry import axis_side, read_chart_image
from report_qa.application.extraction_contract import validate_extraction_batch

VERIFY = """Kiểm tra ảnh biểu đồ và bảng DePlot. Chỉ trả JSON {"rows":[...]};
mỗi row gồm category, series, value, method, label_bbox, measure, unit, period,
axis_label, lower_tick, upper_tick, confidence.
value phải là chuỗi số đúng như DePlot; không tự sửa số DePlot.
method="direct_label" CHỈ nếu thấy đúng số được in cạnh điểm/cột; label_bbox là
[x0,y0,x1,y1] chuẩn hóa 0..1 của NHÃN SỐ trên ẢNH CẮT, gốc trên trái.
method="axis_estimation" chỉ nếu không có nhãn số và thấy trục TUYẾN TÍNH,
hai tick lower_tick/upper_tick và đơn vị; label_bbox=null.
Nếu DePlot mâu thuẫn với ảnh, không phân biệt được dãy số, biểu đồ ngoài phạm vi
hoặc không đủ căn cứ: method="ambiguous", label_bbox=null. Không đoán.
measure dùng doanh_thu cho Revenue/doanh thu, loi_nhuan cho profit/lợi nhuận,
unknown nếu không rõ. unit theo đơn vị ảnh ghi: VND, VND_THOUSAND, VND_MILLION, VND_BILLION
cho đồng/nghìn/triệu/tỷ đồng; THOUSAND, MILLION, BILLION cho nghìn/triệu/tỷ của thứ khác
(nghìn đơn, triệu tấn); PERCENT cho %; null nếu ảnh không ghi. period=null nếu không có. Giữ nhãn category/series đúng
như DePlot. confidence 0..1 là đánh giá của mô hình, không phải xác nhận con người.
"""


# The visual checker's label box is approximate. A label at the chart edge
# often comes back slightly past the crop (e.g. x1=1.036), which used to
# discard a value the checker had confirmed. Clamp small overshoots; still
# reject boxes that are clearly off the image.
_LABEL_BOX_TOLERANCE = 0.1
# Bumped when a change makes earlier stored reads wrong; reads of another version are read again.
# 2: crop to the chart's own image instead of padding into the text around it (padding made
#    DePlot fuse the unit line with the first row and drop it).
# 3: each bar's value points at the number printed above that bar (chart_geometry).
# 4: "70.0%" values and headers are numbers, a title line holding the series names is repaired,
#    pies whose parts do not add up to 100% are not readable, a value outside its axis's range or
#    unlike the rest of its series is withheld, a bar's height checks DePlot's axis estimate, and
#    each value says whether its box is its printed label, its bar or the whole chart.
# 5: a line on the right axis is read where it is drawn, against the right axis's ticks (DePlot read
#    it on the left scale); the legend gives each series its axis and name; tick strips are read
#    again by OCR; quarter and year labels are put back on one consecutive run.
CHART_READER_VERSION = 5
# How far DePlot's value may be from the value a bar's height shows, as a share of the axis range.
_AXIS_TOLERANCE = 0.04


def _same_number(text, value):
    """A printed label ("38", "6,5", "1.250") and a DePlot value ("38", "6.5") name the same number."""
    if text is None or value is None:
        return False
    target = Decimal(value)
    text = text.strip().removesuffix("%")
    for candidate in {text.replace(",", "."), text.replace(".", "").replace(",", "."), text.replace(",", "")}:
        try:
            if Decimal(candidate) == target:
                return True
        except InvalidOperation:
            continue
    return False


def current_chart_reads(document):
    """The stored chart reads made by this reader version, oldest first."""
    return [record for record in document.get("chart_extractions") or [] if record.get("reader_version") == CHART_READER_VERSION]


def chart_crop(page, source_box):
    """The page rectangle to show DePlot for a chart region.

    A chart that is an embedded picture is cropped to that picture: its title,
    unit line and labels are inside it. Otherwise the region is padded by 3%
    of the page (layout detection can leave out the title and tick labels),
    but never into a text block below the region, so a sentence under the
    chart cannot take the place of its header.
    """
    import pymupdf

    width, height = page.rect.width, page.rect.height
    region = pymupdf.Rect(source_box[0] * width, source_box[1] * height, source_box[2] * width, source_box[3] * height)
    best, best_overlap = None, 0.0
    for info in page.get_image_info():
        image = pymupdf.Rect(info["bbox"])
        overlap = (image & region).get_area() / max(1e-9, (image | region).get_area())
        if overlap > best_overlap:
            best, best_overlap = image, overlap
    if best is not None and best_overlap >= 0.6:
        return best & page.rect
    padded = pymupdf.Rect(region.x0 - 0.03 * width, region.y0 - 0.03 * height, region.x1 + 0.03 * width, region.y1 + 0.03 * height) & page.rect
    # Lines, not blocks: a source note and the paragraph under it can be one block that starts inside the chart.
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            x0, y0, x1, _ = line["bbox"]
            if y0 >= region.y1 - 1 and y0 < padded.y1 and x1 > padded.x0 and x0 < padded.x1:
                padded.y1 = y0 - 1
    return padded


def _vector_words(page, rect):
    """The chart's printed words from the PDF, in pixels of the 2x crop; None for a picture (OCR reads those)."""
    import pymupdf

    if any((pymupdf.Rect(info["bbox"]) & rect).get_area() >= 0.6 * rect.get_area() for info in page.get_image_info()):
        return None
    words = [
        {"text": text, "x": 2 * (x0 - rect.x0), "y": 2 * (y0 - rect.y0), "w": 2 * (x1 - x0), "h": 2 * (y1 - y0)}
        for x0, y0, x1, y1, text, *_ in page.get_text("words", clip=rect)
    ]
    return words if sum(any(ch.isdigit() for ch in w["text"]) for w in words) >= 3 else None


def _pie_problem(predictions):
    """Why a pie's DePlot table cannot be used, or None: one series whose parts add up to the whole."""
    values = [Decimal(value) for _, _, _, value in predictions if value is not None]
    if len({series for _, series, _, _ in predictions}) != 1 or len(values) != len(predictions) or len(values) < 2:
        return "Biểu đồ tròn này chưa đọc được: bảng DePlot đọc ra không phải một dãy số cho các phần."
    total = sum(values)
    if Decimal("97") <= total <= Decimal("103") or Decimal("0.97") <= total <= Decimal("1.03"):
        if len({category for category, _, _, _ in predictions}) == len(predictions):
            return None
        return "Biểu đồ tròn này chưa đọc được: DePlot đọc lặp một phần."
    percent = total * 100 if total <= Decimal("1.5") else total  # parts given as shares of 1
    return (f"Biểu đồ tròn này chưa đọc được: các phần DePlot đọc ra cộng lại {format(percent.normalize(), 'f')}%, "
            "không phải 100%. Có phần bị thiếu hoặc đọc sai.")


def _percent_outliers(predictions):
    """Values written unlike most of their series: "759" among "32%, 45%…", or "29%" among plain numbers."""
    by_series: dict[str, list[bool]] = {}
    for _, series, token, value in predictions:
        if value is not None:
            by_series.setdefault(series, []).append(token.strip().endswith("%"))
    odd = set()
    for category, series, token, value in predictions:
        flags = by_series.get(series, [])
        if value is None or len(flags) < 3:
            continue
        percent = token.strip().endswith("%")
        if flags.count(not percent) > flags.count(percent):
            odd.add((category, series, token))
    return odd


def _not_readable(key, question_id, version, raw, reason):
    """A chart read with no values and the reason, stored so the chart is not read again for nothing."""
    batch = {
        "schema_version": 2,
        "document_version_id": version,
        "extraction_run_id": str(uuid4()),
        "scope": "on_demand_chart",
        "trigger": {"question_plan_id": question_id, "fact_keys": ["chart-data"], "chart_region_keys": [key]},
        "evidences": [],
        "warnings": [{"code": "CHART_NOT_READABLE", "message": reason, "evidence_key": None}],
    }
    validate_extraction_batch(batch)
    return {
        "status": "not_readable",
        "evidence_batch": batch,
        "raw_output": raw,
        "visual_check_output": "",
        "visual_check_error": None,
        "reader_version": CHART_READER_VERSION,
    }


_QUARTER = re.compile(r"Q\s*([1-4])\s*[/\u2044]\s*(\d{2}|\d{4})", re.IGNORECASE)
_YEAR = re.compile(r"((?:19|20)\d{2})")


def _period_sequence(labels):
    """Quarter or year labels made consecutive when DePlot misread a few of them.

    S2 Biểu đồ 1 runs Q1/25…Q3/26, but DePlot read Q2/25 as "Q2/26" and Q1/26
    as "Q1/28". When most labels already fall on one consecutive run, the
    others are put back on it. None when the labels are not periods or do
    not agree enough.
    """
    quarters = [_QUARTER.fullmatch(label.strip()) for label in labels]
    if all(quarters):
        short = sum(len(m.group(2)) == 2 for m in quarters) * 2 >= len(quarters)
        steps = [int(m.group(2)[-2:]) * 4 + int(m.group(1)) - 1 for m in quarters]
        name = lambda step: f"Q{step % 4 + 1}/{step // 4:02d}" if short else f"Q{step % 4 + 1}/20{step // 4:02d}"  # noqa: E731
    elif all(_YEAR.fullmatch(label.strip()) for label in labels):
        steps = [int(label.strip()) for label in labels]
        name = str
    else:
        return None
    starts = [step - index for index, step in enumerate(steps)]
    start = max(set(starts), key=starts.count)
    if starts.count(start) == len(labels) or starts.count(start) < max(3, 0.6 * len(labels)):
        return None
    return [name(start + index) for index in range(len(labels))]


def _reading(value, axis):
    """A value read from the image, to the precision its axis allows: "17.9" on a 10..24 axis, "1903" on 0..2500."""
    return format(Decimal(f"{value:.1f}" if axis["high"] - axis["low"] <= 100 else f"{value:.0f}"), "f")


def _tick(value):
    """An axis tick as the decimal text the contract stores: 2500.0 is "2500", 0.5 is "0.5"."""
    return format(Decimal(repr(float(value))).normalize(), "f")


def _label_box(label):
    if not (isinstance(label, list) and len(label) == 4) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in label
    ):
        return None
    if any(v < -_LABEL_BOX_TOLERANCE or v > 1 + _LABEL_BOX_TOLERANCE for v in label):
        return None
    clamped = [min(1.0, max(0.0, float(v))) for v in label]
    return clamped if clamped[0] < clamped[2] and clamped[1] < clamped[3] else None


_ROW_TEXT_FIELDS = ("category", "series", "method", "measure", "unit", "period", "axis_label")


def _checked_row(row):
    """A verifier row whose text fields are text: the model may return any JSON type."""
    return {**row, **{name: row.get(name) if isinstance(row.get(name), str) else None for name in _ROW_TEXT_FIELDS}}


def read_chart_region(path, region, version, question_id, *, complete, predictor=None):
    import pymupdf
    from PIL import Image

    from report_qa.application.evidence_extraction import (
        _measure,
        _unit_near,
        unit_note,
    )
    from report_qa.application.numeric_extraction import period_near

    key = region["chart_region_key"]
    number = region["page_number"]
    source_box = region["bbox"]
    with pymupdf.open(path) as pdf:
        page = pdf[number - 1]
        rect = chart_crop(page, source_box)
        box = [rect.x0 / page.rect.width, rect.y0 / page.rect.height, rect.x1 / page.rect.width, rect.y1 / page.rect.height]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=rect, alpha=False)
        png = pix.tobytes("png")
        from report_qa.application.deplot_reading import MODEL_ID, REVISION

        cache_key = hashlib.sha256(png + REVISION.encode()).hexdigest()
        cache_root = session_storage.RUNTIME_ROOT / "chart-cache"
        cache_path = cache_root / (cache_key + ".json")
        raw = None
        if predictor is None and cache_path.is_file():
            try:
                raw = json.loads(cache_path.read_text())["raw_output"]
            except (ValueError, KeyError):
                pass
        if raw is None:
            raw = (predictor or predict_chart)(
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            )
            if predictor is None:
                cache_root.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(
                        {"model": MODEL_ID, "revision": REVISION, "raw_output": raw},
                        ensure_ascii=False,
                    )
                )
        try:
            title, predictions = parse_table(raw)
        except ValueError as exc:
            seen = read_chart_image(png, box, [], [], words=[])
            reason = (
                "Biểu đồ tròn này chưa đọc được: DePlot không trả về bảng các phần dùng được."
                if seen["shape"] == "pie"
                else f"Biểu đồ này chưa đọc được: DePlot không trả về bảng số liệu dùng được ({exc})."
            )
            return _not_readable(key, question_id, version, raw, reason)
        # What the image itself shows: its shape, each bar's place and printed number, the axis scales.
        series_order = list(dict.fromkeys(p[1] for p in predictions))
        seen = read_chart_image(
            png, box, list(dict.fromkeys(p[0] for p in predictions)), series_order,
            words=_vector_words(page, rect), rows=len(predictions) // len(series_order),
        )
        if seen["shape"] == "pie" and (problem := _pie_problem(predictions)):
            return _not_readable(key, question_id, version, raw, problem)
        image = "data:image/png;base64," + base64.b64encode(png).decode()
        verification_raw = ""
        verification_error = None
        try:
            verification_raw = complete(
                VERIFY,
                [
                    {"type": "text", "text": "DePlot output:\n" + raw},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            )
            checked = _json_from_content(verification_raw)
            rows = checked.get("rows", [])
            if not isinstance(rows, list):
                raise ValueError("Invalid chart verifier output")  # noqa: TRY004
            rows = [_checked_row(row) for row in rows if isinstance(row, dict)]
        except (ValueError, RuntimeError) as exc:
            rows = []
            verification_error = str(exc)
        evidences = []
        warnings = []
        if verification_error:
            warnings.append(
                {
                    "code": "CHART_VISUAL_CHECK_FAILED",
                    "message": verification_error,
                    "evidence_key": None,
                }
            )
        marks = seen["marks"]
        odd = _percent_outliers(predictions)
        # One unnamed series takes the chart's title from DePlot, garbled; the region's caption reads better.
        caption = (region.get("text") or "").strip()
        series_names = {series for _, series, _, _ in predictions}
        shown_series = caption if caption and series_names == {title.strip()} else None
        # Legend entries that name their axis, one per series in DePlot's column order: they give each
        # series its axis and its printed name ("Biên lợi nhuận gộp (trục phải)" for DePlot's "Biểu đồ").
        legend_of = dict(zip(series_order, seen["legend"])) if len(seen["legend"]) == len(series_order) else {}
        periods = _period_sequence([p[0] for p in predictions[::len(series_order)]])
        repeats: dict[tuple, int] = {}
        for index, (category, series, token, value) in enumerate(predictions):
            row = index // len(series_order)
            # DePlot can repeat a category; the repeat count keeps keys unique
            # while a first occurrence keeps the key it always had.
            repeat = repeats.get((category, series), 0)
            repeats[(category, series)] = repeat + 1
            identity = f"{version}:{key}:{category}:{series}" + (f":{repeat}" if repeat else "")
            digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
            # Not "chart-": the planner flow reads the same chart under that
            # prefix, and one key must never name two stored values.
            eid = "chart-tools-" + digest
            matches = [
                r
                for r in rows
                if r.get("category") == category
                and (
                    r.get("series") == series
                    or (
                        r.get("series") is None
                        and sum(row[0] == category for row in predictions) == 1
                    )
                )
            ]
            r = matches[0] if len(matches) == 1 else {}
            try:
                agrees = value is not None and Decimal(str(r.get("value"))) == Decimal(
                    value
                )
            except InvalidOperation:
                agrees = False
            method = r.get("method")
            valid = False
            label_box_unusable = False
            location = box
            assumptions = ["deplot_table", "model_visual_check_not_human_confirmation"]
            mark = marks.get((category, series)) if not repeat else None
            # The label printed under the bars (vector charts) is exact; DePlot's spelling is not.
            label_category = periods[row] if periods else seen["names"].get(category, category)
            label_series = shown_series or legend_of.get(series, {}).get("text") or series
            if mark:
                location = mark["bar"]
            if mark and mark["label"] and _same_number(mark["text"], value):
                # The number printed above this bar is DePlot's value: point at it.
                location = mark["label"]
                valid = True
                method = "direct_label"
                assumptions.append("geometry_printed_label_match")
            elif agrees and method == "direct_label":
                native = _native_label(page, box, category, value)
                label = _label_box(r.get("label_bbox"))
                if native:
                    location = native
                    valid = True
                    assumptions.append("native_printed_label_match")
                elif label:
                    location = [
                        box[0] + label[0] * (box[2] - box[0]),
                        box[1] + label[1] * (box[3] - box[1]),
                        box[0] + label[2] * (box[2] - box[0]),
                        box[1] + label[3] * (box[3] - box[1]),
                    ]
                    valid = True
                    assumptions.append("vlm_printed_label_bbox_approximate")
                else:
                    # DePlot and the checker agree on a printed label, but the
                    # checker's box is unusable (seen offset fully past the
                    # crop for the right-most bar). The box only places the
                    # highlight: keep the value, point at the chart region,
                    # and cap confidence below a located label.
                    valid = True
                    label_box_unusable = True
                    assumptions.append("label_bbox_unusable_chart_region_used")
            lower = upper = None
            if agrees and method == "axis_estimation" and r.get("unit"):
                try:
                    lo, hi = (
                        Decimal(str(r.get("lower_tick"))),
                        Decimal(str(r.get("upper_tick"))),
                    )
                    if (
                        lo.is_finite()
                        and hi.is_finite()
                        and lo <= Decimal(value) <= hi
                        and lo < hi
                    ):
                        lower, upper = format(lo, "f"), format(hi, "f")
                        valid = True
                        assumptions += [
                            "vlm_assessed_linear_axis",
                            "chart_bbox_not_exact_point",
                        ]
                except InvalidOperation:
                    pass
            # The bar's height on its axis is a second reading of an estimated value: it confirms or overrules it.
            side = axis_side(series) or legend_of.get(series, {}).get("side")
            estimate = mark.get("estimate") if mark else None
            printed = "geometry_printed_label_match" in assumptions or "native_printed_label_match" in assumptions
            problem = None
            if value is not None and estimate is not None and not printed:
                axis = seen["axes"]["right" if side == "right" else "left"]
                if abs(float(value) - estimate) <= _AXIS_TOLERANCE * (axis["high"] - axis["low"]):
                    if not valid:
                        valid = True
                        method = "axis_estimation"
                        lower, upper = _tick(axis["low"]), _tick(axis["high"])
                        assumptions += ["geometry_axis_estimate_match", "chart_bbox_not_exact_point"]
                else:
                    shown = f"{estimate:.1f}" if abs(estimate) < 100 else f"{estimate:.0f}"
                    problem = ("CHART_VALUE_DISAGREES_WITH_BAR",
                               f"{label_category} · {label_series}: DePlot đọc {token}, nhưng chiều cao cột trên trục cho khoảng {shown}.")
            # A line on the right axis is read where it is drawn. DePlot often reads it on the left
            # axis's scale (S2 Biểu đồ 1: 241 for a 17.9% margin): then the point read on the right axis is used.
            point = seen["right_line"][row] if side == "right" and seen["right_line"] and row < len(seen["right_line"]) else None
            if point and not problem:
                axis = seen["axes"]["right"]
                reading = _reading(point["value"], axis)
                location = point["box"]
                lower, upper = _tick(axis["low"]), _tick(axis["high"])
                if value is not None and abs(float(value) - point["value"]) <= _AXIS_TOLERANCE * (axis["high"] - axis["low"]):
                    if not valid:
                        valid, method = True, "axis_estimation"
                        assumptions += ["geometry_line_point_match", "chart_bbox_not_exact_point"]
                else:
                    warnings.append({"code": "CHART_VALUE_FROM_LINE", "evidence_key": eid,
                                     "message": f"{label_category} · {label_series}: DePlot đọc {token}, không khớp trục phải; "
                                                f"điểm trên đường đọc theo trục phải là {reading}."})
                    token, value = reading, reading
                    valid, method = True, "axis_estimation"
                    assumptions += ["geometry_line_point_reading", "deplot_value_replaced", "chart_bbox_not_exact_point"]
            axis = seen["axes"].get(side) if side else None
            if value is not None and axis and not problem and not point:
                # A linear scale reaches past the ticks OCR read; otherwise allow a little past the ticks seen.
                margin = 0.05 * (axis["high"] - axis["low"])
                low, high = axis.get("reach") or (axis["low"] - margin, axis["high"] + margin)
                if not low <= float(value) <= high:
                    where = "phải" if side == "right" else "trái"
                    problem = ("CHART_VALUE_OFF_AXIS",
                               f"{label_category} · {label_series}: DePlot đọc {token}, ngoài thang trục {where} ({_tick(axis['low'])} đến {_tick(axis['high'])}). Có thể đã đọc theo trục kia.")
            if (category, series, token) in odd and not problem:
                problem = ("CHART_VALUE_INCONSISTENT",
                           f"{label_category} · {label_series}: DePlot đọc {token}, khác kiểu với các số còn lại của dãy (có hoặc không có %).")
            if problem:
                valid = False
                warnings.append({"code": problem[0], "message": problem[1], "evidence_key": eid})
            if method not in {"direct_label", "axis_estimation"}:
                method = "axis_estimation"
            if not valid:
                warnings.append(
                    {
                        "code": "CHART_READ_AMBIGUOUS",
                        "message": "Giá trị DePlot chưa được đối chiếu chắc chắn với nhãn/trục.",
                        "evidence_key": eid,
                    }
                )
                assumptions.append("unverified_method_do_not_calculate")
            confidence = r.get("confidence", 0)
            if not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
                confidence = 0
            if "geometry_printed_label_match" in assumptions:
                # Two independent reads (DePlot and OCR of the printed label) agree on the number.
                confidence = max(float(confidence), 0.8)
            elif {"geometry_axis_estimate_match", "geometry_line_point_match", "geometry_line_point_reading"} & set(assumptions):
                # DePlot and the bar's measured height agree, but both are estimates.
                confidence = max(float(confidence), 0.6)
            # A value taken from the image alone, or a label box that is only the chart, stays at 0.6.
            capped = label_box_unusable or "deplot_value_replaced" in assumptions
            confidence = max(0, min(0.6 if capped else 0.85, float(confidence))) if valid else 0
            if confidence < 0.5:
                valid = False
            # Where the value's box is, so a reader can tell a tap target from the whole chart.
            if point and location == point["box"]:
                assumptions.append("box_point")
            elif mark and location == mark["bar"]:
                assumptions.append("box_bar")
            elif location is box or label_box_unusable:
                assumptions.append("box_whole_chart")
            else:
                assumptions.append("box_printed_label")
            evidences.append(
                {
                    "evidence_key": eid,
                    "source_region_key": key,
                    "source_type": "chart",
                    "page_number": number,
                    "bbox": location,
                    "raw_text": token,
                    "numeric_value": value if valid else None,
                    "data_status": "valid" if valid else "ambiguous",
                    "extraction_method": method,
                    "method_label": "đọc từ nhãn"
                    if method == "direct_label"
                    else "ước lượng theo trục",
                    "semantic": {
                        "measure": str(r.get("measure") or _measure(label_series)),
                        "subject": label_category,
                        "period": period_near(str(r.get("period") or ""), 0),
                        # The checker's reading of the unit, else the chart's own unit note, else the series name.
                        "unit": r.get("unit") or unit_note(title or "") or _unit_near(series, token),
                        "dimensions": {"category": label_category, "series": label_series},
                    },
                    "table_locator": None,
                    "chart_read": {
                        "chart_region_key": key,
                        "series_label": label_series,
                        "category_label": label_category,
                        "axis_label": r.get("axis_label"),
                        "axis_unit": r.get("unit"),
                        "lower_tick": lower,
                        "upper_tick": upper,
                        "assumptions": assumptions,
                    },
                    "confidence": confidence,
                }
            )
    batch = {
        "schema_version": 2,
        "document_version_id": version,
        "extraction_run_id": str(uuid4()),
        "scope": "on_demand_chart",
        "trigger": {
            "question_plan_id": question_id,
            "fact_keys": ["chart-data"],
            "chart_region_keys": [key],
        },
        "evidences": evidences,
        "warnings": warnings,
    }
    validate_extraction_batch(batch)
    return {
        "status": "completed",
        "evidence_batch": batch,
        "raw_output": raw,
        "visual_check_output": verification_raw,
        "visual_check_error": verification_error,
        "reader_version": CHART_READER_VERSION,
    }
