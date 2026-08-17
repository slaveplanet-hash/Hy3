"""Capability schema — the single surface every tool, model, skill, and retriever
registers through (principle P1: "everything is a capability").

A Capability is frozen: once registered it is immutable, so the planner can rely
on it and the registry can be replaced/extended without surprising the orchestrator.
Validation runs in ``__post_init__`` so malformed capabilities fail at construction
time, never mid-plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

# Capability ids are a dotted lowercase namespace with at least one dot, e.g.
# "net.scan.lan", "model.plan", "memory.flag_bad". Segments may contain digits
# and underscores (matching the plan's own examples). This keeps the planner's
# vocabulary stable and lets ids double as a cheap capability-group selector.
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


def _no_op(*args, **kwargs):  # pragma: no cover - only invoked once wired
    """Default handler for Phase 1 capabilities; execution lands in later phases."""
    raise NotImplementedError(f"capability handler not wired in Phase 1: {args}")


class Kind(str, Enum):
    """What category of thing a capability is."""

    TOOL = "tool"
    MODEL = "model"
    SKILL = "skill"
    RETRIEVER = "retriever"


class Risk(str, Enum):
    """Risk tier — a first-class, code-enforced field (principle P4)."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    PRIVILEGED = "privileged"


@dataclass(frozen=True)
class Cost:
    """Per-call cost estimate. All fields non-negative.

    vram_gb      — resident VRAM the capability's model holds (0 for pure tools)
    usd_per_call — provider cost if any egress happens
    p50_latency_ms — rough median latency, used by the scheduler
    """

    vram_gb: float = 0.0
    usd_per_call: float = 0.0
    p50_latency_ms: int = 0

    def __post_init__(self) -> None:
        if self.vram_gb < 0 or self.usd_per_call < 0 or self.p50_latency_ms < 0:
            raise ValueError("Cost fields must be non-negative")


@dataclass(frozen=True)
class Capability:
    """One registered capability.

    ``summary`` is the single line the planner sees (<=100 chars). ``schema_in`` /
    ``schema_out`` are JSON Schema dicts. ``requires`` lists preconditions (e.g.
    "netscope_server", "elevated") that gate execution. ``handler`` is the callable
    that performs the work — left as a no-op until its phase wires it up.
    """

    id: str
    kind: Kind
    summary: str
    schema_in: dict
    schema_out: dict
    risk: Risk
    cost: Cost
    requires: tuple[str, ...]
    provenance: str
    tags: tuple[str, ...]
    handler: Callable = field(default=_no_op, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, Kind):
            raise ValueError(f"kind must be a Kind, got {self.kind!r}")
        if not isinstance(self.risk, Risk):
            raise ValueError(f"risk must be a Risk, got {self.risk!r}")
        if not isinstance(self.cost, Cost):
            raise ValueError(f"cost must be a Cost, got {self.cost!r}")
        if not _ID_RE.match(self.id):
            raise ValueError(
                f"capability id must match {_ID_RE.pattern}: {self.id!r}"
            )
        if len(self.summary) > 100:
            raise ValueError(
                f"summary must be <=100 chars (got {len(self.summary)}): {self.summary!r}"
            )
        if not isinstance(self.schema_in, dict) or not isinstance(self.schema_out, dict):
            raise ValueError("schema_in and schema_out must be dicts")
        if not isinstance(self.requires, tuple) or not all(
            isinstance(r, str) for r in self.requires
        ):
            raise ValueError("requires must be a tuple of str")
        if not isinstance(self.tags, tuple) or not all(
            isinstance(t, str) for t in self.tags
        ):
            raise ValueError("tags must be a tuple of str")
        # Defensive normalization so list inputs are accepted too.
        object.__setattr__(self, "requires", tuple(self.requires))
        object.__setattr__(self, "tags", tuple(self.tags))

    @classmethod
    def build(
        cls,
        *,
        id: str,
        kind,
        summary: str,
        risk,
        tags: tuple[str, ...] = (),
        requires: tuple[str, ...] = (),
        schema_in: dict | None = None,
        schema_out: dict | None = None,
        cost: Cost | None = None,
        provenance: str = "builtin",
        handler: Callable = _no_op,
    ) -> "Capability":
        """Concise constructor: accepts Kind/Risk as enums or strings, fills defaults."""
        k = kind if isinstance(kind, Kind) else Kind(kind)
        r = risk if isinstance(risk, Risk) else Risk(risk)
        return cls(
            id=id,
            kind=k,
            summary=summary,
            risk=r,
            schema_in=schema_in if schema_in is not None else {},
            schema_out=schema_out if schema_out is not None else {},
            cost=cost if cost is not None else Cost(),
            requires=tuple(requires),
            provenance=provenance,
            tags=tuple(tags),
            handler=handler,
        )

    @property
    def text(self) -> str:
        """The text used for embedding/retrieval: summary plus its tags."""
        return f"{self.summary} {' '.join(self.tags)}"
