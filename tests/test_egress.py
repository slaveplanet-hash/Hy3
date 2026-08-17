"""Tests for the egress classifier (plan §6/§14/§16).

Tricky cases from the plan: an RFC1918 address *inside a URL*, MAC in both colon
and dash forms, ``.local`` hostnames, UNC paths, and credential patterns.
"""
from __future__ import annotations

import pytest

from hy3.providers.base import EgressBlocked
from hy3.providers.egress import (
    Finding,
    check,
    contains_sensitive,
    hash_payload,
    redact,
    require_local,
)


def test_rfc1918_inside_url_is_blocked() -> None:
    v = check("open http://192.168.1.1/admin in the browser")
    assert v.blocked
    assert any(f.type == "private_ip" and f.text == "192.168.1.1" for f in v.findings)


def test_cgnat_and_link_local_blocked() -> None:
    assert check("reach 100.64.0.1 now").blocked
    assert check("arp says 169.254.1.7").blocked


def test_public_ip_is_allowed() -> None:
    v = check("query 8.8.8.8 and 1.1.1.1 for dns")
    assert not v.blocked


def test_mac_colon_and_dash_forms_blocked() -> None:
    assert check("host 00:1B:44:11:3A:9F is up").blocked
    assert check("nic DE-AD-BE-EF-00-11 seen").blocked


def test_local_hostname_blocked() -> None:
    assert check("ping router.local to debug").blocked


def test_windows_and_unc_paths_blocked() -> None:
    assert check("file at C:\\Users\\tom\\scan.txt").blocked
    assert check("share \\\\nas\\backups\\log.pcap").blocked


def test_credentials_blocked() -> None:
    assert check("use api_key=sk-1234567890abcdef").blocked
    assert check("Authorization: Bearer eyJabc.def.ghi").blocked


def test_capture_extension_blocked() -> None:
    assert check("wrote capture.pcapng from the tap").blocked


def test_clean_payload_passes() -> None:
    v = check("summarize the Q2 earnings report")
    assert not v.blocked
    assert v.redacted_preview == "summarize the Q2 earnings report"


def test_redact_masks_matched_spans() -> None:
    out = redact("host 192.168.1.1 at C:\\tmp\\x", [Finding("private_ip", "192.168.1.1")])
    assert "192.168.1.1" not in out
    assert "<REDACTED>" in out


def test_hash_is_deterministic() -> None:
    assert hash_payload("abc") == hash_payload("abc")
    assert hash_payload("abc") != hash_payload("abd")


def test_require_local_raises_on_sensitive() -> None:
    with pytest.raises(EgressBlocked):
        require_local("tell me about 10.0.0.5")


def test_contains_sensitive_matches_policy_use() -> None:
    assert contains_sensitive("10.0.0.5")
    assert not contains_sensitive("all good")
