"""Question-scoped deterministic reader for simple vector bar charts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from report_qa.domain.contracts import validate_document_evidence_v2


NUMBER_RE = re.compile(r"(?<![\w/])[-+]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?%?")


@dataclass(frozen=True, slots=True)
class ChartReadRequest:
    document_version_id: str
    question_plan_id: str
    fact_keys: tuple[str, ...]
    chart_region_keys: tuple[str, ...] = ()
    source_pdf_path: Path | None = None
    page_numbers: tuple[int, ...] = ()
    fact_requirements: tuple[dict[str, Any], ...] = ()


class ChartReader(Protocol):
    def read(self, request: ChartReadRequest) -> dict[str, Any]: ...


def _decimal_text(raw: str) -> str:
    value = raw.strip().replace(" ", "").removesuffix("%")
    sign = ""
    if value[:1] in {"+", "-"}:
        sign, value = value[0], value[1:]
    if "," in value and "." in value:
        sep = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if sep == "," else ",", "").replace(sep, ".")
    elif "," in value or "." in value:
        sep = "," if "," in value else "."
        pieces = value.split(sep)
        value = "".join(pieces) if len(pieces) > 2 or (len(pieces) == 2 and len(pieces[1]) == 3) else ".".join(pieces)
    value = value.lstrip("0") or "0"
    return f"{sign}{value}" if value != "0" else "0"


def _bbox(x0: float, y0: float, x1: float, y1: float, width: float, height: float) -> list[float]:
    return [round(max(0.0, min(1.0, value)), 6) for value in (x0 / width, 1 - y1 / height, x1 / width, 1 - y0 / height)]


def _semantic(requirement: dict[str, Any]) -> dict[str, Any]:
    period = requirement.get("period")
    return {"measure": requirement.get("measure", "unknown"), "subject": requirement.get("subject"), "period": {"label": period} if isinstance(period, str) else period, "unit": requirement.get("unit"), "dimensions": requirement.get("dimensions", {})}


class PdfVectorChartReader:
    """Read only a provable subset: independent bars on one linear y-axis.

    A printed value next to a bar becomes ``direct_label`` / “đọc từ nhãn”.
    Without it, the bar top is interpolated between two labelled y-axis ticks
    as ``axis_estimation`` / “ước lượng theo trục”.  Stacked/overlaid bars are
    rejected instead of guessed.
    """

    def read(self, request: ChartReadRequest) -> dict[str, Any]:
        if request.source_pdf_path is None or not request.source_pdf_path.exists():
            return self._result(request, "not_available", "CHART_SOURCE_UNAVAILABLE")
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError:
            return self._result(request, "not_available", "PDF_READER_UNAVAILABLE")
        reader = PdfReader(str(request.source_pdf_path))
        pages = set(request.page_numbers) or set(range(1, len(reader.pages) + 1))
        requirements = list(request.fact_requirements) or [{"fact_key": key, "measure": "unknown", "period": None, "unit": None, "dimensions": {}} for key in request.fact_keys]
        warnings: list[dict[str, Any]] = []
        evidences: list[dict[str, Any]] = []
        for number, page in enumerate(reader.pages, start=1):
            if number in pages:
                evidences.extend(self._read_page(page, number, request, requirements, warnings))
        batch = {"schema_version": 2, "document_version_id": request.document_version_id, "extraction_run_id": str(uuid4()), "scope": "on_demand_chart", "trigger": {"question_plan_id": request.question_plan_id, "fact_keys": list(request.fact_keys)}, "evidences": evidences, "warnings": warnings}
        validate_document_evidence_v2(batch)
        return {"status": "completed" if evidences else "not_found", "code": None if evidences else "CHART_FACT_NOT_RESOLVED", "question_plan_id": request.question_plan_id, "fact_keys": list(request.fact_keys), "evidence_batch": batch}

    def _read_page(self, page: Any, page_number: int, request: ChartReadRequest, requirements: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        width, height = float(page.mediabox.width) or 1.0, float(page.mediabox.height) or 1.0
        texts: list[dict[str, Any]] = []
        rectangles: list[tuple[float, float, float, float]] = []
        def text_visitor(text: str, _cm: Any, tm: Any, _font: Any, font_size: float) -> None:
            if text and text.strip(): texts.append({"text": text.strip(), "x": float(tm[4]), "y": float(tm[5]), "size": float(font_size or 10)})
        def operand_visitor(operator: bytes, operands: Any, _cm: Any, _tm: Any) -> None:
            if operator == b"re" and len(operands) == 4:
                try:
                    x, y, rw, rh = (float(value) for value in operands)
                    if rw >= 3 and rh >= 3: rectangles.append((x, y, rw, rh))
                except (TypeError, ValueError): pass
        page.extract_text(visitor_text=text_visitor, visitor_operand_before=operand_visitor)
        bars = sorted((item for item in rectangles if item[2] <= width * .25 and item[3] <= height * .9), key=lambda item: item[0])
        if not bars: return []
        if len({round(item[0], 1) for item in bars}) != len(bars):
            warnings.append({"code": "CHART_AMBIGUOUS_STACKED_OR_OVERLAID", "message": "Biểu đồ có cột chồng hoặc đè; không nội suy giá trị.", "page_number": page_number})
            return []
        labels, ticks, result = self._direct_labels(texts, bars), self._axis_ticks(texts, bars), []
        for index, (bar, requirement) in enumerate(zip(bars, requirements)):
            x, y, rw, rh = bar
            if index in labels:
                raw, tx, ty = labels[index]
                result.append(self._evidence(page_number, index, request, requirement, raw, _bbox(tx, ty, tx + max(8, len(raw) * 6), ty + 12, width, height), "direct_label", {"kind": "printed_value_label", "bar_bbox": _bbox(x, y, x + rw, y + rh, width, height)}))
            elif len(ticks) >= 2 and ticks[-1][1] != ticks[0][1]:
                lower, upper = ticks[0], ticks[-1]
                value = lower[0] + (y + rh - lower[1]) * (upper[0] - lower[0]) / (upper[1] - lower[1])
                step, precision = abs(upper[0] - lower[0]), 0 if abs(upper[0] - lower[0]) >= 10 else 1
                raw = f"{value:.{precision}f}"
                meta = {"kind": "linear_axis_interpolation", "axis_label": None, "axis_unit": requirement.get("unit"), "lower_tick": {"value": str(lower[0]), "pdf_y": lower[1]}, "upper_tick": {"value": str(upper[0]), "pdf_y": upper[1]}, "assumptions": ["single_linear_y_axis", "independent_bar", "bar_top_interpolated"]}
                result.append(self._evidence(page_number, index, request, requirement, raw, _bbox(x, y, x + rw, y + rh, width, height), "axis_estimation", meta))
        return result

    @staticmethod
    def _direct_labels(texts: list[dict[str, Any]], bars: list[tuple[float, float, float, float]]) -> dict[int, tuple[str, float, float]]:
        found: dict[int, tuple[str, float, float]] = {}
        for index, (x, y, rw, rh) in enumerate(bars):
            candidates = []
            for span in texts:
                if not NUMBER_RE.fullmatch(span["text"]): continue
                if abs((span["x"] + len(span["text"]) * 3) - (x + rw / 2)) <= max(rw * 1.8, 28) and y - 4 <= span["y"] <= y + rh + 28:
                    candidates.append((abs(span["y"] - (y + rh)), span["text"], span["x"], span["y"]))
            if candidates:
                _, raw, tx, ty = min(candidates); found[index] = (raw, tx, ty)
        return found

    @staticmethod
    def _axis_ticks(texts: list[dict[str, Any]], bars: list[tuple[float, float, float, float]]) -> list[tuple[float, float]]:
        left, low, high = min(item[0] for item in bars), min(item[1] for item in bars) - 12, max(item[1] + item[3] for item in bars) + 12
        ticks = []
        for span in texts:
            if NUMBER_RE.fullmatch(span["text"]) and span["x"] < left and low <= span["y"] <= high:
                try: ticks.append((float(_decimal_text(span["text"])), span["y"]))
                except ValueError: pass
        return sorted(set((value, round(y, 2)) for value, y in ticks), key=lambda item: item[1])

    @staticmethod
    def _evidence(page_number: int, index: int, request: ChartReadRequest, requirement: dict[str, Any], raw: str, bbox: list[float], method: str, chart_read: dict[str, Any]) -> dict[str, Any]:
        digest = hashlib.sha256(f"{request.question_plan_id}:{page_number}:{index}:{raw}:{method}".encode()).hexdigest()[:16]
        return {"evidence_key": f"chart-{digest}", "source_region_key": f"page-{page_number}-chart-vector", "source_type": "chart", "page_number": page_number, "bbox": bbox, "raw_text": raw, "numeric_value": _decimal_text(raw), "data_status": "valid", "extraction_method": method, "method_label": "đọc từ nhãn" if method == "direct_label" else "ước lượng theo trục", "semantic": _semantic(requirement), "table_locator": None, "chart_read": chart_read, "confidence": .98 if method == "direct_label" else .65}

    @staticmethod
    def _result(request: ChartReadRequest, status: str, code: str) -> dict[str, Any]:
        return {"status": status, "code": code, "question_plan_id": request.question_plan_id, "fact_keys": list(request.fact_keys), "evidence_batch": None}


class UnavailableChartReader:
    def read(self, request: ChartReadRequest) -> dict[str, Any]:
        return PdfVectorChartReader._result(request, "not_available", "CHART_READER_DISABLED")


__all__ = ["ChartReadRequest", "ChartReader", "PdfVectorChartReader", "UnavailableChartReader"]
