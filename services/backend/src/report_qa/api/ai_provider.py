"""Optional Gemini 2.5 Flash boundary with validated structured output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_LOCAL_ENV_KEYS = {
    "REPORT_QA_AI_MODE", "REPORT_QA_AI_TIMEOUT_SECONDS", "REPORT_QA_AI_RETRIES",
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_API_BASE_URL",
    "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_BASE_URL",
    "SAMBANOVA_API_KEY", "SAMBANOVA_MODEL", "SAMBANOVA_BASE_URL",
    "REPORT_QA_PLANNER_MODE", "REPORT_QA_PLANNER_MODEL",
}


def _load_local_env() -> None:
    """Load local .env values without overriding an explicitly exported env."""
    for parent in Path(__file__).resolve().parents:
        env_path = parent / ".env"
        if not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if match and match.group(1) in _LOCAL_ENV_KEYS and match.group(1) not in os.environ:
                os.environ[match.group(1)] = match.group(2).strip().strip('"').strip("'")
        return


class ProviderError(RuntimeError):
    """Safe, stable error raised at the provider boundary."""

    def __init__(self, code: str, message: str = "AI provider request failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProviderAnswer:
    answer_text: str
    cited_pages: list[int]
    provider: str
    model: str
    response_sha256: str
    structured: dict[str, Any] | None = None


def provider_mode() -> str:
    _load_local_env()
    return os.getenv("REPORT_QA_AI_MODE", "deterministic").strip().lower()


def _json_from_content(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
    if not isinstance(content, str):
        raise ProviderError("AI_INVALID_OUTPUT", "AI output content is not text")
    cleaned = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError("AI_INVALID_OUTPUT", "AI output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderError("AI_INVALID_OUTPUT", "AI output must be a JSON object")
    return value


def _validated_pages(value: Any, allowed_pages: set[int]) -> list[int]:
    if not isinstance(value, list) or any(type(page) is not int for page in value):
        raise ProviderError("AI_INVALID_OUTPUT", "cited_pages must be an integer array")
    pages = list(dict.fromkeys(value))
    if not pages:
        raise ProviderError("AI_INVALID_OUTPUT", "cited_pages must contain at least one page")
    if any(page not in allowed_pages for page in pages):
        raise ProviderError("AI_UNGROUNDED_CITATION", "AI cited a page outside the server context")
    return pages


def validate_answer(payload: dict[str, Any], allowed_pages: set[int], *, provider: str, model: str, raw_response: str) -> ProviderAnswer:
    """Backward-compatible validator for the original two-field fixture."""
    answer_text = payload.get("answer_text")
    if not isinstance(answer_text, str) or not answer_text.strip() or len(answer_text) > 12000:
        raise ProviderError("AI_INVALID_OUTPUT", "answer_text must be a non-empty bounded string")
    return ProviderAnswer(answer_text=answer_text.strip(), cited_pages=_validated_pages(payload.get("cited_pages"), allowed_pages), provider=provider, model=model, response_sha256=hashlib.sha256(raw_response.encode("utf-8")).hexdigest())


GEMINI_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "answer": {"type": "STRING"}, "summary": {"type": "STRING"},
        "sections": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "heading": {"type": "STRING"}, "points": {"type": "ARRAY", "items": {"type": "STRING"}}, "evidence_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        }, "required": ["heading", "points", "evidence_pages"]}},
        "formulas": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name": {"type": "STRING"}, "expression": {"type": "STRING"}, "substitution": {"type": "STRING"}, "result": {"type": "STRING"}, "unit": {"type": "STRING"}, "evidence_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        }, "required": ["name", "expression", "substitution", "result", "unit", "evidence_pages"]}},
        "tables": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "title": {"type": "STRING"}, "columns": {"type": "ARRAY", "items": {"type": "STRING"}}, "rows": {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}}, "evidence_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        }, "required": ["title", "columns", "rows", "evidence_pages"]}},
        "claims": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "claim": {"type": "STRING"}, "evidence_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}}, "evidence_quotes": {"type": "ARRAY", "items": {"type": "STRING"}},
        }, "required": ["claim", "evidence_pages", "evidence_quotes"]}},
        "warnings": {"type": "ARRAY", "items": {"type": "STRING"}}, "cited_pages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
    },
    "required": ["answer", "summary", "sections", "formulas", "tables", "claims", "warnings", "cited_pages"],
}


def _lower_schema(value: Any) -> Any:
    """Convert Gemini's enum-style schema types to JSON Schema spellings."""
    if isinstance(value, dict):
        converted = {key: (_lower_schema(item).lower() if key == "type" and isinstance(item, str) else _lower_schema(item)) for key, item in value.items()}
        if converted.get("type") == "object":
            converted["additionalProperties"] = False
        return converted
    if isinstance(value, list):
        return [_lower_schema(item) for item in value]
    return value


