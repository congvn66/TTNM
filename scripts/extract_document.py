"""CLI handoff: PDF -> canonical evidence, optionally read triggered charts.

Run from the repository root after `pip install -e '.[docling-deplot]'`.
"""

import argparse
import json
from pathlib import Path

from report_qa.application.chart_reading import ChartReadRequest
from report_qa.application.deplot_reading import DeplotChartReader
from report_qa.application.docling_extraction import extract_docling_artifact


def main():
    parser = argparse.ArgumentParser(
        description="Extract positioned numbers with Docling; read charts only with an explicit request."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--document-version-id", required=True)
    parser.add_argument("--locale", choices=["vi", "en"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--chart-request",
        type=Path,
        help="JSON containing ready plan trigger, chart regions and fact requirements",
    )
    args = parser.parse_args()
    artifact = extract_docling_artifact(
        args.pdf, args.document_version_id, locale=args.locale
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "document.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2)
    )
    (args.output / "base-evidence.json").write_text(
        json.dumps(artifact["evidence_batch"], ensure_ascii=False, indent=2)
    )
    if args.chart_request:
        payload = json.loads(args.chart_request.read_text())
        if payload.get("status") != "ready":
            parser.error("Chart extraction requires a ready question plan")
        request = ChartReadRequest(
            document_version_id=args.document_version_id,
            question_plan_id=payload["question_plan_id"],
            fact_keys=tuple(payload["fact_keys"]),
            chart_region_keys=tuple(payload["chart_region_keys"]),
            source_pdf_path=args.pdf,
            page_numbers=tuple(payload.get("page_numbers", [])),
            fact_requirements=tuple(payload["fact_requirements"]),
            chart_regions=tuple(payload["chart_regions"]),
        )
        result = DeplotChartReader().read(request)
        (args.output / "chart-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    print(
        f"Saved {len(artifact['evidence_batch']['evidences'])} base values to {args.output}"
    )


if __name__ == "__main__":
    main()
