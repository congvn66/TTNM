"""Question Planner contract tests. No network: the AI is a fake that returns fixed replies."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from report_qa.application.question_planner import CatalogEntry, PlannerError, build_catalog, plan_from_model_output, plan_question, user_message
from report_qa.domain.contracts import validate_question_plan_v2

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = Draft202012Validator(json.loads((ROOT / "contracts" / "question-plan-v2.schema.json").read_text(encoding="utf-8")))

CATALOG = [
    CatalogEntry("doanh_thu", "Tập đoàn", "Q1/2025", "VND_BILLION", "Doanh thu thuần", "table"),
    CatalogEntry("doanh_thu", "Tập đoàn", "Q1/2026", "VND_BILLION", "Doanh thu thuần", "table"),
    CatalogEntry("doanh_thu", "Tập đoàn", "Q2/2026", "VND_BILLION", "Doanh thu thuần", "table"),
    CatalogEntry("bien_loi_nhuan_gop", "Tập đoàn", "Q1/2025", "PERCENT", "Biên lợi nhuận gộp", "table"),
    CatalogEntry("bien_loi_nhuan_gop", "Tập đoàn", "Q1/2026", "PERCENT", "Biên lợi nhuận gộp", "table"),
    CatalogEntry("loi_nhuan", "Tập đoàn", "Q1/2026", "VND_BILLION", "Lợi nhuận gộp", "table"),
    CatalogEntry("loi_nhuan", "Tập đoàn", "Q1/2026", "VND_BILLION", "Lợi nhuận sau thuế", "table"),
]


def fact(key, measure="doanh_thu", period="Q1/2026", unit="VND_BILLION", subject="Tập đoàn"):
    return {"key": key, "measure": measure, "subject": subject, "period": period, "unit": unit}


def fake(reply):
    calls = []

    def complete(system, user):
        calls.append((system, user))
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)

    complete.calls = calls
    return complete


def plan(question, reply, **kwargs):
    result = plan_question(question, "docv-1", catalog=kwargs.pop("catalog", CATALOG), complete=fake(reply), model_name="fake", **kwargs)
    assert not list(SCHEMA.iter_errors(result.plan)), list(SCHEMA.iter_errors(result.plan))
    validate_question_plan_v2(result.plan)
    return result


GROWTH = {"status": "ready", "operation": "growth_rate", "facts": [fact("current"), fact("baseline", period="Q1/2025")]}


# --- the 10 acceptance tests of doc/HANDOUT/duc-anh-question-planning.md section 8 ---

def test_1_lookup_has_period_and_subject():
    result = plan("Doanh thu thuần của Tập đoàn Q1/2026 là bao nhiêu?", {"status": "ready", "operation": "lookup", "facts": [fact("value")]})
    assert result.planner == "ai:fake"
    assert result.plan["operation"] == {"type": "lookup", "formula_id": "identity_v1", "operand_fact_keys": ["value"], "result_unit": "VND_BILLION"}
    assert result.plan["facts"][0]["period"] == "Q1/2026" and result.plan["facts"][0]["subject"] == "Tập đoàn"


def test_2_sum_of_facts_with_one_unit():
    reply = {"status": "ready", "operation": "sum", "facts": [fact("item_1"), fact("item_2", period="Q2/2026")]}
    result = plan("Tổng doanh thu Q1/2026 và Q2/2026 là bao nhiêu?", reply)
    assert result.plan["operation"]["formula_id"] == "sum_v1" and result.plan["operation"]["operand_fact_keys"] == ["item_1", "item_2"]


def test_3_difference_keeps_operand_order():
    reply = {"status": "ready", "operation": "difference", "facts": [fact("b", period="Q1/2025"), fact("a")]}
    result = plan("Chênh lệch doanh thu giữa Q1/2026 và Q1/2025 là bao nhiêu tỷ?", reply)
    assert result.plan["operation"]["operand_fact_keys"] == ["a", "b"]
    assert [f["period"] for f in result.plan["facts"]] == ["Q1/2026", "Q1/2025"]


def test_4_growth_rate_has_current_and_baseline():
    result = plan("Doanh thu Q1/2026 tăng bao nhiêu phần trăm so với Q1/2025?", GROWTH)
    assert result.plan["operation"] == {"type": "growth_rate", "formula_id": "growth_rate_v1", "operand_fact_keys": ["current", "baseline"], "result_unit": "PERCENT"}
    assert result.plan["facts"][1]["period"] == "Q1/2025"


def test_5_growth_rate_is_not_percentage_point_change():
    points = {"status": "ready", "operation": "percentage_point_change",
              "facts": [fact("current", "bien_loi_nhuan_gop", unit="PERCENT"), fact("baseline", "bien_loi_nhuan_gop", "Q1/2025", "PERCENT")]}
    assert plan("Biên lợi nhuận gộp Q1/2026 tăng bao nhiêu điểm phần trăm so với Q1/2025?", points).plan["operation"]["formula_id"] == "percentage_point_change_v1"
    relative = {**points, "operation": "growth_rate"}
    asked = plan("Biên lợi nhuận gộp Q1/2026 tăng bao nhiêu % so với Q1/2025?", relative).plan
    assert asked["status"] == "needs_clarification" and asked["clarification"]["reason_code"] == "AMBIGUOUS_OPERATION"


@pytest.mark.parametrize("question,reply,reason", [
    ("Doanh thu Q1/2026 tăng bao nhiêu so với Q1/2025?", GROWTH, "AMBIGUOUS_OPERATION"),
    ("Doanh thu quý 1 là bao nhiêu?", {"status": "ready", "operation": "lookup", "facts": [fact("value", period=None)]}, "AMBIGUOUS_PERIOD"),
    ("Lợi nhuận Q1/2026 là bao nhiêu?", {"status": "ready", "operation": "lookup", "facts": [fact("value", "loi_nhuan")]}, "AMBIGUOUS_MEASURE"),
    ("Doanh thu của công ty con Q1/2026?", {"status": "needs_clarification", "reason_code": "AMBIGUOUS_SUBJECT", "question": "Bạn hỏi công ty con nào?", "options": ["Công ty A", "Công ty B"]}, "AMBIGUOUS_SUBJECT"),
])
def test_6_ambiguity_asks_back_even_when_the_model_picks_one_meaning(question, reply, reason):
    result = plan(question, reply)
    assert result.plan["status"] == "needs_clarification" and result.plan["operation"] is None
    assert result.plan["clarification"]["reason_code"] == reason and len(result.plan["clarification"]["options"]) >= 2


def test_7_follow_up_without_context_does_not_invent_a_period():
    reply = {"status": "ready", "operation": "lookup", "facts": [fact("value", period="Q2/2026")]}
    result = plan("Còn quý trước thì sao?", reply)
    assert result.plan["status"] == "needs_clarification" and result.plan["clarification"]["reason_code"] == "MISSING_CONTEXT"


def test_8_no_chart_when_text_or_table_has_the_fact():
    assert plan("Doanh thu Q1/2026 tăng bao nhiêu phần trăm so với Q1/2025?", GROWTH).plan["source_strategy"]["chart_fact_keys"] == []


def test_9_only_the_unmatched_fact_may_need_a_chart():
    reply = {"status": "ready", "operation": "growth_rate", "facts": [fact("current", period="Q3/2026"), fact("baseline", period="Q1/2025")]}
    strategy = plan("Doanh thu Q3/2026 tăng bao nhiêu phần trăm so với Q1/2025?", reply).plan["source_strategy"]
    assert strategy == {"priority": ["table", "text", "chart"], "chart_policy": "only_if_required_fact_unresolved", "chart_fact_keys": ["current"]}


@pytest.mark.parametrize("reply", [
    {"status": "ready", "operation": "growth_rate", "facts": [fact("current")]},
    {"status": "ready", "operation": "growth_rate", "facts": [fact("x"), fact("y")]},
    {"status": "ready", "operation": "average", "facts": [fact("value")]},
    {"status": "ready", "operation": "lookup", "facts": []},
    {"status": "needs_clarification", "question": "?", "options": ["chỉ một"]},
    {"status": "maybe"},
    "đây không phải JSON",
])
def test_10_bad_model_output_is_rejected_and_rules_take_over(reply):
    with pytest.raises(PlannerError):
        from report_qa.application.question_planner import extract_json
        plan_from_model_output(extract_json(reply if isinstance(reply, str) else json.dumps(reply)), "q", "docv-1", CATALOG)
    result = plan("Doanh thu Q1/2026 tăng bao nhiêu phần trăm so với Q1/2025?", reply)
    assert result.planner == "rules" and result.fallback_code == "PLANNER_INVALID_OUTPUT"


# --- behaviour around the model ---

def test_the_model_never_sees_a_value():
    extraction = {"evidence_batch": {"evidences": [{"evidence_key": "e1", "data_status": "valid", "numeric_value": "1250.50", "raw_text": "1,250.50", "source_type": "table",
                                                    "semantic": {"measure": "doanh_thu", "subject": "Q1", "period": None, "unit": None},
                                                    "table_locator": {"row_header": "Q1", "column_header": "Doanh thu"}}]}}
    catalog = build_catalog(extraction)
    message = user_message("Doanh thu Q1?", catalog, [])
    assert "1250" not in message and "1,250" not in message and "Doanh thu / Q1" in message


def test_a_provider_failure_falls_back_to_rules():
    def broken(system, user):
        raise TimeoutError("slow")

    result = plan_question("By what percent did revenue change from Q1/2025 to Q1/2026?", "docv-1", catalog=CATALOG, complete=broken)
    assert result.planner == "rules" and result.fallback_code == "PLANNER_PROVIDER_FAILED"
    assert result.plan["operation"]["formula_id"] == "growth_rate_v1"


def test_no_client_uses_rules_and_rules_still_ask_back():
    result = plan_question("How much did revenue increase from Q1/2025 to Q1/2026?", "docv-1", catalog=CATALOG)
    assert result.planner == "rules" and result.plan["status"] == "needs_clarification"


def test_choosing_an_option_does_not_ask_the_same_question_again():
    first = plan("Doanh thu Q1/2026 tăng bao nhiêu so với Q1/2025?", GROWTH).plan
    second = plan("Tỷ lệ tăng phần trăm", GROWTH, prior_clarification_plan=first,
                  history=[{"question": "Doanh thu Q1/2026 tăng bao nhiêu so với Q1/2025?", "plan": first}]).plan
    assert second["status"] == "ready" and second["operation"]["formula_id"] == "growth_rate_v1"
    assert second["original_question"].startswith("Doanh thu Q1/2026 tăng bao nhiêu so với Q1/2025?")


def test_history_reaches_the_model_and_follow_up_is_planned():
    first = plan("Doanh thu Q1/2026 là bao nhiêu?", {"status": "ready", "operation": "lookup", "facts": [fact("value")]}).plan
    complete = fake({"status": "ready", "operation": "lookup", "facts": [fact("value", period="Q2/2026")]})
    result = plan_question("Còn Q2/2026 thì sao?", "docv-1", catalog=CATALOG, history=[{"question": "Doanh thu Q1/2026 là bao nhiêu?", "plan": first}], complete=complete)
    assert result.plan["facts"][0]["period"] == "Q2/2026"
    assert "Doanh thu Q1/2026 là bao nhiêu?" in complete.calls[0][1]


def test_unsupported_question_has_no_operation():
    result = plan("Dự báo doanh thu năm 2027?", {"status": "unsupported", "reason": "dự báo"})
    assert result.plan["status"] == "unsupported" and result.plan["operation"] is None and result.plan["facts"] == []


def test_named_percent_overrides_an_absolute_pick():
    reply = {"status": "ready", "operation": "absolute_change", "facts": [fact("current"), fact("baseline", period="Q1/2025")]}
    result = plan("Doanh thu Q1/2026 tăng bao nhiêu phần trăm so với Q1/2025?", reply)
    assert result.plan["operation"]["formula_id"] == "growth_rate_v1" and "percent_named" in result.rules_applied


def test_model_reply_in_a_code_fence_is_read():
    result = plan("Doanh thu Q1/2026 là bao nhiêu?", "```json\n" + json.dumps({"status": "ready", "operation": "lookup", "facts": [fact("value")]}) + "\n```")
    assert result.planner == "ai:fake"


def test_text_labels_hide_every_number_but_keep_period_names():
    extraction = {"evidence_contexts": {"e1": "Revenue Q1/2025 was 100. Revenue Q1/2026 was 120, up 20% to 1,250.5 tỷ"},
                  "evidence_batch": {"evidences": [{"evidence_key": "e1", "data_status": "valid", "numeric_value": "120", "raw_text": "120", "source_type": "text",
                                                    "semantic": {"measure": "doanh_thu", "subject": None, "period": {"label": "Q1/2026"}, "unit": None}}]}}
    label = build_catalog(extraction)[0].label
    assert "Q1/2025" in label and "Q1/2026" in label
    assert not any(number in label for number in ("100", "120", "20%", "1,250"))