OPENROUTER_RESPONSE_SCHEMA: dict[str, Any] = _lower_schema(GEMINI_RESPONSE_SCHEMA)


def _string(value: Any, field: str, *, max_len: int = 12000) -> str:
    if not isinstance(value, str) or len(value) > max_len:
        raise ProviderError("AI_INVALID_OUTPUT", f"{field} must be a bounded string")
    return value.strip()


def _string_list(value: Any, field: str, *, max_items: int = 40) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items or any(not isinstance(item, str) for item in value):
        raise ProviderError("AI_INVALID_OUTPUT", f"{field} must be a string array")
    values = [item.strip() for item in value]
    if any(not item for item in values):
        raise ProviderError("AI_INVALID_OUTPUT", f"{field} must not contain empty strings")
    return values


def _normalized_search_text(value: str) -> str:
    """Normalize PDF/LLM text for conservative quote matching.

    PDF text extraction frequently inserts spaces inside Vietnamese glyphs and
    models vary in punctuation/quote style.  We keep letters, numbers and the
    percent sign, remove formatting punctuation and whitespace, and preserve
    token order.  This does not turn a paraphrase into a citation: the whole
    normalized quote still has to occur contiguously in the cited page.
    """
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(char for char in normalized if char.isalnum() or char == "%")


def _grounding_repair_instruction(error: ProviderError) -> str:
    return (
        "JSON trước đó bị từ chối vì evidence_quotes không phải chuỗi có thể tìm thấy "
        "nguyên văn trong context đã gửi. Hãy tạo lại toàn bộ JSON đúng schema. "
        "Mỗi evidence_quotes phải là đoạn ngắn copy nguyên văn, liên tiếp từ một trang "
        "context sau khi bỏ khoảng trắng và dấu câu; không dịch, không diễn đạt lại, "
        "không ghép các phần ở vị trí khác nhau của bảng. Nếu không tìm được đoạn exact, "
        "bỏ claim đó và ghi lý do trong warnings. Không thay đổi số liệu để làm quote khớp. "
        f"Lỗi kiểm tra: {error}"
    )


def _decimal_tokens(value: str) -> list[Decimal]:
    tokens = re.findall(r"[-+]?\d+(?:[.,]\d+)?", value.replace("%", ""))
    numbers: list[Decimal] = []
    for token in tokens:
        try:
            numbers.append(Decimal(token.replace(",", ".")))
        except InvalidOperation:
            continue
    return numbers


def _verify_growth_formula(formula: dict[str, str]) -> dict[str, str]:
    """Verify the common growth formula without executing model-provided code."""
    expression = formula["expression"].replace("−", "-").replace("×", "*").casefold()
    if "/" not in expression or "-" not in expression or formula["unit"].strip() not in {"%", "％"}:
        return {"status": "unverified", "reason": "unsupported_formula_shape"}
    values = _decimal_tokens(formula["substitution"])
    if len(values) < 2 or values[1] == 0:
        return {"status": "unverified", "reason": "missing_or_zero_denominator"}
    with localcontext() as context:
        context.prec = 34
        exact = (values[0] - values[1]) / values[1] * Decimal("100")
    exact_text = format(exact.normalize(), "f") if exact != exact.to_integral() else format(exact.quantize(Decimal("1")), "f")
    return {"status": "verified", "computed_result": exact_text, "unit": "%", "calculator": "decimal_growth_v1"}


