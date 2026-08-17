"""Profile-batched scheduler + acceptance + escalation driver (plan §7).

Runs a ``Dag`` batch-by-batch (one model load per batch), gates each job by risk,
snapshots before write-tier jobs, executes, and runs the acceptance check. Failures
retry up to the per-job budget, then escalate to the boss for a replan (capped) —
never crashing. Execution, the operator gate, snapshots, and acceptance runners are
all injected so the whole path is testable without a GPU or a live model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from hy3.orchestrator.dag import Dag, Job, risk_level, Risk
from hy3.orchestrator.acceptance import accept
from hy3.orchestrator.escalate import Action, Escalator, MAX_ATTEMPTS
from hy3.orchestrator.boss import Boss
from hy3.providers.base import Provider, Result
from hy3.providers.policy import BudgetGuard

ExecuteFn = Callable[[Job, dict], Result]
GateFn = Callable[[Risk], bool]
SnapshotFn = Callable[[Job], None]


@dataclass
class JobRecord:
    """Outcome of one job (the original, or a replanned replacement)."""

    job_id: str
    status: str  # ok | blocked | escalated | giveup
    attempts: int = 0
    verdict: bool = False
    error: str = ""


@dataclass
class RunReport:
    records: list[JobRecord]
    loads: int
    replans: int
    report: dict


class Scheduler:
    def __init__(
        self,
        registry,
        provider: Provider,
        *,
        boss: Optional[Boss] = None,
        budget: Optional[BudgetGuard] = None,
        execute: Optional[ExecuteFn] = None,
        gate: Optional[GateFn] = None,
        snapshot: Optional[SnapshotFn] = None,
        runners: Optional[dict] = None,
        escalator: Optional[Escalator] = None,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self.boss = boss
        self.budget = budget
        self.execute = execute or self._default_execute
        self.gate = gate or (lambda risk: True)
        self.snapshot = snapshot or (lambda job: None)
        self.runners = runners or {}
        self.escalator = escalator or Escalator()

    # -- public --------------------------------------------------------------
    def run(self, dag: Dag, *, goal: str = "") -> RunReport:
        self._dep: dict[str, Result] = {}
        self._loads = 0
        records: list[JobRecord] = []
        self._run_dag(dag, records)
        report = (self.boss.synthesize(records, goal=goal) if self.boss
                  else Boss().synthesize(records, goal=goal))
        return RunReport(
            records=records,
            loads=self._loads,
            replans=self.escalator.replans,
            report=report,
        )

    # -- internals -----------------------------------------------------------
    def _run_dag(self, dag: Dag, records: list[JobRecord]) -> None:
        for profile, batch in dag.batches():
            self.provider.load(profile)
            self._loads += 1
            for job in batch:
                rec, result = self._run_job(job)
                records.append(rec)
                if rec.verdict and rec.status == "ok":
                    self._dep[job.id] = result
                elif rec.status == "escalated":
                    new_dag = self._escalate(job, result)
                    if new_dag is None:
                        rec.status = "giveup"
                    else:
                        self._run_dag(new_dag, records)
                elif rec.status == "giveup":
                    return  # stop the whole run; goal is unreachable
            self.provider.unload(profile)

    def _run_job(self, job: Job) -> tuple[JobRecord, Optional[Result]]:
        # A job may request fewer retries, but never more than the global cap.
        budget = min(MAX_ATTEMPTS, max(1, job.retries + 1))
        attempts = 0
        last_result: Optional[Result] = None
        while True:
            attempts += 1
            if not self.gate(job.risk):
                return (
                    JobRecord(job.id, "blocked", attempts, False, "operator denied"),
                    last_result,
                )
            if risk_level(job.risk) >= risk_level(Risk.WRITE):
                self.snapshot(job)
            verdict = False
            try:
                result = self.execute(job, self._dep)
            except Exception as exc:
                err = f"execute raised: {exc}"
            else:
                last_result = result
                try:
                    verdict = accept(
                        job, result, registry=self.registry, runners=self.runners
                    )
                    err = ""
                except Exception as exc:
                    verdict = False
                    err = f"acceptance error: {exc}"
                if self.budget is not None and result is not None:
                    try:
                        self.budget.charge(result.usage)
                    except Exception:
                        return (
                            JobRecord(job.id, "giveup", attempts, False,
                                      "budget exceeded"),
                            last_result,
                        )
            if verdict:
                return JobRecord(job.id, "ok", attempts, True, ""), last_result
            action = self.escalator.decision(attempts, budget)
            if action is Action.RETRY:
                continue
            # Out of attempts: escalate (replan) or give up.
            return (
                JobRecord(job.id, "escalated", attempts, False, err),
                last_result,
            )

    def _escalate(self, job: Job, result: Optional[Result]) -> Optional[Dag]:
        if self.boss is None:
            return None
        try:
            return self.boss.replan(job, result)
        except Exception:
            return None

    def _default_execute(self, job: Job, dep_outputs: dict) -> Result:
        """Real executor: invoke the capability's wired handler, wrap output as Result.

        Handlers are no-ops until their phase wires them (Phase 1 note), so callers
        that want execution today inject their own ``execute``.
        """
        cap = self.registry.get(job.capability_id)
        if cap is None or getattr(cap.handler, "__name__", "") == "_no_op":
            raise RuntimeError(f"no wired handler for {job.capability_id}")
        out = cap.handler(job.inputs)
        text = out if isinstance(out, str) else json.dumps(out)
        return Result(text=text)
