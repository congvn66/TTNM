"""Merge one model's reply files into one recording. Later lines with the same key replace earlier ones."""

import json
import sys
from pathlib import Path


def merge(folder: Path, out: Path) -> int:
    seen = {}
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                seen[row["key"]] = row["reply"]
    out.write_text("".join(json.dumps({"key": k, "reply": v}, ensure_ascii=False) + "\n" for k, v in seen.items()), encoding="utf-8")
    return len(seen)


if __name__ == "__main__":
    for base in sys.argv[1:]:
        for folder in sorted(p for p in Path(base).iterdir() if p.is_dir()):
            print(folder, merge(folder, Path(base) / f"{folder.name}.jsonl"))