def validate_structured_answer(payload: dict[str, Any], allowed_pages: set[int], *, provider: str, model: str, raw_response: str, page_text_by_page: dict[int, str] | None = None) -> ProviderAnswer:
    """Validate and normalize the presentation contract returned by Gemini."""
    answer = _string(payload.get("answer"), "answer")
    summary = _string(payload.get("summary"), "summary", max_len=4000)
    if not answer:
        raise ProviderError("AI_INVALID_OUTPUT", "answer must not be empty")
    sections: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("sections", [])):
        if not isinstance(item, dict):
            raise ProviderError("AI_INVALID_OUTPUT", f"sections[{index}] must be an object")
        heading = _string(item.get("heading"), f"sections[{index}].heading", max_len=300)
        if not heading:
            raise ProviderError("AI_INVALID_OUTPUT", f"sections[{index}].heading must not be empty")
        sections.append({"heading": heading, "points": _string_list(item.get("points"), f"sections[{index}].points"), "evidence_pages": _validated_pages(item.get("evidence_pages"), allowed_pages)})
    formulas: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("formulas", [])):
        if not isinstance(item, dict):
            raise ProviderError("AI_INVALID_OUTPUT", f"formulas[{index}] must be an object")
        formula = {"name": _string(item.get("name"), f"formulas[{index}].name", max_len=300), "expression": _string(item.get("expression"), f"formulas[{index}].expression", max_len=2000), "substitution": _string(item.get("substitution"), f"formulas[{index}].substitution", max_len=4000), "result": _string(item.get("result"), f"formulas[{index}].result", max_len=1000), "unit": _string(item.get("unit"), f"formulas[{index}].unit", max_len=100), "evidence_pages": _validated_pages(item.get("evidence_pages"), allowed_pages)}
        if any(not formula[field] for field in ("name", "expression", "substitution", "result")):
            raise ProviderError("AI_INVALID_OUTPUT", f"formulas[{index}] required fields must not be empty")
        formula["calculation"] = _verify_growth_formula(formula)
        formulas.append(formula)
    tables: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("tables", [])):
        if not isinstance(item, dict):
            raise ProviderError("AI_INVALID_OUTPUT", f"tables[{index}] must be an object")
        columns = _string_list(item.get("columns"), f"tables[{index}].columns", max_items=30)
        rows = item.get("rows")
        if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, list) or any(not isinstance(cell, str) for cell in row) for row in rows):
            raise ProviderError("AI_INVALID_OUTPUT", f"tables[{index}].rows must be a string matrix")
        tables.append({"title": _string(item.get("title"), f"tables[{index}].title", max_len=300), "columns": columns, "rows": rows, "evidence_pages": _validated_pages(item.get("evidence_pages"), allowed_pages)})
    claims: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("claims", [])):
        if not isinstance(item, dict):
            raise ProviderError("AI_INVALID_OUTPUT", f"claims[{index}] must be an object")
        pages = _validated_pages(item.get("evidence_pages"), allowed_pages)
        quotes = _string_list(item.get("evidence_quotes"), f"claims[{index}].evidence_quotes", max_items=5)
        if not quotes:
            raise ProviderError("AI_INVALID_OUTPUT", f"claims[{index}].evidence_quotes must not be empty")
        if page_text_by_page is not None:
            searchable = " ".join(_normalized_search_text(page_text_by_page.get(page, "")) for page in pages)
            for quote in quotes:
                if _normalized_search_text(quote) not in searchable:
                    raise ProviderError("AI_UNSUPPORTED_EVIDENCE", f"claims[{index}] quote is not present in cited context")
        claim = _string(item.get("claim"), f"claims[{index}].claim", max_len=1200)
        if not claim:
            raise ProviderError("AI_INVALID_OUTPUT", f"claims[{index}].claim must not be empty")
        claims.append({"claim": claim, "evidence_pages": pages, "evidence_quotes": quotes})
    normalized_pages = _validated_pages(payload.get("cited_pages"), allowed_pages)
    warnings = _string_list(payload.get("warnings", []), "warnings")
    if formulas:
        if any(item["calculation"]["status"] != "verified" for item in formulas):
            warnings.append("Một số công thức chỉ được trình bày; calculator deterministic chưa xác minh được dạng biểu thức.")
    normalized = {"answer": answer, "summary": summary, "sections": sections, "formulas": formulas, "tables": tables, "claims": claims, "warnings": list(dict.fromkeys(warnings)), "cited_pages": normalized_pages}
    return ProviderAnswer(answer_text=answer, cited_pages=normalized_pages, provider=provider, model=model, response_sha256=hashlib.sha256(raw_response.encode("utf-8")).hexdigest(), structured=normalized)


def _display_text(structured: dict[str, Any]) -> str:
    lines = [structured["answer"], "", structured["summary"]]
    for section in structured["sections"]:
        lines.extend(["", section["heading"], *[f"- {point}" for point in section["points"]]])
    for formula in structured["formulas"]:
        lines.extend(["", f"{formula['name']}: {formula['expression']}", f"Thay số: {formula['substitution']}", f"Kết quả: {formula['result']} {formula['unit']}".strip()])
    return "\n".join(lines).strip()


