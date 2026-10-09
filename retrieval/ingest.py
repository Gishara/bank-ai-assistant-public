"""Build the search indexes.

    python -m retrieval.ingest            # local index, plus Pinecone if configured
    python -m retrieval.ingest --local    # local index only

Writes data/index/chunks.jsonl and data/index/bm25.json (always), then, with a
PINECONE_API_KEY, creates a serverless dotproduct index and upserts dense +
sparse vectors into one namespace per department.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict

from core.config import get_settings
from retrieval.bm25 import BM25Encoder
from retrieval.chunking import Chunk, chunk_document, load_corpus

EMBED_BATCH = 90  # under the inference API's 96-input limit


def build_local(settings) -> tuple[list[Chunk], BM25Encoder]:
    docs = load_corpus(settings.corpus_dir)
    chunks = [c for d in docs for c in chunk_document(d)]
    encoder = BM25Encoder().fit([c.text for c in chunks])
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    encoder.save(settings.index_dir / "bm25.json")
    with (settings.index_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps({"id": c.id, "metadata": c.metadata()}) + "\n")
    print(f"Local index: {len(docs)} documents, {len(chunks)} chunks -> {settings.index_dir}")
    return chunks, encoder


def build_pinecone(settings, chunks: list[Chunk], encoder: BM25Encoder) -> None:
    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=settings.pinecone_api_key)
    if not pc.has_index(settings.pinecone_index):
        print(f"Creating index {settings.pinecone_index} (dotproduct, dim {settings.embed_dimension})")
        pc.create_index(name=settings.pinecone_index, dimension=settings.embed_dimension, metric="dotproduct",
                        spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region))
        while not pc.describe_index(settings.pinecone_index).status.ready:
            time.sleep(2)
    index = pc.Index(name=settings.pinecone_index)

    by_ns: dict[str, list[dict]] = defaultdict(list)
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start:start + EMBED_BATCH]
        embeddings = pc.inference.embed(model=settings.embed_model, inputs=[c.text for c in batch],
                                        parameters={"input_type": "passage", "truncate": "END"})
        for chunk, emb in zip(batch, embeddings):
            by_ns[chunk.department].append({
                "id": chunk.id,
                "values": list(emb.values),
                "sparse_values": encoder.encode_document(chunk.text),
                "metadata": chunk.metadata(),
            })
    for ns, vectors in by_ns.items():
        index.upsert(vectors=vectors, namespace=ns, batch_size=50, show_progress=False)
        print(f"  upserted {len(vectors):3d} vectors into namespace '{ns}'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--local", action="store_true", help="skip Pinecone")
    args = parser.parse_args()
    settings = get_settings()
    chunks, encoder = build_local(settings)
    if args.local or not settings.pinecone_enabled:
        print("Pinecone skipped (no PINECONE_API_KEY or --local).")
        return
    build_pinecone(settings, chunks, encoder)


if __name__ == "__main__":
    main()
