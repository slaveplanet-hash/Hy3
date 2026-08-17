"""llama-swap provider (plan §6).

llama-swap sits in front of llama-server and proxies the OpenAI chat format. The
harness makes ordinary OpenAI calls and changes only the ``model`` field per
profile; load/unload happens beneath it, so there is NO model-lifecycle code here
— ``load``/``unload`` are intentionally no-ops.
"""
from __future__ import annotations

from typing import Sequence

from .base import HttpClient, ProviderCaps, Result, Usage, complete_openai

DEFAULT_BASE_URL = "http://localhost:8080/v1"


class LocalSwapProvider:
    """OpenAI-compatible local provider backed by llama-swap."""

    def __init__(
        self,
        *,
        model: str = "local",
        base_url: str = DEFAULT_BASE_URL,
        http: HttpClient | None = None,
        caps: ProviderCaps | None = None,
    ) -> None:
        self.name = "local_swap"
        self.model = model
        self.base_url = base_url
        self._http = http
        self.caps = caps or ProviderCaps(
            json_schema=True, grammar=True, tools=True, ctx_len=8192
        )

    def load(self, profile: str) -> None:
        # llama-swap owns model lifecycle; nothing to do here.
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
            raise RuntimeError(
                "LocalSwapProvider requires an injected http client (or a live llama-swap)"
            )
        return complete_openai(
            self._http,
            base_url=self.base_url,
            api_key=None,
            model=self.model,
            messages=messages,
            caps=self.caps,
            schema=schema,
            grammar=grammar,
            tools=tools,
            max_tokens=max_tokens,
            stop=stop,
        )
