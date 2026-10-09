"""Recursive research agent (RLM-style) as a LangGraph subgraph.

    describe_catalog -> write_plan -> run_plan --Send x N--> analyze_batch --(split?)--> analyze_batch ...
                            ^             |                                                       |
                            +-- retry ----+                                         reduce (deferred)

The planner sees catalog statistics, never document bodies. It writes Python
that the sandbox runs over the user's readable catalog; the plan's `emit()`
decides how documents are batched. Each batch goes to a small-model
sub-agent. A batch too large for one context splits itself in half and
recurses, up to `rlm_max_depth`. `reduce` is a deferred node, so it runs once,
after every branch at every depth has finished.

Counting is done in Python from typed findings, so the numbers in the final
answer are computed, not generated.
"""

from __future__ import annotations

import asyncio
import operator
from collections import defaultdict
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from core.auth import get_user
from core.config import get_settings
from core.llm import structured
from graph.events import emit
from rlm.catalog import catalog_stats
from rlm.prompts import ANALYZER_PROMPT, CLUSTER_PROMPT, PLANNER_PROMPT
from rlm.schemas import BatchFindings, Clusters, SearchPlan
from security import sandbox
from security.injection import sanitize_passage
from tools.registry import docs_for

MAX_DOCS = 60
_semaphore: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().rlm_concurrency)
    return _semaphore


class RLMState(TypedDict, total=False):
    question: str
    user_id: str
    today: str
    plan_reasoning: str
    plan_code: str
    plan_attempts: int
    plan_error: str | None
    plan_stdout: str
    batches: list[list[str]]
    expected_docs: int
    task: str
    findings: Annotated[list[dict], operator.add]
    notes: Annotated[list[str], operator.add]
    batch_stats: Annotated[list[dict], operator.add]
    result: dict


class BatchState(TypedDict):
    question: str
    user_id: str
    task: str
    doc_ids: list[str]
    depth: int
    label: str


def _docs(user_id: str) -> list[dict]:
    user = get_user(user_id)
    if user is None:
        raise PermissionError("Unknown user")
    return docs_for(user)


def _tokens(text: str) -> int:
    return int(len(text.split()) * 1.35)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def write_plan(state: RLMState) -> dict:
    docs = _docs(state["user_id"])
    stats = catalog_stats(docs)
    if not state.get("plan_attempts"):
        emit("rlm_catalog", documents=len(docs), stats=stats)
    previous = ""
    if state.get("plan_error"):
        previous = (f"\nYour previous plan failed. Fix it.\nPrevious code:\n{state.get('plan_code', '')}\n"
                    f"Error: {state['plan_error']}\n")
    prompt = PLANNER_PROMPT.format(question=state["question"], today=state["today"], stats=stats,
                                   previous_error=previous)
    plan: SearchPlan = await structured(SearchPlan, "large").ainvoke(prompt)
    attempt = state.get("plan_attempts", 0) + 1
    emit("rlm_plan", attempt=attempt, reasoning=plan.reasoning, code=plan.code)
    return {"plan_reasoning": plan.reasoning, "plan_code": plan.code, "plan_attempts": attempt, "plan_error": None}


async def run_plan(state: RLMState) -> dict:
    docs = _docs(state["user_id"])
    known = {d["doc_id"] for d in docs}
    res = await sandbox.run(state["plan_code"], "rlm", {"today": state["today"], "docs": docs}, timeout_s=10)
    error = None
    batches: list[list[str]] = []
    if not res.ok:
        error = res.error
    elif not res.emitted:
        error = "The plan did not call emit()."
    else:
        seen: set[str] = set()
        for batch in res.emitted["batches"]:
            clean = [i for i in batch if i in known and i not in seen]
            seen.update(clean)
            if clean:
                batches.append(clean)
        if not batches:
            error = "The plan selected no documents. Broaden the filters."
    emit("rlm_sandbox", ok=error is None, error=error, stdout=res.stdout[-1500:], duration_ms=res.duration_ms)

    if error:
        return {"plan_error": error, "plan_stdout": res.stdout}

    total = sum(len(b) for b in batches)
    notes = []
    if total > MAX_DOCS:  # bound cost: keep the first MAX_DOCS in plan order
        kept, trimmed = 0, []
        for b in batches:
            room = MAX_DOCS - kept
            if room <= 0:
                break
            trimmed.append(b[:room])
            kept += len(b[:room])
        notes.append(f"Plan selected {total} documents; analyzed the first {MAX_DOCS}.")
        batches = trimmed
    emit("rlm_batches", documents=sum(len(b) for b in batches), batches=[len(b) for b in batches],
         task=res.emitted["task"])
    return {"batches": batches, "expected_docs": sum(len(b) for b in batches), "task": res.emitted["task"],
            "plan_stdout": res.stdout, "notes": notes}


