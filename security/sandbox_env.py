"""Names available inside the sandbox, built in the child process.

`rlm` kind (research plans):
    catalog       list[Doc]  documents the user may read; metadata plus .text
    today, date, timedelta, Counter
    grep(docs, pattern)            docs whose text matches a regex (case-insensitive)
    bm25_rank(docs, query, top=None)  docs sorted by keyword relevance
    chunk(items, size)             split a list into batches
    emit(batches, task)            hand batches of docs to sub-agents (call once)

`analysis` kind (python_analysis tool):
    incidents     list[dict] structured incident records
    docs          list[Doc] documents the user may read
    Counter, statistics helpers mean/median, date, timedelta
    Set `result = ...` and/or print().
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from statistics import mean, median


class Doc:
    __slots__ = ("doc_id", "title", "document_type", "department", "access_level", "created_date",
                 "tags", "severity", "services", "text")

    def __init__(self, d: dict) -> None:
        self.doc_id = d["doc_id"]
        self.title = d["title"]
        self.document_type = d["document_type"]
        self.department = d["department"]
        self.access_level = d["access_level"]
        self.created_date = date.fromisoformat(d["created_date"])
        self.tags = list(d.get("tags", []))
        self.severity = d.get("severity")
        self.services = list(d.get("services", []))
        self.text = d.get("text", "")

    def __repr__(self) -> str:
        return f"Doc({self.doc_id}, {self.document_type}, {self.created_date})"


def _ids(items) -> list[str]:
    return [i.doc_id if isinstance(i, Doc) else str(i) for i in items]


def build(kind: str, data: dict) -> tuple[dict, dict]:
    state: dict = {}
    docs = [Doc(d) for d in data.get("docs", [])]

    def grep(items, pattern):
        rx = re.compile(pattern, re.I)
        return [d for d in items if rx.search(d.title) or rx.search(d.text)]

    def bm25_rank(items, query, top=None):
        from retrieval.bm25 import BM25Encoder

        items = list(items)
        if not items:
            return []
        enc = BM25Encoder().fit([d.text for d in items])
        q = enc.encode_query(query)
        qmap = dict(zip(q["indices"], q["values"]))

        def score(d):
            v = enc.encode_document(d.text)
            return sum(qmap.get(i, 0.0) * w for i, w in zip(v["indices"], v["values"]))

        ranked = sorted(items, key=score, reverse=True)
        return ranked[:top] if top else ranked

    def chunk(items, size):
        items = list(items)
        size = max(1, int(size))
        return [items[i:i + size] for i in range(0, len(items), size)]

    def emit(batches, task):
        if "emitted" in state:
            raise RuntimeError("emit() may be called only once")
        state["emitted"] = {"batches": [_ids(b) for b in batches], "task": str(task)}

    common = {"date": date, "timedelta": timedelta, "Counter": Counter, "today": date.fromisoformat(data["today"])}
    if kind == "rlm":
        env = common | {"catalog": docs, "grep": grep, "bm25_rank": bm25_rank, "chunk": chunk, "emit": emit}
    elif kind == "analysis":
        env = common | {"incidents": data.get("incidents", []), "docs": docs, "mean": mean, "median": median,
                        "grep": grep}
    else:
        raise ValueError(f"unknown sandbox kind {kind!r}")
    return env, state
