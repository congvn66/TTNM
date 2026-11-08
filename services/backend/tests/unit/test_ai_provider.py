from __future__ import annotations

import sys
import unittest
import json
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from report_qa.api.ai_provider import GeminiProvider, OpenRouterProvider, ProviderError, _json_from_content, validate_answer, validate_structured_answer


class AIProviderContractTests(unittest.TestCase):
    def test_valid_structured_answer_is_bounded_to_allowed_pages(self) -> None:
        result = validate_answer(
            {"answer_text": "Doanh thu tăng.", "cited_pages": [2, 2]},
            {2, 3},
            provider="fake",
            model="fixture",
            raw_response='{"answer_text":"Doanh thu tăng.","cited_pages":[2,2]}',
        )
        self.assertEqual(result.cited_pages, [2])
        self.assertEqual(result.provider, "fake")

    def test_unknown_page_is_rejected_as_ungrounded(self) -> None:
        with self.assertRaisesRegex(ProviderError, "outside the server context"):
            validate_answer(
                {"answer_text": "Không rõ.", "cited_pages": [9]},
                {2},
                provider="fake",
                model="fixture",
                raw_response="{}",
            )

    def test_fenced_json_is_supported_but_non_json_is_rejected(self) -> None:
        self.assertEqual(_json_from_content("```json\n{\"answer_text\":\"ok\"}\n```"), {"answer_text": "ok"})
        with self.assertRaisesRegex(ProviderError, "valid JSON"):
            _json_from_content("not json")

    def test_structured_answer_preserves_sections_formula_and_tables(self) -> None:
        payload = {
            "answer": "Doanh thu tăng",
            "summary": "Tăng so với kỳ trước.",
            "sections": [{"heading": "Kết luận", "points": ["Tăng rõ rệt"], "evidence_pages": [2]}],
            "formulas": [{"name": "Tăng trưởng", "expression": "(mới-cũ)/cũ", "substitution": "120/100", "result": "20", "unit": "%", "evidence_pages": [2]}],
            "tables": [{"title": "So sánh", "columns": ["Kỳ", "Giá trị"], "rows": [["Q1", "120"]], "evidence_pages": [2]}],
            "warnings": [],
            "claims": [], "cited_pages": [2, 2],
        }
        result = validate_structured_answer(payload, {2, 3}, provider="gemini", model="gemini-2.5-flash", raw_response="raw")
        self.assertEqual(result.cited_pages, [2])
        self.assertEqual(result.structured["formulas"][0]["result"], "20")
        self.assertEqual(result.structured["formulas"][0]["calculation"], {"status": "verified", "computed_result": "20", "unit": "%", "calculator": "decimal_growth_v1"})
        self.assertEqual(result.structured["tables"][0]["rows"][0][1], "120")

    def test_structured_answer_rejects_evidence_outside_context(self) -> None:
        payload = {"answer": "x", "summary": "y", "sections": [{"heading": "h", "points": [], "evidence_pages": [9]}], "formulas": [], "tables": [], "claims": [], "warnings": [], "cited_pages": [2]}
        with self.assertRaisesRegex(ProviderError, "outside the server context"):
            validate_structured_answer(payload, {2}, provider="gemini", model="gemini-2.5-flash", raw_response="raw")

    def test_claim_quotes_must_be_present_in_selected_context(self) -> None:
        payload = {
            "answer": "Bookings tăng.", "summary": "Có căn cứ.", "sections": [],
            "formulas": [], "tables": [],
            "claims": [{"claim": "Bookings tăng 48%.", "evidence_pages": [3], "evidence_quotes": ["Tổng bookings tăng 48% YoY"]}],
            "warnings": [], "cited_pages": [3],
        }
        result = validate_structured_answer(
            payload, {3}, provider="openrouter", model="openai/gpt-6-luna", raw_response="raw",
            page_text_by_page={3: "Kết quả: Tổng bookings tăng 48% YoY trong kỳ."},
        )
        self.assertEqual(result.structured["claims"][0]["evidence_pages"], [3])
        payload["claims"][0]["evidence_quotes"] = ["Bookings tăng 99%"]
        with self.assertRaisesRegex(ProviderError, "not present in cited context"):
            validate_structured_answer(
                payload, {3}, provider="openrouter", model="openai/gpt-6-luna", raw_response="raw",
                page_text_by_page={3: "Kết quả: Tổng bookings tăng 48% YoY trong kỳ."},
            )

    def test_claim_quote_matching_tolerates_pdf_spacing_and_punctuation(self) -> None:
        payload = {
            "answer": "Bookings tăng.", "summary": "Có căn cứ.", "sections": [],
            "formulas": [], "tables": [],
            "claims": [{"claim": "Bookings tăng 48%.", "evidence_pages": [3], "evidence_quotes": ["Tổng bookings tăng 48%!!!"]}],
            "warnings": [], "cited_pages": [3],
        }
        result = validate_structured_answer(
            payload, {3}, provider="openrouter", model="openai/gpt-6-luna", raw_response="raw",
            page_text_by_page={3: "T ổng bookings tăng 48 % YoY trong kỳ."},
        )
        self.assertEqual(result.structured["claims"][0]["evidence_quotes"], ["Tổng bookings tăng 48%!!!"])

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "openai/gpt-6-luna", "REPORT_QA_AI_RETRIES": "1"}, clear=False)
    @patch("report_qa.api.ai_provider.urlopen")
    def test_openrouter_retries_once_after_unsupported_quote(self, mocked_urlopen) -> None:
        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        invalid = {"answer": "x", "summary": "s", "sections": [], "formulas": [], "tables": [], "claims": [{"claim": "Bookings tăng.", "evidence_pages": [2], "evidence_quotes": ["Không có trong trang"]}], "warnings": [], "cited_pages": [2]}
        valid = {"answer": "x", "summary": "s", "sections": [], "formulas": [], "tables": [], "claims": [{"claim": "Bookings tăng.", "evidence_pages": [2], "evidence_quotes": ["Bookings tăng 48%"]}], "warnings": [], "cited_pages": [2]}
        mocked_urlopen.side_effect = [
            FakeResponse({"choices": [{"message": {"content": json.dumps(invalid, ensure_ascii=False)}}]}),
            FakeResponse({"choices": [{"message": {"content": json.dumps(valid, ensure_ascii=False)}}]}),
        ]
        result = OpenRouterProvider().answer("Bookings?", [{"page": 2, "text": "Bookings tăng 48% trong kỳ."}])
        self.assertEqual(result.structured["claims"][0]["evidence_quotes"], ["Bookings tăng 48%"])
        self.assertEqual(mocked_urlopen.call_count, 2)
        repair_body = json.loads(mocked_urlopen.call_args_list[1].args[0].data)
        self.assertIn("evidence_quotes", repair_body["messages"][-1]["content"])

    def test_unsupported_formula_is_marked_unverified_not_executed(self) -> None:
        payload = {
            "answer": "x", "summary": "y", "sections": [],
            "formulas": [{"name": "Tỷ lệ", "expression": "x / y", "substitution": "10/2", "result": "5", "unit": "điểm", "evidence_pages": [2]}],
            "tables": [], "claims": [], "warnings": [], "cited_pages": [2],
        }
        result = validate_structured_answer(payload, {2}, provider="fake", model="fixture", raw_response="raw")
        self.assertEqual(result.structured["formulas"][0]["calculation"]["status"], "unverified")
        self.assertTrue(any("chỉ được trình bày" in warning for warning in result.structured["warnings"]))

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-2.5-flash"}, clear=False)
    @patch("report_qa.api.ai_provider.urlopen")
    def test_gemini_envelope_is_parsed_and_request_is_structured(self, mocked_urlopen) -> None:
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self):
                return b'{"candidates":[{"content":{"parts":[{"text":"{\\"answer\\":\\"ok\\",\\"summary\\":\\"s\\",\\"sections\\":[],\\"formulas\\":[],\\"tables\\":[],\\"warnings\\":[],\\"cited_pages\\":[2]}"}]}}]}'
        mocked_urlopen.return_value = FakeResponse()
        result = GeminiProvider().answer("Doanh thu?", [{"page": 2, "text": "Doanh thu"}])
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent")
        self.assertEqual(request.headers["X-goog-api-key"], "test-key")
        self.assertEqual(json.loads(request.data)["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(result.structured["answer"], "ok")

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "openai/gpt-6-luna"}, clear=False)
    @patch("report_qa.api.ai_provider.urlopen")
    def test_openrouter_envelope_uses_requested_model_and_schema(self, mocked_urlopen) -> None:
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"answer\\":\\"ok\\",\\"summary\\":\\"s\\",\\"sections\\":[],\\"formulas\\":[],\\"tables\\":[],\\"warnings\\":[],\\"cited_pages\\":[2]}"}}]}'
        mocked_urlopen.return_value = FakeResponse()
        result = OpenRouterProvider().answer("Doanh thu?", [{"page": 2, "text": "Doanh thu"}])
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/chat/completions")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "openai/gpt-6-luna")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertFalse(body["response_format"]["json_schema"]["schema"]["additionalProperties"])
        self.assertEqual(result.provider, "openrouter")
