from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "doc"
EXPECTED_TABLES = {
    "users", "projects", "documents", "project_documents", "document_versions",
    "extraction_runs", "source_regions", "extracted_evidences", "chats",
    "chat_sources", "chat_evidences", "evidence_revisions", "messages",
    "answer_revisions", "answer_inputs", "answer_scopes", "message_pins",
    "auth_sessions", "account_tokens", "jobs", "job_events", "audit_events",
    "request_keys",
}
BANNED_SCOPE_TERMS = ("screen reader", "screen-reader", "nvda", "wcag", "wai-aria")
EXPECTED_CONTRACTS = {
    "answer-scope-v1.schema.json",
    "calculation-result-v1.schema.json",
    "document-evidence-v2.schema.json",
    "provider-extraction-v1.schema.json",
    "question-context-v1.schema.json",
    "question-plan-v2.schema.json",
    "semantic-v1.schema.json",
}


class DesignConsistencyError(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DesignConsistencyError(message)


def check_markdown_links() -> int:
    checked = 0
    pattern = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")
    for path in [ROOT / "AGENTS.md", *sorted(DOC.rglob("*.md")), ROOT / "contracts" / "README.md", ROOT / "tests" / "mock_data" / "README.md"]:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            target_text = match.group(1)
            if "://" in target_text or target_text.startswith("mailto:"):
                continue
            target = (path.parent / target_text).resolve()
            require(target.exists(), f"broken link in {path.relative_to(ROOT)}: {target_text}")
            checked += 1
    return checked


def check_removed_scope() -> None:
    for path in [ROOT / "AGENTS.md", *sorted(DOC.rglob("*.md"))]:
        lowered = path.read_text(encoding="utf-8").lower()
        for term in BANNED_SCOPE_TERMS:
            require(term not in lowered, f"removed scope term '{term}' in {path.relative_to(ROOT)}")


def check_schema() -> dict[str, int]:
    sql = (DOC / "initial-schema.sql").read_text(encoding="utf-8")
    tables = set(re.findall(r"(?m)^CREATE TABLE ([a-z_]+) \(", sql))
    require(tables == EXPECTED_TABLES, f"schema table mismatch: {tables ^ EXPECTED_TABLES}")
    triggers = len(re.findall(r"(?m)^CREATE (?:CONSTRAINT )?TRIGGER ", sql))
    require(triggers >= 10, f"schema has too few integrity triggers: {triggers}")
    require("dedup_key text NOT NULL UNIQUE" in sql, "schema missing job dedup key")
    require("next_sequence_no bigint NOT NULL" in sql, "schema missing message sequence allocator")
    return {"tables": len(tables), "triggers": triggers}


def check_requirement_traceability() -> dict[str, int]:
    requirements = (DOC / "requirements.md").read_text(encoding="utf-8")
    traceability = (DOC / "traceability.md").read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| ((?:FR|DI|NFR)-[A-Z]+-[0-9]{3}|DI-[0-9]{3}) \| (MUST|SHOULD|MAY) \|", requirements)
    require(rows, "requirements: no machine-readable requirement rows")
    must = {requirement_id for requirement_id, level in rows if level == "MUST"}
    missing = sorted(requirement_id for requirement_id in must if requirement_id not in traceability)
    require(not missing, f"traceability missing MUST IDs: {missing}")
    return {"requirements": len(rows), "must": len(must)}


def check_json_contracts() -> int:
    paths = sorted((ROOT / "contracts").glob("*.schema.json"))
    require({path.name for path in paths} == EXPECTED_CONTRACTS, "JSON contract inventory mismatch")
    loaded: dict[str, dict[str, Any]] = {}
    for path in paths:
        schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", f"wrong JSON Schema draft: {path.name}")
        require(schema.get("additionalProperties") is False, f"root must be closed: {path.name}")
        loaded[path.name] = schema

    evidence = loaded["document-evidence-v2.schema.json"]["$defs"]["evidence"]
    require({"page_number", "bbox", "extraction_method", "method_label"} <= set(evidence["required"]), "numeric evidence locator/method is not required")
    require(set(evidence["properties"]["extraction_method"]["enum"]) >= {"direct_label", "axis_estimation"}, "chart provenance methods missing")
    require(set(evidence["properties"]["method_label"]["enum"]) >= {"đọc từ nhãn", "ước lượng theo trục"}, "Vietnamese chart method labels missing")

    plan = loaded["question-plan-v2.schema.json"]
    require(set(plan["properties"]["status"]["enum"]) == {"ready", "needs_clarification", "unsupported"}, "question plan statuses drifted")
    require(plan["properties"]["source_strategy"]["properties"]["chart_policy"]["const"] == "only_if_required_fact_unresolved", "chart must remain on-demand")

    calculation = loaded["calculation-result-v1.schema.json"]
    require(set(calculation["properties"]["status"]["enum"]) >= {"missing_data", "zero_denominator", "unit_mismatch", "ambiguous"}, "calculator failure statuses missing")

    examples = ROOT / "contracts" / "examples"
    evidence_example = json.loads((examples / "document-evidence-v2.example.json").read_text(encoding="utf-8"))
    plan_example = json.loads((examples / "question-plan-v2.example.json").read_text(encoding="utf-8"))
    result_example = json.loads((examples / "calculation-result-v1.example.json").read_text(encoding="utf-8"))
    require(evidence_example["schema_version"] == 2 and plan_example["schema_version"] == 2, "v2 example version mismatch")
    require(result_example["question_plan_id"] == plan_example["question_plan_id"], "plan/calculation example correlation mismatch")
    require(all(len(item["bbox"]) == 4 and item["page_number"] >= 1 for item in evidence_example["evidences"]), "example evidence locator invalid")
    operands = {item["fact_key"]: Decimal(item["value"]) for item in result_example["operands"]}
    expected_growth = (operands["current"] - operands["baseline"]) / operands["baseline"] * Decimal("100")
    require(Decimal(result_example["value"]) == expected_growth, "calculation example is not produced by growth_rate_v1")
    return len(paths)


def check_all() -> dict[str, int]:
    check_removed_scope()
    result = check_schema()
    result.update(check_requirement_traceability())
    result["contracts"] = check_json_contracts()
    result["links"] = check_markdown_links()
    return result


def main() -> None:
    print(json.dumps(check_all(), sort_keys=True))


if __name__ == "__main__":
    main()
