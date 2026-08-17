"""Capability registry — load, index, and query.

The registry is the single read surface the orchestrator and console use to discover
what the harness can do. It is built once at startup from all loaders, validates
that ids are unique, and offers filtering by ``kind``/``risk`` plus the two-stage
``retrieve(goal)`` used to trim the planner's context.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .capability import Capability, Kind, Risk
from .loaders import load_all
from .router import TwoStageRouter

_PINNED = ("plan.replan", "memory.search", "report.write")


class Registry:
    """In-memory index of every registered capability."""

    def __init__(self, capabilities: Iterable[Capability]) -> None:
        self._caps: dict[str, Capability] = {}
        for cap in capabilities:
            if cap.id in self._caps:
                raise ValueError(f"duplicate capability id: {cap.id}")
            self._caps[cap.id] = cap

    @classmethod
    def load(cls) -> "Registry":
        """Build the registry from all loaders (builtin + mcp + skills + rag)."""
        return cls(load_all())

    def all(self) -> list[Capability]:
        """All capabilities, insertion order."""
        return list(self._caps.values())

    def ids(self) -> list[str]:
        return list(self._caps)

    def get(self, cap_id: str) -> Capability | None:
        return self._caps.get(cap_id)

    def by_kind(self, kind: Kind | str) -> list[Capability]:
        k = kind if isinstance(kind, Kind) else Kind(kind)
        return [c for c in self._caps.values() if c.kind is k]

    def by_risk(self, risk: Risk | str) -> list[Capability]:
        r = risk if isinstance(risk, Risk) else Risk(risk)
        return [c for c in self._caps.values() if c.risk is r]

    def by_provenance(self, prefix: str) -> list[Capability]:
        return [c for c in self._caps.values() if c.provenance.startswith(prefix)]

    def retrieve(
        self,
        goal: str,
        top_k: int = 15,
        pinned: Sequence[str] = _PINNED,
    ) -> list[Capability]:
        """Two-stage routing: top-k similar caps unioned with the pinned set."""
        router = TwoStageRouter(self.all(), top_k=top_k, pinned=pinned)
        return router.route(goal)


__all__ = ["Registry", "Capability", "Kind", "Risk", "TwoStageRouter"]
