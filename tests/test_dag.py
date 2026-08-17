"""DAG validation, topological sort, and profile-batch grouping (plan §7)."""
from __future__ import annotations

import pytest

from hy3.orchestrator.dag import Dag, DagError, Job, risk_level
from hy3.registry import Registry
from hy3.registry.capability import Risk

REG = Registry.load()


def job(**kw) -> Job:
    base = dict(id="j", capability_id="net.scan.lan", profile="boss")
    base.update(kw)
    return Job.from_dict(base)


def make_dag(specs, **kw) -> Dag:
    jobs = [Job.from_dict(s) for s in specs]
    return Dag(jobs, capability_ids=REG.ids(), **kw)


# -- risk ordering ----------------------------------------------------------
def test_risk_level_orders_tiers():
    assert risk_level(Risk.READ) < risk_level(Risk.WRITE)
    assert risk_level(Risk.WRITE) < risk_level(Risk.DESTRUCTIVE)
    assert risk_level(Risk.DESTRUCTIVE) < risk_level(Risk.PRIVILEGED)


# -- validation -------------------------------------------------------------
def test_valid_linear_chain_passes():
    make_dag([
        {"id": "a", "capability_id": "net.scan.lan", "profile": "analyst"},
        {"id": "b", "capability_id": "net.diag.dns", "profile": "analyst",
         "depends_on": ["a"]},
    ])


def test_cycle_raises():
    with pytest.raises(DagError):
        make_dag([
            {"id": "a", "capability_id": "net.scan.lan", "profile": "x",
             "depends_on": ["b"]},
            {"id": "b", "capability_id": "net.diag.dns", "profile": "x",
             "depends_on": ["a"]},
        ])


def test_unknown_capability_raises():
    with pytest.raises(DagError):
        make_dag([{"id": "a", "capability_id": "does.not.exist", "profile": "x"}])


def test_unknown_dependency_raises():
    with pytest.raises(DagError):
        make_dag([{"id": "a", "capability_id": "net.scan.lan",
                   "depends_on": ["ghost"]}])


def test_risk_over_ceiling_raises():
    with pytest.raises(DagError):
        make_dag(
            [{"id": "a", "capability_id": "net.scan.lan", "risk": "write"}],
            session_ceiling=Risk.READ,
        )


def test_none_acceptance_only_for_read():
    # risk=read + none acceptance is allowed
    make_dag([{"id": "a", "capability_id": "net.scan.lan",
               "risk": "read", "acceptance": {"type": "none"}}])
    # risk=write + none acceptance is rejected
    with pytest.raises(DagError):
        make_dag([{"id": "a", "capability_id": "net.scan.lan",
                   "risk": "write", "acceptance": {"type": "none"}}])


def test_too_many_jobs_raises():
    specs = [
        {"id": f"j{i}", "capability_id": "net.scan.lan", "profile": "x"}
        for i in range(5)
    ]
    with pytest.raises(DagError):
        make_dag(specs, max_jobs=3)


def test_duplicate_job_id_raises():
    with pytest.raises(DagError):
        make_dag([
            {"id": "a", "capability_id": "net.scan.lan"},
            {"id": "a", "capability_id": "net.diag.dns"},
        ])


# -- topo order + batches ----------------------------------------------------
def test_topo_order_respects_dependencies():
    dag = make_dag([
        {"id": "c", "capability_id": "report.write", "depends_on": ["b"]},
        {"id": "a", "capability_id": "net.scan.lan"},
        {"id": "b", "capability_id": "net.diag.dns", "depends_on": ["a"]},
    ])
    order = dag.topo_order()
    assert order.index("a") < order.index("b") < order.index("c")


def test_batches_are_contiguous_same_profile_runs():
    dag = make_dag([
        {"id": "a1", "capability_id": "net.scan.lan", "profile": "analyst"},
        {"id": "a2", "capability_id": "net.diag.dns", "profile": "analyst"},
        {"id": "b1", "capability_id": "memory.search", "profile": "boss"},
        {"id": "c1", "capability_id": "report.write", "profile": "coder"},
    ])
    batches = dag.batches()
    ids = [j.id for _, b in batches for j in b]
    assert ids == dag.topo_order()  # every job exactly once, in topo order
    for profile, jobs in batches:
        assert all(j.profile == profile for j in jobs)


def test_single_profile_plan_is_one_batch():
    dag = make_dag([
        {"id": "a", "capability_id": "net.scan.lan", "profile": "x"},
        {"id": "b", "capability_id": "net.diag.dns", "profile": "x"},
    ])
    assert len(dag.batches()) == 1
