"""Boss: planning, replanning, synthesis (plan §7, §15).

In production the boss is a small local model (profile ``boss``) that emits
grammar-constrained plan JSON. This module is the harness-side contract: it turns a
job-spec list into a validated ``Dag`` and knows how to fold a failure back into a
replan and fold results into a report. The actual model call is injected, so the
orchestrator is fully testable without a GPU.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from hy3.orchestrator.dag import Dag, Job
from hy3.registry.capability import Risk
from hy3.registry import Registry

# (failed_job, last_result) -> a revised Dag, or None if the goal is unreachable.
Planner = Callable[[Job, object], Optional[Dag]]


class Boss:
    def __init__(self, *, planner: Optional[Planner] = None) -> None:
        self.planner = planner

    def plan_from_spec(
        self,
        jobs_spec: Sequence[dict],
        *,
        registry: Registry,
        session_ceiling: Risk = Risk.PRIVILEGED,
        max_jobs: int = 12,
    ) -> Dag:
        """Build and validate a Dag from raw job specs (as the boss would emit)."""
        jobs = [Job.from_dict(s) for s in jobs_spec]
        return Dag(
            jobs,
            capability_ids=registry.ids(),
            session_ceiling=session_ceiling,
            max_jobs=max_jobs,
        )

    def replan(self, failed_job: Job, last_result) -> Optional[Dag]:
        """Produce a revised plan for a failed job, or None if unreachable."""
        if self.planner is None:
            return None
        return self.planner(failed_job, last_result)

    def synthesize(self, records: Sequence[object], *, goal: str = "") -> dict:
        """Fold per-job records into a human-readable run report dict."""
        total = len(records)
        ok = sum(1 for r in records if getattr(r, "verdict", False))
        escalated = sum(1 for r in records if getattr(r, "status", "") == "escalated")
        giveup = sum(1 for r in records if getattr(r, "status", "") == "giveup")
        blocked = sum(1 for r in records if getattr(r, "status", "") == "blocked")
        lines = [
            f"{getattr(r, 'job_id', '?'):>6}: {'OK' if getattr(r, 'verdict', False) else getattr(r, 'status', '?')}"
            for r in records
        ]
        return {
            "goal": goal,
            "jobs": total,
            "ok": ok,
            "escalated": escalated,
            "giveup": giveup,
            "blocked": blocked,
            # Goal is reached only if nothing was given up or blocked by the operator.
            "reached": giveup == 0 and blocked == 0,
            "lines": lines,
            "text": "\n".join(lines),
        }
