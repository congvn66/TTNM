"""Command line: ask, chat, recompute, check."""

import argparse
import json
import sys
from pathlib import Path

from .adapters.docling_csv import table_to_evidences
from .evidence import StoreError, load_store, store_from_dict
from .parsers.llm import LLMParser
from .parsers.rules import RuleParser
from .pipeline import Session, ask, choose_option
from .providers import ProviderError, make_provider
from .recompute import recompute


def make_parser(spec: str):
    if spec == "rules":
        return RuleParser()
    return LLMParser(make_provider(spec))


def _print(record: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return
    print(record["answer_text"])
    if record.get("formula_display"):
        print(f"  Công thức: {record['formula_display']}")
    if record.get("scope"):
        print(f"  {record['scope']}")
    clarification = record.get("clarification")
    if clarification:
        for index, option in enumerate(clarification["options"], 1):
            print(f"  {index}. {option['label']}")


def cmd_ask(args) -> int:
    store = load_store(args.store)
    record = ask(store, args.question, make_parser(args.parser), Session())
    _print(record, args.json)
    return 0


def cmd_chat(args) -> int:
    store = load_store(args.store)
    parser, session = make_parser(args.parser), Session()
    print(f"Báo cáo {store.document_code}: {len(store.items)} số liệu. Gõ 'thoat' để dừng.")
    last_question = ""
    while True:
        try:
            line = input("\nHỏi> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in {"thoat", "thoát", "exit", "quit"}:
            return 0
        if not line:
            continue
        if line.isdigit() and session.pending_options:
            index = int(line) - 1
            if 0 <= index < len(session.pending_options):
                _print(choose_option(store, last_question, index, session), args.json)
            else:
                print("Không có lựa chọn này.")
            continue
        last_question = line
        _print(ask(store, line, parser, session), args.json)


def cmd_recompute(args) -> int:
    store = load_store(args.store)
    interaction = json.loads(Path(args.interaction).read_text(encoding="utf-8"))
    print(json.dumps(recompute(interaction, store), ensure_ascii=False, indent=2))
    return 0


def cmd_check(args) -> int:
    store = load_store(args.store)
    print(f"{store.document_code}: {len(store.items)} số liệu hợp lệ, {len(store.series_names())} chỉ tiêu.")
    return 0


def cmd_from_docling(args) -> int:
    units = json.loads(args.units) if args.units else {}
    items = table_to_evidences(Path(args.csv).read_text(encoding="utf-8"), page=args.page, units=units, locale=args.locale)
    data = {"document_code": args.document, "file_name": Path(args.csv).name, "page_count": args.page, "evidences": items}
    store_from_dict(data)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã ghi {len(items)} số liệu vào {args.out}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    root = argparse.ArgumentParser(prog="qunderstand", description="Hỏi đáp có kiểm chứng trên danh sách số liệu của báo cáo")
    sub = root.add_subparsers(dest="command", required=True)
    for name, handler, helptext in (("ask", cmd_ask, "hỏi một câu"), ("chat", cmd_chat, "hội thoại nhiều lượt")):
        command = sub.add_parser(name, help=helptext)
        command.add_argument("--store", required=True, help="file JSON danh sách số liệu")
        command.add_argument("--parser", default="rules", help="rules, gemini[:model], openai[:model], deepseek[:model], anthropic[:model], recorded:path")
        command.add_argument("--json", action="store_true", help="in bản ghi đầy đủ theo data_design.pdf mục 4.2")
        if name == "ask":
            command.add_argument("question")
        command.set_defaults(func=handler)
    command = sub.add_parser("recompute", help="tính lại một câu trả lời đã lưu")
    command.add_argument("--store", required=True)
    command.add_argument("--interaction", required=True)
    command.set_defaults(func=cmd_recompute)
    command = sub.add_parser("check", help="kiểm tra file danh sách số liệu")
    command.add_argument("--store", required=True)
    command.set_defaults(func=cmd_check)
    command = sub.add_parser("from-docling", help="đổi CSV bảng của Docling thành file danh sách số liệu")
    command.add_argument("--csv", required=True)
    command.add_argument("--out", required=True)
    command.add_argument("--document", required=True, help="mã tài liệu")
    command.add_argument("--page", type=int, default=1)
    command.add_argument("--units", help='đơn vị theo cột, ví dụ {"Doanh thu": "triệu đồng"}')
    command.add_argument("--locale", default="en", choices=["en", "vi"], help="en: 1,250.50; vi: 1.250,50")
    command.set_defaults(func=cmd_from_docling)
    args = root.parse_args(argv)
    try:
        return args.func(args)
    except (StoreError, ProviderError, OSError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
