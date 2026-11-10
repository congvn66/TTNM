"""Score every question set with every parser and write eval/results.json."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qunderstand.evaluate import run

ROOT = Path(__file__).resolve().parent.parent
SETS = {"own": (ROOT / "eval" / "cases.jsonl", ROOT / "datasets", ROOT / "eval" / "recorded"),
        "independent_1": (ROOT / "eval" / "holdout" / "cases.jsonl", ROOT / "eval" / "holdout" / "datasets", ROOT / "eval" / "holdout" / "recorded"),
        "independent_2": (ROOT / "eval" / "holdout2" / "cases.jsonl", ROOT / "eval" / "holdout2" / "datasets", ROOT / "eval" / "holdout2" / "recorded")}


def main():
    report = {}
    for name, (cases, datasets, recorded) in SETS.items():
        for parser, spec in (("haiku", f"recorded:{recorded}/haiku.jsonl"), ("sonnet", f"recorded:{recorded}/sonnet.jsonl"), ("rules", "rules")):
            for guards in (True, False):
                result = run(spec, cases, datasets=datasets, use_guards=guards)
                total = result["summary"]["all"]
                row = {"cases": sum(total.values()), "pass": total.get("pass", 0), "silent_wrong": total.get("silent_wrong", 0), "safe_miss": total.get("wrong_status", 0)}
                report[f"{name}|{parser}|{'guards' if guards else 'no_guards'}"] = {**row, "silent_ids": [r["id"] for r in result["rows"] if r["outcome"] == "silent_wrong"],
                                                                                   "miss_ids": [r["id"] for r in result["rows"] if r["outcome"] == "wrong_status"] if guards else []}
                print(f"{name:14} {parser:7} {'guards' if guards else 'no guards':9} pass {row['pass']:>3}/{row['cases']:<3} silent_wrong {row['silent_wrong']:>2} safe_miss {row['safe_miss']:>2} {report[f'{name}|{parser}|' + ('guards' if guards else 'no_guards')]['silent_ids'] or ''}")
    (ROOT / "eval" / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
