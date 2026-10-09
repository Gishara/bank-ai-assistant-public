# Bank AI Assistant

A knowledge assistant for bank staff. Ask it about internal policies, runbooks, incident reports, architecture docs, product specs or meeting notes, and it answers with citations, streams the response, and shows its work in a live activity panel. Access is role-based, so people only ever see what they're cleared for.

A few things worth knowing about how it's built:

- **Multi-agent, via LangGraph.** A supervisor decides, hop by hop, whether the next step is retrieval, research, a tool call or an admin action, then runs a guarded answer loop.
- **Hybrid search on Pinecone.** Dense + BM25 sparse vectors in one `dotproduct` index, metadata filtering, hosted reranking, and every answer traces back to a source.
- **A research agent for the bigger questions.** When a question spans the whole corpus, the model writes a short Python search plan, a sandbox runs it, and sub-agents read the selected documents in parallel. Batches that are too big split themselves and recurse.
- **Security lives in code, not in the prompt.** Tools are filtered by role before the model ever sees them, a gateway re-checks every call, ACL filters are applied server-side, citations are validated, and admin actions wait for human approval.
- **You can see what it's doing.** LangSmith tracing, plus an activity panel in the UI driven by typed SSE events.

Diagrams of how it all fits together are in [`docs/architecture.html`](docs/architecture.html).

---

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,dev]"
cp .env.example .env            # add ANTHROPIC_API_KEY (and optionally PINECONE / LANGSMITH keys)

python scripts/generate_corpus.py   # already committed; regenerates the same files
python -m retrieval.ingest           # local index always; Pinecone too if PINECONE_API_KEY is set

# three terminals
python -m mcp_server.server                       # MCP server on :8001
uvicorn api.main:app --port 8000                  # API
streamlit run ui/streamlit_app.py                 # UI on :8501
```

In VS Code: open the folder, select the `.venv` interpreter, then pick **Full stack (MCP + API + UI)** in Run and Debug and press F5. Tests appear in the Testing panel.

Or with Docker (after filling in `.env`):

```bash
docker compose up --build
docker compose run --rm api python -m retrieval.ingest   # one-off Pinecone upsert
```

Demo users (password `demo123` for all):

| User | Role | Can |
|---|---|---|
| `viewer` | Viewer | Search and read public and internal documents |
| `analyst` | Analyst | + confidential documents, Python analysis, MCP lookups |
| `admin` | Administrator | + restricted documents, audit log, reindex (with approval), fault injection |

Without `PINECONE_API_KEY` the assistant runs on the local BM25 index and says so in every answer (keyword-only mode). Without an LLM key, nothing that needs a model will run, but the test suite still passes (see Testing).

---

## How a question flows

```
POST /chat ─ auth (JWT) ─ rate limit ─ input guard ──► LangGraph run (checkpointed per user+thread)

prepare ─► supervisor ─┬► retrieve ──┐   (workers return to the supervisor, max 4 hops)
  memory     route      ├► research ──┤
  recall                ├► tools ─────┤
                        ├► admin ─────┘── interrupt() for approval
                        └► respond ─► output_guard ─fail once─► respond
                                           └─pass─► memory_write ─► END
