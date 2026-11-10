"""Write one work file per store so a model can answer every prompt, and convert its replies into a recording."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qunderstand.evidence import load_store
from qunderstand.parsers.llm import SYSTEM_PROMPT, user_message
from qunderstand.pipeline import Session
from qunderstand.providers import prompt_key

ROOT = Path(__file__).resolve().parent.parent


def export(cases: Path, datasets: Path, batch: Path):
    batch.mkdir(parents=True, exist_ok=True)
    work: dict[str, dict] = {}
    for line in cases.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        store_name = case["store"]
        store = load_store(datasets / f"{store_name}.json")
        turns = case["history"] + [case["question"]]
        for index, question in enumerate(turns):
            history = turns[:index]
            session = Session(history=[{"question": q, "request": {"xem": "câu trả lời của bạn ở lượt này"}} for q in history])
            key = prompt_key(user_message(question, store, session))
            bucket = work.setdefault(store_name, {"catalog": user_message("", store, None).split("\n\nCÂU HỎI", 1)[0], "items": {}})
            bucket["items"][key] = {"key": key, "history": history, "question": question}
    for name, bucket in work.items():
        (batch / f"{name}.json").write_text(json.dumps({"catalog": bucket["catalog"], "items": list(bucket["items"].values())}, ensure_ascii=False, indent=1), encoding="utf-8")
    (batch / "SYSTEM_PROMPT.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    print({k: len(v["items"]) for k, v in work.items()})


if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if base:
        export(base / "cases.jsonl", base / "datasets", base / "batches")
    else:
        export(ROOT / "eval" / "cases.jsonl", ROOT / "datasets", ROOT / "eval" / "batches")
