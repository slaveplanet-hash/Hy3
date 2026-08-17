"""Escalation policy (plan §7).

After a job fails its acceptance check the scheduler asks the ``Escalator`` what to
do next. The hard safety rule from the plan: **two failures means no third attempt** —
escalate to the boss for a replan. Replans are capped per run so a failing goal can't
loop forever.
"""
from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    RETRY = "retry"
    ESCALATE = "escalate"
    GIVE_UP = "give_up"


MAX_ATTEMPTS = 2  # total attempts before escalation; never a 3rd
MAX_REPLANS = 3   # replans per run before giving up


class Escalator:
    """Tracks the replan budget for one run and decides retry/escalate/give-up."""

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        max_replans: int = MAX_REPLANS,
    ) -> None:
        self.max_attempts = max_attempts
        self.max_replans = max_replans
        self.replans = 0

    def decision(self, attempts: int, budget: int | None = None) -> Action:
        """What to do after ``attempts`` failed attempts on a job.

        ``budget`` is the per-job attempt ceiling (``min(MAX_ATTEMPTS, retries+1)``),
        so a job may ask for fewer retries but never more than ``MAX_ATTEMPTS``.
        """
        cap = budget if budget is not None else self.max_attempts
        if attempts < cap:
            return Action.RETRY
        if self.replans < self.max_replans:
            self.replans += 1
            return Action.ESCALATE
        return Action.GIVE_UP
