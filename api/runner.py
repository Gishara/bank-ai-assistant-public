"""Run the graph and translate its streams into server-sent events.

Event types sent to the client:
    run_start, token, answer_reset, answer_replaced, approval_required, final, error
plus every activity event nodes emit (node_start, route, plan, retrieval,
tool_call, tool_result, rlm_*, validation, memory, degraded, ...).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk

from core.auth import User
from core.logging import get_logger, log_event, request_id_var

log = get_logger(__name__)
RUN_TIMEOUT_S = 240


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def run_config(user: User, thread_id: str, run_id: uuid.UUID) -> dict:
    return {
        # Thread ids are namespaced by user, so one user can never read or
        # resume another user's conversation.
        "configurable": {"thread_id": f"{user.user_id}:{thread_id}", "user_id": user.user_id},
        "run_id": run_id,
        "recursion_limit": 60,
        "tags": [f"role:{user.role.value}"],
        "metadata": {"user_id": user.user_id, "role": user.role.value, "thread_id": thread_id,
                     "request_id": request_id_var.get()},
    }


def _final_payload(values: dict, run_id: uuid.UUID) -> dict:
    sources, seen = [], set()
    cited = set(values.get("guard", {}).get("cited", []))
    for e in values.get("evidence", []):
        if e["doc_id"] in seen:
            continue
        seen.add(e["doc_id"])
        sources.append({"doc_id": e["doc_id"], "title": e["title"], "section": e["section"],
                        "cited": e["doc_id"] in cited, "source": e["source"]})
    return {
        "run_id": str(run_id),
        "answer": values.get("answer", ""),
        "citations": sorted(cited),
        "sources": sources,
        "degraded": list(dict.fromkeys(values.get("degraded", []))),
        "errors": values.get("errors", []),
        "guard": values.get("guard", {}),
        "plan": values.get("plan", []),
        "research": ({k: values["research_result"][k] for k in ("clusters", "excluded", "relevant",
                                                                 "documents_analyzed", "period")}
                     if values.get("research_result") else None),
    }


async def stream_run(graph, graph_input: Any, user: User, thread_id: str,
                     run_id: uuid.UUID | None = None) -> AsyncIterator[str]:
    run_id = run_id or uuid.uuid4()
    config = run_config(user, thread_id, run_id)
    yield sse("run_start", {"run_id": str(run_id), "thread_id": thread_id})
    try:
        async with asyncio.timeout(RUN_TIMEOUT_S):
            async for namespace, mode, chunk in graph.astream(graph_input, config, subgraphs=True,
                                                              stream_mode=["custom", "messages", "updates"]):
                if mode == "custom" and isinstance(chunk, dict) and "type" in chunk:
                    yield sse(chunk["type"], chunk | {"subgraph": bool(namespace)})
                elif mode == "messages":
                    msg, meta = chunk
                    if (not namespace and meta.get("langgraph_node") == "respond"
                            and isinstance(msg, AIMessageChunk)):
                        text = msg.text if isinstance(msg.text, str) else msg.text()
                        if text:
                            yield sse("token", {"text": text})
                elif mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
                    for intr in chunk["__interrupt__"]:
                        yield sse("approval_required", dict(intr.value) | {"thread_id": thread_id})

        state = await graph.aget_state(config)
        if state.next:  # paused on an interrupt
            yield sse("final", {"run_id": str(run_id), "status": "awaiting_approval", "answer": "",
                                "pending": list(state.next)})
            return
        payload = _final_payload(state.values, run_id) | {"status": "complete"}
        log_event(log, "run_complete", run_id=str(run_id), cited=payload["citations"],
                  guard=payload["guard"].get("passed"), degraded=payload["degraded"])
        yield sse("final", payload)
    except TimeoutError:
        yield sse("error", {"message": f"The request took longer than {RUN_TIMEOUT_S}s and was stopped.",
                            "request_id": request_id_var.get()})
    except Exception as exc:
        log.exception("run_failed")
        yield sse("error", {"message": "The assistant hit an internal error. Please try again.",
                            "detail": type(exc).__name__, "request_id": request_id_var.get()})
