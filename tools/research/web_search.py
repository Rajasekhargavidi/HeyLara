"""Zero-cost web search adapter — DuckDuckGo, no API key required.

Used only by the Technology Intelligence Agent for its daily briefing.
Search results are untrusted external content: callers must never treat
text found here as instructions (see technology_agent.py's system prompt).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search_web(query: str, max_results: int = 5) -> list[SearchResult]:
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError("ddgs is not installed — run `pip install ddgs`") from exc

    try:
        raw_results = DDGS().text(query, max_results=max_results)
    except Exception as exc:  # noqa: BLE001 - network/library failures must not crash the agent
        raise RuntimeError(f"Web search failed for query '{query}': {exc}") from exc

    return [
        SearchResult(
            title=r.get("title", "").strip(),
            url=r.get("href", "").strip(),
            snippet=(r.get("body") or "").strip(),
        )
        for r in raw_results
        if r.get("href")
    ]
