# Phase 3 — Orchestrator (v0.4.0)

Phase 3 turns a boss plan into a validated, profile-batched, acceptance-checked run
that escalates to a replan on repeated failure instead of crashing. It ships the
orchestrator package, a `hy3 plan validate` CLI, and 34 new tests (94 total green).

## What was built

### `hy3/orchestrator/dag.py` — `Job` + `Dag`
- `Job.from_dict` parses the boss's grammar-constrained JSON (id, capability_id,
  profile, depends_on, inputs, acceptance, risk, max_tokens, retries).
- `Dag.validate()` enforces, up front: job count ≤ `max_jobs`; every
  `capability_id` exists in the registry; `risk ≤ session_ceiling`; `'none'`
  acceptance only for `risk=read`; all `depends_on` resolve. Cycles raise.
- Kahn topological sort; `batches()` returns contiguous same-profile runs of the
  topo order so the scheduler loads a model at most once per batch. Each batch is a
  contiguous subsegment of a valid topo order, so dependencies are always satisfied.

### `hy3/orchestrator/acceptance.py` — `accept(job, result, ...)`
- `none` (read-only pass), `schema` (JSON parse + required keys + property types;
  `schema_ref` resolved against the registry capability's `schema_out`), `regex`
  (match / `negate`), `test` (injected runner, or a tiny shell-free subprocess
  fallback), `critic` / `state` (injected runners — no core dependency).

### `hy3/orchestrator/escalate.py` — `Escalator`
- Hard safety rule from the plan: **two failures → no third attempt.** `MAX_ATTEMPTS=2`
  caps attempts; `MAX_REPLANS=3` caps replans per run to stop loops. `decision()`
  returns `RETRY | ESCALATE | GIVE_UP`.

### `hy3/orchestrator/boss.py` — `Boss`
- `plan_from_spec(jobs, registry)` → validated `Dag`; `replan(failed_job, result)`
  via an injected planner → `Dag | None`; `synthesize(records)` → report dict
  (jobs/ok/escalated/giveup/blocked, `reached` flag, text).

### `hy3/orchestrator/scheduler.py` — `Scheduler`
- Runs a `Dag` batch-by-batch: `provider.load(profile)` per batch, gate-by-risk,
  snapshot before write-tier jobs, execute, `accept`, retry within the per-job
  budget, then escalate → `boss.replan`. Execution, the operator gate, snapshots,
  acceptance runners, and the budget guard are all injected → fully testable with no
  GPU. `RunReport(records, loads, replans, report)`.

### CLI — `hy3 plan validate <file>`
- Reads a plan JSON (a job list or `{"jobs":[...], "session_ceiling", "max_jobs"}`),
  validates it, and prints the topological order and the profile batches (one model
  load each). Exits non-zero on an invalid plan.

## The Phase 3 gate (both hold)
- **"5-job plan executes with ≤3 model loads."** A 5-job plan over profiles
  `{analyst, analyst, boss, boss, coder}` builds 3 contiguous batches ⇒ exactly 3
  model loads (`tests/test_scheduler.py::test_five_job_plan_loads_at_most_three_models`).
- **"An injected failure escalates to replan, not to a crash."**
  `test_injected_failure_escalates_to_replan_not_crash` fails one job (regex
  acceptance), retries it (2 attempts), escalates to the boss's replan, runs the
  replan to success, and reports `reached=True` with no exception. Fault-injection
  variants cover: execute raises, goal unreachable (`replan→None` ⇒ giveup), budget
  exhaustion (hard stop), and operator gate denial (blocked, no crash).

## Notes / carry-forward
- Execution is injected; real `execute` needs capability handlers wired (Phase 4+).
  `Scheduler._default_execute` invokes the capability handler and wraps its output as
  a `Result` once handlers exist.
- `reached` is `True` only when nothing was given up or blocked by the operator.
- Next phases per plan: Phase 4 (memory tiers), Phase 5 (network/PC read tier +
  NetScope wrap + 8 playbooks), Phase 6 (operator console UI).
