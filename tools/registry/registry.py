"""Tool Registry.

Agents never call external systems directly. They call named tools through
this registry, which enforces an allow-list, timeouts, and audit logging.
This is deliberately simple in Phase 1 (in-memory, synchronous); permission
checks against real user roles and DB-backed audit storage land in a later
phase.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("jarvis.tools")

DEFAULT_TIMEOUT_SECONDS = 10


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    requires_approval: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.audit_log: list[dict] = []
        # Optional callback set by the app at startup to persist audit
        # entries to the database. Kept optional so tests/CLI usage don't
        # need a DB session wired up.
        self.audit_sink: Callable[[dict], None] | None = None

    def register(self, name: str, fn: Callable[..., Any], requires_approval: bool = False) -> None:
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = ToolSpec(name=name, fn=fn, requires_approval=requires_approval)

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def requires_approval(self, name: str) -> bool:
        spec = self._tools.get(name)
        return bool(spec and spec.requires_approval)

    def call(self, name: str, actor: str, **kwargs: Any) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(ok=False, error=f"Tool '{name}' is not on the allow-list")

        start = time.monotonic()
        try:
            output = spec.fn(**kwargs)
            duration_ms = (time.monotonic() - start) * 1000
            self._audit(actor, name, kwargs, ok=True, duration_ms=duration_ms)
            return ToolResult(ok=True, output=output, duration_ms=duration_ms)
        except Exception as exc:  # noqa: BLE001 - surfaced to caller, not swallowed
            duration_ms = (time.monotonic() - start) * 1000
            self._audit(actor, name, kwargs, ok=False, duration_ms=duration_ms, error=str(exc))
            return ToolResult(ok=False, error=str(exc), duration_ms=duration_ms)

    def _audit(self, actor: str, tool: str, args: dict, ok: bool, duration_ms: float, error: str | None = None) -> None:
        entry = {
            "actor": actor,
            "tool": tool,
            "args": {k: str(v) for k, v in args.items()},
            "ok": ok,
            "duration_ms": round(duration_ms, 2),
            "error": error,
        }
        self.audit_log.append(entry)
        logger.info("tool_call %s", entry)
        if self.audit_sink is not None:
            try:
                self.audit_sink(entry)
            except Exception:  # noqa: BLE001 - audit persistence must never break the tool call
                logger.exception("audit_sink failed for tool_call %s", entry)


# Process-wide singleton registry used by agents in Phase 1.
registry = ToolRegistry()
