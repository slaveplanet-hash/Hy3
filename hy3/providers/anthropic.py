"""Anthropic (remote) provider (plan §6) — egress-enforced.

Same guarantee as the OpenAI provider: the egress classifier must clear the payload
before any bytes leave. Anthropic uses its own messages wire format (not OpenAI),
so this provider has a dedicated request/parse rather than ``complete_openai``.
"""
from __future__ import annotations

import json
from dataclasses import field
from typing import Any, Sequence

from .base import HttpClient, ProviderCaps, Result, Usage, _post_json
from .egress import require_local

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


class AnthropicProvider:
    """Remote Anthropic provider (Messages API)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-3-5-sonnet-latest",
        base_url: str = DEFAULT_BASE_URL,
        http: HttpClient | None = None,
        price_per_1k_in_usd: float = 0.0,
        price_per_1k_out_usd: float = 0.0,
        caps: ProviderCaps | None = None,
    ) -> None:
        self.name = "anthropic"
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._http = http
        self._pin = price_per_1k_in_usd
        self._pout = price_per_1k_out_usd
        self.caps = caps or ProviderCaps(
            json_schema=True, grammar=False, tools=True, ctx_len=200_000
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
            raise RuntimeError("AnthropicProvider requires an injected http client")
        # Hard block before anything leaves.
        require_local(json.dumps(list(messages), ensure_ascii=False))

        url = self.base_url.rstrip("/") + "/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        system = [m["content"] for m in messages if m.get("role") == "system"]
        convo = [m for m in messages if m.get("role") != "system"]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(convo),
            "max_tokens": max_tokens or 1024,
        }
        if system:
            body["system"] = system[0] if len(system) == 1 else " ".join(system)
        if tools and self.caps.tools:
            body["tools"] = tools

        status, payload = _post_json(self._http, url, headers, body)
        if status >= 400:
            raise RuntimeError(f"anthropic returned {status}: {payload}")
        text_parts = [
            b.get("text", "")
            for b in (payload.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        usage_json = payload.get("usage") or {}
        usage = Usage(
            tokens_in=int(usage_json.get("input_tokens", 0)),
            tokens_out=int(usage_json.get("output_tokens", 0)),
            usd=int(usage_json.get("input_tokens", 0)) / 1000 * self._pin
            + int(usage_json.get("output_tokens", 0)) / 1000 * self._pout,
        )
        return Result(text="".join(text_parts), usage=usage, raw=payload)
