"""HY3 — local-first agent harness for PC management, network engineering, and deep research.

Phase 0 delivers the storage spine and session lifecycle:
migrations, a SQLite store (WAL + FTS5), an append-only event writer,
session create/resume/fork/end, and a content-addressed artifact store.

Phase 1 delivers the capability registry: a frozen `Capability` schema, a
`Registry` that loads/indexes/queries, and a two-stage router that embeds a goal
and returns the top-k capabilities unioned with a pinned planner set. The CLI
exposes it via `hy3 caps list|show|route`.

Phase 2 delivers the provider layer: one `Provider` interface over local
(llama-swap, LM Studio) and remote (OpenAI, Anthropic) backends, an egress
classifier that blocks private/local data from leaving the machine, and a budget
guard with session-USD / run-token hard caps.

Phase 3 delivers the orchestrator: a `Dag` (validate + topo sort + profile-batch
grouping), a two-stage `accept` gate (none/schema/regex/test/critic/state), an
`Escalator` that retries within a per-job budget then escalates to a replan (capped
at 3, never a third attempt), and a profile-batched `Scheduler` that loads a model
at most once per batch. The CLI exposes it via `hy3 plan validate <file>`.

No UI yet — that is Phase 6 (console).
"""

__version__ = "0.4.0"
