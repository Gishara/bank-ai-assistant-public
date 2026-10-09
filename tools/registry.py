"""Tool definitions: argument schemas and implementations.

Implementations receive the authenticated `User` from the gateway, never from
the model. Access scopes live in core.rbac.TOOL_SCOPES.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core import audit
from core.auth import User
from core.config import get_settings
from core.rbac import can_read
from retrieval.filters import SearchFilters
from retrieval.store import get_retriever
from security import sandbox
from tools.mcp_client import call_mcp


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeSearchArgs(Args):
    query: str = Field(description="Search query in natural language; include ids like INC-2026-0412 verbatim")
    filters: SearchFilters | None = Field(None, description="Optional metadata filters")


class PythonAnalysisArgs(Args):
    code: str = Field(description=(
        "Python code. Available: `incidents` (list of dicts: incident_id, title, date 'YYYY-MM-DD', severity, "
        "services, duration_minutes, failed_transactions, customers_affected, open_actions), `docs` (documents "
        "with .doc_id .title .document_type .department .created_date .tags .severity .text), Counter, mean, "
        "median, date, timedelta, grep(docs, pattern). No imports. Assign the answer to `result`."))


class EmployeeDirectoryArgs(Args):
    query: str = Field(description="Name, employee id, team, department or job title")


class ServiceCatalogArgs(Args):
    service_id: str | None = Field(None, description="Exact service id, e.g. card-auth-service")
    query: str | None = Field(None, description="Free-text search when the id is unknown")


class IncidentRecordsArgs(Args):
    incident_id: str | None = Field(None, description="Fetch one incident, e.g. INC-2026-0412")
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    service_id: str | None = None


class AuditLogArgs(Args):
    limit: int = Field(20, ge=1, le=100)


class ReindexArgs(Args):
    scope: Literal["local", "all"] = Field("all", description="'local' rebuilds the keyword index only; "
                                                              "'all' also re-upserts Pinecone")


Impl = Callable[[User, Any], Awaitable[dict]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[Args]
    impl: Impl
    backend: str  # for timeouts/circuit breakers and the activity panel


# --------------------------------------------------------------------------
# Implementations
# --------------------------------------------------------------------------

async def _knowledge_search(user: User, args: KnowledgeSearchArgs) -> dict:
    res = await get_retriever().search(args.query, user.role, args.filters)
    return {
        "mode": res.mode,
        "reranked": res.reranked,
        "alpha": res.alpha,
        "degraded_reason": res.degraded_reason,
        "hits": [{"chunk_id": h.chunk_id, "doc_id": h.doc_id, "title": h.title, "section": h.section,
                  "text": h.text, "score": round(h.score, 4), "document_type": h.metadata.get("document_type"),
                  "created_date": h.metadata.get("created_date"), "access_level": h.metadata.get("access_level")}
                 for h in res.hits],
    }


@lru_cache
def _all_docs() -> list[dict]:
    from retrieval.chunking import load_corpus

    return [{"doc_id": d.doc_id, "title": d.title, "document_type": d.document_type, "department": d.department,
             "access_level": d.access_level, "created_date": d.created_date, "tags": d.tags,
             "severity": d.severity, "services": d.services, "text": d.body}
            for d in load_corpus(get_settings().corpus_dir)]


def docs_for(user: User) -> list[dict]:
    """Documents this user may read. Used to build sandbox catalogs."""
    return [d for d in _all_docs() if can_read(user.role, d["access_level"])]


@lru_cache
def _incident_data() -> list[dict]:
    return json.loads((get_settings().mcp_data_dir / "incidents.json").read_text())


def incident_records_for(user: User) -> list[dict]:
    readable = {d["doc_id"] for d in docs_for(user)}
    return [r for r in _incident_data() if r["report_doc_id"] in readable]


async def _python_analysis(user: User, args: PythonAnalysisArgs) -> dict:
    data = {"today": date.today().isoformat(), "docs": docs_for(user), "incidents": incident_records_for(user)}
    res = await sandbox.run(args.code, "analysis", data, timeout_s=8)
    if not res.ok:
        raise RuntimeError(res.error)
    return {"result": res.result, "stdout": res.stdout, "duration_ms": res.duration_ms}


async def _employee_directory(user: User, args: EmployeeDirectoryArgs) -> dict:
    return await call_mcp("lookup_employee", {"query": args.query})


async def _service_catalog(user: User, args: ServiceCatalogArgs) -> dict:
    if args.service_id:
        return await call_mcp("get_service", {"service_id": args.service_id})
    return await call_mcp("search_services", {"query": args.query or ""})


async def _incident_records(user: User, args: IncidentRecordsArgs) -> dict:
    if args.incident_id:
        result = await call_mcp("get_incident", {"incident_id": args.incident_id})
        rows = [result["incident"]] if result.get("found") else []
    else:
        params = {k: (v.isoformat() if isinstance(v, date) else v)
                  for k, v in args.model_dump(exclude={"incident_id"}).items() if v is not None}
        rows = (await call_mcp("list_incidents", params))["incidents"]
    # Records follow their report's access level.
    readable = {d["doc_id"] for d in docs_for(user)}
    visible = [r for r in rows if r["report_doc_id"] in readable]
    return {"count": len(visible), "withheld": len(rows) - len(visible),
            "total_failed_transactions": sum(r["failed_transactions"] for r in visible),
            "incidents": visible}


async def _audit_log(user: User, args: AuditLogArgs) -> dict:
    return {"entries": audit.recent(args.limit)}


async def _reindex(user: User, args: ReindexArgs) -> dict:
    from retrieval import ingest, store

    settings = get_settings()
    chunks, encoder = await asyncio.to_thread(ingest.build_local, settings)
    pinecone = "skipped"
    if args.scope == "all" and settings.pinecone_enabled:
        await asyncio.to_thread(ingest.build_pinecone, settings, chunks, encoder)
        pinecone = "upserted"
    store._local_store.cache_clear()
    _all_docs.cache_clear()
    return {"chunks": len(chunks), "pinecone": pinecone}


SPECS: dict[str, ToolSpec] = {s.name: s for s in [
    ToolSpec("knowledge_search", "Search the internal knowledge base (policies, runbooks, incident reports, "
             "architecture, specs, meeting notes). Returns passages with doc ids and sections.",
             KnowledgeSearchArgs, _knowledge_search, "pinecone"),
    ToolSpec("python_analysis", "Run a short Python computation over structured incident records and "
             "documents, e.g. counts, totals, averages, grouping.", PythonAnalysisArgs, _python_analysis, "sandbox"),
    ToolSpec("employee_directory", "Look up employees: name, title, team, department, on-call status.",
             EmployeeDirectoryArgs, _employee_directory, "mcp"),
    ToolSpec("service_catalog", "Look up services: owner, tier, dependencies, dependents, runbooks.",
             ServiceCatalogArgs, _service_catalog, "mcp"),
    ToolSpec("incident_records", "Structured incident records: severity, dates, duration, failed transactions, "
             "customers affected, open actions. Filter by id, severity, date range or service.",
             IncidentRecordsArgs, _incident_records, "mcp"),
    ToolSpec("admin_view_audit_log", "Show recent audit log entries (tool calls, denials, admin actions).",
             AuditLogArgs, _audit_log, "internal"),
    ToolSpec("admin_reindex_documents", "Rebuild the search indexes from the document corpus. Requires approval.",
             ReindexArgs, _reindex, "internal"),
]}
