"""Run the question set through a parser and score the outcomes.

The key measure is silent wrong: the system answers with confidence and the number is wrong.
A refusal or a question back costs the user a little time. A silent wrong number can reach a report.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from .cli import make_parser
from .evidence import load_store
from .pipeline import Session, ask, choose_option
from .units import convert, parse_unit

ROOT = Path(__file__).resolve().parent.parent


def check_options(store, question: str, session: Session, expect: dict) -> tuple[str, str]:
    """A question back is correct only if its options lead to the numbers the user could mean."""
    wanted = list(expect["option_values"])
    tolerance = max(expect.get("tol", 0), 0.05)
    pending = list(session.pending_options)
    got = []
    for index in range(len(pending)):
        session.pending_options = pending
        got.append(choose_option(store, question, index, session)["computed_result"].get("value"))
    for value in wanted:
        match = next((g for g in got if g is not None and abs(g - value) <= tolerance), None)
        if match is None:
            return "wrong_status", f"options give {got}, expected {wanted}"
        got.remove(match)
    return "pass", ""


def check(record: dict, expect: dict) -> tuple[str, str]:
    """Return (outcome, detail). outcome: pass, silent_wrong, wrong_status."""
    result = record["computed_result"]
    status = result["status"]
    if status not in expect["status"]:
        if status == "ok":
            return "silent_wrong", f"answered, expected {expect['status']}: {record['answer_text'][:120]}"
        return "wrong_status", f"got {status}, expected {expect['status']}"
    if status != "ok":
        return "pass", ""
    if "value" in expect:
        value = result.get("value")
        tolerance = expect.get("tol", 0.0001)
        if value is not None and expect.get("value_unit"):
            source, wanted = parse_unit(result.get("unit")), parse_unit(expect["value_unit"])
            if source.compatible(wanted):
                value = float(convert(Decimal(str(value)), source, wanted))
        allowed = [expect["value"]] + list(expect.get("also", []))
        if value is None or all(abs(value - item) > tolerance for item in allowed):
            return "silent_wrong", f"value {value}, expected {expect['value']}"
    if "leader" in expect:
        ranking = result.get("ranking") or []
        leaders = [f"{r.get('label', '')} {r.get('period', '')}" for r in ranking if r.get("rank") == 1]
        if not any(expect["leader"].lower() in l.lower() for l in leaders):
            return "silent_wrong", f"leader {leaders}, expected {expect['leader']}"
    for text in expect.get("contains") or []:
        if text.lower() not in record["answer_text"].lower():
            return "silent_wrong", f"answer has no {text!r}: {record['answer_text'][:120]}"
    return "pass", ""


def run(parser_spec: str, cases_path: Path, *, only_group: str | None = None, datasets: Path | None = None, use_guards: bool = True) -> dict:
    parser = make_parser(parser_spec)
    datasets = datasets or ROOT / "datasets"
    stores = {}
    rows = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        if only_group and case["group"] != only_group:
            continue
        store = stores.setdefault(case["store"], load_store(datasets / f"{case['store']}.json"))
        session = Session()
        for earlier in case["history"]:
            ask(store, earlier, parser, session, use_guards=use_guards)
        record = ask(store, case["question"], parser, session, use_guards=use_guards)
        outcome, detail = check(record, case["expect"])
        if outcome == "pass" and record["computed_result"]["status"] == "needs_clarification" and case["expect"].get("option_values"):
            outcome, detail = check_options(store, case["question"], session, case["expect"])
        rows.append({"id": case["id"], "group": case["group"], "store": case["store"], "question": case["question"], "outcome": outcome, "detail": detail,
                     "status": record["computed_result"]["status"], "value": record["computed_result"].get("value"), "answer": record["answer_text"]})
    return {"parser": parser.name, "rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        groups[row["group"]][row["outcome"]] += 1
        groups["all"][row["outcome"]] += 1
    return {name: dict(counter) for name, counter in groups.items()}


def main(argv=None) -> int:
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument("--parser", default="rules")
    args_parser.add_argument("--cases", default=str(ROOT / "eval" / "cases.jsonl"))
    args_parser.add_argument("--group")
    args_parser.add_argument("--datasets")
    args_parser.add_argument("--no-guards", action="store_true", help="switch off the program's ambiguity rules, to measure what they add")
    args_parser.add_argument("--out")
    args_parser.add_argument("-v", "--verbose", action="store_true")
    args = args_parser.parse_args(argv)
    report = run(args.parser, Path(args.cases), only_group=args.group, datasets=Path(args.datasets) if args.datasets else None, use_guards=not args.no_guards)
    for name, counter in sorted(report["summary"].items()):
        total = sum(counter.values())
        print(f"{name:12} pass {counter.get('pass', 0):>3}/{total:<3}  silent_wrong {counter.get('silent_wrong', 0):>2}  wrong_status {counter.get('wrong_status', 0):>2}")
    if args.verbose:
        for row in report["rows"]:
            if row["outcome"] != "pass":
                print(f"\n[{row['outcome']}] {row['id']}: {row['question']}\n   {row['detail']}")
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
