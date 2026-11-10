"""Model backends. The standard library only, so the CLI has no install step."""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    pass


def _post(url: str, payload: dict, headers: dict, timeout: float, attempts: int = 3, opener=urllib.request.urlopen) -> dict:
    body = json.dumps(payload).encode()
    delay = 1.0
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
        try:
            with opener(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUS or attempt == attempts - 1:
                # The body can echo request data, so only the status is reported.
                raise ProviderError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise ProviderError(f"network error: {type(exc).__name__}") from None
        time.sleep(delay)
        delay *= 2
    raise ProviderError("no response")


class GeminiProvider:
    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None, timeout: float = 60):
        self.model, self.timeout = model, timeout
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise ProviderError("set GEMINI_API_KEY")
        self.name = f"gemini/{model}"

    def complete(self, system: str, user: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {"system_instruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        data = _post(url, payload, {"x-goog-api-key": self.api_key}, self.timeout)
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError("unexpected Gemini response") from exc


class OpenAICompatibleProvider:
    """OpenAI, Azure AI, DeepSeek and others that follow the chat completions format."""

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None, timeout: float = 60):
        self.model, self.timeout = model, timeout
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError("set OPENAI_API_KEY")
        self.name = f"openai-compatible/{model}"

    def complete(self, system: str, user: str) -> str:
        payload = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        data = _post(f"{self.base_url}/chat/completions", payload, {"Authorization": f"Bearer {self.api_key}"}, self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError("unexpected response") from exc


class AnthropicProvider:
    def __init__(self, model: str = "claude-haiku-5-5", api_key: str | None = None, timeout: float = 60):
        self.model, self.timeout = model, timeout
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ProviderError("set ANTHROPIC_API_KEY")
        self.name = f"anthropic/{model}"

    def complete(self, system: str, user: str) -> str:
        payload = {"model": self.model, "max_tokens": 1500, "system": system, "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = _post("https://api.anthropic.com/v1/messages", payload, headers, self.timeout)
        try:
            return "".join(block.get("text", "") for block in data["content"])
        except (KeyError, TypeError) as exc:
            raise ProviderError("unexpected response") from exc


def prompt_key(user: str) -> str:
    """Key on catalog, earlier questions and the question, so a recording does not depend on how a past request was printed."""
    catalog = user.split("\n\n", 1)[0]
    history = ""
    if "LỊCH SỬ:\n" in user:
        raw = user.split("LỊCH SỬ:\n", 1)[1].split("\n\nCÂU HỎI:", 1)[0]
        history = "|".join(turn["question"] for turn in json.loads(raw))
    question = user.rsplit("<question>", 1)[-1]
    return hashlib.sha256(f"{catalog}\n{history}\n{question}".encode()).hexdigest()[:16]


class RecordedProvider:
    """Replay saved model replies by the hash of the prompt. Tests and evaluation use this to repeat a run exactly."""

    def __init__(self, path: str, name: str = "recorded"):
        with open(path, encoding="utf-8") as handle:
            self.replies = {json.loads(line)["key"]: json.loads(line)["reply"] for line in handle if line.strip()}
        self.name = name
        self.misses = 0

    def complete(self, system: str, user: str) -> str:
        key = prompt_key(user)
        if key not in self.replies:
            self.misses += 1
            raise ProviderError(f"no recorded reply for {key}")
        reply = self.replies[key]
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


def make_provider(spec: str):
    """'gemini', 'gemini:gemini-2.5-pro', 'openai:gpt-5', 'deepseek:deepseek-chat', 'anthropic:claude-haiku-5-5', 'recorded:path'."""
    kind, _, model = spec.partition(":")
    if kind == "gemini":
        return GeminiProvider(model or "gemini-2.5-flash")
    if kind == "openai":
        return OpenAICompatibleProvider(model or "gpt-5-mini")
    if kind == "deepseek":
        return OpenAICompatibleProvider(model or "deepseek-chat", base_url="https://api.deepseek.com/v1", api_key=os.environ.get("DEEPSEEK_API_KEY"))
    if kind == "anthropic":
        return AnthropicProvider(model or "claude-haiku-5-5")
    if kind == "recorded":
        return RecordedProvider(model)
    raise ProviderError(f"unknown provider {kind!r}")
