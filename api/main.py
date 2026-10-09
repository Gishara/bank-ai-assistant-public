"""FastAPI application.

    uvicorn api.main:app --port 8000
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from api.ratelimit import limiter
from api.runner import sse, stream_run
from api.schemas import ChatRequest, FaultRequest, FeedbackRequest, LoginRequest, ResumeRequest, TokenResponse
from core import audit
from core.auth import AuthError, User, authenticate, issue_token, verify_token
from core.config import get_settings
from core.logging import configure_logging, get_logger, log_event, request_id_var, user_id_var
from core.rbac import Role, tools_for
from core.resilience import breakers, faults
from graph.build import build_graph
from security import injection

log = get_logger("api")
bearer = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    configure_logging()
    settings = get_settings()
    if not (settings.index_dir / "chunks.jsonl").exists():
        from retrieval.ingest import build_local
        build_local(settings)
    settings.state_db.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(settings.state_db)) as saver, \
            AsyncSqliteStore.from_conn_string(str(settings.state_db.with_suffix(".store.sqlite"))) as store:
        await saver.setup()
        await store.setup()
        app.state.graph = build_graph(checkpointer=saver, store=store)
        log_event(log, "startup", pinecone=settings.pinecone_enabled, model=settings.llm_large,
                  faults=faults.snapshot())
        yield


app = FastAPI(title="Bank AI Assistant", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# middleware and error handling
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    started = time.monotonic()
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    log_event(log, "http", method=request.method, path=request.url.path, status=response.status_code,
              ms=int((time.monotonic() - started) * 1000))
    return response


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message,
                                                     "request_id": request_id_var.get(), **extra})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
    return _error(422, "invalid_request", "The request is invalid.", details=details)


@app.exception_handler(HTTPException)
async def http_handler(_: Request, exc: HTTPException):
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 429: "rate_limited"}.get(
        exc.status_code, "error")
    resp = _error(exc.status_code, code, str(exc.detail))
    for k, v in (exc.headers or {}).items():
        resp.headers[k] = v
    return resp


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    log.exception("unhandled")
    return _error(500, "internal_error", "Something went wrong. Quote the request id when reporting it.")


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if creds is None:
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        user = verify_token(creds.credentials)
    except AuthError as exc:
        raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc
    user_id_var.set(user.user_id)
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.ADMINISTRATOR:
        audit.record(user.user_id, user.role.value, "admin_endpoint", "denied")
        raise HTTPException(403, "Administrator role required")
    return user


async def rate_limited(user: User = Depends(current_user)) -> User:
    ok, retry_after = limiter.check(user.user_id, user.role)
    if not ok:
        raise HTTPException(429, f"Too many requests. Try again in {retry_after:.0f}s.",
                            headers={"Retry-After": str(int(retry_after))})
    return user


def _user_payload(user: User) -> dict:
    return {"user_id": user.user_id, "username": user.username, "name": user.display_name,
            "role": user.role.value, "department": user.department, "tools": tools_for(user.role)}


@app.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    try:
        user = authenticate(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    return TokenResponse(access_token=issue_token(user), user=_user_payload(user))


@app.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    return _user_payload(user)


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------

def _refusal_stream(reason: str, matches: list[str]):
    async def gen():
        run_id = str(uuid.uuid4())
        yield sse("run_start", {"run_id": run_id})
        yield sse("input_guard", {"blocked": True, "matches": matches, "reason": reason})
        text = ("I can't help with that request. It looks like an attempt to change my instructions or reach "
                "information outside your access. Please rephrase your question about our internal knowledge.")
        yield sse("token", {"text": text})
        yield sse("final", {"run_id": run_id, "status": "blocked", "answer": text, "citations": [], "sources": [],
                            "degraded": [], "errors": [], "guard": {"passed": True, "blocked_input": True}})
    return gen()


@app.post("/chat")
async def chat(body: ChatRequest, request: Request, user: User = Depends(rate_limited)):
    try:
        message = injection.validate_input(body.message)
    except injection.InputValidationError as exc:
        raise HTTPException(422, str(exc)) from exc

    verdict = injection.scan(message)
    blocked, reason = verdict.blocked, "pattern match"
    if not blocked and verdict.uncertain:
        try:
            llm_verdict = await injection.classify(message)
            blocked, reason = llm_verdict.is_injection, f"classifier: {llm_verdict.reason}"
        except Exception as exc:  # the classifier is a second opinion; other controls still apply
            log_event(log, "classifier_failed", error=str(exc))
    if blocked:
        audit.record(user.user_id, user.role.value, "chat", "blocked_injection", matches=verdict.matches,
                     reason=reason, excerpt=message[:200])
        return StreamingResponse(_refusal_stream(reason, verdict.matches), media_type="text/event-stream")

    async def gen():
        yield sse("input_guard", {"blocked": False, "score": verdict.score, "matches": verdict.matches})
        async for chunk in stream_run(request.app.state.graph, {"messages": [HumanMessage(message)]},
                                      user, body.thread_id):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/chat/resume")
async def resume(body: ResumeRequest, request: Request, user: User = Depends(require_admin)):
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": f"{user.user_id}:{body.thread_id}", "user_id": user.user_id}}
    state = await graph.aget_state(config)
    if not state.next:
        raise HTTPException(409, "Nothing is waiting for approval in this conversation.")
    audit.record(user.user_id, user.role.value, "approval", "approved" if body.approved else "rejected",
                 thread_id=body.thread_id, comment=body.comment)
    command = Command(resume={"approved": body.approved, "approver": user.display_name, "comment": body.comment})
    return StreamingResponse(stream_run(graph, command, user, body.thread_id), media_type="text/event-stream")


@app.get("/threads/{thread_id}")
async def thread_history(thread_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    config = {"configurable": {"thread_id": f"{user.user_id}:{thread_id}", "user_id": user.user_id}}
    state = await request.app.state.graph.aget_state(config)
    messages = [{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
                for m in state.values.get("messages", []) if isinstance(m, (HumanMessage, AIMessage))]
    return {"thread_id": thread_id, "messages": messages, "summary": state.values.get("summary", ""),
            "awaiting_approval": bool(state.next)}


@app.post("/feedback")
async def feedback(body: FeedbackRequest, user: User = Depends(current_user)) -> dict:
    sent = False
    if os.environ.get("LANGSMITH_API_KEY"):
        try:
            from langsmith import Client

            Client().create_feedback(run_id=body.run_id, key="user_score", score=body.score,
                                     comment=body.comment, source_info={"user_id": user.user_id})
            sent = True
        except Exception as exc:
            log_event(log, "feedback_failed", error=str(exc))
    audit.record(user.user_id, user.role.value, "feedback", "recorded", run_id=str(body.run_id),
                 score=body.score, sent_to_langsmith=sent)
    return {"recorded": True, "langsmith": sent}


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"status": "ok", "models": {"large": s.llm_large, "small": s.llm_small, "fallback": s.llm_fallback or None},
            "vector_search": "pinecone" if s.pinecone_enabled else "local keyword index",
            "circuits": {k: b.state for k, b in breakers.items()}, "faults": faults.snapshot()}


@app.get("/admin/faults")
async def get_faults(_: User = Depends(require_admin)) -> dict:
    return faults.snapshot()


@app.post("/admin/faults")
async def set_fault(body: FaultRequest, user: User = Depends(require_admin)) -> dict:
    faults.set(body.name, body.enabled)
    if not body.enabled and body.name in breakers:  # let the circuit close again right away
        breakers[body.name].failures, breakers[body.name].opened_at = 0, None
    audit.record(user.user_id, user.role.value, "fault_injection", "set", fault=body.name, enabled=body.enabled)
    return faults.snapshot()


@app.get("/admin/audit")
async def audit_log(limit: int = 50, _: User = Depends(require_admin)) -> dict:
    return {"entries": audit.recent(min(max(limit, 1), 200))}
