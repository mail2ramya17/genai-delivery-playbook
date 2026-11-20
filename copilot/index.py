"""In-memory TF-IDF vector index with per-user ACL trimming.

Stands in for Azure AI Search / OpenSearch so the repo runs anywhere. The important
property is the same as in production: the ACL filter is applied *inside* the
search call, before ranking, never as a post-processing step in the app.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .ingestion import Chunk

STOPWORDS = frozenset(
    "a an and are as at be by can do for from how i if in is it my of on or the to "
    "what when where which who why will with you your me we our does".split()
)


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


class VectorIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = list(chunks)
        df: Counter[str] = Counter()
        self._tf = []
        for chunk in self.chunks:
            terms = Counter(tokenize(chunk.title + " " + chunk.text))
            self._tf.append(terms)
            df.update(terms.keys())
        n = len(self.chunks)
        self._idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self._vectors = [self._weigh(tf) for tf in self._tf]

    def _weigh(self, tf: Counter[str]) -> dict[str, float]:
        vec = {t: c * self._idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, query: str, user_groups: set[str], top_k: int = 5,
               min_score: float = 0.05) -> list[tuple[Chunk, float]]:
        """Return the top_k chunks the user is entitled to see (security trimming)."""
        if not user_groups:
            return []  # fail closed: no identity, no documents
        qvec = self._weigh(Counter(tokenize(query)))
        results = []
        for chunk, vec in zip(self.chunks, self._vectors):
            if not (chunk.groups & user_groups):
                continue  # ACL filter happens before scoring
            score = sum(w * vec.get(t, 0.0) for t, w in qvec.items())
            if score >= min_score:
                results.append((chunk, score))
        results.sort(key=lambda r: r[1], reverse=True)
        return results[:top_k]
