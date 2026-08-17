"""LM Studio provider (plan §6).

Same OpenAI-compatible interface as llama-swap, reached through LM Studio's local
server at :1234. Implemented so the orchestrator can route to LM Studio when you
want its UI in the loop, with no change to call sites.
"""
from __future__ import annotations

from typing import Sequence

from .base import HttpClient, ProviderCaps, Result, complete_openai

DEFAULT_BASE_URL = "http://localhost:1234/v1"


class LMStudioProvider:
    """OpenAI-compatible local provider backed by LM Studio."""

    def __init__(
        self,
        *,
        model: str = "local",
        base_url: str = DEFAULT_BASE_URL,
        http: HttpClient | None = None,
        caps: ProviderCaps | None = None,
    ) -> None:
        self.name = "lmstudio"
        self.model = model
        self.base_url = base_url
        self._http = http
        self.caps = caps or ProviderCaps(
            json_schema=True, grammar=True, tools=True, vision=True, ctx_len=8192
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
            raise RuntimeError(
                "LMStudioProvider requires an injected http client (or a live LM Studio)"
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
