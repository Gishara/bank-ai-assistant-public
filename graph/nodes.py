"""Graph nodes.

Every node reads the user from the run config (`configurable.user_id`, set by
the API from the verified token) and resolves the role from the user store.
Worker nodes are wrapped by `worker()`: an exception becomes an entry in
`state.errors` and control returns to the supervisor, so one failing
component degrades the answer instead of failing the request.
"""

from __future__ import annotations

import functools
import json
import re
import time
import uuid
from datetime import date
from typing import Literal

from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage, RemoveMessage, SystemMessage,
                                     ToolMessage)
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_store
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from core.auth import User, get_user
from core.config import get_settings
from core.llm import chat, structured
from core.logging import get_logger, log_event
from core.rbac import Role, can_use_tool
from graph import prompts
from graph.events import emit
from graph.state import RESET, AgentState
from retrieval.filters import SearchFilters
from rlm.graph import run_research
from security.output_guard import check_answer
from tools.gateway import ToolGateway

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def current_user(config: RunnableConfig) -> User:
    user_id = (config.get("configurable") or {}).get("user_id")
    user = get_user(user_id) if user_id else None
    if user is None:
        raise PermissionError("No authenticated user in run config")
    return user


def text_of(message: AnyMessage | str) -> str:
    if isinstance(message, str):
        return message
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


def history_text(messages: list[AnyMessage], summary: str = "", last: int = 6) -> str:
    lines = [f"(Earlier: {summary})"] if summary else []
    # The current question is the last message; it is shown separately.
    for m in messages[:-1][-last:]:
        who = "User" if isinstance(m, HumanMessage) else "Assistant"
        lines.append(f"{who}: {text_of(m)[:600]}")
    return "\n".join(lines) or "(no earlier messages)"


def evidence_digest(evidence: list[dict], limit: int = 15) -> str:
    if not evidence:
        return "(none yet)"
    rows = [f"- {e['doc_id']} §{e['section']}: {e['title']}" for e in evidence[:limit]]
    if len(evidence) > limit:
        rows.append(f"- ... and {len(evidence) - limit} more")
    return "\n".join(rows)


def worker(name: str):
    """Emit start/end events and convert failures into state errors."""
    def wrap(fn):
        @functools.wraps(fn)
        async def run(state: AgentState, config: RunnableConfig):
            started = time.monotonic()
            emit("node_start", node=name)
            try:
                update = await fn(state, config)
            except GraphBubbleUp:  # interrupts must propagate
                raise
            except Exception as exc:
                log.exception("node_failed", extra={"data": {"node": name}})
                update = {"errors": [{"node": name, "error": f"{type(exc).__name__}: {exc}"[:400]}],
                          "worker_log": [{"worker": name, "ok": False}]}
                emit("error", node=name, error=f"{type(exc).__name__}: {str(exc)[:300]}")
            emit("node_end", node=name, ms=int((time.monotonic() - started) * 1000))
            return update
        return run
    return wrap


# ---------------------------------------------------------------------------
# prepare: start of turn, short- and long-term memory
# ---------------------------------------------------------------------------

class ConversationSummary(BaseModel):
    summary: str


