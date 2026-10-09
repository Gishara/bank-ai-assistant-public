import pytest
from pydantic import ValidationError

from core.rbac import Role, allowed_access_levels, can_use_tool, tools_for
from retrieval.bm25 import tokenize
from retrieval.chunking import chunk_document, load_corpus
from retrieval.filters import SearchFilters, build_filter, matches
from retrieval.store import get_retriever


def test_role_access_levels():
    assert allowed_access_levels(Role.VIEWER) == ["public", "internal"]
    assert "confidential" in allowed_access_levels(Role.ANALYST)
    assert "restricted" not in allowed_access_levels(Role.ANALYST)
    assert "restricted" in allowed_access_levels(Role.ADMINISTRATOR)


def test_tool_scopes_fail_closed():
    assert tools_for(Role.VIEWER) == ["knowledge_search"]
    assert not can_use_tool(Role.ANALYST, "admin_reindex_documents")
    assert can_use_tool(Role.ADMINISTRATOR, "admin_reindex_documents")
    assert not can_use_tool(Role.ADMINISTRATOR, "tool_that_does_not_exist")


def test_model_filters_cannot_touch_access_level():
    with pytest.raises(ValidationError):
        SearchFilters.model_validate({"access_level": ["restricted"]})


def test_acl_clause_always_wraps_model_filters():
    flt = build_filter(Role.VIEWER, SearchFilters(document_types=["policy"]))
    assert flt["$and"][0] == {"access_level": {"$in": ["public", "internal"]}}
    restricted = {"access_level": "restricted", "document_type": "policy"}
    assert not matches(restricted, flt)
    assert matches({"access_level": "internal", "document_type": "policy"}, flt)


def test_chunks_follow_sections():
    docs = {d.doc_id: d for d in load_corpus(__import__("core.config").config.get_settings().corpus_dir)}
    chunks = chunk_document(docs["INC-2026-0412"])
    sections = [c.section for c in chunks]
    assert "Root Cause" in sections and "Timeline" in sections
    assert all(c.text.startswith("INC-2026-0412:") for c in chunks)


def test_tokenizer_keeps_ids_whole_and_split():
    toks = tokenize("See INC-2026-0412 for card-auth-service")
    assert "inc-2026-0412" in toks and "0412" in toks and "card-auth-service" in toks and "auth" in toks


async def test_viewer_never_sees_confidential_documents(viewer, analyst):
    q = "fraud score decline thresholds card not present"
    viewer_hits = (await get_retriever().search(q, viewer.role)).hits
    analyst_hits = (await get_retriever().search(q, analyst.role)).hits
    assert all(h.metadata["access_level"] in ("public", "internal") for h in viewer_hits)
    assert "POL-RSK-004" not in {h.doc_id for h in viewer_hits}
    assert analyst_hits[0].doc_id == "POL-RSK-004"


async def test_restricted_document_only_for_admin(analyst, admin):
    q = "master key custodians key ceremony"
    assert "POL-SEC-009" not in {h.doc_id for h in (await get_retriever().search(q, analyst.role)).hits}
    assert "POL-SEC-009" in {h.doc_id for h in (await get_retriever().search(q, admin.role)).hits}


async def test_filters_and_keyword_fallback(viewer):
    res = await get_retriever().search("payment outage root cause", viewer.role,
                                       SearchFilters(document_types=["incident"], date_from="2026-06-01"))
    assert res.mode == "keyword" and res.degraded_reason
    assert res.hits and all(h.metadata["document_type"] == "incident" for h in res.hits)
    assert all(h.metadata["created_date"] >= "2026-06-01" for h in res.hits)


async def test_id_queries_use_lower_alpha_and_find_the_document(viewer):
    r = get_retriever()
    assert r.alpha_for("What happened in INC-2025-1203?") < r.alpha_for("what happened last december")
    hits = (await r.search("What happened in INC-2025-1203?", viewer.role)).hits
    assert "INC-2025-1203" in {h.doc_id for h in hits[:3]}
