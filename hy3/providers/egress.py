"""Egress classifier (plan §6, §14, §16).

Every payload that would leave the machine for a remote provider is scanned here
first. We block by default: if it contains RFC1918/CGNAT/link-local addresses, MAC
addresses, ``.local`` hostnames, Windows/UNC paths, credentials, or capture
artifacts, it must not be sent to an API model. The operator may release specific
payloads; on release we record exactly what left (a hash) via ``egress.allow``.

This is what makes it safe to point the harness at your own network.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .base import EgressBlocked

# --- IPv4 candidate + private-range classification --------------------------------
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def _is_private(ip: str) -> bool:
    """True if ``ip`` is RFC1918, CGNAT (100.64/10), or link-local (169.254/16)."""
    parts = [int(p) for p in ip.split(".")]
    if len(parts) != 4 or any(p < 0 or p > 255 for p in parts):
        return False
    a, b = parts[0], parts[1]
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 100 and 64 <= b <= 127:  # CGNAT
        return True
    if a == 169 and b == 254:  # link-local
        return True
    return False


_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_LOCAL_RE = re.compile(r"\b[a-zA-Z0-9-]+\.local\b")
_WINDOWS_PATH_RE = re.compile(r"\b[a-zA-Z]:\\[^\s\"']+|\\\\[^\s\\]+\\[^\s\"']+")
_CRED_RE = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|token|authorization)"
    r"\s*[:=]\s*\S+|\bBearer\s+[A-Za-z0-9._-]{8,}"
)
_PCAP_RE = re.compile(r"(?i)\b(?:[\w-]+\.pcapng?|[\w-]+\.cap)\b")


class FindingType:
    PRIVATE_IP = "private_ip"
    MAC = "mac"
    LOCAL_HOST = "local_host"
    WINDOWS_PATH = "windows_path"
    CREDENTIAL = "credential"
    CAPTURE = "capture"


@dataclass
class Finding:
    type: str
    text: str


@dataclass
class EgressVerdict:
    """Result of scanning a payload that may leave the machine."""

    blocked: bool
    findings: list[Finding] = field(default_factory=list)
    redacted_preview: str = ""
    payload_hash: str = ""

    @property
    def reasons(self) -> list[str]:
        return [f"{f.type}:{f.text}" for f in self.findings]


def _find_private_ips(text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in _IPV4_RE.finditer(text):
        ip = m.group(0)
        if _is_private(ip):
            out.append(Finding(FindingType.PRIVATE_IP, ip))
    return out


def _scan(text: str) -> list[Finding]:
    findings: list[Finding] = []
    findings += _find_private_ips(text)
    for m in _MAC_RE.finditer(text):
        findings.append(Finding(FindingType.MAC, m.group(0)))
    for m in _LOCAL_RE.finditer(text):
        findings.append(Finding(FindingType.LOCAL_HOST, m.group(0)))
    for m in _WINDOWS_PATH_RE.finditer(text):
        findings.append(Finding(FindingType.WINDOWS_PATH, m.group(0)))
    for m in _CRED_RE.finditer(text):
        findings.append(Finding(FindingType.CREDENTIAL, m.group(0)))
    for m in _PCAP_RE.finditer(text):
        findings.append(Finding(FindingType.CAPTURE, m.group(0)))
    return findings


def check(payload: str) -> EgressVerdict:
    """Scan ``payload`` and return whether it may leave the machine.

    Blocked by default whenever any sensitive pattern is found. The redaction
    preview shows what would be masked; ``payload_hash`` identifies exactly what
    left if the operator later releases it.
    """
    findings = _scan(payload)
    blocked = len(findings) > 0
    return EgressVerdict(
        blocked=blocked,
        findings=findings,
        redacted_preview=redact(payload, findings) if findings else payload,
        payload_hash=hash_payload(payload),
    )


def contains_sensitive(payload: str) -> bool:
    """Convenience predicate for the routing policy."""
    return bool(_scan(payload))


def redact(payload: str, findings: list[Finding]) -> str:
    """Mask every matched span. Overlapping spans are handled by sorting."""
    if not findings:
        return payload
    spans = sorted(
        ((payload.find(f.text), len(f.text)) for f in findings if f.text),
        reverse=True,
    )
    out = payload
    for start, length in spans:
        if start >= 0:
            out = out[:start] + "<REDACTED>" + out[start + length:]
    return out


def hash_payload(payload: str) -> str:
    """SHA-256 of exactly what would leave, for the egress.allow record."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def require_local(payload: str) -> None:
    """Raise ``EgressBlocked`` if ``payload`` cannot be sent to a remote provider.

    Called by remote providers inside ``complete()`` before any bytes leave.
    """
    verdict = check(payload)
    if verdict.blocked:
        raise EgressBlocked(
            "payload blocked by egress classifier: "
            + ", ".join(verdict.reasons)
        )
