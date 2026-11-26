"""Read one requested image with DePlot, then inspect label/axis provenance.

The visual checker sees the source crop and the unchanged DePlot table. Its
assessment is model-based, not a human confirmation; uncertain values remain
ambiguous. Stored raw outputs support later review and correction.
"""

import base64
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from report_qa.api.ai_provider import _json_from_content
from report_qa.application.deplot_reading import (
    _native_label,
    parse_table,
    predict_chart,
)
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
unknown nếu không rõ. unit VND_MILLION nếu million VND/triệu đồng, PERCENT cho %,
null nếu ảnh không ghi. period=null nếu không có. Giữ nhãn category/series đúng
như DePlot. confidence 0..1 là đánh giá của mô hình, không phải xác nhận con người.
"""


# The visual checker's label box is approximate. A label at the chart edge
# often comes back slightly past the crop (e.g. x1=1.036), which used to
# discard a value the checker had confirmed. Clamp small overshoots; still
# reject boxes that are clearly off the image.
_LABEL_BOX_TOLERANCE = 0.1


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
        _period_near,
        _unit_near,
    )

    key = region["chart_region_key"]
    number = region["page_number"]
    source_box = region["bbox"]
    # Layout detection can exclude the title/tick labels at the picture edge.
    box = [
        max(0, source_box[0] - 0.03),
        max(0, source_box[1] - 0.03),
        min(1, source_box[2] + 0.03),
        min(1, source_box[3] + 0.03),
    ]
    with pymupdf.open(path) as pdf:
        page = pdf[number - 1]
        rect = pymupdf.Rect(
            box[0] * page.rect.width,
            box[1] * page.rect.height,
            box[2] * page.rect.width,
            box[3] * page.rect.height,
        )
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=rect, alpha=False)
        png = pix.tobytes("png")
        from report_qa.application.deplot_reading import MODEL_ID, REVISION

        cache_key = hashlib.sha256(png + REVISION.encode()).hexdigest()
        cache_root = Path(__file__).resolve().parents[5] / "runtime" / "chart-cache"
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
        _title, predictions = parse_table(raw)
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
        seen: dict[tuple, int] = {}
        for category, series, token, value in predictions:
            # DePlot can repeat a category; the repeat count keeps keys unique
            # while a first occurrence keeps the key it always had.
            repeat = seen.get((category, series), 0)
            seen[(category, series)] = repeat + 1
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
            if agrees and method == "direct_label":
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
            confidence = max(0, min(0.6 if label_box_unusable else 0.85, float(confidence))) if valid else 0
            if confidence < 0.5:
                valid = False
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
                        "measure": str(r.get("measure") or _measure(series)),
                        "subject": category,
                        "period": _period_near(str(r.get("period") or ""), 0),
                        "unit": r.get("unit") or _unit_near(series, token),
                        "dimensions": {"category": category, "series": series},
                    },
                    "table_locator": None,
                    "chart_read": {
                        "chart_region_key": key,
                        "series_label": series,
                        "category_label": category,
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
    }