```

The API streams three kinds of events over one SSE connection: `token` (answer text from the `respond` node only), activity events (`route`, `retrieval`, `tool_call`, `rlm_split`, `validation`, `memory`, ...), and a `final` payload with the answer, citations, sources, research tables and the LangSmith run id.

---

## Where things live

| Feature | Where |
|---|---|
| Multi-agent design, conditional routing, subgraphs, state | `graph/build.py`, `graph/nodes.py`, `graph/state.py`, `rlm/graph.py` |
| Error isolation ("butterfly effect") | `worker()` wrapper in `graph/nodes.py`; gateway returns `ToolOutcome` instead of raising |
| Pinecone hybrid search, metadata filters, attribution, reranking | `retrieval/store.py`, `retrieval/filters.py`, `retrieval/bm25.py`, `retrieval/ingest.py` |
| RLM (recursive decomposition, Python search plans) | `rlm/graph.py`, `rlm/prompts.py`, `security/sandbox*.py` |
| Short- and long-term memory | `prepare` and `memory_write` in `graph/nodes.py` (checkpointer + LangGraph Store) |
| RBAC that the agent cannot bypass | `core/rbac.py`, `tools/gateway.py`, `retrieval/filters.py` |
| MCP server and client | `mcp_server/server.py`, `tools/mcp_client.py` |
| Python analysis tool | `python_analysis` in `tools/registry.py` |
| Prompt-injection defense, input validation, citation validation, brand rules | `security/injection.py`, `security/output_guard.py`, `security/brand_policy.py`, `security/pii.py` |
| Streaming, async, rate limiting, structured errors, logging | `api/main.py`, `api/runner.py`, `api/ratelimit.py`, `core/logging.py` |
| Graceful degradation (LLM, Pinecone, MCP, timeouts) | `core/llm.py`, `core/resilience.py`, `retrieval/store.py`, `extractive_answer` in `graph/nodes.py` |
| LangSmith tracing and feedback | env-configured tracing; `/feedback` in `api/main.py` |
| Activity panel | `ui/streamlit_app.py`, `ui/activity.py` |
| Bonus: HITL, reranking, long-term memory, Docker, feedback | `admin` node, `PineconeStore.rerank`, Store, `docker-compose.yml`, thumbs in UI |

---

## Design decisions

**Supervisor that re-plans each hop, rather than a fixed pipeline.** Questions differ: some need one search, some need research plus a data lookup. The supervisor sees what has run and what was found, and stops as soon as evidence is enough. Loops are bounded by a hop budget (4) and a repeated-step check, both enforced in code.

**A tool gateway as the single path to data.** Every call to Pinecone, MCP, the sandbox or an admin action goes through `ToolGateway.execute`, which re-checks the role, enforces approval, validates arguments with Pydantic (`extra="forbid"`), applies timeouts, strips injected instructions from results and writes an audit entry. RBAC, timeouts and auditing are written once.

**Authorization never depends on model output.** The user id travels in the run config from the verified JWT; the role is looked up in the user store. Tools are filtered by role before they are bound, so a viewer's model never sees analyst or admin tools. Search filters the model may set have no access-level field; the ACL clause is added server-side and wraps them; results are post-filtered again by role. The research sandbox only receives documents the user may read.

**Research as an RLM, not as a long context.** The planner sees catalog statistics, never document bodies, and writes a Python plan. The sandbox executes it; `emit()` decides the batches. Sub-agents run on the small model in parallel (`Send`), and a batch above the token limit splits itself and recurses (`Command(goto=[Send, Send])`, depth ≤ 2). The reducer is plain Python over typed findings, so counts in the answer are computed. A failed plan is retried once with its error; a second failure falls back to keyword ranking.

**Validation after generation.** The output guard checks that every `[DOC-ID §Section]` names a document retrieved in this turn and every `[tool:name]` a tool that ran. It also checks for a system-prompt canary and brand violations, and masks card, NIC, phone and account numbers. On failure the answer is regenerated once with the issues as feedback. On a second failure the user gets only the verified source list.

**Model split.** The large model handles routing, research planning and the final answer, where quality decides the outcome. The small model handles steps that run many times per question (batch analysis, memory extraction, summaries), where cost and latency multiply. Both are configurable strings (`LLM_LARGE`, `LLM_SMALL`), with an optional `LLM_FALLBACK` from another provider.

**Embeddings and reranking on Pinecone Inference** (`multilingual-e5-large`, `bge-reranker-v2-m3`) so the stack needs one vector-store key, not a second embeddings provider. BM25 is implemented locally (`retrieval/bm25.py`) so it works offline and doubles as the degraded-mode index.

**Memory.** Short-term: the checkpointer keeps full state per thread, and after 16 messages older turns are folded into a running summary with the small model. Long-term: a LangGraph Store namespaced `("users", user_id)` holds facts users state about themselves. Facts are written only after the answer passed validation and only when the user spoke in the first person, so an injected document cannot become a memory.

## Assumptions

- Authentication uses hardcoded users with JWT (option A). The authorization design does not change with Keycloak.
- The corpus is synthetic (55 documents, `data/README.md`) with planted recurring root causes and a ground-truth file, so the research agent's output can be scored.
- "Administrative tools" are defined as viewing the audit log and reindexing documents. Reindexing requires human approval.
- The research sandbox is available to all roles because it only reads the user's already-filtered catalog. The user-facing `python_analysis` tool is analyst and above.
- The sandbox (AST allow-list, separate interpreter with an empty environment, CPU, memory and time limits) is adequate for a POC. Production would add an OS-level sandbox such as gVisor or a managed code-execution service.
- SQLite holds checkpoints and the memory store. Moving to Postgres is a constructor change.
- The `deepagents` package was not used. The graph is plain LangGraph so every node, edge and event is explicit and traceable.

## Graceful degradation

| Failure | Behaviour | Demo |
|---|---|---|
| LLM error | Retries with backoff, then `LLM_FALLBACK` if set. Without a fallback: default routing to one search, and an extractive answer that quotes the top passages with citations. | Admin sidebar toggle "LLM provider down" |
| Pinecone down | Circuit breaker opens after 3 failures; local BM25 index answers, labelled keyword-only. | "Pinecone down" |
| MCP down | Tool returns `unavailable`; the answer names the missing source. | "MCP server down" |
| Tool timeout | `asyncio.wait_for` per tool (8 s default). | |
| Worker crash | Caught by the worker wrapper, recorded in `state.errors`, supervisor continues. | |
| Research batch fails | Other batches still count; the answer notes which documents were not analyzed. | |
| Rate limit | Per-user token bucket by role; `429` with `Retry-After`. | Send 11 quick messages as viewer |
| Invalid input | `422` with field-level details. | |

---

## Testing

```bash
pytest            # 68 tests, about 6 seconds, no API keys needed
```

Tests replace the two model entry points (`core.llm.chat`, `core.llm.structured`) with a scripted model (`tests/fakes.py`) that streams real token chunks. The research tests label incidents with their planted ground-truth cause, so they check the mechanics: plan in the sandbox, fan-out, recursive splits, single reduce, and counts that match `data/ground_truth.json`.

Coverage: RBAC and ACL filtering, retrieval filters and fallback, injection and output guards, PII masking, sandbox rejections and limits, gateway checks, MCP tools, research pipeline (including retries, recursion and failures), HITL approve/reject, worker-crash isolation, LLM-outage fallback, short and long-term memory, SSE streaming, thread isolation, rate limiting, admin endpoints.

**Evals against a live deployment** (needs real keys):

```bash
python scripts/run_evals.py --out evals/report.md
```

This runs the 19 questions in `evals/questions.jsonl`, each as its listed role, and checks cited documents, required phrases, refusals, input blocks, approval pauses and leakage. Question q07 (the payment-outage research question) is scored against the ground truth for incident recall and precision and for cluster coverage.

---

## Project layout

```
api/          FastAPI app, SSE runner, rate limiter, request schemas
core/         settings, RBAC tables, auth, logging, model factory, resilience, audit log
graph/        LangGraph state, nodes, prompts, events, graph assembly
rlm/          research subgraph: planner, batch analyzers, reducer
retrieval/    chunking, BM25, Pinecone + local stores, ingest
security/     injection screening, output guard, brand rules, PII masking, sandbox
tools/        tool registry, gateway, MCP client
mcp_server/   bank-ops MCP server and its data
ui/           Streamlit app and activity formatting
scripts/      corpus generator, eval runner
data/         corpus, ground truth
evals/        eval questions
tests/        pytest suite and the scripted model
docs/         architecture page
```
