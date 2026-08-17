"""Routing policy + budget guard (plan §6, §14).

Routing evaluates, in order:
  1. ``--local-only`` flag                 -> local, always
  2. payload has private/local data (egress) -> local (API call would leak it)
  3. vision / UI grounding                 -> local VLM (API fallback later)
  4. >32k context or plan-quality bottleneck -> API
  5. otherwise                             -> local (default; cheapest)

The budget guard enforces a per-session USD cap and a per-run token cap. Both are
hard stops: exceeding either raises ``BudgetExceeded`` (the harness emits
``budget.exceeded`` and halts the run).
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Usage
from .egress import contains_sensitive

LOCAL = "local"
API = "api"

LARGE_CONTEXT = 32_000


@dataclass
class RouteRequest:
    """What the policy needs to pick a transport for one call."""

    payload: str
    local_only: bool = False
    ctx_len: int | None = None
    needs_vision: bool = False
    quality_sensitive: bool = False


@dataclass
class RouteDecision:
    transport: str  # "local" | "api"
    reason: str


def decide(req: RouteRequest) -> RouteDecision:
    """Pick a transport for ``req`` following the plan's routing table."""
    if req.local_only:
        return RouteDecision(LOCAL, "--local-only flag set")
    if contains_sensitive(req.payload):
        return RouteDecision(
            LOCAL, "payload has private/local data; cannot leave the machine"
        )
    if req.needs_vision:
        return RouteDecision(LOCAL, "vision/UI grounding -> local VLM (API fallback)")
    if (req.ctx_len and req.ctx_len > LARGE_CONTEXT) or req.quality_sensitive:
        return RouteDecision(API, "plan quality / large-context bottleneck")
    return RouteDecision(LOCAL, "default: keep local for cost")


class BudgetExceeded(Exception):
    """Raised when a charge would break the session USD or run token cap."""


@dataclass
class BudgetGuard:
    """Hard-stop budgets for one run. Charge raises on overflow."""

    session_usd_cap: float
    run_token_cap: int
    _usd: float = 0.0
    _tokens: int = 0

    @property
    def usd_used(self) -> float:
        return self._usd

    @property
    def tokens_used(self) -> int:
        return self._tokens

    def remaining_usd(self) -> float:
        return max(0.0, self.session_usd_cap - self._usd)

    def remaining_tokens(self) -> int:
        return max(0, self.run_token_cap - self._tokens)

    def charge(self, usage: Usage) -> None:
        """Record ``usage``; raise ``BudgetExceeded`` if it would overflow a cap."""
        if self._usd + usage.usd > self.session_usd_cap:
            raise BudgetExceeded(
                f"session USD cap {self.session_usd_cap} exceeded "
                f"(would be {self._usd + usage.usd:.4f})"
            )
        if self._tokens + usage.tokens_out > self.run_token_cap:
            raise BudgetExceeded(
                f"run token cap {self.run_token_cap} exceeded "
                f"(would be {self._tokens + usage.tokens_out})"
            )
        self._usd += usage.usd
        self._tokens += usage.tokens_out
