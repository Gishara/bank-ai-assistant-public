"""Search backends and the hybrid retriever.

`Retriever.search` is the only entry point. It always:
  1. builds the ACL filter from the caller's role (never from model output),
  2. tries Pinecone hybrid search behind a circuit breaker,
  3. falls back to the local BM25 index if Pinecone is down,
  4. reranks with Pinecone's hosted reranker when available,
  5. drops any hit the role may not read, as a second check after the filter.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.config import get_settings
from core.logging import get_logger, log_event
from core.rbac import Role, can_read
from core.resilience import CircuitOpen, InjectedFault, breakers, check_fault
from retrieval.bm25 import BM25Encoder
from retrieval.filters import SearchFilters, build_filter, matches, namespaces_for

log = get_logger(__name__)
ID_PATTERN = re.compile(r"\b(?:INC|POL|ARC|RB|SPEC|MTG)-[A-Z0-9]+-\d{3,4}\b", re.I)


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    score: float
    metadata: dict

    def citation(self) -> str:
        return f"[{self.doc_id} §{self.section}]"


@dataclass
class RetrievalResult:
    hits: list[Hit]
    mode: str  # "hybrid" or "keyword"
    reranked: bool
    alpha: float
    namespaces: list[str]
    degraded_reason: str | None = None
    filter: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Local keyword index (fallback and offline mode)
# ---------------------------------------------------------------------------

class LocalStore:
    def __init__(self, index_dir: Path) -> None:
        chunks_path = index_dir / "chunks.jsonl"
        if not chunks_path.exists():
            raise FileNotFoundError(f"{chunks_path} missing. Run: python -m retrieval.ingest")
        self.chunks = [json.loads(line) for line in chunks_path.read_text().splitlines() if line.strip()]
        self.encoder = BM25Encoder.load(index_dir / "bm25.json")
        self._doc_vecs = [self._as_dict(self.encoder.encode_document(c["metadata"]["text"])) for c in self.chunks]

    @staticmethod
    def _as_dict(sparse: dict) -> dict[int, float]:
        return dict(zip(sparse["indices"], sparse["values"]))

    def search(self, query: str, flt: dict, top_k: int) -> list[Hit]:
        q = self._as_dict(self.encoder.encode_query(query))
        scored = []
        for chunk, vec in zip(self.chunks, self._doc_vecs):
            meta = chunk["metadata"]
            if not matches(meta, flt):
                continue
            score = sum(w * vec.get(i, 0.0) for i, w in q.items())
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda s: -s[0])
        return [_hit(c["id"], c["metadata"], s) for s, c in scored[:top_k]]


def _hit(chunk_id: str, meta: dict, score: float) -> Hit:
    return Hit(chunk_id=chunk_id, doc_id=meta["doc_id"], title=meta["title"], section=meta["section"],
               text=meta["text"], score=float(score), metadata=meta)


# ---------------------------------------------------------------------------
# Pinecone hybrid index
# ---------------------------------------------------------------------------

class PineconeStore:
    def __init__(self) -> None:
        from pinecone import Pinecone

        s = get_settings()
        self.settings = s
        self.pc = Pinecone(api_key=s.pinecone_api_key)
        self.index = self.pc.Index(name=s.pinecone_index)

    def embed_query(self, text: str) -> list[float]:
        res = self.pc.inference.embed(model=self.settings.embed_model, inputs=[text],
                                      parameters={"input_type": "query", "truncate": "END"})
        return list(res[0].values)

    def query_namespace(self, ns: str, dense: list[float], sparse: dict, flt: dict, top_k: int) -> list[Hit]:
        res = self.index.query(namespace=ns, top_k=top_k, vector=dense, sparse_vector=sparse,
                               filter=flt, include_metadata=True)
        return [_hit(m.id, dict(m.metadata), m.score) for m in res.matches]

    def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        if not hits:
            return hits
        res = self.pc.inference.rerank(model=self.settings.rerank_model, query=query,
                                       documents=[{"id": h.chunk_id, "text": h.text} for h in hits],
                                       top_n=min(top_n, len(hits)), return_documents=False)
        ranked = []
        for item in res.data:
            hit = hits[item.index]
            hit.score = float(item.score)
            ranked.append(hit)
        return ranked


@lru_cache
def _local_store() -> LocalStore:
    return LocalStore(get_settings().index_dir)


@lru_cache
def _pinecone_store() -> PineconeStore:
    return PineconeStore()


def _scale(dense: list[float], sparse: dict, alpha: float) -> tuple[list[float], dict]:
    """Convex combination: score = alpha*dense + (1-alpha)*sparse under dotproduct."""
    return ([v * alpha for v in dense],
            {"indices": sparse["indices"], "values": [v * (1 - alpha) for v in sparse["values"]]})


class Retriever:
    def __init__(self) -> None:
        self.settings = get_settings()

    def alpha_for(self, query: str) -> float:
        return self.settings.hybrid_alpha_ids if ID_PATTERN.search(query) else self.settings.hybrid_alpha

    async def _pinecone_search(self, query: str, flt: dict, namespaces: list[str], alpha: float) -> list[Hit]:
        check_fault("pinecone")
        store = _pinecone_store()
        local = _local_store()
        dense = await asyncio.to_thread(store.embed_query, query)
        dense, sparse = _scale(dense, local.encoder.encode_query(query), alpha)
        top_k = self.settings.retrieve_top_k
        per_ns = await asyncio.gather(*(asyncio.to_thread(store.query_namespace, ns, dense, sparse, flt, top_k)
                                        for ns in namespaces))
        merged = sorted((h for hits in per_ns for h in hits), key=lambda h: -h.score)[:top_k]
        return merged

    async def search(self, query: str, role: Role, filters: SearchFilters | None = None,
                     top_n: int | None = None) -> RetrievalResult:
        top_n = top_n or self.settings.rerank_top_n
        flt = build_filter(role, filters)
        namespaces = namespaces_for(filters)
        alpha = self.alpha_for(query)
        mode, reranked, reason = "hybrid", False, None
        hits: list[Hit] = []

        if self.settings.pinecone_enabled:
            try:
                hits = await breakers["pinecone"].call(lambda: self._pinecone_search(query, flt, namespaces, alpha))
                try:
                    hits = await asyncio.to_thread(_pinecone_store().rerank, query, hits, top_n)
                    reranked = True
                except Exception as exc:  # reranking is an optimization; keep hybrid order
                    log_event(log, "rerank_failed", error=str(exc))
                    hits = hits[:top_n]
            except (CircuitOpen, InjectedFault, Exception) as exc:
                mode, reason = "keyword", f"Vector search unavailable ({type(exc).__name__}: {exc})"
        else:
            mode, reason = "keyword", "Pinecone not configured; using local keyword index"

        if mode == "keyword":
            hits = await asyncio.to_thread(_local_store().search, query, flt, top_n)

        # Defense in depth: never return a chunk the role cannot read, even if
        # a backend ignored the filter.
        visible = [h for h in hits if can_read(role, h.metadata.get("access_level", "restricted"))]
        if len(visible) != len(hits):
            log_event(log, "acl_postfilter_dropped", dropped=len(hits) - len(visible))
        log_event(log, "retrieval", mode=mode, hits=len(visible), alpha=alpha, reranked=reranked)
        return RetrievalResult(hits=visible, mode=mode, reranked=reranked, alpha=alpha,
                               namespaces=namespaces, degraded_reason=reason, filter=flt)


@lru_cache
def get_retriever() -> Retriever:
    return Retriever()
