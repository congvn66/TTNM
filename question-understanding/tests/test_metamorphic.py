"""Change the data under every answered question and check that the system reacts the way it must."""

import copy
import json
from pathlib import Path

import pytest

from qunderstand.evidence import store_from_dict
from qunderstand.parsers.llm import LLMParser
from qunderstand.pipeline import Session, ask
from qunderstand.providers import RecordedProvider
from qunderstand.recompute import recompute

ROOT = Path(__file__).resolve().parent.parent
SETS = [(ROOT / "eval" / "cases.jsonl", ROOT / "datasets", ROOT / "eval" / "recorded" / "sonnet.jsonl"),
        (ROOT / "eval" / "holdout" / "cases.jsonl", ROOT / "eval" / "holdout" / "datasets", ROOT / "eval" / "holdout" / "recorded" / "sonnet.jsonl"),
        (ROOT / "eval" / "holdout2" / "cases.jsonl", ROOT / "eval" / "holdout2" / "datasets", ROOT / "eval" / "holdout2" / "recorded" / "sonnet.jsonl")]


def _answered():
    found = []
    for cases, datasets, recording in SETS:
        parser = LLMParser(RecordedProvider(recording))
        for line in cases.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            data = json.loads((datasets / f"{case['store']}.json").read_text(encoding="utf-8"))
            store = store_from_dict(data)
            session = Session()
            for earlier in case["history"]:
                ask(store, earlier, parser, session)
            history = copy.deepcopy(session.history)
            record = ask(store, case["question"], parser, session)
            if record["computed_result"]["status"] == "ok" and record["computed_result"]["value"] is not None:
                found.append((case, data, parser, history, record))
    return found


ANSWERED = _answered()


def _mutated(data, code, **fields):
    clone = copy.deepcopy(data)
    for row in clone["evidences"]:
        if row["evidence_code"] == code:
            row.update(fields)
    return store_from_dict(clone)


def _ask_again(case, store, parser):
    session = Session()
    for earlier in case["history"]:
        ask(store, earlier, parser, session)
    return ask(store, case["question"], parser, session)


def test_the_set_is_large_enough():
    assert len(ANSWERED) > 100


@pytest.mark.parametrize("field,value,status", [("data_status", "missing", "missing_data"), ("data_status", "error", "extraction_error")])
def test_a_bad_input_never_gives_a_number(field, value, status):
    checked = 0
    for case, data, parser, _history, record in ANSWERED:
        if record["operation_name"] == "rank_group":
            continue
        for row in record["computed_result"]["inputs"]:
            if row["value"] is None:
                continue
            twin = [e for e in data["evidences"] if e["series_name"] == row["series_name"] and e["time_period"] == row["time_period"]]
            if len(twin) > 1:
                continue
            store = _mutated(data, row["evidence_code"], current_value=None, **{field: value})
            again = _ask_again(case, store, parser)
            assert again["computed_result"]["value"] is None, (case["id"], row["evidence_code"], again["answer_text"])
            checked += 1
    assert checked > 100


def test_a_corrected_number_gives_the_same_result_as_asking_again():
    checked = 0
    for case, data, parser, _history, record in ANSWERED:
        for row in record["computed_result"]["inputs"]:
            if row["value"] is None:
                continue
            new_value = row["value"] * 2 + 7
            store = _mutated(data, row["evidence_code"], current_value=new_value, verification_status="edited")
            again = _ask_again(case, store, parser)
            redone = recompute(record, store)
            if again["computed_result"]["status"] != "ok":
                continue
            assert redone["computed_result"]["value"] == pytest.approx(again["computed_result"]["value"]), (case["id"], row["evidence_code"])
            has_zero = any(item["value"] == 0 for item in record["computed_result"]["inputs"])
            assert again["computed_result"]["value"] != record["computed_result"]["value"] or record["operation_name"] == "rank_group" or has_zero, (case["id"], row["evidence_code"])
            checked += 1
    assert checked > 100