class GeminiProvider:
    """Stdlib REST client for Gemini generateContent structured output."""

    def __init__(self) -> None:
        _load_local_env()
        self.base_url = os.getenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout_seconds = float(os.getenv("REPORT_QA_AI_TIMEOUT_SECONDS", "20"))
        self.max_retries = min(2, max(0, int(os.getenv("REPORT_QA_AI_RETRIES", "0"))))
        if not self.api_key:
            raise ProviderError("AI_NOT_CONFIGURED", "GEMINI_API_KEY is not configured")

    def answer(self, question: str, pages: list[dict[str, Any]]) -> ProviderAnswer:
        allowed_pages = {int(page["page"]) for page in pages}
        context = [{"page": int(page["page"]), "text": str(page.get("text", ""))[:12000]} for page in pages]
        system = ("Bạn là trợ lý phân tích báo cáo. Chỉ dùng context được cung cấp. Trả về JSON đúng schema. "
                  "Chia câu trả lời thành sections ngắn, ghi công thức ở expression, phép thay số ở substitution và kết quả ở result. "
                  "Với mỗi claim quan trọng, evidence_quotes phải là đoạn rất ngắn copy nguyên văn, liên tiếp từ đúng context sau khi bỏ khoảng trắng/dấu câu; không dịch, không diễn đạt lại, không ghép các phần khác vị trí. Nếu không có đoạn exact thì bỏ claim và ghi trong warnings. Không tự bịa số liệu; nếu không đủ dữ liệu, nêu trong warnings. cited_pages/evidence_pages chỉ được dùng trang trong context. "
                  "Phép tính chính thức vẫn do calculator của máy chủ thực hiện.")
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": json.dumps({"question": question, "context": context}, ensure_ascii=False)}]}], "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": GEMINI_RESPONSE_SCHEMA}}
        endpoint = f"{self.base_url}/models/{self.model}:generateContent"
        request = Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST", headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        raw_response = ""
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw_response = response.read().decode("utf-8")
                break
            except HTTPError as exc:
                if attempt >= self.max_retries:
                    if exc.code == 404:
                        raise ProviderError("AI_MODEL_UNAVAILABLE", f"Gemini model {self.model} is unavailable (HTTP 404)") from exc
                    if exc.code in {408, 429, 500, 502, 503, 504}:
                        raise ProviderError("AI_PROVIDER_UNAVAILABLE", f"Gemini provider is unavailable (HTTP {exc.code})") from exc
                    raise ProviderError("AI_PROVIDER_HTTP_ERROR", f"Gemini provider rejected the request (HTTP {exc.code})") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError("AI_PROVIDER_UNAVAILABLE", f"Không kết nối được AI provider {self.base_url}; kiểm tra mạng, proxy hoặc API key") from exc
        try:
            envelope = json.loads(raw_response)
            content = envelope["candidates"][0]["content"]["parts"][0]["text"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("AI_INVALID_OUTPUT", "Gemini response envelope is invalid") from exc
        page_text_by_page = {int(page["page"]): str(page.get("text", "")) for page in pages}
        try:
            result = validate_structured_answer(_json_from_content(content), allowed_pages, provider="gemini", model=self.model, raw_response=raw_response, page_text_by_page=page_text_by_page)
        except ProviderError as error:
            # A model can understand a visually ordered table while copying a
            # quote that does not match pypdf's raw reading order. Give it one
            # bounded correction attempt; the same strict validator still
            # guards the corrected response.
            if error.code != "AI_UNSUPPORTED_EVIDENCE" or self.max_retries < 1:
                raise
            repair_body = dict(body)
            repair_body["contents"] = [*body["contents"], {"role": "user", "parts": [{"text": _grounding_repair_instruction(error)}]}]
            repair_request = Request(endpoint, data=json.dumps(repair_body, ensure_ascii=False).encode("utf-8"), method="POST", headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
            try:
                with urlopen(repair_request, timeout=self.timeout_seconds) as response:
                    raw_response = response.read().decode("utf-8")
                repair_envelope = json.loads(raw_response)
                content = repair_envelope["candidates"][0]["content"]["parts"][0]["text"]
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise ProviderError("AI_PROVIDER_UNAVAILABLE", "Gemini correction request failed") from exc
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ProviderError("AI_INVALID_OUTPUT", "Gemini correction response envelope is invalid") from exc
            result = validate_structured_answer(_json_from_content(content), allowed_pages, provider="gemini", model=self.model, raw_response=raw_response, page_text_by_page=page_text_by_page)
        return ProviderAnswer(answer_text=_display_text(result.structured or {}), cited_pages=result.cited_pages, provider=result.provider, model=result.model, response_sha256=result.response_sha256, structured=result.structured)


class OpenRouterProvider:
    """OpenRouter chat-completions adapter using the same validated answer contract."""

    def __init__(self) -> None:
        _load_local_env()
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.model = os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna")
        self.timeout_seconds = float(os.getenv("REPORT_QA_AI_TIMEOUT_SECONDS", "20"))
        self.max_retries = min(2, max(0, int(os.getenv("REPORT_QA_AI_RETRIES", "0"))))
        if not self.api_key:
            raise ProviderError("AI_NOT_CONFIGURED", "OPENROUTER_API_KEY is not configured")

    def answer(self, question: str, pages: list[dict[str, Any]]) -> ProviderAnswer:
        allowed_pages = {int(page["page"]) for page in pages}
        context = [{"page": int(page["page"]), "text": str(page.get("text", ""))[:12000]} for page in pages]
        system = ("Bạn là trợ lý phân tích báo cáo. Chỉ dùng context được cung cấp. Trả về JSON đúng schema report_answer. "
                  "Chia câu trả lời thành sections, ghi công thức ở expression, phép thay số ở substitution và kết quả ở result. "
                  "Với mỗi claim quan trọng, evidence_quotes phải là đoạn rất ngắn copy nguyên văn, liên tiếp từ đúng context sau khi bỏ khoảng trắng/dấu câu; không dịch, không diễn đạt lại, không ghép các phần khác vị trí. Nếu không có đoạn exact thì bỏ claim và ghi trong warnings. Không bịa số liệu; nếu thiếu dữ liệu ghi warnings. cited_pages/evidence_pages chỉ được dùng trang trong context. "
                  "Các trường công thức chỉ là trình bày; phép tính authoritative do máy chủ thực hiện.")
        body = {
            "model": self.model, "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": {"name": "report_answer", "strict": True, "schema": OPENROUTER_RESPONSE_SCHEMA}},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"question": question, "context": context}, ensure_ascii=False)}],
        }
        endpoint = f"{self.base_url}/chat/completions"
        request = Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://127.0.0.1:4173", "X-Title": "SourceLens"})
        raw_response = ""
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw_response = response.read().decode("utf-8")
                break
            except HTTPError as exc:
                if attempt >= self.max_retries:
                    if exc.code in {408, 429, 500, 502, 503, 504}:
                        raise ProviderError("AI_PROVIDER_UNAVAILABLE", f"OpenRouter provider is unavailable (HTTP {exc.code})") from exc
                    if exc.code == 404:
                        raise ProviderError("AI_MODEL_UNAVAILABLE", f"OpenRouter model {self.model} is unavailable (HTTP 404)") from exc
                    raise ProviderError("AI_PROVIDER_HTTP_ERROR", f"OpenRouter rejected the request (HTTP {exc.code})") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError("AI_PROVIDER_UNAVAILABLE", f"Không kết nối được AI provider {self.base_url}; kiểm tra mạng, proxy hoặc API key") from exc
        try:
            envelope = json.loads(raw_response)
            content = envelope["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("AI_INVALID_OUTPUT", "OpenRouter response envelope is invalid") from exc
        page_text_by_page = {int(page["page"]): str(page.get("text", "")) for page in pages}
        try:
            result = validate_structured_answer(_json_from_content(content), allowed_pages, provider="openrouter", model=self.model, raw_response=raw_response, page_text_by_page=page_text_by_page)
        except ProviderError as error:
            if error.code != "AI_UNSUPPORTED_EVIDENCE" or self.max_retries < 1:
                raise
            repair_body = dict(body)
            repair_body["messages"] = [*body["messages"], {"role": "user", "content": _grounding_repair_instruction(error)}]
            repair_request = Request(endpoint, data=json.dumps(repair_body, ensure_ascii=False).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://127.0.0.1:4173", "X-Title": "SourceLens"})
            try:
                with urlopen(repair_request, timeout=self.timeout_seconds) as response:
                    raw_response = response.read().decode("utf-8")
                repair_envelope = json.loads(raw_response)
                content = repair_envelope["choices"][0]["message"]["content"]
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise ProviderError("AI_PROVIDER_UNAVAILABLE", "OpenRouter correction request failed") from exc
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ProviderError("AI_INVALID_OUTPUT", "OpenRouter correction response envelope is invalid") from exc
            result = validate_structured_answer(_json_from_content(content), allowed_pages, provider="openrouter", model=self.model, raw_response=raw_response, page_text_by_page=page_text_by_page)
        return ProviderAnswer(answer_text=_display_text(result.structured or {}), cited_pages=result.cited_pages, provider=result.provider, model=result.model, response_sha256=result.response_sha256, structured=result.structured)


def live_provider() -> GeminiProvider | OpenRouterProvider | None:
    if provider_mode() == "gemini":
        return GeminiProvider()
    if provider_mode() == "openrouter":
        return OpenRouterProvider()
    return None


PLANNER_PROVIDERS = {
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1", "OPENROUTER_MODEL", "openai/gpt-6-luna"),
    "sambanova": ("SAMBANOVA_API_KEY", "SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1", "SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta", "GEMINI_MODEL", "gemini-2.5-flash"),
}


def planner_mode() -> str:
    """AI is the default planner whenever a key is configured. 'rules' only when no key exists or it is asked for."""
    _load_local_env()
    explicit = os.getenv("REPORT_QA_PLANNER_MODE", "").strip().lower()
    if explicit:
        return explicit
    ai_mode = provider_mode()
    if ai_mode in PLANNER_PROVIDERS and os.getenv(PLANNER_PROVIDERS[ai_mode][0]):
        return ai_mode
    return next((name for name, spec in PLANNER_PROVIDERS.items() if os.getenv(spec[0])), "rules")


class PlannerChatClient:
    """OpenAI-compatible chat completions for the question planner. OpenRouter, SambaNova and Gemini all speak it."""

    def __init__(self, mode: str) -> None:
        _load_local_env()
        if mode not in PLANNER_PROVIDERS:
            raise ProviderError("AI_NOT_CONFIGURED", f"planner mode {mode!r} is not supported")
        key_name, base_name, base_default, model_name, model_default = PLANNER_PROVIDERS[mode]
        self.mode = mode
        self.api_key = os.getenv(key_name, "")
        base = os.getenv(base_name, base_default).rstrip("/")
        self.base_url = f"{base}/openai" if mode == "gemini" and not base.endswith("/openai") else base
        self.model = os.getenv("REPORT_QA_PLANNER_MODEL") or os.getenv(model_name, model_default)
        self.timeout_seconds = float(os.getenv("REPORT_QA_AI_TIMEOUT_SECONDS", "20"))
        self.max_retries = min(2, max(0, int(os.getenv("REPORT_QA_AI_RETRIES", "1"))))
        if not self.api_key:
            raise ProviderError("AI_NOT_CONFIGURED", f"{key_name} is not configured")

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.mode == "openrouter":
            headers.update({"HTTP-Referer": "http://127.0.0.1:4173", "X-Title": "SourceLens"})
        request = Request(f"{self.base_url}/chat/completions", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST", headers=headers)
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    envelope = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                retryable = exc.code in {408, 429, 500, 502, 503, 504}
                if attempt >= self.max_retries or not retryable:
                    code = "AI_PROVIDER_UNAVAILABLE" if retryable else ("AI_MODEL_UNAVAILABLE" if exc.code == 404 else "AI_PROVIDER_HTTP_ERROR")
                    raise ProviderError(code, f"{self.mode} planner request failed (HTTP {exc.code})") from exc
                time.sleep(min(8.0, 2.0 * (attempt + 1)))
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError("AI_PROVIDER_UNAVAILABLE", f"{self.mode} planner is unreachable") from exc
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("AI_INVALID_OUTPUT", f"{self.mode} planner response envelope is invalid") from exc
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        if not isinstance(content, str):
            raise ProviderError("AI_INVALID_OUTPUT", "planner output is not text")
        return content


def planner_client() -> PlannerChatClient | None:
    mode = planner_mode()
    if mode in {"rules", "deterministic", "off", "none"}:
        return None
    try:
        return PlannerChatClient(mode)
    except ProviderError:
        return None


__all__ = ["PLANNER_PROVIDERS", "PlannerChatClient", "planner_client", "planner_mode", "GEMINI_RESPONSE_SCHEMA", "OPENROUTER_RESPONSE_SCHEMA", "GeminiProvider", "OpenRouterProvider", "ProviderAnswer", "ProviderError", "_json_from_content", "live_provider", "provider_mode", "validate_answer", "validate_structured_answer"]
