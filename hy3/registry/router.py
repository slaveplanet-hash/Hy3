"""Two-stage capability routing (plan §5, a P6 corollary).

A small boss model cannot hold 200 capability descriptions, so we never send the
full list to the planner. Instead:

  1. Embed the goal (or sub-goal). Score it against every capability's
     ``summary + tags`` embedding; take the top-k (~15).
  2. Always union in a small pinned set the planner must always be able to reach
     (``plan.replan``, ``memory.search``, ``report.write``).
  3. The orchestrator renders only that final set into the planner prompt.

The ``Embedder`` is pluggable. Phase 1 ships ``LexicalEmbedder`` — a dependency-free
TF-IDF vectorizer — so routing works with zero model downloads and is fully
testable. When Phase 2 brings the ``embed`` provider, swap in a real embedding
model by passing a different ``Embedder``; the two-stage logic is unchanged.
"""
from __future__ import annotations

import math
import re
from typing import Protocol, Sequence

from .capability import Capability

_STOP = {
    "a", "an", "the", "of", "to", "for", "and", "or", "in", "on", "at", "by",
    "with", "from", "into", "as", "is", "are", "be", "my", "me", "you", "it",
    "this", "that", "what", "which", "how", "why", "do", "does", "did", "can",
    "will", "would", "should", "i", "we", "they", "them", "their", "our",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens, dropping short tokens and stopwords."""
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        tok = m.group(0)
        if len(tok) < 2 or tok in _STOP:
            continue
        out.append(tok)
    return out


class Embedder(Protocol):
    """Anything that turns text into a fixed-length float vector."""

    dim: int

    def embed(self, text: str) -> list[float]: ...

    def fit(self, capabilities: Sequence[Capability]) -> None: ...


class LexicalEmbedder:
    """TF-IDF over a vocabulary built from the capability corpus.

    No external dependency, deterministic, and good enough for lexical routing
    over a few hundred capabilities. IDF down-weights ubiquitous words
    ("network", "list") so a specific goal still surfaces its best matches.
    """

    def __init__(self, dim: int | None = None) -> None:
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._n: int = 0
        self.dim: int = 0
        self._dim_hint = dim

    def fit(self, capabilities: Sequence[Capability]) -> None:
        self._n = len(capabilities)
        df: dict[str, int] = {}
        for cap in capabilities:
            seen: set[str] = set()
            for tok in _tokenize(cap.text):
                seen.add(tok)
            for tok in seen:
                df[tok] = df.get(tok, 0) + 1
        self._vocab = {tok: i for i, tok in enumerate(sorted(df))}
        for tok, d in df.items():
            # Smoothed IDF.
            self._idf[tok] = math.log((self._n + 1) / (d + 1)) + 1.0
        self.dim = self._dim_hint or len(self._vocab)

    def _vec(self, tokens: list[str]) -> list[float]:
        vec = [0.0] * len(self._vocab)
        tf: dict[int, float] = {}
        for tok in tokens:
            idx = self._vocab.get(tok)
            if idx is None:
                continue
            tf[idx] = tf.get(idx, 0.0) + 1.0
        for idx, count in tf.items():
            vec[idx] = (1.0 + math.log(count)) * self._idf.get(
                list(self._vocab)[idx], 1.0
            )
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, text: str) -> list[float]:
        return self._vec(_tokenize(text))


def _cosine(a: list[float], b: list[float]) -> float:
    """Dot product of two L2-normalized vectors (both already normalized)."""
    return sum(x * y for x, y in zip(a, b))


class TwoStageRouter:
    """Embed a goal, take the top-k capabilities, union the pinned set."""

    # Always available to the planner regardless of goal similarity.
    DEFAULT_PINNED = ("plan.replan", "memory.search", "report.write")

    def __init__(
        self,
        capabilities: Sequence[Capability],
        embedder: Embedder | None = None,
        top_k: int = 15,
        pinned: Sequence[str] = DEFAULT_PINNED,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        self.top_k = top_k
        self.pinned = tuple(pinned)
        self.embedder = embedder or LexicalEmbedder()
        if not hasattr(self.embedder, "fit"):
            raise ValueError("embedder must implement fit()")
        self.embedder.fit(list(capabilities))
        self._by_id: dict[str, Capability] = {c.id: c for c in capabilities}
        self._vectors: dict[str, list[float]] = {
            c.id: self.embedder.embed(c.text) for c in capabilities
        }

    def rank(self, goal: str) -> list[Capability]:
        """ANN-style top-k over capability embeddings (exact cosine; N is small)."""
        goal_vec = self.embedder.embed(goal)
        scored = sorted(
            (
                (cap, _cosine(goal_vec, self._vectors[cap.id]))
                for cap in self._by_id.values()
            ),
            key=lambda t: t[1],
            reverse=True,
        )
        return [cap for cap, _ in scored[: self.top_k]]

    def route(self, goal: str) -> list[Capability]:
        """Two-stage result the planner should actually see.

        Returns the top-k by similarity, with any pinned capabilities that were
        not already in the top-k appended (deduped). The pinned set guarantees the
        planner can always replan, search memory, and write a report.
        """
        top = self.rank(goal)
        out = list(top)
        present = {c.id for c in top}
        for pid in self.pinned:
            if pid not in present and pid in self._by_id:
                out.append(self._by_id[pid])
                present.add(pid)
        return out
