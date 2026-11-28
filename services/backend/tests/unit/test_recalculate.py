import pytest

from report_qa.api.document_assistant_flow import recalculate


def row(key, value, region="Miền Bắc", status="valid"):
    return {"evidence_key": key, "numeric_value": value, "data_status": status, "page_number": 1, "bbox": [0.1, 0.1, 0.2, 0.12],
            "table_locator": {"row_header": region, "column_header": "Doanh thu · Quý 2/2026"}}


BY_KEY = {"north": row("north", "21350"), "south": row("south", "17420", "Miền Nam"), "total": row("total", "49880", "Tổng"), "blank": row("blank", None, status="missing")}
SHARE = {"expression": "a = value('north')\nb = value(\"total\")\nresult = round(a / b * 100, 2)", "substitution": "Tỷ trọng"}


def test_runs_the_stored_script_again_with_one_cell_swapped() -> None:
    out = recalculate(SHARE, BY_KEY, {"north": "south"})
    assert out["status"] == "succeeded"
    assert out["formula"]["result"] == "34.92"
    assert [item["evidence_key"] for item in out["formula"]["inputs"]] == ["south", "total"]
    # The formula shown is the script as it ran.
    assert "value('south')" in out["formula"]["expression"]


def test_swaps_a_cell_read_through_a_list_or_with_spaces() -> None:
    script = {"expression": "keys = ['north', 'total']\nresult = sum(value(k) for k in keys) + value( 'south' )"}
    out = recalculate(script, BY_KEY, {"north": "south", "south": "north"})
    assert out["formula"]["result"] == str(17420 + 49880 + 21350)


def test_no_swap_gives_the_same_result_on_todays_numbers() -> None:
    assert recalculate(SHARE, BY_KEY, {})["formula"]["result"] == "42.80"


def test_rejects_a_swap_of_a_cell_the_script_does_not_read_or_an_unknown_cell() -> None:
    # The script reads north, so "north" is used, but "south" itself is never read: nothing was swapped.
    with pytest.raises(ValueError, match="FORMULA_SWAP_INVALID"):
        recalculate(SHARE, BY_KEY, {"south": "north"})
    with pytest.raises(ValueError, match="FORMULA_SWAP_INVALID"):
        recalculate(SHARE, BY_KEY, {"north": "nowhere"})


def test_a_formula_without_cells_cannot_be_recalculated() -> None:
    with pytest.raises(ValueError, match="FORMULA_NOT_RECALCULABLE"):
        recalculate({"expression": "result = 1 + 1"}, BY_KEY, {})


def test_a_swap_to_a_cell_without_a_number_fails_without_raising() -> None:
    out = recalculate(SHARE, BY_KEY, {"north": "blank"})
    assert out["status"] == "failed"
    assert "blank" in out["error"]


def test_a_swap_whose_read_failed_and_was_caught_is_not_a_swap() -> None:
    script = {"expression": "try:\n    x = value('north')\nexcept:\n    x = value('south')\nresult = x + value('total')"}
    with pytest.raises(ValueError, match="FORMULA_SWAP_INVALID"):
        recalculate(script, BY_KEY, {"north": "blank"})
