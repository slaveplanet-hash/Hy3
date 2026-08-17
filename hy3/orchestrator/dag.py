"""DAG construction, validation, and profile-grouped scheduling (plan §7).

The boss emits ``Job`` specs (grammar-constrained JSON). ``Dag`` validates them
against the registry and the session's risk ceiling, topologically sorts them, and
groups them into contiguous same-profile batches so the scheduler can load a model at
most once per batch.

Correctness note: a batch is a contiguous subsegment of a valid topological order.
A node therefore only depends on (a) earlier nodes in the same batch or (b) nodes in
an earlier batch — never on a later batch — so running batches in order, jobs in topo
order, always satisfies dependencies.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from hy3.registry.capability import Risk

_RISK_ORDER = {
    Risk.READ: 0,
    Risk.WRITE: 1,
    Risk.DESTRUCTIVE: 2,
    Risk.PRIVILEGED: 3,
}


def risk_level(risk: Risk) -> int:
    """Ordinal rank of a risk tier (higher == more dangerous)."""
    return _RISK_ORDER[risk]


class DagError(Exception):
    """Raised when a plan fails validation (cycle, unknown cap, over-ceiling, ...)."""


@dataclass
class Job:
    """One unit of work emitted by the boss.

    ``capability_id`` and ``profile`` are indirections — never raw model names or
    shell strings (plan §7). ``acceptance`` is the machine-checkable success gate.
    """

    id: str
    capability_id: str
    profile: str
    depends_on: tuple[str, ...] = ()
    inputs: dict = field(default_factory=dict)
    acceptance: dict = field(default_factory=lambda: {"type": "none"})
    risk: Risk = Risk.READ
    max_tokens: int | None = None
    retries: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        raw_risk = d.get("risk", "read")
        risk = raw_risk if isinstance(raw_risk, Risk) else Risk(raw_risk)
        acc = d.get("acceptance")
        return cls(
            id=d["id"],
            capability_id=d["capability_id"],
            profile=d.get("profile", "boss"),
            depends_on=tuple(d.get("depends_on", ())),
            inputs=d.get("inputs") or {},
            acceptance=acc if acc is not None else {"type": "none"},
            risk=risk,
            max_tokens=d.get("max_tokens"),
            retries=int(d.get("retries", 0)),
        )

    @property
    def acceptance_type(self) -> str:
        return (self.acceptance or {}).get("type", "none")


class Dag:
    def __init__(
        self,
        jobs: Iterable[Job],
        *,
        capability_ids: Sequence[str],
        session_ceiling: Risk = Risk.PRIVILEGED,
        max_jobs: int = 12,
    ) -> None:
        jobs_list = list(jobs)
        self._jobs = {j.id: j for j in jobs_list}
        if len(self._jobs) != len(jobs_list):
            raise DagError("duplicate job id in plan")
        self.capability_ids = set(capability_ids)
        self.session_ceiling = session_ceiling
        self.max_jobs = max_jobs
        self.validate()

    @property
    def jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    # -- validation -----------------------------------------------------------
    def validate(self) -> None:
        if len(self._jobs) > self.max_jobs:
            raise DagError(
                f"plan has {len(self._jobs)} jobs, exceeds max_jobs={self.max_jobs}"
            )
        ids = set(self._jobs)
        for j in self._jobs.values():
            if j.capability_id not in self.capability_ids:
                raise DagError(
                    f"job {j.id!r} references unknown capability {j.capability_id!r}"
                )
            if risk_level(j.risk) > risk_level(self.session_ceiling):
                raise DagError(
                    f"job {j.id!r} risk {j.risk.value} exceeds session ceiling "
                    f"{self.session_ceiling.value}"
                )
            if j.acceptance_type == "none" and j.risk is not Risk.READ:
                raise DagError(
                    f"job {j.id!r}: 'none' acceptance is only allowed for risk=read"
                )
            for dep in j.depends_on:
                if dep not in ids:
                    raise DagError(f"job {j.id!r} depends on unknown job {dep!r}")
        self._topo = self._topo_sort()

    def _topo_sort(self) -> list[str]:
        indeg = {jid: 0 for jid in self._jobs}
        adj: dict[str, list[str]] = {jid: [] for jid in self._jobs}
        for j in self._jobs.values():
            for dep in j.depends_on:
                adj[dep].append(j.id)
                indeg[j.id] += 1
        q = deque(sorted(jid for jid, d in indeg.items() if d == 0))
        order: list[str] = []
        while q:
            n = q.popleft()
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        if len(order) != len(self._jobs):
            raise DagError("cycle detected in job dependency graph")
        return order

    # -- scheduling views -----------------------------------------------------
    def topo_order(self) -> list[str]:
        """Job ids in a valid topological order (dependencies first)."""
        return list(self._topo)

    def batches(self) -> list[tuple[str, list[Job]]]:
        """Contiguous same-profile runs of the topo order.

        Each batch shares one ``profile``; the scheduler loads that profile once for
        the whole batch. See module docstring for why this is always dependency-safe.
        """
        batches: list[tuple[str, list[Job]]] = []
        for jid in self._topo:
            j = self._jobs[jid]
            if batches and batches[-1][0] == j.profile:
                batches[-1][1].append(j)
            else:
                batches.append((j.profile, [j]))
        return batches
