"""Append-only audit log of tool calls, denials and admin actions."""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import UTC, datetime

from core.config import get_settings

_lock = threading.Lock()
_recent: deque[dict] = deque(maxlen=500)


def record(user_id: str, role: str, action: str, outcome: str, **detail) -> dict:
    entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "user_id": user_id, "role": role,
             "action": action, "outcome": outcome, **detail}
    with _lock:
        _recent.append(entry)
        path = get_settings().state_db.parent / "audit.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass  # the in-memory log still has it
    return entry


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        return list(_recent)[-limit:][::-1]
