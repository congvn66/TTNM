from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "mock_data"
CONTRACTS = ROOT / "contracts"
REQUIRED_TABLES = {
    "users", "projects", "documents", "project_documents", "document_versions",
    "extraction_runs", "source_regions", "extracted_evidences", "chats",
    "chat_sources", "chat_evidences", "evidence_revisions", "messages",
    "answer_revisions", "answer_inputs", "answer_scopes", "message_pins",
    "auth_sessions", "account_tokens", "jobs", "job_events", "audit_events",
    "request_keys",
}


class ValidationError(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def keyed(rows: list[dict[str, Any]], table: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        require("id" in row, f"{table}: row without id")
        require(row["id"] not in result, f"{table}: duplicate id {row['id']}")
        result[row["id"]] = row
    return result


def validate_domain(seed: dict[str, Any]) -> None:
    actual_tables = set(seed) - {"_ids"}
    require(actual_tables == REQUIRED_TABLES, f"domain tables mismatch: {actual_tables ^ REQUIRED_TABLES}")
    for table in REQUIRED_TABLES:
        require(isinstance(seed[table], list) and seed[table], f"{table}: fixture must be non-empty")

    users = keyed(seed["users"], "users")
    projects = keyed(seed["projects"], "projects")
    documents = keyed(seed["documents"], "documents")
    versions = keyed(seed["document_versions"], "document_versions")
    runs = keyed(seed["extraction_runs"], "extraction_runs")
    regions = keyed(seed["source_regions"], "source_regions")
    evidences = keyed(seed["extracted_evidences"], "extracted_evidences")
    chats = keyed(seed["chats"], "chats")
    sources = keyed(seed["chat_sources"], "chat_sources")
    chat_evidences = keyed(seed["chat_evidences"], "chat_evidences")
    revisions = keyed(seed["evidence_revisions"], "evidence_revisions")
    messages = keyed(seed["messages"], "messages")
    answers = keyed(seed["answer_revisions"], "answer_revisions")
    jobs = keyed(seed["jobs"], "jobs")

    normalized_emails = [row["normalized_email"] for row in users.values()]
    require(len(normalized_emails) == len(set(normalized_emails)), "users: duplicate normalized email")
    for row in projects.values():
        require(row["owner_id"] in users, "projects: missing owner")
    for row in documents.values():
        require(row["owner_id"] in users, "documents: missing owner")
    for row in seed["project_documents"]:
        require(row["project_id"] in projects and row["document_id"] in documents, "project_documents: missing parent")
        require(projects[row["project_id"]]["owner_id"] == row["owner_id"] == documents[row["document_id"]]["owner_id"], "project_documents: cross-owner link")
    for row in versions.values():
        require(row["document_id"] in documents, "document_versions: missing document")
    for row in runs.values():
        require(row["document_version_id"] in versions, "extraction_runs: missing version")
    for row in regions.values():
        require(row["extraction_run_id"] in runs, "source_regions: missing run")
        bbox = row.get("bbox")
        if bbox is not None:
            require(len(bbox) == 4, "source_regions: bbox length")
            require(all(isinstance(value, (int, float)) for value in bbox), "source_regions: bbox types")
            require(0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1, "source_regions: bbox order/range")
    for row in evidences.values():
        require(row["extraction_run_id"] in runs and row["source_region_id"] in regions, "extracted_evidences: missing parent")
        require(regions[row["source_region_id"]]["extraction_run_id"] == row["extraction_run_id"], "extracted_evidences: cross-run region")
        valid = row["data_status"] == "valid"
        if row["value_kind"] == "number":
            require((valid and row["raw_value"] is not None and row["raw_text"] is None) or (not valid and row["raw_value"] is None and row["raw_text"] is None), "extracted_evidences: invalid numeric state")
        else:
            require((valid and row["raw_text"] is not None and row["raw_value"] is None) or (not valid and row["raw_value"] is None and row["raw_text"] is None), "extracted_evidences: invalid text state")
    for row in chats.values():
        require(row["owner_id"] in users, "chats: missing owner")
        if row.get("project_id"):
            require(projects[row["project_id"]]["owner_id"] == row["owner_id"], "chats: project owner mismatch")
    for row in sources.values():
        require(row["chat_id"] in chats and row["document_version_id"] in versions and row["extraction_run_id"] in runs, "chat_sources: missing parent")
        require(runs[row["extraction_run_id"]]["document_version_id"] == row["document_version_id"], "chat_sources: run/version mismatch")
        require(row["source_status"] != "active" or runs[row["extraction_run_id"]]["status"] == "completed", "chat_sources: active incomplete run")
    for row in chat_evidences.values():
        require(row["chat_id"] in chats and row["chat_source_id"] in sources and row["extracted_evidence_id"] in evidences, "chat_evidences: missing parent")
        require(sources[row["chat_source_id"]]["chat_id"] == row["chat_id"], "chat_evidences: source/chat mismatch")
        require(evidences[row["extracted_evidence_id"]]["extraction_run_id"] == row["extraction_run_id"] == sources[row["chat_source_id"]]["extraction_run_id"], "chat_evidences: origin run mismatch")
    for row in revisions.values():
        require(row["chat_evidence_id"] in chat_evidences, "evidence_revisions: missing evidence")
        require(chat_evidences[row["chat_evidence_id"]]["chat_id"] == row["chat_id"], "evidence_revisions: chat mismatch")
        valid = row["data_status"] == "valid"
        if row["value_kind"] == "number":
            require((valid and row["numeric_value"] is not None and row["text_value"] is None) or (not valid and row["numeric_value"] is None and row["text_value"] is None), "evidence_revisions: invalid numeric state")
        else:
            require((valid and row["text_value"] is not None and row["numeric_value"] is None) or (not valid and row["numeric_value"] is None and row["text_value"] is None), "evidence_revisions: invalid text state")
    for row in chat_evidences.values():
        require(row["current_revision_id"] in revisions, "chat_evidences: missing current revision")
        require(revisions[row["current_revision_id"]]["chat_evidence_id"] == row["id"], "chat_evidences: current revision belongs to another evidence")
    sequences: dict[str, set[int]] = defaultdict(set)
    for row in messages.values():
        require(row["chat_id"] in chats, "messages: missing chat")
        require(row["sequence_no"] not in sequences[row["chat_id"]], "messages: duplicate sequence")
        sequences[row["chat_id"]].add(row["sequence_no"])
        if row.get("reply_to_message_id"):
            require(row["reply_to_message_id"] in messages and messages[row["reply_to_message_id"]]["chat_id"] == row["chat_id"], "messages: invalid reply")
    for row in answers.values():
        require(row["message_id"] in messages and messages[row["message_id"]]["role"] == "assistant", "answer_revisions: owner must be assistant message")
        require(messages[row["message_id"]]["chat_id"] == row["chat_id"], "answer_revisions: chat mismatch")
    for row in messages.values():
        if row.get("current_answer_revision_id"):
            require(row["current_answer_revision_id"] in answers and answers[row["current_answer_revision_id"]]["message_id"] == row["id"], "messages: invalid current answer")
    for row in seed["answer_inputs"]:
        require(row["answer_revision_id"] in answers and row["evidence_revision_id"] in revisions, "answer_inputs: missing parent")
        require(answers[row["answer_revision_id"]]["chat_id"] == row["chat_id"] == revisions[row["evidence_revision_id"]]["chat_id"], "answer_inputs: cross-chat")
    for row in seed["answer_scopes"]:
        require(row["answer_revision_id"] in answers and row["chat_source_id"] in sources, "answer_scopes: missing parent")
        require(answers[row["answer_revision_id"]]["chat_id"] == row["chat_id"] == sources[row["chat_source_id"]]["chat_id"], "answer_scopes: cross-chat")
    for row in seed["message_pins"]:
        require(row["message_id"] in messages and row["chat_id"] in chats, "message_pins: missing parent")
        require(chats[row["chat_id"]]["owner_id"] == row["owner_id"] and messages[row["message_id"]]["chat_id"] == row["chat_id"], "message_pins: ownership mismatch")
    for table in ("auth_sessions", "account_tokens"):
        for row in seed[table]:
            require(row["user_id"] in users, f"{table}: missing user")
    dedup_keys = set()
    for row in jobs.values():
        if row.get("owner_id"):
            require(row["owner_id"] in users, "jobs: missing owner")
        if row.get("chat_id"):
            require(row["chat_id"] in chats, "jobs: missing chat")
        require(row["dedup_key"] not in dedup_keys, "jobs: duplicate dedup key")
        dedup_keys.add(row["dedup_key"])
    for row in seed["job_events"]:
        require(row["job_id"] in jobs, "job_events: missing job")
    for row in seed["audit_events"]:
        require(row.get("actor_id") is None or row["actor_id"] in users, "audit_events: missing actor")
    for row in seed["request_keys"]:
        require(row["owner_id"] in users, "request_keys: missing owner")


def validate_evaluation(reports: list[dict[str, Any]], questions: list[dict[str, Any]]) -> None:
    require(len(reports) == 20, "reports: expected 20")
    require(len(questions) == 180, "questions: expected 180")
    report_ids = {row["report_id"] for row in reports}
    require(len(report_ids) == len(reports), "reports: duplicate report_id")
    question_ids = {row["question_id"] for row in questions}
    require(len(question_ids) == len(questions), "questions: duplicate question_id")
    require(all(row["report_id"] in report_ids for row in questions), "questions: unknown report")
    expected = {
        ("dev", "lookup"): 30, ("dev", "calculation"): 30, ("dev", "mixed"): 20,
        ("dev", "followup"): 20, ("dev", "exception"): 20,
        ("final", "lookup"): 15, ("final", "calculation"): 15, ("final", "mixed"): 10,
        ("final", "followup"): 10, ("final", "exception"): 10,
    }
    actual = Counter((row["split"], row["primary_task"]) for row in questions)
    require(actual == expected, f"questions: distribution mismatch {actual}")
    report_splits: dict[str, set[str]] = defaultdict(set)
    conversation_splits: dict[str, set[str]] = defaultdict(set)
    for row in questions:
        report_splits[row["report_id"]].add(row["split"])
        conversation_splits[row["conversation_id"]].add(row["split"])
        require(row["expected_action"] in {"answer", "clarify", "insufficient_data", "select_source"}, "questions: invalid action")
        require((row["expected_action"] == "answer") == (row["oracle_answer"] is not None), "questions: answer/oracle mismatch")
    require(all(len(value) == 1 for value in report_splits.values()), "questions: report leakage across splits")
    require(all(len(value) == 1 for value in conversation_splits.values()), "questions: conversation leakage across splits")


def validate_files(manifest: dict[str, Any], reports: list[dict[str, Any]]) -> None:
    for relative, expected_hash in manifest["sha256"].items():
        path = DATA / relative
        require(path.is_file(), f"manifest: missing {relative}")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual_hash == expected_hash, f"manifest: checksum mismatch {relative}")
    for report in reports:
        path = DATA / report["file"]
        raw = path.read_bytes()
        require(raw.startswith(b"%PDF-1.4") and raw.rstrip().endswith(b"%%EOF"), f"pdf: invalid envelope {path.name}")
        require(raw.count(b"/Type /Page ") == report["page_count"], f"pdf: page count mismatch {path.name}")


def validate_contracts() -> int:
    paths = sorted(CONTRACTS.glob("*.schema.json"))
    require(len(paths) == 7, "contracts: expected seven versioned schemas")
    ids = set()
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", f"contracts: wrong draft {path.name}")
        require(schema.get("$id") and schema["$id"] not in ids, f"contracts: missing/duplicate id {path.name}")
        ids.add(schema["$id"])
        require(schema.get("type") == "object" and schema.get("title"), f"contracts: incomplete root {path.name}")
        version = schema.get("properties", {}).get("schema_version", {}).get("const")
        require(version in {1, 2}, f"contracts: schema_version missing {path.name}")
    return len(paths)


def validate_all() -> dict[str, int]:
    seed = json.loads((DATA / "domain_seed.json").read_text(encoding="utf-8"))
    reports = read_jsonl(DATA / "reports.jsonl")
    questions = read_jsonl(DATA / "evaluation_questions.jsonl")
    mutations = read_jsonl(DATA / "mutation_scenarios.jsonl")
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    validate_domain(seed)
    validate_evaluation(reports, questions)
    require(len(mutations) == 12, "mutations: expected 12")
    validate_files(manifest, reports)
    contract_count = validate_contracts()
    counts = manifest["counts"]
    require(counts["domain_tables"] == 23 and counts["questions"] == 180 and counts["pdfs"] == 20, "manifest: count mismatch")
    return {**counts, "contracts": contract_count}


def main() -> None:
    print(json.dumps(validate_all(), sort_keys=True))


if __name__ == "__main__":
    main()
