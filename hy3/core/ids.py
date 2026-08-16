"""ULID generation — 26-char, lexicographically sortable, monotonic within a process.

No external dependency. Crockford base32, 48-bit millisecond timestamp + 80-bit
randomness. When the clock does not advance between calls (or goes backwards),
the randomness component is incremented instead, preserving sort order.
"""
import os
import threading
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # excludes I L O U
_LOCK = threading.Lock()
_LAST_MS = 0
_LAST_RAND = bytes(10)


def _now_ms() -> int:
    """Return the current wall-clock time as integer milliseconds (UTC)."""
    return time.time_ns() // 1_000_000


def _encode_ts(ms: int) -> str:
    """Encode a 48-bit millisecond value into 10 Crockford base32 chars."""
    out = ""
    for _ in range(10):
        out = _CROCKFORD[ms & 0x1F] + out
        ms >>= 5
    return out


def _encode_rand(rand: bytes) -> str:
    """Encode 10 random bytes (80 bits) into 16 Crockford base32 chars."""
    n = int.from_bytes(rand, "big")
    out = ""
    for _ in range(16):
        out = _CROCKFORD[n & 0x1F] + out
        n >>= 5
    return out


def _increment(b: bytes) -> bytes:
    """Increment a big-endian byte string, wrapping at the top (extremely rare)."""
    data = bytearray(b)
    for i in range(len(data) - 1, -1, -1):
        if data[i] == 0xFF:
            data[i] = 0
        else:
            data[i] += 1
            break
    return bytes(data)


def ulid() -> str:
    """Return a new ULID string, monotonic within this process."""
    global _LAST_MS, _LAST_RAND
    with _LOCK:
        now = _now_ms()
        if now <= _LAST_MS:
            # Clock stalled or went backwards: keep the timestamp, advance randomness.
            rand = _increment(_LAST_RAND)
            ts = _LAST_MS
        else:
            _LAST_MS = now
            rand = os.urandom(10)
            ts = now
        _LAST_RAND = rand
    return _encode_ts(ts) + _encode_rand(rand)
