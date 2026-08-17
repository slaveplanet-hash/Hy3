"""Tests for the provider layer (plan §6 gate: same prompt routes to local and
API through one interface; classifier blocks a payload with an RFC1918 address).
"""
from __future__ import annotations

import pytest

from hy3.providers.anthropic import AnthropicProvider
from hy3.providers.base import EgressBlocked, Result
from hy3.providers.lmstudio import LMStudioProvider
from hy3.providers.local_swap import LocalSwapProvider
from hy3.providers.openai import OpenAIProvider


class FakeHttp:
    """Records the last request body and returns a canned completion."""

    def __init__(self, kind: str = "openai") -> None:
        self.kind = kind
        self.last_body: dict = {}
        self.last_url: str = ""

    def __call__(self, url: str, headers: dict, body: bytes):
        import json

        self.last_url = url
        self.last_body = json.loads(body.decode("utf-8"))
        if self.kind == "anthropic":
            return 200, {
                "content": [{"type": "text", "text": "anthropic reply"}],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }
        return 200, {
            "choices": [{"message": {"content": "provider reply", "tool_calls": []}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def test_same_prompt_routes_through_one_interface() -> None:
    msgs = [{"role": "user", "content": "list the services"}]
    local = LocalSwapProvider(model="boss", http=FakeHttp())
    api = OpenAIProvider(
        api_key="sk-test", http=FakeHttp(),
        price_per_1k_in_usd=0.001, price_per_1k_out_usd=0.002,
    )
    r_local = local.complete(msgs)
    r_api = api.complete(msgs)
    assert isinstance(r_local, Result) and isinstance(r_api, Result)
    assert r_local.text == "provider reply" == r_api.text
    # USD computed from the pricing hook.
    assert r_api.usage.usd == pytest.approx(0.00002, abs=1e-9)


def test_openai_blocks_rfc1918_payload() -> None:
    api = OpenAIProvider(api_key="sk-test", http=FakeHttp())
    with pytest.raises(EgressBlocked):
        api.complete([{"role": "user", "content": "scan host 192.168.1.1"}])


def test_local_is_not_egress_blocked() -> None:
    # Local providers never send data off-machine, so private payloads are fine.
    local = LocalSwapProvider(model="boss", http=FakeHttp())
    r = local.complete([{"role": "user", "content": "scan host 192.168.1.1"}])
    assert r.text == "provider reply"


def test_schema_is_forwarded_to_openai_compatible_backend() -> None:
    fake = FakeHttp()
    local = LocalSwapProvider(model="boss", http=fake)
    local.complete(
        [{"role": "user", "content": "emit json"}],
        schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
    )
    assert fake.last_body.get("response_format", {}).get("type") == "json_schema"


def test_anthropic_one_interface() -> None:
    anth = AnthropicProvider(api_key="x", http=FakeHttp("anthropic"))
    r = anth.complete([{"role": "user", "content": "hello"}])
    assert isinstance(r, Result)
    assert r.text == "anthropic reply"
    assert r.usage.tokens_in == 12


def test_anthropic_blocks_rfc1918_payload() -> None:
    anth = AnthropicProvider(api_key="x", http=FakeHttp("anthropic"))
    with pytest.raises(EgressBlocked):
        anth.complete([{"role": "user", "content": "host 10.0.0.9"}])


def test_lmstudio_one_interface() -> None:
    lm = LMStudioProvider(model="local", http=FakeHttp())
    r = lm.complete([{"role": "user", "content": "ping"}])
    assert isinstance(r, Result)
    assert r.text == "provider reply"
