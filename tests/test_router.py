"""Tests for the two-stage capability router (plan §5).

Gate (plan §15): the router must return a sane top-15 for 20 test goals, and the
pinned set (plan.replan, memory.search, report.write) must always be present.
"""
from __future__ import annotations

from hy3.registry import Registry

REGISTRY = Registry.load()
PINNED = {"plan.replan", "memory.search", "report.write"}

# 20 goals across the capability space, each with the tag vocabulary a routed
# capability should overlap with.
GOALS: list[tuple[str, set[str]]] = [
    ("scan my LAN for devices", {"scan", "hosts", "lan", "network", "discovery"}),
    ("why does my Wi-Fi keep dropping", {"wifi", "network"}),
    ("check DNS resolution for example.com", {"dns"}),
    ("traceroute to 8.8.8.8 and show latency", {"traceroute"}),
    ("list listening ports on this machine", {"ports", "listening"}),
    ("what processes are making external connections", {"flows", "connections", "process"}),
    ("who owns this IP address", {"whois", "endpoint"}),
    ("capture a baseline of my network", {"baseline"}),
    ("what changed since the last baseline", {"baseline", "diff", "drift"}),
    ("restart the Print Spooler service", {"svc", "restart", "services"}),
    ("show me my Windows host info", {"host", "pc"}),
    ("list my scheduled tasks", {"scheduled", "tasks"}),
    ("read SMART data from my disk", {"disk", "smart"}),
    ("search the web for recent CVEs", {"web", "search", "research"}),
    ("fetch this article and summarize it", {"web", "fetch", "research"}),
    ("look up our Network MD docs on slow internet", {"rag", "research"}),
    ("take a screenshot of the desktop", {"screenshot", "desktop"}),
    ("click the OK button in the dialog", {"click", "desktop"}),
    ("plan how to diagnose the outage", {"plan", "replan"}),
    ("propose a skill from the last successful runs", {"skill"}),
]


def test_pinned_set_always_routed() -> None:
    for goal, _ in GOALS:
        routed = REGISTRY.retrieve(goal, top_k=15)
        ids = {c.id for c in routed}
        assert PINNED <= ids, f"pinned set missing for goal {goal!r}: {ids ^ PINNED}"


def test_top_k_is_bounded() -> None:
    for goal, _ in GOALS:
        routed = REGISTRY.retrieve(goal, top_k=15)
        # ANN top-15 plus the (<=3) pinned extras.
        assert len(routed) <= 18, f"routed set too large for {goal!r}: {len(routed)}"


def test_relevant_capability_is_routed_per_goal() -> None:
    for goal, expected_tags in GOALS:
        routed = REGISTRY.retrieve(goal, top_k=15)
        routed_tags = {t for c in routed for t in c.tags}
        assert expected_tags & routed_tags, (
            f"no relevant capability routed for {goal!r}; "
            f"expected tags {expected_tags}, got {routed_tags}"
        )


def test_route_is_deterministic() -> None:
    a = [c.id for c in REGISTRY.retrieve("scan my LAN for devices", top_k=15)]
    b = [c.id for c in REGISTRY.retrieve("scan my LAN for devices", top_k=15)]
    assert a == b
