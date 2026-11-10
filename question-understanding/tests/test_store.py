import copy
import json
from pathlib import Path

import pytest

from qunderstand.evidence import StoreError, load_store, store_from_dict

ROOT = Path(__file__).resolve().parent.parent
GOOD = {"evidence_code": "EVD_A", "source_type": "table_cell", "extraction_method": "direct_label", "location": {"page": 1, "bbox": [0, 0, 1, 1]}, "series_name": "Doanh thu - A",
        "time_period": "Quý 1", "unit": "triệu đồng", "raw_value": 5, "current_value": 5, "text_content": None, "data_status": "valid", "verification_status": "unverified"}


def build(**changes):
    item = copy.deepcopy(GOOD)
    item.update(changes)
    return {"document_code": "D", "evidences": [item]}


@pytest.mark.parametrize("name", ["S1", "S2", "R1", "R2", "VNG", "design_example", "edge"])
def test_all_datasets_load(name):
    assert load_store(ROOT / "datasets" / f"{name}.json").items


def test_good_item():
    assert store_from_dict(build()).items[0].current_value == 5


@pytest.mark.parametrize("change,message", [({"data_status": "ok"}, "data_status"), ({"source_type": "image"}, "source_type"), ({"current_value": "1,250"}, "two numbers"), ({"current_value": "abc"}, "not a number"),
                                            ({"data_status": "missing"}, "Use null"), ({"current_value": None}, "current_value is null"), ({"location": {"bbox": []}}, "location.page"), ({"location": {"page": 0}}, "location.page"),
                                            ({"evidence_code": ""}, "evidence_code")])
def test_bad_items_are_reported(change, message):
    with pytest.raises(StoreError, match=message):
        store_from_dict(build(**change))


def test_duplicate_code_and_unknown_revision():
    data = build()
    data["evidences"].append(copy.deepcopy(data["evidences"][0]))
    with pytest.raises(StoreError, match="duplicate"):
        store_from_dict(data)
    with pytest.raises(StoreError, match="revises"):
        store_from_dict(build(location={"page": 1, "meta": {"revises": "EVD_NOPE"}}))


def test_every_problem_is_listed_once():
    data = {"document_code": "D", "evidences": [dict(GOOD, evidence_code="A", data_status="x"), dict(GOOD, evidence_code="B", source_type="y")]}
    with pytest.raises(StoreError, match="2 problem"):
        store_from_dict(data)


def test_missing_top_level_and_bad_json(tmp_path):
    with pytest.raises(StoreError):
        store_from_dict({"evidences": []})
    path = tmp_path / "x.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(StoreError, match="not valid JSON"):
        load_store(path)


def test_catalog_never_contains_values():
    for name in ("S1", "R1"):
        store = load_store(ROOT / "datasets" / f"{name}.json")
        for row in store.catalog():
            assert set(row) == {"series", "period", "unit", "kind"}
        text = json.dumps(store.catalog(), ensure_ascii=False)
        assert "21350" not in text and "55159" not in text


def test_one_series_written_many_ways_becomes_one_name():
    def row(code, name):
        return {"evidence_code": code, "source_type": "table_cell", "extraction_method": "direct_label", "location": {"page": 1, "bbox": [], "meta": {}}, "series_name": name,
                "time_period": "Q1/2026", "unit": "tỷ đồng", "raw_value": 1, "current_value": 1, "text_content": None, "data_status": "valid", "verification_status": "unverified"}
    store = store_from_dict({"document_code": "D", "evidences": [row("A", "DOANH THU THUẦN "), row("B", "Doanh thu  thuần"), row("C", "Doanh thu thuan")]})
    assert store.series_names() == ["Doanh thu thuần"]
