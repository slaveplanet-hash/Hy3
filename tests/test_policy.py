"""Tests for the routing policy and budget guard (plan §6/§14)."""
from __future__ import annotations

import pytest

from hy3.providers.base import Usage
from hy3.providers.policy import (
    API,
    LOCAL,
    BudgetExceeded,
    BudgetGuard,
    RouteRequest,
    decide,
)


def test_local_only_forces_local() -> None:
    d = decide(RouteRequest(payload="plan the outage", local_only=True))
    assert d.transport == LOCAL
    assert "local-only" in d.reason


def test_sensitive_payload_forces_local() -> None:
    d = decide(RouteRequest(payload="diagnose 192.168.1.1"))
    assert d.transport == LOCAL
    assert "private" in d.reason


def test_vision_goes_local_vlm() -> None:
    d = decide(RouteRequest(payload="read this screenshot", needs_vision=True))
    assert d.transport == LOCAL


def test_quality_sensitive_goes_api() -> None:
    d = decide(RouteRequest(payload="write the report", quality_sensitive=True))
    assert d.transport == API


def test_large_context_goes_api() -> None:
    d = decide(RouteRequest(payload="summarize", ctx_len=40_000))
    assert d.transport == API


def test_default_is_local() -> None:
    d = decide(RouteRequest(payload="list files"))
    assert d.transport == LOCAL
    assert "default" in d.reason


def test_budget_guard_accumulates() -> None:
    g = BudgetGuard(session_usd_cap=1.0, run_token_cap=100)
    g.charge(Usage(tokens_out=40, usd=0.2))
    assert g.tokens_used == 40
    assert g.remaining_tokens() == 60
    g.charge(Usage(tokens_out=60, usd=0.3))
    assert g.usd_used == 0.5


def test_budget_guard_blocks_on_token_overflow() -> None:
    g = BudgetGuard(session_usd_cap=10.0, run_token_cap=100)
    with pytest.raises(BudgetExceeded):
        g.charge(Usage(tokens_out=101))


def test_budget_guard_blocks_on_usd_overflow() -> None:
    g = BudgetGuard(session_usd_cap=0.5, run_token_cap=10_000)
    with pytest.raises(BudgetExceeded):
        g.charge(Usage(usd=0.6))
