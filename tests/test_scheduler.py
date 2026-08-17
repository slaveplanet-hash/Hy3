"""Scheduler: profile batching, acceptance, retry, and escalation (plan §7).

This is the Phase 3 acceptance gate:
  * a 5-job plan executes with <=3 model loads, and
  * an injected failure escalates to a replan rather than crashing.
Plus fault-injection: execute raises, budget exhausts, gate denies, goal unreachable.
"""
from __future__ import annotations

from hy3.orchestrator import Boss, Scheduler
from hy3.orchestrator.dag import Job
from hy3.orchestrator.escalate import MAX_ATTEMPTS
from hy3.providers.base import ProviderCaps, Result
from hy3.providers.policy import BudgetExceeded, BudgetGuard
from hy3.registry import Registry
from hy3.registry.capability import Risk

REG = Registry.load()


class FakeProvider:
    """Records load/unload calls; the scheduler never calls complete (execute is injected)."""

    def __init__(self) -> None:
        self.loads: list[str] = []
        self.unloads: list[str] = []
        self.name = "fake"
        self.caps = ProviderCaps()

    def load(self, profile: str) -> None:
        self.loads.append(profile)

    def unload(self, profile: str) -> None:
        self.unloads.append(profile)

    def complete(self, *a, **k) -> Result:  # pragma: no cover - not used here
        return Result(text="x")


def success_executor(job: Job, deps: dict) -> Result:
    return Result(text=f"SUCCESS {job.id}")


def pass_executor_for(ok_ids):
    def _exec(job, deps):
        if job.id in ok_ids:
            return Result(text=f"SUCCESS {job.id}")
        return Result(text="FAIL")
    return _exec


def plan(specs, ceiling: Risk = Risk.PRIVILEGED, max_jobs: int = 12):
    return Boss().plan_from_spec(specs, registry=REG, session_ceiling=ceiling,
                                 max_jobs=max_jobs)


# -- GATE 1: 5-job plan, <=3 model loads -------------------------------------
def test_five_job_plan_loads_at_most_three_models():
    # ids sort to a1,a2,b1,b2,c1 -> profiles analyst,analyst,boss,boss,coder
    # => 3 contiguous profile batches => 3 loads.
    specs = [
        {"id": "a1", "capability_id": "net.scan.lan", "profile": "analyst"},
        {"id": "a2", "capability_id": "net.diag.dns", "profile": "analyst"},
        {"id": "b1", "capability_id": "memory.search", "profile": "boss"},
        {"id": "b2", "capability_id": "plan.replan", "profile": "boss"},
        {"id": "c1", "capability_id": "report.write", "profile": "coder"},
    ]
    dag = plan(specs)
    prov = FakeProvider()
    sched = Scheduler(REG, prov, execute=success_executor)
    report = sched.run(dag, goal="diagnose network")

    assert report.loads == 3, report.loads
    assert report.loads <= 3
    assert all(r.verdict for r in report.records)
    assert report.report["reached"] is True
    assert report.replans == 0


# -- GATE 2: injected failure escalates to replan, no crash ------------------
def test_injected_failure_escalates_to_replan_not_crash():
    specs = [
        {"id": "a1", "capability_id": "net.scan.lan", "profile": "analyst"},
        {"id": "a2", "capability_id": "net.diag.dns", "profile": "analyst"},
        {"id": "b1", "capability_id": "memory.search", "profile": "boss"},
        {"id": "b2", "capability_id": "plan.replan", "profile": "boss"},
        # c1 will fail its acceptance, then escalate; retries=1 -> 2 attempts.
        {"id": "c1", "capability_id": "report.write", "profile": "coder",
         "risk": "read", "retries": 1,
         "acceptance": {"type": "regex", "pattern": "SUCCESS"}},
    ]
    dag = plan(specs)

    # executor fails c1 (no SUCCESS), succeeds for everyone else.
    prov = FakeProvider()
    boss = Boss(planner=lambda failed_job, result: plan([
        {"id": "r1", "capability_id": "memory.search", "profile": "boss"},
    ]))
    sched = Scheduler(REG, prov, boss=boss,
                      execute=pass_executor_for({"a1", "a2", "b1", "b2"}))
    report = sched.run(dag, goal="flakey goal")

    # No exception; c1 escalated; boss produced a replan that ran and passed.
    c1 = next(r for r in report.records if r.job_id == "c1")
    assert c1.status == "escalated"
    assert c1.attempts == 2  # exactly two attempts, never a third
    assert report.replans == 1
    assert report.report["reached"] is True
    assert any(r.job_id == "r1" and r.verdict for r in report.records)


