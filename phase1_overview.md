# HY3 Phase 1 — Capability Registry & Two-Stage Router

**Status:** shipped · commit `0cb0432` · tag `v0.2.0` · 31 tests green (was 17)
**Gate (plan §15): met** — `hy3 caps list` shows all tooling under one schema; the
two-stage router returns a sane top-15 for 20 test goals.

## What was built

| File | Role |
|---|---|
| `hy3/registry/capability.py` | Frozen `Capability` dataclass + `Kind`/`Risk`/`Cost` enums + validation (`__post_init__`) + `build()` factory |
| `hy3/registry/router.py` | `Embedder` protocol, zero-dep `LexicalEmbedder` (TF-IDF), `TwoStageRouter` (embed → top-k → union pinned) |
| `hy3/registry/__init__.py` | `Registry`: load/index/query/by_kind/by_risk + `retrieve(goal)` |
| `hy3/registry/loaders/builtin.py` | Seeds **41** builtin capabilities from plan §9/§10/§11 + planner meta-caps + pinned set |
| `hy3/registry/loaders/{mcp,skills,rag}.py` | Documented extension points (return `[]` until those integrations land) |
| `bin/hy3.py` | New `caps list | show | route "<goal>"` subcommand |
| `tests/test_registry.py`, `tests/test_router.py` | Schema validation, load/kind/risk checks, 20-goal routing gate |

## Key design decisions

- **One schema surface (P1).** Every tool, model, skill, and retriever registers through
  the frozen `Capability` dataclass. `summary` (≤100 chars) is the only line the planner
  sees; `risk` is a first-class, code-enforced field (P4); `requires` carries preconditions.
- **Validation at construction.** Bad id, oversized summary, wrong enum, or negative cost
  raise immediately — malformed caps never reach a plan.
- **Two-stage routing (P5/§5).** A small boss can't hold 200 descriptions, so we never send
  the full list. The router embeds the goal, takes the top-k by cosine similarity over
  `summary + tags`, then **always** unions the pinned set (`plan.replan`, `memory.search`,
  `report.write`). The embedder is pluggable: Phase 1 ships a dependency-free TF-IDF
  embedder so routing works and is testable with zero model downloads; swap in the real
  `embed` provider in Phase 2 without changing router logic.
- **Honest loaders.** `builtin` holds the hand-authored seed. `mcp`/`skills`/`rag` are
  documented stubs (return `[]`) because those integrations don't exist yet — no duplicate
  ids, and the registry core is unchanged when they arrive.
- **net.* carries `requires=("netscope_server",)`** on the 12 NetScope-mapped caps so the
  precondition gate can emit the real "start `node server.js`, open `http://localhost:8089/`"
  message once, instead of every caller re-deriving it.

## CLI

```
hy3 caps list                 # 41 capabilities, one schema
hy3 caps show net.scan.lan    # full schema, cost, requires, tags
hy3 caps route "scan my LAN"  # top-15 + pinned set the planner would see
```

## Next (Phase 2)
Provider abstraction (`base.py`, `local_swap.py`, `lmstudio.py`), the egress classifier,
and the budget guard. The real `embed` provider plugs into `TwoStageRouter` here.
