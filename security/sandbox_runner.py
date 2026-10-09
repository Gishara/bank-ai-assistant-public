"""Child-process entry point for the sandbox.

    python -E -s -m security.sandbox_runner  < request.json  > response.json

Started by security.sandbox with an empty environment (no API keys), resource
limits applied before any user code runs.
"""

from __future__ import annotations

import io
import json
import sys


def main() -> None:
    req = json.loads(sys.stdin.read())
    try:
        import resource

        mem = req["mem_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (req["cpu_s"], req["cpu_s"] + 1))
    except Exception:  # not available on every platform; the parent's wall-clock timeout still applies
        pass

    from security.sandbox import MAX_OUTPUT_CHARS, SAFE_BUILTINS, _json_safe
    from security import sandbox_env

    out = io.StringIO()
    try:
        env, state = sandbox_env.build(req["kind"], req["data"])

        def _print(*args, **_kw):
            out.write(" ".join(str(a) for a in args) + "\n")
            if out.tell() > MAX_OUTPUT_CHARS:
                raise RuntimeError("output limit exceeded")

        scope = {"__builtins__": dict(SAFE_BUILTINS, print=_print), **env}
        exec(compile(req["code"], "<plan>", "exec"), scope)  # noqa: S102 - validated, restricted, isolated
        resp = {"ok": True, "result": _json_safe(scope.get("result")), "stdout": out.getvalue()[:MAX_OUTPUT_CHARS],
                "emitted": state.get("emitted")}
    except BaseException as exc:  # report everything, including limits hit
        resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "stdout": out.getvalue()[:MAX_OUTPUT_CHARS]}
    sys.stdout.write(json.dumps(resp, default=str))


if __name__ == "__main__":
    main()