# -- fault injection: execute raises ----------------------------------------
def test_execute_raises_escalates_then_replan_ok():
    specs = [
        {"id": "c1", "capability_id": "report.write", "profile": "coder",
         "risk": "read", "retries": 1,
         "acceptance": {"type": "regex", "pattern": "SUCCESS"}},
    ]
    dag = plan(specs)

    def boom(job, deps):
        if job.id == "c1":
            raise RuntimeError("model OOM")
        return Result(text="SUCCESS")

    boss = Boss(planner=lambda fj, r: plan([
        {"id": "r1", "capability_id": "memory.search", "profile": "boss"},
    ]))
    sched = Scheduler(REG, FakeProvider(), boss=boss, execute=boom)
    report = sched.run(dag)
    c1 = next(r for r in report.records if r.job_id == "c1")
    assert c1.status == "escalated"
    assert report.replans == 1
    assert report.report["reached"] is True


# -- fault injection: goal unreachable (planner returns None) ----------------
def test_failure_with_no_replan_marks_giveup():
    specs = [
        {"id": "c1", "capability_id": "report.write", "profile": "coder",
         "risk": "read", "acceptance": {"type": "regex", "pattern": "SUCCESS"}},
    ]
    dag = plan(specs)
    boss = Boss(planner=lambda fj, r: None)  # unreachable
    sched = Scheduler(REG, FakeProvider(), boss=boss,
                      execute=pass_executor_for(set()))
    report = sched.run(dag)
    c1 = next(r for r in report.records if r.job_id == "c1")
    assert c1.status == "giveup"
    assert report.replans == 1
    assert report.report["reached"] is False


# -- fault injection: budget exhaustion --------------------------------------
def test_budget_exhaustion_halts_run():
    specs = [
        {"id": "c1", "capability_id": "net.scan.lan", "profile": "analyst"},
    ]
    dag = plan(specs)
    budget = BudgetGuard(session_usd_cap=1e9, run_token_cap=5)

    def big(job, deps):
        return Result(text="x", usage=__import__("hy3.providers.base",
                                                  fromlist=["Usage"]).Usage(tokens_out=100))
    sched = Scheduler(REG, FakeProvider(), budget=budget, execute=big)
    report = sched.run(dag)
    c1 = next(r for r in report.records if r.job_id == "c1")
    assert c1.status == "giveup"
    assert "budget" in c1.error.lower()
    assert report.report["reached"] is False


# -- gate denies -------------------------------------------------------------
def test_gate_denial_blocks_job_without_crash():
    specs = [
        {"id": "c1", "capability_id": "net.scan.lan", "profile": "analyst",
         "risk": "privileged", "acceptance": {"type": "regex", "pattern": "SUCCESS"}},
    ]
    dag = plan(specs)
    sched = Scheduler(REG, FakeProvider(),
                      execute=success_executor,
                      gate=lambda risk: risk is not Risk.PRIVILEGED)
    report = sched.run(dag)
    c1 = next(r for r in report.records if r.job_id == "c1")
    assert c1.status == "blocked"
    assert report.report["reached"] is False


# -- retries budget respects job.retries -------------------------------------
def test_retries_zero_means_single_attempt_before_escalate():
    specs = [
        {"id": "c1", "capability_id": "report.write", "profile": "coder",
         "risk": "read", "retries": 0,
         "acceptance": {"type": "regex", "pattern": "SUCCESS"}},
    ]
    dag = plan(specs)
    boss = Boss(planner=lambda fj, r: plan([
        {"id": "r1", "capability_id": "memory.search", "profile": "boss"},
    ]))
    sched = Scheduler(REG, FakeProvider(), boss=boss,
                      execute=pass_executor_for(set()))
    report = sched.run(dag)
    c1 = next(r for r in report.records if r.job_id == "c1")
    assert c1.attempts == 1  # no retry
    assert c1.status == "escalated"
    assert MAX_ATTEMPTS == 2  # global ceiling still holds
