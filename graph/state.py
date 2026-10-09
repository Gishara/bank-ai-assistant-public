"""Graph state.

The checkpointer keeps this per thread, so conversation history survives
between turns. Per-turn fields (evidence, errors, tool results...) are reset
by the `prepare` node at the start of each turn through the `RESET` marker,
which the reducers below understand.

Identity is deliberately absent: nodes read the user id from the run config
set by the API, and look the role up in the user store, so no node output can
change who the user is or what they may do.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

RESET: dict = {"$reset": True}


def _is_reset(value: Any) -> bool:
    return isinstance(value, dict) and value.get("$reset") is True


def append_or_reset(left: list | None, right: list | dict | None) -> list:
    if _is_reset(right):
        return []
    return (left or []) + list(right or [])


def merge_evidence(left: list | None, right: list | dict | None) -> list:
    """Append evidence, de-duplicated by chunk id."""
    if _is_reset(right):
        return []
    merged = list(left or [])
    seen = {e["chunk_id"] for e in merged}
    for item in right or []:
        if item["chunk_id"] not in seen:
            merged.append(item)
            seen.add(item["chunk_id"])
    return merged


class Evidence(TypedDict):
    chunk_id: str
    doc_id: str          # document id, or "tool:<name>" for tool results
    title: str
    section: str
    text: str
    source: str          # search | research | tool
    score: float


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    summary: str                     # rolling summary of older turns
    user_facts: list[str]            # long-term memory recalled for this user

    question: str
    plan: list[str]
    hops: int
    next: str
    decision: dict

    evidence: Annotated[list[Evidence], merge_evidence]
    tool_results: Annotated[list[dict], append_or_reset]
    research_result: dict | None
    worker_log: Annotated[list[dict], append_or_reset]
    errors: Annotated[list[dict], append_or_reset]
    degraded: Annotated[list[str], append_or_reset]
    notices: Annotated[list[str], append_or_reset]   # e.g. "admin tools not available to your role"

    draft: str
    answer: str
    guard: dict
    guard_feedback: list[str]
    guard_attempts: int