def fallback_plan(state: RLMState) -> dict:
    """Used when the model cannot produce a working plan in two attempts."""
    from retrieval.bm25 import BM25Encoder

    docs = _docs(state["user_id"])
    enc = BM25Encoder().fit([d["text"] for d in docs])
    q = dict(zip(*enc.encode_query(state["question"]).values()))

    def score(d):
        v = enc.encode_document(d["text"])
        return sum(q.get(i, 0.0) * w for i, w in zip(v["indices"], v["values"]))

    ranked = [d["doc_id"] for d in sorted(docs, key=score, reverse=True)[:24]]
    size = get_settings().rlm_batch_size
    batches = [ranked[i:i + size] for i in range(0, len(ranked), size)]
    note = f"Planner failed twice ({state.get('plan_error')}); used keyword ranking over the catalog instead."
    emit("rlm_batches", documents=len(ranked), batches=[len(b) for b in batches], fallback=True)
    return {"batches": batches, "expected_docs": len(ranked),
            "task": "Extract the facts relevant to the research question.", "notes": [note]}


def after_run(state: RLMState) -> str | list[Send]:
    if state.get("plan_error"):
        return "write_plan" if state.get("plan_attempts", 0) < 2 else "fallback_plan"
    return fan_out(state)


def fan_out(state: RLMState) -> list[Send]:
    return [Send("analyze_batch", BatchState(question=state["question"], user_id=state["user_id"],
                                             task=state["task"], doc_ids=b, depth=0, label=str(i + 1)))
            for i, b in enumerate(state["batches"])]


async def analyze_batch(state: BatchState) -> dict | Command:
    settings = get_settings()
    readable = {d["doc_id"]: d for d in _docs(state["user_id"])}
    docs = [readable[i] for i in state["doc_ids"] if i in readable]
    blocks = []
    for d in docs:
        text, _ = sanitize_passage(d["text"])
        blocks.append(f'<document doc_id="{d["doc_id"]}" date="{d["created_date"]}">\n{text}\n</document>')
    body = "\n\n".join(blocks)
    tokens = _tokens(body)

    if tokens > settings.rlm_batch_token_limit and len(docs) > 1 and state["depth"] < settings.rlm_max_depth:
        mid = len(docs) // 2
        halves = [state["doc_ids"][:mid], state["doc_ids"][mid:]]
        emit("rlm_split", batch=state["label"], depth=state["depth"], tokens=tokens,
             into=[len(h) for h in halves])
        return Command(goto=[Send("analyze_batch", BatchState(question=state["question"], user_id=state["user_id"],
                                                             task=state["task"], doc_ids=h,
                                                             depth=state["depth"] + 1,
                                                             label=f"{state['label']}.{n + 1}"))
                             for n, h in enumerate(halves)])

    emit("rlm_batch_start", batch=state["label"], depth=state["depth"], doc_ids=state["doc_ids"], tokens=tokens)
    prompt = ANALYZER_PROMPT.format(question=state["question"], task=state["task"], documents=body)
    try:
        async with _sem():
            out: BatchFindings = await structured(BatchFindings, "small").ainvoke(prompt)
    except Exception as exc:
        emit("rlm_batch_done", batch=state["label"], ok=False, error=str(exc)[:300])
        return {"notes": [f"Batch {state['label']} failed ({type(exc).__name__}); "
                          f"{len(docs)} documents not analyzed: {', '.join(state['doc_ids'])}"],
                "batch_stats": [{"label": state["label"], "depth": state["depth"], "docs": len(state["doc_ids"]),
                                 "ok": False}]}

    # Keep only findings about documents that were actually in this batch.
    batch_ids = set(state["doc_ids"])
    findings = [f.model_dump() for f in out.findings if f.doc_id in batch_ids]
    missing = batch_ids - {f["doc_id"] for f in findings}
    notes = [f"No finding returned for {', '.join(sorted(missing))}"] if missing else []
    emit("rlm_batch_done", batch=state["label"], ok=True, findings=len(findings),
         relevant=sum(f["relevant"] for f in findings))
    return {"findings": findings, "notes": notes,
            "batch_stats": [{"label": state["label"], "depth": state["depth"], "docs": len(state["doc_ids"]),
                             "ok": True}]}


