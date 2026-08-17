"""RAG capability loader — extension point.

RAG-backed retrievers (plan §8/§11) will register here, one ``Capability`` per
corpus, e.g. ``rag.search`` over the Network MD articles and the operator's docs,
with ``provenance="rag:<corpus>"``. ``rag.search`` is currently seeded from
``builtin.py`` so routing works today; additional per-corpus retrievers land here
when the RAG ingestion pipeline is built (Phase 4). Returns ``[]`` for now to avoid
duplicating the seed id.
"""
from __future__ import annotations

from ..capability import Capability


def load() -> list[Capability]:
    """Per-corpus RAG retrievers are not ingested yet; return an empty set."""
    return []
