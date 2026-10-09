"""Turn streamed agent events into activity-panel lines and an SSE parser.

Kept free of Streamlit imports so it can be unit-tested.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

NODE_LABELS = {
    "supervisor": "Supervisor", "retrieve": "Retrieval agent", "research": "Research agent",
    "tools": "Tools agent", "admin": "Admin action", "respond": "Response agent",
    "output_guard": "Output guard", "memory_write": "Memory",
}


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    event, data = None, []
    for raw in lines:
        line = raw.rstrip("\r")
        if not line:
            if event and data:
                yield event, json.loads("\n".join(data))
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if event and data:
        yield event, json.loads("\n".join(data))


def _docs(hits: list[dict], n: int = 4) -> str:
    shown = ", ".join(f"`{h['doc_id']}` §{h['section']}" for h in hits[:n])
    more = f" +{len(hits) - n} more" if len(hits) > n else ""
    return shown + more


def describe(event: str, d: dict) -> str | None:
    """One markdown line per event, or None for events not shown in the panel."""
    if event == "input_guard":
        if d.get("blocked"):
            return f"🛡️ **Input guard blocked the message** ({', '.join(d.get('matches', [])) or d.get('reason')})"
        return f"🛡️ Input guard passed (risk score {d.get('score', 0)})"
    if event == "memory":
        if d.get("action") == "recall":
            facts = d.get("facts") or []
            extra = f", summarized {d['summarized_messages']} older messages" if d.get("summarized_messages") else ""
            return f"🧠 Memory: recalled {len(facts)} saved fact(s), {d.get('history_messages', 0)} messages in thread{extra}"
        saved = d.get("saved") or []
        return f"🧠 Memory: saved {', '.join(repr(s) for s in saved)}" if saved else "🧠 Memory: conversation saved"
    if event == "plan":
        return "🗺️ **Plan:** " + " → ".join(d.get("steps", []))
    if event == "route":
        denied = f" (asked for *{d['requested']}*, not allowed)" if d.get("requested") != d.get("next") else ""
        q = f" — query: “{d['query']}”" if d.get("query") and d.get("next") in ("retrieve", "research") else ""
        return f"🧭 Supervisor → **{d.get('next')}**{denied}: {d.get('reason', '')}{q}"
    if event == "retrieval":
        if not d.get("ok"):
            return f"❌ Search failed: {d.get('error')}"
        mode = "hybrid dense+BM25" if d.get("mode") == "hybrid" else "keyword only"
        rr = ", reranked" if d.get("reranked") else ""
        san = " · ⚠️ removed injected text" if d.get("sanitized") else ""
        return f"🔎 Search ({mode}, α={d.get('alpha')}{rr}): {len(d.get('hits', []))} hits — {_docs(d.get('hits', []))}{san}"
    if event == "degraded":
        return f"⚠️ Degraded: {d.get('reason')}"
    if event == "tool_call":
        args = json.dumps(d.get("args", {}))[:160]
        return f"🔧 Tool call **{d.get('tool')}** {args}" + (" (code)" if d.get("code") else "")
    if event == "tool_result":
        if d.get("ok"):
            return f"✅ {d.get('tool')} returned in {d.get('duration_ms')} ms"
        return f"❌ {d.get('tool')} failed ({d.get('error_kind')}): {d.get('error')}"
    if event == "approval_required":
        return f"✋ **Waiting for approval:** {d.get('tool')} {json.dumps(d.get('args', {}))}"
    if event == "approval_decision":
        return f"✋ Approval {'granted' if d.get('approved') else 'rejected'} by {d.get('approver')}"
    if event == "rlm_catalog":
        return f"📚 Research: catalog of {d.get('documents')} readable documents (metadata only)"
    if event == "rlm_plan":
        return f"🐍 Research plan (attempt {d.get('attempt')}): {d.get('reasoning')}"
    if event == "rlm_sandbox":
        return (f"🧪 Sandbox ran plan in {d.get('duration_ms')} ms" if d.get("ok")
                else f"🧪 Sandbox rejected plan: {d.get('error')}")
    if event == "rlm_batches":
        sizes = d.get("batches", [])
        fb = " (fallback keyword plan)" if d.get("fallback") else ""
        return f"🪓 {d.get('documents')} documents → {len(sizes)} batches {sizes}{fb}"
    if event == "rlm_split":
        return f"↪️ Batch {d.get('batch')} too large (~{d.get('tokens')} tokens) → split into {d.get('into')} at depth {d.get('depth') + 1}"
    if event == "rlm_batch_start":
        return f"🤖 Sub-agent {d.get('batch')} (depth {d.get('depth')}): {len(d.get('doc_ids', []))} docs"
    if event == "rlm_batch_done":
        if not d.get("ok"):
            return f"❌ Sub-agent {d.get('batch')} failed: {d.get('error')}"
        return f"✔️ Sub-agent {d.get('batch')}: {d.get('relevant')}/{d.get('findings')} relevant"
    if event == "rlm_reduce":
        top = "; ".join(f"{c['name']} ×{c['count']}" for c in d.get("clusters", [])[:5])
        return f"🧮 Reduce: {d.get('relevant')} relevant, {d.get('excluded')} excluded → {top}"
    if event == "validation":
        if d.get("passed"):
            pii = f", masked {d['pii_masked']}" if d.get("pii_masked") else ""
            return f"🛡️ Output guard passed: {len(d.get('cited', []))} citation(s) verified{pii}"
        return f"🛡️ **Output guard failed** (attempt {d.get('attempt')}): {'; '.join(d.get('issues', []))}"
    if event == "answer_reset":
        return "🔁 Regenerating answer after validation feedback"
    if event == "answer_replaced":
        return "🔁 Answer replaced with verified sources only"
    if event == "error":
        return f"❌ {NODE_LABELS.get(d.get('node'), d.get('node') or 'Error')}: {d.get('error') or d.get('message')}"
    if event == "node_end":
        return None
    if event == "node_start" and d.get("node") in ("respond", "output_guard"):
        return f"▶️ {NODE_LABELS[d['node']]}"
    return None
