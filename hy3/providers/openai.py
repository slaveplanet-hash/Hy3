"""OpenAI (remote) provider (plan §6) — egress-enforced.

A remote call is only allowed after the egress classifier clears the payload. If
the prompt contains any private/local data (RFC1918 address, MAC, ``.local`` host,
Windows path, credential), ``complete()`` raises ``EgressBlocked`` — the bytes
never leave the machine. Pricing is a simple per-1k hook so the budget guard has
real USD; defaults to zero until a pricing table lands.
"""
from __future__ import annotations

import json
from typing import Sequence

from .base import HttpClient, ProviderCaps, Result, Usage, complete_openai
from .egress import require_local

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider:
    """Remote OpenAI-compatible provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = DEFAULT_BASE_URL,
        http: HttpClient | None = None,
        price_per_1k_in_usd: float = 0.0,
        price_per_1k_out_usd: float = 0.0,
        caps: ProviderCaps | None = None,
    ) -> None:
        self.name = "openai"
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._http = http
        self._pin = price_per_1k_in_usd
        self._pout = price_per_1k_out_usd
        self.caps = caps or ProviderCaps(
            json_schema=True, grammar=False, tools=True, ctx_len=128_000
        )

    def load(self, profile: str) -> None:
        return None

    def unload(self, profile: str) -> None:
        return None

    def complete(
        self,
        messages: Sequence[dict],
        *,
        schema: dict | None = None,
        grammar: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> Result:
        if self._http is None:
            raise RuntimeError("OpenAIProvider requires an injected http client")
        # Hard block: private/local data must not reach a remote model.
        require_local(json.dumps(list(messages), ensure_ascii=False))
        result = complete_openai(
            self._http,
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            caps=self.caps,
            schema=schema,
            grammar=grammar,
            tools=tools,
            max_tokens=max_tokens,
            stop=stop,
        )
        result.usage = Usage(
            tokens_in=result.usage.tokens_in,
            tokens_out=result.usage.tokens_out,
            usd=result.usage.tokens_in / 1000 * self._pin
            + result.usage.tokens_out / 1000 * self._pout,
        )
        return result
