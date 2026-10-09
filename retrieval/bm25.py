"""BM25 sparse encoder.

Produces Pinecone-compatible sparse vectors. Document vectors carry the BM25
term-frequency component and query vectors carry IDF, so their dot product is
the BM25 score. This is the same split pinecone-text uses, implemented here
without NLTK so it installs and runs offline.

Identifier-like tokens such as `INC-2026-0412` or `card-auth-service` are kept
whole and also split into parts, so exact ids match strongly and partial
words still match.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from collections import Counter
from pathlib import Path

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
STOPWORDS = frozenset("""
a an and are as at be been by can could did do does for from had has have how i if in into is it its
of on or our should so than that the their them then there these they this to was we were what when
where which while who why will with would you your about after all also any before between both each
more most no not only other over same some such through under until up very
""".split())


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS:
            continue
        tokens.append(tok)
        if any(sep in tok for sep in "-_."):
            tokens.extend(p for p in re.split(r"[-_.]", tok) if p and p not in STOPWORDS)
    return tokens


def token_index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8"))


class BM25Encoder:
    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.doc_freq: dict[int, int] = {}
        self.n_docs = 0
        self.avgdl = 0.0

    def fit(self, texts: list[str]) -> BM25Encoder:
        df: Counter[int] = Counter()
        total = 0
        for text in texts:
            tokens = tokenize(text)
            total += len(tokens)
            df.update({token_index(t) for t in tokens})
        self.doc_freq = dict(df)
        self.n_docs = len(texts)
        self.avgdl = total / max(len(texts), 1)
        return self

    def encode_document(self, text: str) -> dict:
        tokens = tokenize(text)
        tf = Counter(token_index(t) for t in tokens)
        norm = self.k1 * (1 - self.b + self.b * len(tokens) / max(self.avgdl, 1e-9))
        indices = list(tf)
        values = [tf[i] * (self.k1 + 1) / (tf[i] + norm) for i in indices]
        return {"indices": indices, "values": values}

    def encode_query(self, text: str) -> dict:
        tf = Counter(token_index(t) for t in tokenize(text))
        indices, values = [], []
        for idx in tf:
            df = self.doc_freq.get(idx, 0)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            indices.append(idx)
            values.append(idf)
        total = sum(values) or 1.0
        return {"indices": indices, "values": [v / total for v in values]}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"k1": self.k1, "b": self.b, "n_docs": self.n_docs, "avgdl": self.avgdl,
                                    "doc_freq": {str(k): v for k, v in self.doc_freq.items()}}))

    @classmethod
    def load(cls, path: Path) -> BM25Encoder:
        data = json.loads(path.read_text())
        enc = cls(data["k1"], data["b"])
        enc.n_docs, enc.avgdl = data["n_docs"], data["avgdl"]
        enc.doc_freq = {int(k): v for k, v in data["doc_freq"].items()}
        return enc