async def reduce(state: RLMState) -> dict:
    # `reduce` is triggered by every analyze_batch step, including steps that
    # only split a batch. Proceed only once every planned document has been
    # through a leaf batch, so it runs exactly once with complete results.
    processed = sum(b["docs"] for b in state.get("batch_stats", []))
    if processed < state.get("expected_docs", 0):
        return {}
    findings = state.get("findings", [])
    relevant = [f for f in findings if f["relevant"]]
    excluded = [{"doc_id": f["doc_id"], "reason": f.get("exclusion_reason") or "not relevant"}
                for f in findings if not f["relevant"]]

    clusters_out: list[dict] = []
    if relevant:
        listing = "\n".join(f"[{i}] {f['doc_id']} ({f['date']}) {f['cause_category']}: {f['cause_summary']}"
                            for i, f in enumerate(relevant))
        assigned: dict[int, int] = {}
        groups: list[dict] = []
        try:
            out: Clusters = await structured(Clusters, "large").ainvoke(CLUSTER_PROMPT.format(findings=listing))
            for c in out.clusters:
                members = [i for i in c.finding_indices if 0 <= i < len(relevant) and i not in assigned]
                if not members:
                    continue
                for i in members:
                    assigned[i] = len(groups)
                groups.append({"name": c.name, "description": c.description, "members": members})
        except Exception as exc:
            emit("rlm_reduce_warning", error=f"clustering failed, grouped by label instead: {exc}"[:300])
        # Anything the model left out is grouped by its own category label.
        by_label: dict[str, list[int]] = defaultdict(list)
        for i, f in enumerate(relevant):
            if i not in assigned:
                by_label[f["cause_category"]].append(i)
        for label, members in by_label.items():
            groups.append({"name": label.replace("_", " "), "description": relevant[members[0]]["cause_summary"],
                           "members": members})

        for g in groups:
            items = sorted((relevant[i] for i in g["members"]), key=lambda f: f["date"])
            doc_ids = list(dict.fromkeys(f["doc_id"] for f in items))
            clusters_out.append({
                "name": g["name"], "description": g["description"], "count": len(doc_ids),
                "recurring": len(doc_ids) > 1, "doc_ids": doc_ids,
                "first": items[0]["date"], "last": items[-1]["date"],
                "carried_over_actions": sum(f["earlier_action_still_open"] for f in items),
            })
        clusters_out.sort(key=lambda c: (-c["count"], c["first"]))

    dates = sorted(f["date"] for f in relevant)
    result = {
        "question": state["question"],
        "documents_analyzed": len(findings),
        "relevant": len(relevant),
        "period": [dates[0], dates[-1]] if dates else None,
        "clusters": clusters_out,
        "findings": sorted(relevant, key=lambda f: f["date"]),
        "excluded": excluded,
        "plan_code": state.get("plan_code"),
        "plan_reasoning": state.get("plan_reasoning"),
        "batches": len(state.get("batches", [])),
        "max_depth": max((b["depth"] for b in state.get("batch_stats", [])), default=0),
        "notes": state.get("notes", []),
    }
    emit("rlm_reduce", relevant=len(relevant), excluded=len(excluded),
         clusters=[{"name": c["name"], "count": c["count"], "doc_ids": c["doc_ids"]} for c in clusters_out])
    return {"result": result}


def build_rlm_graph():
    g = StateGraph(RLMState)
    g.add_node("write_plan", write_plan)
    g.add_node("run_plan", run_plan)
    g.add_node("fallback_plan", fallback_plan)
    g.add_node("analyze_batch", analyze_batch)
    g.add_node("reduce", reduce, defer=True)
    g.add_edge(START, "write_plan")
    g.add_edge("write_plan", "run_plan")
    g.add_conditional_edges("run_plan", after_run, ["write_plan", "fallback_plan", "analyze_batch"])
    g.add_conditional_edges("fallback_plan", fan_out, ["analyze_batch"])
    g.add_edge("analyze_batch", "reduce")
    g.add_edge("reduce", END)
    return g.compile(name="research_agent")


rlm_graph = build_rlm_graph()


async def run_research(question: str, user_id: str, config: RunnableConfig | None = None,
                       today: date | None = None) -> dict[str, Any]:
    out = await rlm_graph.ainvoke({"question": question, "user_id": user_id,
                                   "today": (today or date.today()).isoformat()}, config)
    return out["result"]
