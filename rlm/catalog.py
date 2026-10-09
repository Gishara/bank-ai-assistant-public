"""Catalog statistics shown to the planner instead of document text."""

from __future__ import annotations

from collections import Counter


def catalog_stats(docs: list[dict]) -> str:
    if not docs:
        return "(no documents)"
    by_type = Counter(d["document_type"] for d in docs)
    by_dept = Counter(d["department"] for d in docs)
    tags = Counter(t for d in docs for t in d["tags"])
    dates = sorted(d["created_date"] for d in docs)
    sev = Counter(d["severity"] for d in docs if d.get("severity"))
    lines = [
        f"- {len(docs)} documents, created {dates[0]} to {dates[-1]}",
        "- document_type: " + ", ".join(f"{k} ({v})" for k, v in by_type.most_common()),
        "- department: " + ", ".join(f"{k} ({v})" for k, v in by_dept.most_common()),
        "- incident severity: " + (", ".join(f"{k} ({v})" for k, v in sorted(sev.items())) or "n/a"),
        "- most common tags: " + ", ".join(f"{k} ({v})" for k, v in tags.most_common(30)),
        "- sample rows:",
    ]
    for d in [x for x in docs if x["document_type"] == "incident"][:2] + docs[:1]:
        lines.append(f"    Doc({d['doc_id']!r}, type={d['document_type']!r}, dept={d['department']!r}, "
                     f"date={d['created_date']}, tags={d['tags']}, severity={d.get('severity')!r})")
    return "\n".join(lines)
