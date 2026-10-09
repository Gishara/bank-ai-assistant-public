"""Streamlit front end: chat on the left, live agent activity on the right.

    streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui.activity import describe, parse_sse  # noqa: E402

API_URL = os.environ.get("API_URL", "http://localhost:8000")
DEMO_USERS = {"viewer": "Viewer: search and read", "analyst": "Analyst: + data tools", "admin": "Administrator: + admin actions"}

st.set_page_config(page_title="Bank Knowledge Assistant", page_icon="🏦", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 3.2rem;}
.activity {font-size: 0.85rem; line-height: 1.5;}
.activity p {margin: 0 0 0.35rem 0;}
</style>""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("token", None)
ss.setdefault("user", None)
ss.setdefault("thread_id", uuid.uuid4().hex[:12])
ss.setdefault("messages", [])     # {"role", "content", "final", "activity"}
ss.setdefault("activity", [])
ss.setdefault("pending", None)    # approval request


def headers() -> dict:
    return {"Authorization": f"Bearer {ss.token}"} if ss.token else {}


def api(method: str, path: str, **kw) -> httpx.Response:
    return httpx.request(method, f"{API_URL}{path}", headers=headers(), timeout=30, **kw)


# ---------------------------------------------------------------------------
# sidebar: login, session, admin controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("🏦 Knowledge Assistant")
    if not ss.token:
        with st.form("login"):
            username = st.selectbox("Demo user", list(DEMO_USERS), format_func=lambda u: DEMO_USERS[u])
            password = st.text_input("Password", value="demo123", type="password")
            if st.form_submit_button("Sign in", use_container_width=True):
                try:
                    r = httpx.post(f"{API_URL}/auth/login", json={"username": username, "password": password}, timeout=10)
                except httpx.HTTPError as exc:
                    st.error(f"API not reachable at {API_URL}: {exc}")
                else:
                    if r.status_code == 200:
                        ss.token, ss.user = r.json()["access_token"], r.json()["user"]
                        st.rerun()
                    else:
                        st.error(r.json().get("message", "Sign-in failed"))
        st.caption("All demo users use the password `demo123`.")
        st.stop()

    u = ss.user
    st.markdown(f"**{u['name']}**  \nRole: `{u['role']}` · Dept: {u['department']}")
    st.caption("Tools: " + ", ".join(u["tools"]))
    c1, c2 = st.columns(2)
    if c1.button("New chat", use_container_width=True):
        ss.thread_id, ss.messages, ss.activity, ss.pending = uuid.uuid4().hex[:12], [], [], None
        st.rerun()
    if c2.button("Sign out", use_container_width=True):
        for k in ("token", "user", "messages", "activity", "pending"):
            ss[k] = None if k in ("token", "user", "pending") else []
        st.rerun()
    st.caption(f"Conversation `{ss.thread_id}`")

    try:
        health = api("GET", "/health").json()
        st.caption(f"Vector search: {health['vector_search']}  \nModel: {health['models']['large']}")
    except Exception:
        health = None
        st.warning("API not reachable")

    if u["role"] == "administrator" and health:
        st.divider()
        st.markdown("**Failure injection** (demo)")
        for name, label in (("llm", "LLM provider down"), ("pinecone", "Pinecone down"), ("mcp", "MCP server down")):
            on = st.toggle(label, value=health["faults"].get(name, False), key=f"fault_{name}")
            if on != health["faults"].get(name, False):
                api("POST", "/admin/faults", json={"name": name, "enabled": on})
                st.rerun()

    st.divider()
    st.markdown("**Try asking**")
    examples = [
        "What should on-call do when HSM sessions are saturated?",
        "Summarize all outage reports related to payment failures during the last year and identify recurring root causes.",
        "Who owns the service that failed in INC-2026-0412, and are they on call?",
        "What are the fraud score decline thresholds for card-not-present transactions?",
        "What was discussed in the Digital Channels sync on 18 August?",
        "Reindex all documents now.",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{hash(ex)}", use_container_width=True):
            ss.queued = ex
            st.rerun()


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------

def render_activity(container, lines: list[str]) -> None:
    container.markdown("<div class='activity'>\n\n" + "\n\n".join(lines[-80:]) + "\n\n</div>",
                       unsafe_allow_html=True)


def stream(path: str, payload: dict, answer_box, activity_box, keep_activity: bool = False) -> dict | None:
    tokens: list[str] = []
    lines: list[str] = list(ss.activity) if keep_activity else []
    final = None
    try:
        with httpx.stream("POST", f"{API_URL}{path}", json=payload, headers=headers(), timeout=None) as r:
            if r.status_code != 200:
                r.read()
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                msg = body.get("message", f"HTTP {r.status_code}")
                if r.status_code == 422 and body.get("details"):
                    msg += " " + "; ".join(f"{d['field']}: {d['message']}" for d in body["details"])
                answer_box.error(msg)
                return None
            for event, data in parse_sse(r.iter_lines()):
                if event == "token":
                    tokens.append(data["text"])
                    answer_box.markdown("".join(tokens) + " ▌")
                elif event == "answer_reset":
                    tokens = []
                    answer_box.markdown("_Rewriting the answer after validation…_")
                elif event == "approval_required":
                    ss.pending = data
                elif event == "final":
                    final = data
                elif event == "error":
                    answer_box.error(f"{data.get('message')} (request {data.get('request_id')})")
                line = describe(event, data)
                if line:
                    lines.append(line)
                    render_activity(activity_box, lines)
    except httpx.HTTPError as exc:
        answer_box.error(f"Connection to the API failed: {exc}")
        return None
    ss.activity = lines
    if final:
        final["activity"] = lines
    return final


def render_final(final: dict, key: str) -> None:
    if final.get("degraded"):
        st.warning("Answered in degraded mode: " + "; ".join(final["degraded"]))
    research = final.get("research")
    if research and research.get("clusters"):
        with st.expander(f"Research results: {research['relevant']} relevant of {research['documents_analyzed']} analyzed"):
            st.dataframe([{"Root cause": c["name"], "Incidents": c["count"], "Recurring": "yes" if c["recurring"] else "no",
                           "Documents": ", ".join(c["doc_ids"]), "First": c["first"], "Last": c["last"]}
                          for c in research["clusters"]], hide_index=True, use_container_width=True)
            if research.get("excluded"):
                st.caption("Excluded: " + "; ".join(f"{e['doc_id']} ({e['reason']})" for e in research["excluded"]))
    sources = final.get("sources") or []
    if sources:
        with st.expander(f"Sources ({sum(s['cited'] for s in sources)} cited, {len(sources)} retrieved)"):
            for s in sources:
                mark = "**cited**" if s["cited"] else "retrieved"
                st.markdown(f"- `{s['doc_id']}` {s['title']} — §{s['section']} · {mark}")
    if final.get("run_id") and final.get("status") == "complete":
        score = st.feedback("thumbs", key=f"fb_{key}")
        sent_key = f"fb_sent_{key}"
        if score is not None and not ss.get(sent_key):
            api("POST", "/feedback", json={"run_id": final["run_id"], "score": int(score)})
            ss[sent_key] = True
            st.caption("Thanks, feedback recorded.")


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------

chat_col, activity_col = st.columns([3, 2], gap="large")
with activity_col:
    st.markdown("#### Agent activity")
    activity_box = st.empty()
    if ss.activity:
        render_activity(activity_box, ss.activity)
    else:
        activity_box.caption("Steps appear here while the assistant works: routing, searches, tool calls, "
                             "research batches, validation and memory.")

with chat_col:
    st.markdown("#### Ask about policies, runbooks, incidents and architecture")
    for i, m in enumerate(ss.messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("final"):
                render_final(m["final"], str(i))

    if ss.pending:
        p = ss.pending
        with st.chat_message("assistant"):
            st.info(f"**Approval needed:** {p.get('message')}  \nRequested by {p.get('requested_by')}.")
            if ss.user["role"] == "administrator":
                a, b = st.columns(2)
                decision = None
                if a.button("Approve", type="primary", use_container_width=True):
                    decision = True
                if b.button("Reject", use_container_width=True):
                    decision = False
                if decision is not None:
                    ss.pending = None
                    box = st.empty()
                    final = stream("/chat/resume", {"thread_id": ss.thread_id, "approved": decision}, box, activity_box,
                                   keep_activity=True)
                    if final and final.get("status") == "complete":
                        ss.messages.append({"role": "assistant", "content": final["answer"], "final": final})
                    st.rerun()

prompt = st.chat_input("Ask a question") or ss.pop("queued", None)
if prompt:
    ss.messages.append({"role": "user", "content": prompt})
    with chat_col:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            box = st.empty()
            box.markdown("_Thinking…_")
            final = stream("/chat", {"message": prompt, "thread_id": ss.thread_id}, box, activity_box)
    if final and final.get("status") in ("complete", "blocked"):
        ss.messages.append({"role": "assistant", "content": final["answer"], "final": final})
    st.rerun()
