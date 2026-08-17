"""Orchestrator (plan §7): DAG, profile batching, acceptance, escalation.

The orchestrator turns a boss plan into a validated ``Dag``, runs it batch-by-batch
(one model load per profile batch), gates each job by risk, and checks acceptance
after every job. Failures retry within a per-job budget, then escalate to the boss
for a replan — never crashing.
"""
from __future__ import annotations

from .acceptance import accept
from .boss import Boss
from .dag import Dag, DagError, Job, risk_level
from .escalate import Action, Escalator, MAX_ATTEMPTS, MAX_REPLANS
from .scheduler import JobRecord, RunReport, Scheduler

__all__ = [
    "Dag",
    "DagError",
    "Job",
    "risk_level",
    "accept",
    "Boss",
    "Escalator",
    "Action",
    "MAX_ATTEMPTS",
    "MAX_REPLANS",
    "Scheduler",
    "JobRecord",
    "RunReport",
]
