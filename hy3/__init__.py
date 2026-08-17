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

Phase 6 delivers the operator console: a local-first, dependency-free web UI for
observability. A stdlib HTTP server (`hy3 console`) exposes a read-only JSON API
over the store (`ConsoleApi`), and a vanilla-JS frontend renders a Wireshark-style
master/detail view — a session ribbon, a flat display-filterable event list (with
`kind:cap.call risk:write entity:192.168.1.180` syntax), and selection-linked detail
panes for event payload plus job spec / payload / acceptance / diff. No build step.
"""

__version__ = "0.5.0"
