"""Sandboxed execution of model-written Python.

Used by the research agent (search plans) and the analyst-only
`python_analysis` tool. Layers:

  1. Static check: the AST is walked against an allow-list. Imports, class
     definitions, dunder names, private attributes and dangerous builtins are
     rejected before anything runs.
  2. Restricted globals: only a small set of safe builtins plus the
     data and helpers for that sandbox kind.
  3. Separate process: code runs in a spawned child with CPU-time and memory
     limits and a wall-clock timeout, so a runaway plan cannot block the API.

This is adequate for a POC. Production would add an OS-level sandbox
(gVisor, Firecracker or a managed code-execution service) and network
isolation, since a static allow-list alone is not a security boundary.
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import multiprocessing as mp
import time
from dataclasses import dataclass, field
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


def _child(conn, code: str, kind: str, data: dict, mem_mb: int, cpu_s: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
    except Exception:  # not available on every platform; the wall-clock timeout still applies
        pass
    out = io.StringIO()
    try:
        from security import sandbox_env

        env, state = sandbox_env.build(kind, data)

        def _print(*args, **_kw):
            out.write(" ".join(str(a) for a in args) + "\n")
            if out.tell() > MAX_OUTPUT_CHARS:
                raise RuntimeError("output limit exceeded")

        builtins = dict(SAFE_BUILTINS, print=_print)
        scope = {"__builtins__": builtins, **env}
        exec(compile(code, "<plan>", "exec"), scope)  # noqa: S102 - validated, restricted, isolated
        conn.send({"ok": True, "result": _json_safe(scope.get("result")), "stdout": out.getvalue()[:MAX_OUTPUT_CHARS],
                   "emitted": state.get("emitted")})
    except BaseException as exc:  # report everything, including limits hit
        conn.send({"ok": False, "error": f"{type(exc).__name__}: {exc}", "stdout": out.getvalue()[:MAX_OUTPUT_CHARS]})
    finally:
        conn.close()


def _run_blocking(code: str, kind: str, data: dict, timeout_s: float, mem_mb: int) -> SandboxResult:
    started = time.monotonic()
    try:
        validate(code)
    except SandboxRejected as exc:
        return SandboxResult(ok=False, error=f"Rejected: {exc}", rejected=True)
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(child, code, kind, data, mem_mb, max(1, int(timeout_s))), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout_s):
            proc.kill()
            return SandboxResult(ok=False, error=f"Timed out after {timeout_s:.0f}s",
                                 duration_ms=int((time.monotonic() - started) * 1000))
        msg = parent.recv()
    except EOFError:
        msg = {"ok": False, "error": "Sandbox process exited without a result (memory or CPU limit)"}
    finally:
        proc.join(timeout=1)
        if proc.is_alive():
            proc.kill()
    return SandboxResult(ok=msg["ok"], result=msg.get("result"), stdout=msg.get("stdout", ""),
                         emitted=msg.get("emitted"), error=msg.get("error"),
                         duration_ms=int((time.monotonic() - started) * 1000))


async def run(code: str, kind: str, data: dict, timeout_s: float = 10.0, mem_mb: int = 512) -> SandboxResult:
    return await asyncio.to_thread(_run_blocking, code, kind, data, timeout_s, mem_mb)
