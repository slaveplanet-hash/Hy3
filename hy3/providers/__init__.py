"""Provider layer (plan §6).

One interface, many backends. The orchestrator programs against ``Provider`` and
never learns which backend answered.
"""
from __future__ import annotations

from .base import (
    EgressBlocked,
    ProviderCaps,
    ProviderError,
    Result,
    Usage,
)
from .anthropic import AnthropicProvider
from .egress import EgressVerdict, check, contains_sensitive, redact, require_local
from .lmstudio import LMStudioProvider
from .local_swap import LocalSwapProvider
from .openai import OpenAIProvider
from .policy import (
    API,
    LOCAL,
    BudgetExceeded,
    BudgetGuard,
    RouteDecision,
    RouteRequest,
    decide,
)

__all__ = [
    "ProviderCaps",
    "Usage",
    "Result",
    "ProviderError",
    "EgressBlocked",
    "LocalSwapProvider",
    "LMStudioProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "check",
    "contains_sensitive",
    "redact",
    "require_local",
    "EgressVerdict",
    "decide",
    "RouteRequest",
    "RouteDecision",
    "BudgetGuard",
    "BudgetExceeded",
    "LOCAL",
    "API",
]
