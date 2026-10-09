"""Activity events streamed to the UI's activity panel.

Nodes call `emit()`; LangGraph delivers the payload on the "custom" stream
mode, and the API forwards it as an SSE event. Outside a graph run, `emit` is
a no-op, so nodes can be unit-tested without a runtime.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.config import get_stream_writer


def emit(event_type: str, **data: Any) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer({"type": event_type, "ts": round(time.time(), 3), **data})
    except Exception:
        pass