async def prepare(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    settings = get_settings()
    messages = state.get("messages", [])
    question = text_of(messages[-1]) if messages else ""
    update: dict = {
        "question": question, "plan": [], "hops": 0, "next": "", "decision": {},
        "evidence": RESET, "tool_results": RESET, "worker_log": RESET, "errors": RESET, "degraded": RESET,
        "notices": RESET, "research_result": None, "draft": "", "answer": "", "guard": {},
        "guard_feedback": [], "guard_attempts": 0,
    }

    # Long-term memory: facts this user shared in earlier conversations.
    facts: list[str] = []
    store = get_store()
    if store is not None:
        items = await store.asearch(("users", user.user_id), limit=20)
        facts = [i.value["fact"] for i in items if "fact" in i.value]
    update["user_facts"] = facts

    # Short-term memory: fold older turns into a running summary.
    summarized = 0
    if len(messages) > settings.summarize_after_messages:
        old = messages[:-6]
        try:
            text = "\n".join(f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {text_of(m)[:800]}"
                             for m in old)
            out: ConversationSummary = await structured(ConversationSummary, "small").ainvoke(
                prompts.SUMMARY_PROMPT.format(previous=state.get("summary", ""), messages=text))
            update["summary"] = out.summary
            update["messages"] = [RemoveMessage(id=m.id) for m in old if m.id]
            summarized = len(old)
        except Exception as exc:  # keep the raw history if summarizing fails
            log_event(log, "summary_failed", error=str(exc))
    emit("memory", action="recall", facts=facts, summarized_messages=summarized,
         history_messages=len(messages))
    return update


# ---------------------------------------------------------------------------
# supervisor
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    intent: Literal["knowledge", "research", "data_lookup", "admin", "conversation", "out_of_scope"]
    plan: list[str] = Field(default_factory=list, description="Up to 4 short steps for this question")
    next: Literal["retrieve", "research", "tools", "admin", "respond"]
    reason: str = Field(description="One sentence")
    search_query: str | None = Field(None, description="Self-contained query for retrieve or research")
    filters: SearchFilters | None = None
    tool_task: str | None = Field(None, description="Instruction for the tools worker")
    admin_action: Literal["view_audit_log", "reindex_documents"] | None = None
    reindex_scope: Literal["local", "all"] | None = None


def available_workers(role: Role) -> dict[str, bool]:
    return {
        "retrieve": True,
        "research": True,
        "tools": any(can_use_tool(role, t) for t in ("python_analysis", "employee_directory",
                                                      "service_catalog", "incident_records")),
        "admin": can_use_tool(role, "admin_view_audit_log"),
        "respond": True,
    }


async def supervisor(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    settings = get_settings()
    hops = state.get("hops", 0)
    workers = available_workers(user.role)
    emit("node_start", node="supervisor")

    if hops >= settings.max_hops:
        emit("route", next="respond", reason=f"step budget of {settings.max_hops} reached")
        return {"next": "respond"}

    steps = "\n".join(f"- {w['worker']}: {json.dumps({k: v for k, v in w.items() if k != 'worker'})}"
                      for w in state.get("worker_log", [])) or "(none)"
    if state.get("errors"):
        steps += "\nErrors:\n" + "\n".join(f"- {e['node']}: {e['error']}" for e in state["errors"])
    prompt = prompts.SUPERVISOR_PROMPT.format(
        today=date.today().isoformat(), user_name=user.display_name, role=user.role.value,
        tools_line=("employee directory, service catalog, structured incident records with numbers, Python "
                    "calculations. Available." if workers["tools"] else "NOT available to this user."),
        admin_line=("view audit log; reindex documents (needs human approval). Available."
                    if workers["admin"] else "NOT available to this user."),
        history=history_text(state.get("messages", []), state.get("summary", "")),
        facts="\n".join(f"- {f}" for f in state.get("user_facts", [])) or "(nothing)",
        steps=steps, evidence=evidence_digest(state.get("evidence", [])), question=state["question"])

    decision: RoutingDecision = await structured(RoutingDecision, "large").ainvoke(prompt)
    nxt = decision.next
    notices: list[str] = []

    # Enforce in code what the prompt asks for.
    if not workers.get(nxt, False):
        notices.append(f"The '{nxt}' capability is not available for the {user.role.value} role.")
        log_event(log, "route_denied", requested=nxt, role=user.role.value)
        nxt = "respond"
    key = (nxt, decision.search_query or decision.tool_task or decision.admin_action)
    if nxt != "respond" and any((w["worker"], w.get("input")) == key for w in state.get("worker_log", [])):
        nxt = "respond"

    emit("route", next=nxt, requested=decision.next, intent=decision.intent, reason=decision.reason,
         query=decision.search_query, hop=hops + 1)
    update: dict = {"next": nxt, "decision": decision.model_dump(mode="json"), "notices": notices,
                    "hops": hops + (0 if nxt == "respond" else 1)}
    if hops == 0 and decision.plan:
        update["plan"] = decision.plan[:4]
        emit("plan", steps=decision.plan[:4])
    return update


def route(state: AgentState) -> str:
    return state.get("next") or "respond"


# ---------------------------------------------------------------------------
# workers
# ---------------------------------------------------------------------------

def _hit_to_evidence(h: dict, source: str) -> dict:
    return {"chunk_id": h["chunk_id"], "doc_id": h["doc_id"], "title": h["title"], "section": h["section"],
            "text": h["text"], "source": source, "score": h.get("score", 0.0)}


@worker("retrieve")
async def retrieve(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    d = state.get("decision", {})
    query = d.get("search_query") or state["question"]
    args = {"query": query, "filters": d.get("filters")}
    outcome = await ToolGateway(user).execute("knowledge_search", args)
    log_entry = {"worker": "retrieve", "input": query, "ok": outcome.ok}
    if not outcome.ok:
        emit("retrieval", query=query, ok=False, error=outcome.error)
        return {"errors": [{"node": "retrieve", "error": outcome.error}], "worker_log": [log_entry]}

    data = outcome.data
    hits = data["hits"]
    emit("retrieval", query=query, ok=True, mode=data["mode"], alpha=data["alpha"], reranked=data["reranked"],
         filters=d.get("filters"), sanitized=outcome.sanitized,
         hits=[{"doc_id": h["doc_id"], "section": h["section"], "score": h["score"]} for h in hits])
    update: dict = {"evidence": [_hit_to_evidence(h, "search") for h in hits],
                    "worker_log": [log_entry | {"hits": len(hits), "mode": data["mode"]}]}
    if data.get("degraded_reason"):
        update["degraded"] = [data["degraded_reason"]]
        emit("degraded", component="vector_search", reason=data["degraded_reason"])
    if outcome.sanitized:
        update["notices"] = ["A retrieved document contained instructions aimed at an AI assistant; "
                             "they were removed and ignored."]
    return update


@worker("research")
async def research(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    question = state.get("decision", {}).get("search_query") or state["question"]
    result = await run_research(question, user.user_id, config)
    findings = result.get("findings", [])
    evidence = [{"chunk_id": f"research:{f['doc_id']}", "doc_id": f["doc_id"], "title": f["title"],
                 "section": "Root Cause",
                 "text": f"{f['date']}: {f['cause_summary']} Impact: {f['impact']}. Quote: \"{f['evidence_quote']}\"",
                 "source": "research", "score": 1.0} for f in findings]
    log_entry = {"worker": "research", "input": question, "ok": True, "relevant": len(findings),
                 "clusters": len(result.get("clusters", []))}
    update: dict = {"research_result": result, "evidence": evidence, "worker_log": [log_entry]}
    if result.get("notes"):
        update["degraded"] = [n for n in result["notes"] if "failed" in n or "not analyzed" in n]
    return update


@worker("tools")
async def tools(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    gateway = ToolGateway(user)
    bound = gateway.bindable_tools()
    task = state.get("decision", {}).get("tool_task") or state["question"]
    messages: list[AnyMessage] = [SystemMessage(prompts.TOOLS_PROMPT.format(
        today=date.today().isoformat(), role=user.role.value, task=task, question=state["question"],
        evidence=evidence_digest(state.get("evidence", []))))]
    messages.append(HumanMessage(task))
    model = chat("large", tools=bound)
    results: list[dict] = []
    evidence: list[dict] = []
    errors: list[dict] = []
    for _ in range(4):
        ai: AIMessage = await model.ainvoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            break
        for call in ai.tool_calls:
            emit("tool_call", tool=call["name"], args={k: v for k, v in call["args"].items() if k != "code"},
                 code=call["args"].get("code"))
            outcome = await gateway.execute(call["name"], call["args"])
            emit("tool_result", **outcome.summary())
            payload = outcome.data if outcome.ok else {"error": outcome.error}
            messages.append(ToolMessage(content=json.dumps(payload, default=str)[:8000], tool_call_id=call["id"]))
            results.append({"tool": call["name"], "args": call["args"], "ok": outcome.ok,
                            "data": outcome.data, "error": outcome.error})
            if not outcome.ok:
                errors.append({"node": f"tool:{call['name']}", "error": outcome.error})
            elif call["name"] == "knowledge_search":
                evidence += [_hit_to_evidence(h, "search") for h in outcome.data["hits"]]
    log_entry = {"worker": "tools", "input": task, "ok": not errors,
                 "calls": [r["tool"] for r in results]}
    update: dict = {"tool_results": results, "evidence": evidence, "worker_log": [log_entry], "errors": errors}
    unavailable = [e for e in errors if "unavailable" in (e["error"] or "")]
    if unavailable:
        update["degraded"] = [f"{e['node'].split(':', 1)[1]} was unavailable" for e in unavailable]
    return update


@worker("admin")
async def admin(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    gateway = ToolGateway(user)
    d = state.get("decision", {})
    action = d.get("admin_action") or "view_audit_log"
    log_entry = {"worker": "admin", "input": action}

    if action == "view_audit_log":
        outcome = await gateway.execute("admin_view_audit_log", {"limit": 15})
        emit("tool_result", **outcome.summary())
        return {"tool_results": [{"tool": "admin_view_audit_log", "args": {"limit": 15}, "ok": outcome.ok,
                                  "data": outcome.data, "error": outcome.error}],
                "worker_log": [log_entry | {"ok": outcome.ok}]}

    tool, args = "admin_reindex_documents", {"scope": d.get("reindex_scope") or "all"}
    if not can_use_tool(user.role, tool):  # checked again in the gateway
        return {"notices": [f"{tool} is not available for your role."], "worker_log": [log_entry | {"ok": False}]}
    # The API turns this interrupt into an `approval_required` event. On resume
    # the node runs again from the top and interrupt() returns the decision.
    decision = interrupt({"type": "approval_required", "tool": tool, "args": args,
                          "requested_by": user.display_name,
                          "message": f"Approve {tool} with scope '{args['scope']}'?"})
    approved = isinstance(decision, dict) and decision.get("approved") is True
    approver = (decision or {}).get("approver") if isinstance(decision, dict) else None
    emit("approval_decision", tool=tool, approved=approved, approver=approver)
    if not approved:
        return {"notices": [f"{tool} was not approved, so nothing was changed."],
                "tool_results": [{"tool": tool, "args": args, "ok": False, "data": None, "error": "rejected by approver"}],
                "worker_log": [log_entry | {"ok": False, "approved": False}]}
    outcome = await gateway.execute(tool, args, approved_by=approver or user.user_id)
    emit("tool_result", **outcome.summary())
    return {"tool_results": [{"tool": tool, "args": args, "ok": outcome.ok, "data": outcome.data,
                              "error": outcome.error}],
            "worker_log": [log_entry | {"ok": outcome.ok, "approved": True}]}


# ---------------------------------------------------------------------------
# respond + guard
# ---------------------------------------------------------------------------

def _research_block(result: dict | None) -> str:
    if not result:
        return ""
    lines = [f"Research results (computed by code from {result['documents_analyzed']} documents; "
             f"{result['relevant']} relevant"
             + (f", {result['period'][0]} to {result['period'][1]}" if result.get("period") else "") + "):"]
    for i, c in enumerate(result.get("clusters", []), 1):
        tag = "recurring" if c["recurring"] else "one-off"
        carried = f"; {c['carried_over_actions']} involved an earlier action still open" if c["carried_over_actions"] else ""
        lines.append(f"{i}. {c['name']} ({tag}, {c['count']} incidents{carried}): {', '.join(c['doc_ids'])}. "
                     f"{c['description']}")
    if result.get("excluded"):
        lines.append("Considered and excluded: " + "; ".join(f"{e['doc_id']} ({e['reason']})"
                                                            for e in result["excluded"][:12]))
    for n in result.get("notes", []):
        lines.append(f"Note: {n}")
    return "\n".join(lines) + "\n\n"


def _tools_block(results: list[dict]) -> str:
    if not results:
        return ""
    parts = []
    for r in results:
        body = json.dumps(r["data"], default=str)[:3000] if r["ok"] else f"FAILED: {r['error']}"
        parts.append(f'<tool_result name="{r["tool"]}">\n{body}\n</tool_result>')
    return "Tool results (cite as [tool:name]):\n" + "\n".join(parts) + "\n\n"


def _evidence_block(evidence: list[dict], limit: int = 14) -> str:
    docs = [e for e in evidence if not e["doc_id"].startswith("tool:")]
    if not docs:
        return "(no documents retrieved)"
    # Search hits first by score, research findings after.
    ordered = sorted(docs, key=lambda e: (e["source"] != "search", -e["score"]))[:limit + 20]
    return "\n".join(f'<document id="{e["doc_id"]}" section="{e["section"]}" title="{e["title"]}">\n'
                     f'{e["text"]}\n</document>' for e in ordered)


async def respond(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    emit("node_start", node="respond")
    attempt = state.get("guard_attempts", 0)
    if attempt:
        emit("answer_reset", reason="regenerating after validation")
    notices = list(state.get("notices", []))
    notices += [f"Degraded: {d}" for d in state.get("degraded", [])]
    notices += [f"Error in {e['node']}: {e['error']}" for e in state.get("errors", [])]
    feedback = ""
    if state.get("guard_feedback"):
        feedback = ("Your previous draft failed validation: " + "; ".join(state["guard_feedback"]) +
                    ". Write it again and fix these problems.\n\n")
    facts = state.get("user_facts", [])
    user_msg = prompts.ANSWER_USER.format(
        user_name=user.display_name, role=user.role.value,
        facts=("Known about the user: " + "; ".join(facts) + "\n") if facts else "",
        history=history_text(state.get("messages", []), state.get("summary", "")),
        notices=("Notices:\n" + "\n".join(f"- {n}" for n in notices) + "\n\n") if notices else "",
        research=_research_block(state.get("research_result")),
        tools=_tools_block(state.get("tool_results", [])),
        evidence=_evidence_block(state.get("evidence", [])),
        feedback=feedback, question=state["question"])
    ai = await chat("large", tags=["final_answer"]).ainvoke([SystemMessage(prompts.ANSWER_SYSTEM),
                                                              HumanMessage(user_msg)])
    return {"draft": text_of(ai)}


async def output_guard(state: AgentState, config: RunnableConfig) -> dict:
    emit("node_start", node="output_guard")
    sections: dict[str, set[str]] = {}
    for e in state.get("evidence", []):
        sections.setdefault(e["doc_id"], set()).add(e["section"])
    tools_used = {r["tool"] for r in state.get("tool_results", []) if r["ok"]}
    result = check_answer(state.get("draft", ""), sections, tools_used)
    attempts = state.get("guard_attempts", 0)
    emit("validation", passed=result.passed, issues=result.issues, warnings=result.warnings,
         cited=result.cited_doc_ids, pii_masked=result.pii_masked, attempt=attempts + 1)
    guard = {"passed": result.passed, "issues": result.issues, "warnings": result.warnings,
             "cited": result.cited_doc_ids, "pii_masked": result.pii_masked, "attempts": attempts + 1}
    if result.passed:
        return {"answer": result.answer, "guard": guard}
    if attempts < 1:
        return {"guard_feedback": result.issues, "guard_attempts": attempts + 1, "guard": guard}

    # Second failure: return only what can be verified.
    docs = []
    for e in state.get("evidence", []):
        if not e["doc_id"].startswith("tool:") and e["doc_id"] not in {d[0] for d in docs}:
            docs.append((e["doc_id"], e["section"], e["title"]))
    fallback = "I couldn't produce an answer I could verify against the sources, so I'm not giving one."
    if docs:
        fallback += " These documents look most relevant:\n" + "\n".join(
            f"- {t} [{d} §{s}]" for d, s, t in docs[:6])
    emit("answer_replaced", reason="validation failed twice")
    return {"answer": fallback, "guard": guard | {"fallback": True}}


def after_guard(state: AgentState) -> str:
    return "memory_write" if state.get("answer") else "respond"


# ---------------------------------------------------------------------------
# memory_write
# ---------------------------------------------------------------------------

class MemoryFacts(BaseModel):
    facts: list[str] = Field(default_factory=list, description="Short third-person facts, e.g. 'Works on the cards team'")


FIRST_PERSON = re.compile(r"\b(I|I'm|I am|my|me|we|our)\b", re.I)


async def memory_write(state: AgentState, config: RunnableConfig) -> dict:
    user = current_user(config)
    emit("node_start", node="memory_write")
    update: dict = {"messages": [AIMessage(content=state["answer"], id=str(uuid.uuid4()))]}
    saved: list[str] = []
    store = get_store()
    question = state.get("question", "")
    # Only learn from turns that passed validation, and only when the user
    # said something about themselves.
    if store is not None and state.get("guard", {}).get("passed") and FIRST_PERSON.search(question):
        try:
            known = state.get("user_facts", [])
            out: MemoryFacts = await structured(MemoryFacts, "small").ainvoke(
                prompts.MEMORY_PROMPT.format(known="\n".join(known) or "(nothing)", message=question))
            for fact in out.facts[:3]:
                if fact not in known:
                    await store.aput(("users", user.user_id), str(uuid.uuid4()),
                                     {"fact": fact, "source_question": question[:200]})
                    saved.append(fact)
        except Exception as exc:
            log_event(log, "memory_extract_failed", error=str(exc))
    emit("memory", action="write", saved=saved)
    return update
