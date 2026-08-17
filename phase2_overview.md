# HY3 Phase 2 — Provider Layer, Egress Classifier, Budget Guard

**Status:** shipped · tag `v0.3.0` · 60 tests green (was 31)
**Gate (plan §15): met** — same prompt routes to local and API through one interface;
the classifier blocks a payload containing an RFC1918 address.

## What was built

| File | Role |
|---|---|
| `hy3/providers/base.py` | `Provider` protocol, `ProviderCaps`, `Usage`, `Result`, `ProviderError`, `EgressBlocked`, shared `complete_openai()` helper + injectable `HttpClient` |
| `hy3/providers/egress.py` | Classifier: RFC1918/CGNAT/link-local IPs (even inside a URL), MAC colon+dash, `.local`, Windows/UNC paths, creds, pcap → `check()`/`redact()`/`require_local()` |
| `hy3/providers/policy.py` | Routing table (`decide`) + `BudgetGuard` (session USD / run token hard caps) |
| `hy3/providers/local_swap.py` | `LocalSwapProvider` — llama-swap @ `:8080/v1`, no lifecycle code |
| `hy3/providers/lmstudio.py` | `LMStudioProvider` — LM Studio @ `:1234/v1` |
| `hy3/providers/openai.py` | `OpenAIProvider` — remote, egress-enforced, per-1k pricing hook |
| `hy3/providers/anthropic.py` | `AnthropicProvider` — remote (Messages API), egress-enforced |
| `config/llama-swap.yaml` | Sample profile→launch mapping for the 12GB-card table (boss/coder/analyst/vision/embed) |
| `tests/test_egress.py`, `test_policy.py`, `test_providers.py` | Classifier corpus, routing+budget, one-interface routing |

## Key design decisions

- **One interface, many backends (P1).** The orchestrator calls `Provider.complete()`
  and never learns which backend answered. `load`/`unload` are thin no-ops — llama-swap
  owns model lifecycle, so there is no model download/load code in the harness.
- **Transport is injectable.** Every provider takes an `HttpClient` callable
  `(url, headers, body) -> (status, json)`. Tests use a `FakeHttp` and exercise the
  full path with zero running models — which is why Phase 2 is green without a GPU.
- **Egress is enforced, not advised.** Remote providers call `require_local(payload)`
  *before* any bytes leave; a blocked payload raises `EgressBlocked`. This is what makes
  it safe to point the harness at your own network (plan §5/§14).
- **Budget is a hard stop.** `BudgetGuard.charge(usage)` raises `BudgetExceeded` the
  moment a session-USD or run-token cap would overflow; the orchestrator turns that
  into a `budget.exceeded` event and halts the run.

## Next (Phase 3)
Orchestrator: DAG construction, profile-batch scheduling (≤3 model loads), acceptance
checks (schema/test/regex/critic/state), and escalation → replan on repeated failure.
