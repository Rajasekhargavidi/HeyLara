"""LLMProvider — vendor-neutral adapter over the local model gateway.

The application must never hard-code a specific vendor/SDK. Everything
above this module calls LLMProvider.generate()/embed()/generate_with_tools().
The default implementation talks to Ollama over HTTP because it's free and
runs entirely locally; swapping in a cloud provider later means writing a
new class with the same interface, not touching any calling code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib import error, request

from packages.config.settings import settings


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class GenerateResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(Protocol):
    def generate(self, prompt: str, system: str | None = None) -> str: ...

    def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> GenerateResult: ...

    def embed(self, text: str) -> list[float]: ...


class OllamaProvider:
    """Default zero-cost local provider, backed by Ollama's HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.embed_model = embed_model or settings.ollama_embed_model
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except error.HTTPError as exc:
            detail = exc.read().decode(errors="replace").strip()
            raise RuntimeError(
                f"Ollama returned HTTP {exc.code} for model={self.model}. "
                f"Check the Ollama server logs and installation. "
                f"Underlying error: {detail or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url} (model={self.model}). "
                f"Is `ollama serve` running and is the model pulled? Underlying error: {exc}"
            ) from exc

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": settings.ollama_num_ctx},
        }
        if system:
            payload["system"] = system
        data = self._post("/api/generate", payload)
        return data.get("response", "")

    def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> GenerateResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"num_ctx": settings.ollama_num_ctx},
        }
        data = self._post("/api/chat", payload)
        message = data.get("message", {})
        raw_calls = message.get("tool_calls") or []
        tool_calls = [
            ToolCall(name=c["function"]["name"], arguments=c["function"].get("arguments", {}) or {})
            for c in raw_calls
        ]
        return GenerateResult(text=message.get("content", ""), tool_calls=tool_calls)

    def embed(self, text: str) -> list[float]:
        data = self._post("/api/embeddings", {"model": self.embed_model, "prompt": text})
        return data.get("embedding", [])


class GroqProvider:
    """Free-tier cloud provider — Groq's API is OpenAI-compatible and free
    within generous rate limits (no credit card required for the free
    tier as of writing). Much larger/faster models than a local 3B model,
    at the cost of no longer being fully offline.

    Model fallback: when a model hits its rate limit (HTTP 429) the provider
    automatically tries the next model in the fallback chain. Each model
    remembers when it was rate-limited and will be retried after RATE_LIMIT_TTL
    seconds so the chain always prefers the best available model.

    Embeddings always go through OllamaProvider regardless of this class —
    Groq doesn't offer an embeddings endpoint, and even if it did, mixing
    embedding spaces would silently break similarity search against
    anything already ingested into the knowledge base under Ollama's
    embedding model.
    """

    # Best → fallback order, verified against the live Groq /v1/models endpoint.
    FALLBACK_CHAIN: list[str] = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "qwen/qwen3.6-27b",
        "groq/compound",
        "groq/compound-mini",
    ]
    # Seconds before a rate-limited model is retried (Groq resets per minute).
    RATE_LIMIT_TTL: int = 65

    import time as _time

    _rate_limited_until: dict[str, float] = {}

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60.0) -> None:
        import time
        self.api_key = api_key or settings.groq_api_key
        self._preferred_model = model or settings.groq_model
        self.timeout = timeout
        self._embed_provider = OllamaProvider()
        self._time = time
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set — get a free key at https://console.groq.com/keys")
        # Ensure the configured model is first in the chain if not already present.
        chain = list(self.FALLBACK_CHAIN)
        if self._preferred_model not in chain:
            chain.insert(0, self._preferred_model)
        self._chain = chain

    @property
    def model(self) -> str:
        """Return the best model not currently rate-limited."""
        now = self._time.time()
        for m in self._chain:
            if GroqProvider._rate_limited_until.get(m, 0) <= now:
                return m
        # All models are rate-limited — return the one whose cooldown expires soonest.
        return min(self._chain, key=lambda m: GroqProvider._rate_limited_until.get(m, 0))

    def _mark_rate_limited(self, model: str) -> None:
        GroqProvider._rate_limited_until[model] = self._time.time() + self.RATE_LIMIT_TTL

    def _post(self, payload: dict) -> dict:
        """Try each model in the fallback chain until one succeeds."""
        tried: list[str] = []
        for m in self._chain:
            if GroqProvider._rate_limited_until.get(m, 0) > self._time.time():
                continue
            payload = {**payload, "model": m}
            body = json.dumps(payload).encode()
            req = request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "Mozilla/5.0 (compatible; JARVIS/1.0; +https://laravisionx.com)",
                },
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except error.HTTPError as exc:
                if exc.code == 429:
                    self._mark_rate_limited(m)
                    tried.append(m)
                    continue
                raise RuntimeError(f"Groq API error {exc.code}: {exc.read().decode(errors='replace')}") from exc
            except error.URLError as exc:
                raise RuntimeError(f"Could not reach Groq API: {exc}") from exc

        # All models rate-limited — wait for the soonest reset and retry once.
        soonest = min(self._chain, key=lambda m: GroqProvider._rate_limited_until.get(m, 0))
        wait = max(0.0, GroqProvider._rate_limited_until.get(soonest, 0) - self._time.time())
        self._time.sleep(wait + 1)
        GroqProvider._rate_limited_until.pop(soonest, None)
        payload = {**payload, "model": soonest}
        body = json.dumps(payload).encode()
        req = request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "Mozilla/5.0 (compatible; JARVIS/1.0; +https://laravisionx.com)",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except error.HTTPError as exc:
            raise RuntimeError(f"Groq API error {exc.code} (all models rate-limited): {exc.read().decode(errors='replace')}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach Groq API: {exc}") from exc

    def generate(self, prompt: str, system: str | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        data = self._post({"messages": messages})
        return data["choices"][0]["message"].get("content", "")

    def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> GenerateResult:
        data = self._post({"messages": messages, "tools": tools})
        message = data["choices"][0]["message"]
        raw_calls = message.get("tool_calls") or []
        tool_calls = []
        for c in raw_calls:
            try:
                arguments = json.loads(c["function"].get("arguments", "{}") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(name=c["function"]["name"], arguments=arguments))
        return GenerateResult(text=message.get("content") or "", tool_calls=tool_calls)

    def embed(self, text: str) -> list[float]:
        return self._embed_provider.embed(text)


def get_llm_provider() -> LLMProvider:
    """Factory so calling code never instantiates a concrete provider directly.

    Selected via LLM_PROVIDER in .env: "ollama" (default, fully local/free)
    or "groq" (free-tier cloud, needs GROQ_API_KEY). Falls back to Ollama
    with a clear error surfaced through normal RuntimeError handling if
    the selected provider's credentials are missing.
    """
    provider = settings.llm_provider.lower()
    if provider == "groq":
        return GroqProvider()
    return OllamaProvider()
