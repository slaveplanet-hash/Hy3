"""Provider abstraction (plan §6).

One interface over every model backend — local llama-swap / LM Studio and remote
OpenAI / Anthropic. The orchestrator calls ``complete()`` and never knows which
backend answered. Model lifecycle lives outside the harness (llama-swap owns it),
so ``load``/``unload`` are thin no-ops here.

The actual HTTP transport is behind an injectable ``HttpClient`` so the providers
are fully testable without a running model server.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence


class ProviderError(Exception):
    """Raised when a provider call fails or is refused (e.g. egress block)."""


class EgressBlocked(ProviderError):
    """Raised when a remote provider call would leak data the egress classifier blocked."""


@dataclass(frozen=True)
class ProviderCaps:
    """What a provider/profile can do. Drives router and grammar selection."""

    json_schema: bool = False     # accepts response_format json_schema
    grammar: bool = False         # accepts GBNF grammar constraint
    tools: bool = False           # accepts tool/function calling
    vision: bool = False          # accepts images
    ctx_len: int = 8192           # context window in tokens
    streaming: bool = False       # supports streaming


@dataclass(frozen=True)
class Usage:
    """Token + cost accounting for one call. Feeds the budget guard."""

    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            usd=self.usd + other.usd,
        )


@dataclass
class Result:
    """A provider response."""

    text: str
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class Provider(Protocol):
    """The single surface the orchestrator programs against."""

    name: str
    caps: ProviderCaps

    def complete(
        self,
        messages: Sequence[dict],
        *,
        schema: dict | None = None,
        grammar: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
    ) -> Result: ...

    def load(self, profile: str) -> None: ...

    def unload(self, profile: str) -> None: ...


# An injectable HTTP client: callable(url, headers, body_bytes) -> (status, json_dict)
HttpClient = Callable[[str, dict, bytes], tuple[int, dict]]


def _post_json(
    http: HttpClient, url: str, headers: dict, body: dict
) -> tuple[int, dict]:
    """POST JSON via the injected client. Returns (status, parsed_json)."""
    data = json.dumps(body).encode("utf-8")
    try:
        status, payload = http(url, dict(headers), data)
    except Exception as exc:  # transport-level failure
        raise ProviderError(f"provider request to {url} failed: {exc}") from exc
    return status, (payload or {})


def complete_openai(
    http: HttpClient,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: Sequence[dict],
    caps: ProviderCaps,
    schema: dict | None,
    grammar: str | None,
    tools: list[dict] | None,
    max_tokens: int | None,
    stop: list[str] | None,
) -> Result:
    """Perform an OpenAI-compatible chat completion and parse it into a Result.

    Shared by llama-swap, LM Studio, and OpenAI backends — they differ only in
    base_url / api_key, not in wire format.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict[str, Any] = {"model": model, "messages": list(messages)}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if stop:
        body["stop"] = stop
    if tools and caps.tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if schema and caps.json_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "hy3_output", "schema": schema},
        }
    elif grammar and caps.grammar:
        # GBNF is passed as an vendor extension field llama.cpp servers understand.
        body["grammar"] = grammar

    status, payload = _post_json(http, url, headers, body)
    if status >= 400:
        raise ProviderError(f"provider returned {status}: {payload}")

    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message", {}) or {}
    text = message.get("content") or ""
    tool_calls = [
        tc for tc in (message.get("tool_calls") or []) if isinstance(tc, dict)
    ]
    usage_json = payload.get("usage") or {}
    usage = Usage(
        tokens_in=int(usage_json.get("prompt_tokens", 0)),
        tokens_out=int(usage_json.get("completion_tokens", 0)),
        # usd is filled in by the caller (remote providers know their pricing).
        usd=float(usage_json.get("cost_usd", 0.0)),
    )
    return Result(text=text, usage=usage, tool_calls=tool_calls, raw=payload)
