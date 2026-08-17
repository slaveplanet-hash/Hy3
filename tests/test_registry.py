"""Tests for the capability schema and registry (Phase 1)."""
from __future__ import annotations

import pytest

from hy3.registry import Registry
from hy3.registry.capability import Capability, Cost, Kind, Risk


def test_capability_validation_rejects_long_summary() -> None:
    with pytest.raises(ValueError):
        Capability.build(
            id="x.y", kind="tool",
            summary="x" * 101, risk="read", tags=("t",),
        )


def test_capability_validation_rejects_bad_id() -> None:
    with pytest.raises(ValueError):
        Capability.build(id="NoDots", kind="tool", summary="ok", risk="read")


def test_capability_validation_rejects_bad_risk() -> None:
    with pytest.raises(ValueError):
        Capability.build(id="x.y", kind="tool", summary="ok", risk="bogus")


def test_capability_validation_rejects_negative_cost() -> None:
    with pytest.raises(ValueError):
        Capability.build(
            id="x.y", kind="tool", summary="ok", risk="read",
            cost=Cost(vram_gb=-1),
        )


def test_capability_build_fills_defaults() -> None:
    c = Capability.build(id="a.b", kind="model", summary="run a model", risk="read")
    assert c.kind is Kind.MODEL
    assert c.risk is Risk.READ
    assert c.schema_in == {}
    assert c.schema_out == {}
    assert c.cost == Cost()
    assert c.provenance == "builtin"


def test_registry_loads_unique_ids() -> None:
    reg = Registry.load()
    ids = reg.ids()
    assert len(ids) == len(set(ids)), "capability ids must be unique"


def test_registry_contains_pinned_set() -> None:
    reg = Registry.load()
    for pid in ("plan.replan", "memory.search", "report.write"):
        assert reg.get(pid) is not None, f"pinned capability missing: {pid}"


def test_registry_covers_all_kinds() -> None:
    reg = Registry.load()
    present = {c.kind for c in reg.all()}
    # builtin seeds tool, model, retriever; skill appears once skills loader lands.
    assert Kind.TOOL in present
    assert Kind.MODEL in present
    assert Kind.RETRIEVER in present


def test_registry_by_kind_and_risk() -> None:
    reg = Registry.load()
    assert reg.by_kind("tool")
    assert reg.by_risk("privileged")  # skill.promote
    assert all(c.risk is Risk.PRIVILEGED for c in reg.by_risk("privileged"))


def test_registry_netscope_caps_require_server() -> None:
    reg = Registry.load()
    # Capabilities mapped from the NetScope panels (plan §9.1) must declare the
    # server precondition so the gate can emit the real "start node server.js" copy.
    netscope_mapped = {
        "net.scan.lan", "net.config.get", "net.hosts.list", "net.conn.list",
        "net.l7.flows", "net.ports.listening", "net.endpoint.whois",
        "net.report.export", "net.diag.dns", "net.diag.traceroute",
        "net.diag.tls", "net.throughput.test",
    }
    for cid in netscope_mapped:
        cap = reg.get(cid)
        assert cap is not None, f"expected net capability: {cid}"
        assert "netscope_server" in cap.requires, f"{cid} missing netscope_server precondition"
