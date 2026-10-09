"""Sandboxed execution of model-written Python.

Used by the research agent (search plans) and the analyst-only
`python_analysis` tool. Layers:

  1. Static check: the AST is walked against an allow-list. Imports, class
     definitions, dunder names, private attributes and dangerous builtins are
     rejected before anything runs.
  2. Restricted globals: only a small set of safe builtins plus the
     data and helpers for that sandbox kind.
  3. Separate process: code runs in a fresh interpreter
     (`python -E -s -m security.sandbox_runner`) with an empty environment
     (no API keys), CPU-time and memory limits, and a wall-clock timeout,
     so a runaway plan cannot block or crash the API.

This is adequate for a POC. Production would add an OS-level sandbox
(gVisor, Firecracker or a managed code-execution service) and network
isolation, since a static allow-list alone is not a security boundary.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_CODE_CHARS = 4000
MAX_NODES = 1500
MAX_OUTPUT_CHARS = 6000

FORBIDDEN_NODES = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global,
                   ast.Nonlocal, ast.With, ast.AsyncWith, ast.Try, ast.Raise, ast.Delete, ast.Yield,
                   ast.YieldFrom)
FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "open", "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "__import__", "input", "breakpoint", "help", "dir", "type", "memoryview", "object", "super", "exit", "quit",
})

SAFE_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "len", "list",
                 "map", "max", "min", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple",
                 "zip", "isinstance", "frozenset")
}


class SandboxRejected(ValueError):
    pass


def validate(code: str) -> ast.Module:
    if len(code) > MAX_CODE_CHARS:
        raise SandboxRejected(f"code longer than {MAX_CODE_CHARS} characters")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxRejected(f"syntax error: {exc.msg} (line {exc.lineno})") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise SandboxRejected("code too complex")
    for node in nodes:
        if isinstance(node, FORBIDDEN_NODES):
            raise SandboxRejected(f"{type(node).__name__} is not allowed (line {getattr(node, 'lineno', '?')})")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SandboxRejected(f"access to private attribute '{node.attr}' is not allowed")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise SandboxRejected(f"name '{node.id}' is not allowed")
            if node.id in FORBIDDEN_NAMES:
                raise SandboxRejected(f"'{node.id}' is not allowed")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            raise SandboxRejected("strings containing '__' are not allowed")
    return tree


@dataclass
class SandboxResult:
    ok: bool
    result: Any = None
    stdout: str = ""
    emitted: dict | None = None
    error: str | None = None
    duration_ms: int = 0
    rejected: bool = False
    extra: dict = field(default_factory=dict)


def _json_safe(value: Any) -> Any:
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = json.dumps(repr(value))
    if len(text) > MAX_OUTPUT_CHARS:
        return {"truncated": True, "preview": text[:MAX_OUTPUT_CHARS]}
    return json.loads(text)


ROOT = Path(__file__).resolve().parent.parent


def _child_env() -> dict[str, str]:
    """Env for the sandboxed child: no API keys or other secrets, but not
    literally empty -- on Windows, importing `asyncio` (done by this module,
    and by the child before it ever runs user code) pulls in `socket`, whose
    WSAStartup call fails with WinError 10106 ("requested service provider
    could not be loaded or initialized") if SystemRoot isn't set, since
    Winsock can't locate its provider catalog. SystemRoot/windir carry no
    secret, just the Windows install path, so it's safe to pass through.
    """
    env = {"PYTHONDONTWRITEBYTECODE": "1"}
    if sys.platform == "win32":
        for var in ("SystemRoot", "SystemDrive", "windir"):
            if var in os.environ:
                env[var] = os.environ[var]
    return env


async def run(code: str, kind: str, data: dict, timeout_s: float = 10.0, mem_mb: int = 512) -> SandboxResult:
    """Validate, then execute in a fresh interpreter with no environment variables."""
    started = time.monotonic()
    try:
        validate(code)
    except SandboxRejected as exc:
        return SandboxResult(ok=False, error=f"Rejected: {exc}", rejected=True)

    request = json.dumps({"code": code, "kind": kind, "data": data, "mem_mb": mem_mb,
                          "cpu_s": max(1, int(timeout_s))}, default=str).encode()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-E", "-s", "-m", "security.sandbox_runner",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT), env=_child_env())
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(request), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return SandboxResult(ok=False, error=f"Timed out after {timeout_s:.0f}s",
                             duration_ms=int((time.monotonic() - started) * 1000))
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        msg = json.loads(stdout.decode() or "{}")
        if "ok" not in msg:
            raise ValueError("empty response")
    except ValueError:
        tail = stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        msg = {"ok": False, "error": f"Sandbox process failed (memory or CPU limit?): {tail[0][:200]}"}
    return SandboxResult(ok=msg["ok"], result=msg.get("result"), stdout=msg.get("stdout", ""),
                         emitted=msg.get("emitted"), error=msg.get("error"), duration_ms=elapsed)
