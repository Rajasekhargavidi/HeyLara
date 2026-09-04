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
        except error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url} (model={self.model}). "
                f"Is `ollama serve` running and is the model pulled? Underlying error: {exc}"
            ) from exc

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        data = self._post("/api/generate", payload)
        return data.get("response", "")

    def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> GenerateResult:
        payload = {"model": self.model, "messages": messages, "tools": tools, "stream": False}
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

    Embeddings always go through OllamaProvider regardless of this class —
    Groq doesn't offer an embeddings endpoint, and even if it did, mixing
    embedding spaces would silently break similarity search against
    anything already ingested into the knowledge base under Ollama's
    embedding model.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60.0) -> None:
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.timeout = timeout
        self._embed_provider = OllamaProvider()
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set — get a free key at https://console.groq.com/keys")

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        req = request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # Groq's Cloudflare front-end blocks the default Python
                # urllib User-Agent as a bot signature (error 1010) —
                # a normal-looking UA is required, not optional.
                "User-Agent": "Mozilla/5.0 (compatible; JARVIS/1.0; +https://laravisionx.com)",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except error.HTTPError as exc:
            raise RuntimeError(f"Groq API error {exc.code}: {exc.read().decode(errors='replace')}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach Groq API: {exc}") from exc

    def generate(self, prompt: str, system: str | None = None) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        data = self._post({"model": self.model, "messages": messages})
        return data["choices"][0]["message"].get("content", "")

    def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> GenerateResult:
        data = self._post({"model": self.model, "messages": messages, "tools": tools})
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
