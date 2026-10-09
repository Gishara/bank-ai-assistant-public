"""The tool gateway: the only path from an agent to company data or actions.

For every call it:
  1. checks the authenticated role may use the tool (again, even though the
     model only ever saw tools its role allows),
  2. requires recorded human approval for tools that need it,
  3. validates arguments against the tool's schema (extra fields rejected),
  4. runs the tool with a timeout,
  5. strips instruction-like content from text the tool returns,
  6. writes an audit entry.
Failures come back as a ToolOutcome with ok=False instead of an exception, so
one failing tool degrades an answer rather than crashing the run.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from core import audit
from core.auth import User
from core.config import get_settings
from core.logging import get_logger, log_event
from core.rbac import APPROVAL_REQUIRED, can_use_tool, tools_for
from core.resilience import CircuitOpen, InjectedFault
from security.injection import sanitize_passage
from tools.registry import SPECS

log = get_logger(__name__)


@dataclass
class ToolOutcome:
    name: str
    ok: bool
    data: Any = None
    error: str | None = None
    error_kind: str | None = None  # denied | needs_approval | invalid_args | timeout | unavailable | failed
    duration_ms: int = 0
    sanitized: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"tool": self.name, "ok": self.ok, "error": self.error, "error_kind": self.error_kind,
                "duration_ms": self.duration_ms, "sanitized": self.sanitized}


def _sanitize(value: Any, flagged: list[str]) -> Any:
    if isinstance(value, str):
        cleaned, hits = sanitize_passage(value)
        flagged.extend(hits)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(v, flagged) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v, flagged) for k, v in value.items()}
    return value


def _never_called(**_: Any) -> str:
    raise RuntimeError("Tools are executed by the gateway, not by LangChain")


class ToolGateway:
    def __init__(self, user: User) -> None:
        self.user = user

    def visible_tool_names(self, include_admin: bool = False) -> list[str]:
        names = tools_for(self.user.role)
        return [n for n in names if include_admin or not n.startswith("admin_")]

    def bindable_tools(self, exclude: tuple[str, ...] = ()) -> list[StructuredTool]:
        """Tool schemas for the model: only tools this role may use, never admin tools."""
        return [StructuredTool.from_function(func=_never_called, name=name, description=SPECS[name].description,
                                             args_schema=SPECS[name].args_schema)
                for name in self.visible_tool_names() if name not in exclude]

    async def execute(self, name: str, args: dict | None, *, approved_by: str | None = None) -> ToolOutcome:
        started = time.monotonic()
        args = args or {}
        u = self.user

        def done(outcome: ToolOutcome) -> ToolOutcome:
            outcome.duration_ms = int((time.monotonic() - started) * 1000)
            audit.record(u.user_id, u.role.value, f"tool:{name}", "ok" if outcome.ok else outcome.error_kind or "failed",
                         args={k: v for k, v in args.items() if k != "code"}, error=outcome.error,
                         approved_by=approved_by, duration_ms=outcome.duration_ms)
            log_event(log, "tool_call", tool=name, ok=outcome.ok, error_kind=outcome.error_kind)
            return outcome

        spec = SPECS.get(name)
        if spec is None or not can_use_tool(u.role, name):
            return done(ToolOutcome(name, False, error=f"Your role ({u.role.value}) is not permitted to use {name}.",
                                    error_kind="denied"))
        if name in APPROVAL_REQUIRED and not approved_by:
            return done(ToolOutcome(name, False, error=f"{name} requires human approval.", error_kind="needs_approval"))
        try:
            parsed = spec.args_schema.model_validate(args)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return done(ToolOutcome(name, False, error=f"Invalid arguments: {msg}", error_kind="invalid_args"))

        timeout = get_settings().tool_timeout_s * (3 if spec.backend in ("internal",) else 1)
        try:
            data = await asyncio.wait_for(spec.impl(u, parsed), timeout=timeout)
        except TimeoutError:
            return done(ToolOutcome(name, False, error=f"{name} timed out after {timeout:.0f}s", error_kind="timeout"))
        except (InjectedFault, CircuitOpen, ConnectionError, OSError) as exc:
            return done(ToolOutcome(name, False, error=f"{spec.backend} unavailable: {exc}", error_kind="unavailable"))
        except Exception as exc:
            kind = "unavailable" if "connect" in str(exc).lower() else "failed"
            return done(ToolOutcome(name, False, error=f"{type(exc).__name__}: {exc}", error_kind=kind))

        flagged: list[str] = []
        clean = _sanitize(data, flagged)
        return done(ToolOutcome(name, True, data=clean, sanitized=sorted(set(flagged))))
