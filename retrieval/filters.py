"""Search filters.

`SearchFilters` is what the model is allowed to ask for. It has no
access-level field and rejects unknown fields, so a model cannot widen what a
user may see. The access-control clause is added by `build_filter` from the
authenticated role and always wraps whatever the model asked for.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.rbac import Role, allowed_access_levels

DocumentType = Literal["incident", "policy", "runbook", "architecture", "product_spec", "meeting_notes"]
Department = Literal["payments", "platform", "security", "risk", "product", "hr"]
DEPARTMENTS: tuple[str, ...] = ("payments", "platform", "security", "risk", "product", "hr")


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_types: list[DocumentType] | None = Field(None, description="Restrict to these document types")
    departments: list[Department] | None = Field(None, description="Restrict to these departments")
    date_from: date | None = Field(None, description="Earliest created date, inclusive")
    date_to: date | None = Field(None, description="Latest created date, inclusive")
    severities: list[Literal["SEV1", "SEV2", "SEV3", "SEV4"]] | None = Field(None, description="Incident severities")


def _ts(d: date, end: bool = False) -> int:
    t = time(23, 59, 59) if end else time()
    return int(datetime.combine(d, t, tzinfo=timezone.utc).timestamp())


def build_filter(role: Role, filters: SearchFilters | None) -> dict:
    """Pinecone metadata filter: the ACL clause AND the model's own filters."""
    clauses: list[dict] = [{"access_level": {"$in": allowed_access_levels(role)}}]
    f = filters or SearchFilters()
    if f.document_types:
        clauses.append({"document_type": {"$in": list(f.document_types)}})
    if f.departments:
        clauses.append({"department": {"$in": list(f.departments)}})
    if f.severities:
        clauses.append({"severity": {"$in": list(f.severities)}})
    if f.date_from:
        clauses.append({"created_ts": {"$gte": _ts(f.date_from)}})
    if f.date_to:
        clauses.append({"created_ts": {"$lte": _ts(f.date_to, end=True)}})
    return {"$and": clauses}


def namespaces_for(filters: SearchFilters | None) -> list[str]:
    if filters and filters.departments:
        return list(filters.departments)
    return list(DEPARTMENTS)


def matches(meta: dict, flt: dict) -> bool:
    """Evaluate the subset of Pinecone's filter language that build_filter emits."""
    for key, cond in flt.items():
        if key == "$and":
            if not all(matches(meta, c) for c in cond):
                return False
            continue
        if key == "$or":
            if not any(matches(meta, c) for c in cond):
                return False
            continue
        value = meta.get(key)
        ops = cond if isinstance(cond, dict) else {"$eq": cond}
        for op, target in ops.items():
            if op == "$eq" and value != target:
                return False
            if op == "$ne" and value == target:
                return False
            if op == "$in":
                values = value if isinstance(value, list) else [value]
                if not any(v in target for v in values):
                    return False
            if op == "$nin":
                values = value if isinstance(value, list) else [value]
                if any(v in target for v in values):
                    return False
            if op in ("$gte", "$gt", "$lte", "$lt"):
                if value is None:
                    return False
                if op == "$gte" and not value >= target:
                    return False
                if op == "$gt" and not value > target:
                    return False
                if op == "$lte" and not value <= target:
                    return False
                if op == "$lt" and not value < target:
                    return False
    return True
