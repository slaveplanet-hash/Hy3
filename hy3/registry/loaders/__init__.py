"""Capability loaders.

Each loader returns a list of ``Capability`` objects. The registry aggregates them
so adding a new source (MCP server, skill library, RAG corpus) is a matter of
filling in one loader, not touching the registry core.
"""
from __future__ import annotations

from ..capability import Capability
from . import builtin, mcp, rag, skills

_LOADERS = (builtin, mcp, rag, skills)


def load_all() -> list[Capability]:
    """Load capabilities from every registered loader, in order."""
    out: list[Capability] = []
    for mod in _LOADERS:
        out.extend(mod.load())
    return out


__all__ = ["load_all", "builtin", "mcp", "rag", "skills", "Capability"]
