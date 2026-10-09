"""Load corpus documents and split them into citable chunks.

Chunks follow `##` sections, so every citation can name a section a reader can
find. Sections longer than MAX_WORDS are split on paragraph boundaries with
one paragraph of overlap.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

import yaml

MAX_WORDS = 350


@dataclass
class Document:
    doc_id: str
    title: str
    department: str
    document_type: str
    access_level: str
    created_date: str
    author: str
    tags: list[str]
    body: str
    path: str
    severity: str | None = None
    services: list[str] = field(default_factory=list)

    @property
    def created(self) -> date:
        return date.fromisoformat(self.created_date)


@dataclass
class Chunk:
    id: str
    doc_id: str
    title: str
    section: str
    text: str
    department: str
    document_type: str
    access_level: str
    created_date: str
    created_ts: int
    tags: list[str]
    severity: str | None = None
    services: list[str] = field(default_factory=list)

    def metadata(self) -> dict:
        """Pinecone metadata: strings, numbers and string lists only, no nulls."""
        meta = asdict(self)
        meta.pop("id")
        return {k: v for k, v in meta.items() if v is not None and v != []}


def parse_document(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not match:
        raise ValueError(f"{path}: missing front matter")
    meta = yaml.safe_load(match.group(1))
    return Document(
        doc_id=meta["doc_id"], title=meta["title"], department=meta["department"],
        document_type=meta["document_type"], access_level=meta["access_level"],
        created_date=str(meta["created_date"]), author=meta["author"], tags=list(meta.get("tags", [])),
        severity=meta.get("severity"), services=list(meta.get("services", [])),
        body=match.group(2).strip(), path=str(path),
    )


def load_corpus(corpus_dir: Path) -> list[Document]:
    docs = [parse_document(p) for p in sorted(corpus_dir.rglob("*.md")) if p.name != "README.md"]
    if not docs:
        raise FileNotFoundError(f"No documents under {corpus_dir}. Run scripts/generate_corpus.py first.")
    return docs


def _sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current, lines = "Overview", []
    for line in body.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            if any(l.strip() for l in lines):
                sections.append((current, "\n".join(lines).strip()))
            current, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if any(l.strip() for l in lines):
        sections.append((current, "\n".join(lines).strip()))
    return sections


def _windows(text: str) -> list[str]:
    if len(text.split()) <= MAX_WORDS:
        return [text]
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    windows, current = [], []
    for para in paragraphs:
        if current and len(" ".join(current + [para]).split()) > MAX_WORDS:
            windows.append("\n\n".join(current))
            current = current[-1:]  # one paragraph of overlap
        current.append(para)
    if current:
        windows.append("\n\n".join(current))
    return windows


def chunk_document(doc: Document) -> list[Chunk]:
    ts = int(datetime.combine(doc.created, time(), tzinfo=timezone.utc).timestamp())
    chunks: list[Chunk] = []
    for section, content in _sections(doc.body):
        for part in _windows(content):
            chunks.append(Chunk(
                id=f"{doc.doc_id}#{len(chunks)}", doc_id=doc.doc_id, title=doc.title, section=section,
                text=f"{doc.doc_id}: {doc.title}\nSection: {section}\n\n{part}",
                department=doc.department, document_type=doc.document_type,
                access_level=doc.access_level, created_date=doc.created_date, created_ts=ts,
                tags=doc.tags, severity=doc.severity, services=doc.services,
            ))
    return chunks
