"""Acceptance check types (plan §7): none / schema / regex / test / critic / state."""
from __future__ import annotations

import pytest

from hy3.orchestrator.acceptance import accept
from hy3.orchestrator.dag import Job
from hy3.providers.base import Result
from hy3.registry.capability import Risk


def read_job(**kw) -> Job:
    base = dict(id="j", capability_id="net.scan.lan", risk="read")
    base.update(kw)
    return Job.from_dict(base)


def res(text: str) -> Result:
    return Result(text=text)


# -- none --------------------------------------------------------------------
def test_none_accepts_read_job():
    assert accept(read_job(acceptance={"type": "none"}), res("anything"))


def test_none_rejects_write_job():
    job = read_job(risk="write", acceptance={"type": "none"})
    assert accept(job, res("anything")) is False


# -- schema ------------------------------------------------------------------
def test_schema_pass():
    job = read_job(acceptance={
        "type": "schema",
        "schema": {"required": ["ip"],
                   "properties": {"ip": {"type": "string"}}},
    })
    assert accept(job, res('{"ip": "10.0.0.1"}'))


def test_schema_missing_required_fails():
    job = read_job(acceptance={
        "type": "schema",
        "schema": {"required": ["ip"], "properties": {}},
    })
    assert not accept(job, res("{}"))


def test_schema_wrong_type_fails():
    job = read_job(acceptance={
        "type": "schema",
        "schema": {"required": ["ip"], "properties": {"ip": {"type": "string"}}},
    })
    assert not accept(job, res('{"ip": 123}'))


def test_schema_not_json_fails():
    job = read_job(acceptance={
        "type": "schema",
        "schema": {"required": ["ip"], "properties": {}},
    })
    assert not accept(job, res("not json at all"))


def test_schema_ref_resolves_via_registry():
    # schema_ref to a real capability whose schema_out is empty -> falls back to
    # "accept any object". We just verify the path doesn't crash and accepts JSON.
    reg = pytest.importorskip("hy3.registry").Registry.load()
    job = read_job(acceptance={"type": "schema", "schema_ref": "net.scan.lan"})
    assert accept(job, res('{"ok": true}'), registry=reg)


# -- regex -------------------------------------------------------------------
def test_regex_match():
    job = read_job(acceptance={"type": "regex", "pattern": "ERROR"})
    assert accept(job, res("line 1 ERROR boom"))


def test_regex_no_match_fails():
    job = read_job(acceptance={"type": "regex", "pattern": "ERROR"})
    assert not accept(job, res("all good"))


def test_regex_negate():
    job = read_job(acceptance={"type": "regex", "pattern": "ERROR", "negate": True})
    assert accept(job, res("all good"))
    assert not accept(job, res("ERROR here"))


# -- injected runners --------------------------------------------------------
def test_test_runner_injected():
    job = read_job(acceptance={"type": "test", "command": "echo hi"})
    assert accept(job, res(""), runners={"test": lambda cmd: True})
    assert not accept(job, res(""), runners={"test": lambda cmd: False})


def test_critic_runner_injected():
    job = read_job(acceptance={"type": "critic", "threshold": 0.5})
    assert accept(job, res(""), runners={"critic": lambda j, r: 0.9})
    assert not accept(job, res(""), runners={"critic": lambda j, r: 0.1})


def test_state_runner_injected():
    job = read_job(acceptance={"type": "state"})
    assert accept(job, res(""), runners={"state": lambda j, r: True})
    assert not accept(job, res(""), runners={"state": lambda j, r: False})


def test_state_without_runner_raises():
    job = read_job(acceptance={"type": "state"})
    with pytest.raises(ValueError):
        accept(job, res(""))


def test_unknown_acceptance_type_raises():
    job = read_job(acceptance={"type": "bogus"})
    with pytest.raises(ValueError):
        accept(job, res(""))
