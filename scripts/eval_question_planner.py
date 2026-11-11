"""Run every question of the question-understanding test sets through planner -> resolver -> calculator.

The test sets live in the `ducanh` branch (folder question-understanding). Each store is turned into
document-evidence-v2 style evidences with clean semantics, so this measures the planner and the
calculator, not the PDF reading.

    python scripts/eval_question_planner.py --qu-root ../question-understanding --model meta-llama/llama-3.1-8b-instruct --budget 0.08

Outcomes: pass; silent_wrong (a number came out and it is wrong, or a number came out where none should);
safe_miss (no number, but a number or a different stop was expected);
text_path (a plain lookup the app sends to text retrieval and the answer writer, as api/main.py does; not scored here).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "backend" / "src"))

from report_qa.application.p0_pipeline import execute_calculation, resolve_evidence  # noqa: E402
from report_qa.application.question_planner import build_catalog, plan_question  # noqa: E402
from report_qa.domain.contracts import validate_question_plan_v2  # noqa: E402

UNIT_CODES = {"triệu đồng": "VND_MILLION", "tỷ đồng": "VND_BILLION", "nghìn đồng": "VND_THOUSAND", "đồng": "VND", "%": "PERCENT", "triệu USD": "USD_MILLION", "USD": "USD"}
SOURCES = {"table_cell": "table", "text_paragraph": "text", "chart_bar": "chart", "chart_line": "chart"}
SETS = [("own", "eval/cases.jsonl", "datasets"), ("independent_1", "eval/holdout/cases.jsonl", "eval/holdout/datasets"), ("independent_2", "eval/holdout2/cases.jsonl", "eval/holdout2/datasets")]


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c)).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "unknown"


def period_label(text: str) -> str | None:
    text = (text or "").strip()
    match = re.fullmatch(r"Quý\s*([1-4])\s*/\s*(\d{4})", text, flags=re.IGNORECASE)
    return f"Q{match.group(1)}/{match.group(2)}" if match else (text or None)


def to_extraction(store: dict) -> tuple[dict, dict]:
    evidences, labels = [], {}
    for raw in store["evidences"]:
        if raw.get("source_type") == "text_paragraph" and raw.get("current_value") is None:
            continue
        head, _, tail = (raw.get("series_name") or "").strip().partition(" - ")
        unit = (raw.get("unit") or "").strip() or None
        code = UNIT_CODES.get(unit, unit)
        labels[code] = unit
        value = raw.get("current_value")
        evidences.append({
            "evidence_key": raw["evidence_code"], "current_revision_id": f"evr:{raw['evidence_code']}", "source_type": SOURCES.get(raw["source_type"], "table"),
            "page_number": raw["location"]["page"], "bbox": [0.1, 0.1, 0.2, 0.2], "raw_text": None if value is None else str(value),
            "numeric_value": None if value is None else format(Decimal(str(value)), "f"), "data_status": raw["data_status"], "method_label": raw["extraction_method"],
            "semantic": {"measure": slug(head), "subject": tail or None, "period": {"label": period_label(raw.get("time_period"))}, "unit": code, "dimensions": {}},
            "table_locator": {"column_header": head, "row_header": tail or None},
        })
    return {"evidence_batch": {"evidences": evidences}, "evidence_contexts": {}}, labels


class MeteredClient:
    """OpenRouter chat call that adds up the real cost of every request and refuses to go over budget."""

    def __init__(self, model: str, budget: float, api_key: str) -> None:
        self.model, self.budget, self.api_key = model, budget, api_key
        self.spent, self.calls, self.lock = 0.0, 0, threading.Lock()

    def complete(self, system: str, user: str) -> str:
        with self.lock:
            if self.spent >= self.budget:
                raise RuntimeError("budget reached")
        body = {"model": self.model, "temperature": 0, "usage": {"include": True}, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        request = Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body, ensure_ascii=False).encode(), method="POST",
                          headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "X-Title": "SourceLens planner eval"})
        for attempt in range(4):
            try:
                with urlopen(request, timeout=60) as response:
                    envelope = json.loads(response.read().decode())
                break
            except HTTPError as exc:
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
            except (URLError, TimeoutError, OSError):
                if attempt == 3:
                    raise
                time.sleep(3)
        with self.lock:
            self.calls += 1
            self.spent += float((envelope.get("usage") or {}).get("cost") or 0)
        return envelope["choices"][0]["message"]["content"] or ""


def _key(system: str, user: str) -> str:
    import hashlib
    return hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:20]


class RecordingClient:
    def __init__(self, inner, path: str) -> None:
        self.inner, self.path, self.lock = inner, Path(path), threading.Lock()

    def complete(self, system: str, user: str) -> str:
        reply = self.inner.complete(system, user)
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": _key(system, user), "reply": reply}, ensure_ascii=False) + "\n")
        return reply

    @property
    def calls(self):
        return self.inner.calls

    @property
    def spent(self):
        return self.inner.spent


class ReplayClient:
    spent, calls = 0.0, 0

    def __init__(self, path: str) -> None:
        self.replies = {json.loads(line)["key"]: json.loads(line)["reply"] for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()}

    def complete(self, system: str, user: str) -> str:
        key = _key(system, user)
        if key not in self.replies:
            raise RuntimeError("no recorded reply")
        return self.replies[key]


def close(value: float, expected: float, tol: float) -> bool:
    return abs(value - expected) <= max(tol, 1e-9)


def run_case(case: dict, stores: dict, complete, model_name: str) -> dict:
    extraction, labels = stores[case["store"]]
    catalog = build_catalog(extraction)
    history, prior = [], None
    plan, planner, fallback = None, "", None
    for question in case["history"] + [case["question"]]:
        result = plan_question(question, case["store"], catalog=catalog, history=history, prior_clarification_plan=prior, complete=complete, model_name=model_name)
        plan = validate_question_plan_v2(result.plan)
        planner, fallback = result.planner, result.fallback_code
        history.append({"question": question, "plan": plan})
        prior = plan if plan["status"] == "needs_clarification" else None
    value, unit, calc_status = None, None, None
    operation = (plan.get("operation") or {}).get("type")
    # Same gate as api/main.py: a plain lookup without a known measure and period goes to text retrieval, not to the calculator.
    to_calculator = plan["status"] == "ready" and (operation != "lookup" or any(f["measure"] != "unknown" and f["period"] for f in plan["facts"]))
    if plan["status"] == "ready" and not to_calculator:
        calc_status = "text_path"
    if to_calculator:
        resolution = resolve_evidence(plan, extraction, set(range(1, 200)))
        calc = execute_calculation(plan, resolution)
        calc_status = calc["status"]
        if calc["status"] == "succeeded" and calc["value"] is not None:
            value, unit = float(calc["value"]), calc.get("unit")
    expect = case["expect"]
    outcome = "pass"
    if calc_status == "text_path":
        return {"id": case["id"], "question": case["question"], "outcome": "text_path", "plan_status": plan["status"], "operation": operation, "calc_status": calc_status,
                "value": None, "expected": expect, "planner": planner, "fallback": fallback}
    if value is not None:
        wanted = [expect["value"], *expect.get("also", [])] if "value" in expect and "ok" in expect["status"] else []
        tol = expect.get("tol", 0.01)
        scaled = [value]
        if expect.get("value_unit") and unit:
            scaled += [value * 1000, value / 1000]
        if not wanted or not any(close(v, w, tol) for v in scaled for w in wanted):
            outcome = "silent_wrong"
    else:
        stopped = "needs_clarification" if plan["status"] == "needs_clarification" else "no_number"
        if "ok" in expect["status"] and set(expect["status"]) == {"ok"}:
            outcome = "safe_miss"
        elif "needs_clarification" in expect["status"] and stopped != "needs_clarification" and not (set(expect["status"]) - {"needs_clarification", "ok"}):
            outcome = "safe_miss"
        elif stopped == "needs_clarification" and "needs_clarification" not in expect["status"] and not ({"source_conflict"} & set(expect["status"])):
            outcome = "pass"
    return {"id": case["id"], "question": case["question"], "outcome": outcome, "plan_status": plan["status"], "operation": (plan.get("operation") or {}).get("type"),
            "calc_status": calc_status, "value": value, "expected": expect, "planner": planner, "fallback": fallback}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qu-root", required=True, help="folder question-understanding from branch ducanh")
    parser.add_argument("--model", default="rules", help="OpenRouter model id, or rules")
    parser.add_argument("--budget", type=float, default=0.08, help="stop after this many USD")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--record", help="append every model reply here (JSONL), so a run can be replayed for free")
    parser.add_argument("--replay", help="answer from a --record file instead of calling the model")
    args = parser.parse_args()
    qu = Path(args.qu_root)
    client = None
    if args.model != "rules" and not args.replay:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise SystemExit("set OPENROUTER_API_KEY")
        client = MeteredClient(args.model, args.budget, key)
    if args.replay:
        client = ReplayClient(args.replay)
    elif client and args.record:
        client = RecordingClient(client, args.record)
    only = set(args.only.split(",")) if args.only else None
    jobs = []
    for set_name, cases_path, datasets in SETS:
        stores = {}
        for line in (qu / cases_path).read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            if "ok" in case["expect"]["status"] and "value" not in case["expect"]:
                continue
            if only and case["id"] not in only:
                continue
            if case["store"] not in stores:
                stores[case["store"]] = to_extraction(json.loads((qu / datasets / f"{case['store']}.json").read_text(encoding="utf-8")))
            jobs.append((set_name, case, stores))
    started = time.time()
    done = []

    def one(job):
        row = {"set": job[0], **run_case(job[1], job[2], client.complete if client else None, args.model)}
        done.append(row)
        cost = f" ${client.spent:.4f}" if client else ""
        print(f"[{len(done)}/{len(jobs)}{cost}] {row['outcome']:12} {row['id']:14} {row['planner'][:14]:14} {row['question'][:70]}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, jobs))
    summary: dict[str, dict] = {}
    for row in rows:
        for name in (row["set"], "all"):
            bucket = summary.setdefault(name, {"cases": 0, "pass": 0, "silent_wrong": 0, "safe_miss": 0, "text_path": 0, "ai_used": 0})
            bucket["cases"] += 1
            bucket[row["outcome"]] += 1
            bucket["ai_used"] += row["planner"].startswith("ai")
    for name, bucket in summary.items():
        print(f"{args.model:42} {name:14} pass {bucket['pass']:>3}/{bucket['cases']:<3} silent_wrong {bucket['silent_wrong']:>2} safe_miss {bucket['safe_miss']:>3} text_path {bucket['text_path']:>3} ai_used {bucket['ai_used']}")
    if client:
        print(f"cost ${client.spent:.4f} for {client.calls} calls in {time.time() - started:.0f}s")
    for row in rows:
        if row["outcome"] == "silent_wrong":
            print(f"  SILENT {row['id']}: {row['question'][:80]} -> {row['operation']} {row['value']} (expected {row['expected'].get('value', row['expected']['status'])})")
    if args.out:
        Path(args.out).write_text(json.dumps({"model": args.model, "summary": summary, "rows": rows, "cost": client.spent if client else 0}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
