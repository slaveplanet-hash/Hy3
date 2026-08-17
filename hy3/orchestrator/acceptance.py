"""Acceptance checks (plan §7).

Every job declares a machine-checkable success condition. ``accept`` is the single
entry point the scheduler calls after execution. Built-in types: ``none``, ``schema``,
``regex``. ``test`` / ``critic`` / ``state`` defer to injected runners so the harness
stays dependency-free and fully testable (e.g. a ``test`` runner can shell out, a
``critic`` runner can score prose, a ``state`` runner can re-observe the world).

``none`` is accepted only for ``risk=read`` observation jobs — that gate is enforced
earlier in ``Dag.validate``, but we also guard here so a Job built out of band fails loud.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Any, Callable, Optional

from hy3.orchestrator.dag import Job
from hy3.providers.base import Result

# runner contracts
TestRunner = Callable[[str], bool]          # command string -> success?
CriticRunner = Callable[[Job, Result], float]  # -> score in [0, 1]
StateRunner = Callable[[Job, Result], bool]    # re-observe & diff -> ok?

_TYPE_MAP = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _type_ok(value: Any, declared: str) -> bool:
    exp = _TYPE_MAP.get(declared)
    if exp is None:  # unknown declared type -> don't block
        return True
    return isinstance(value, exp)


def _validate_schema(data: Any, schema: dict) -> bool:
    """Minimal JSON-Schema check: required keys present + property types match."""
    if not isinstance(data, dict):
        return False
    for key in schema.get("required", []):
        if key not in data:
            return False
    props = schema.get("properties", {})
    for key, value in data.items():
        if key in props and not _type_ok(value, props[key].get("type", "")):
            return False
    return True


def _resolve_schema(spec: dict, job: Job, registry) -> dict:
    """A job's acceptance schema comes from ``spec['schema']`` or a registry ref."""
    if "schema" in spec and isinstance(spec["schema"], dict):
        return spec["schema"]
    ref = spec.get("schema_ref")
    if ref and registry is not None:
        cap = registry.get(ref)
        if cap is not None and cap.schema_out:
            return cap.schema_out
    # No schema available -> accept any parsed JSON object.
    return {"type": "object"}


def _default_test_runner(command: str) -> bool:
    """Fallback ``test`` runner: run the command, require exit 0.

    Used only when no runner is injected; kept deliberately tiny and shell-free
    (no shell=True) so a bad command can't expand.
    """
    if not command:
        return False
    try:
        rc = subprocess.run(
            shlex.split(command), capture_output=True, text=True
        ).returncode
    except Exception:
        return False
    return rc == 0


def accept(
    job: Job,
    result: Any,
    *,
    registry=None,
    runners: Optional[dict] = None,
) -> bool:
    """Return True iff ``result`` satisfies ``job.acceptance``.

    ``result`` is normally a ``Result``; a plain string is also accepted for tests.
    """
    runners = runners or {}
    spec = job.acceptance or {}
    atype = spec.get("type", "none")
    text = result.text if isinstance(result, Result) else str(result)

    if atype == "none":
        if job.risk is not None and job.risk.value != "read":
            # Enforced upstream too; fail loud if a Job slipped through.
            return False
        return True

    if atype == "schema":
        schema = _resolve_schema(spec, job, registry)
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return False
        return _validate_schema(data, schema)

    if atype == "regex":
        pattern = spec.get("pattern", "")
        try:
            match = re.search(pattern, text) is not None
        except re.error:
            return False
        return (not match) if spec.get("negate") else match

    if atype == "test":
        command = spec.get("command", "")
        runner = runners.get("test")
        if runner is None:
            return _default_test_runner(command)
        return bool(runner(command))

    if atype == "state":
        runner = runners.get("state")
        if runner is None:
            raise ValueError("'state' acceptance requires an injected runner")
        return bool(runner(job, result))

    if atype == "critic":
        runner = runners.get("critic")
        if runner is None:
            raise ValueError("'critic' acceptance requires an injected runner")
        score = float(runner(job, result))
        threshold = float(spec.get("threshold", 0.5))
        return score >= threshold

    raise ValueError(f"unknown acceptance type: {atype!r}")
