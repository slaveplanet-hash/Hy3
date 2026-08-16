"""ULID generator tests."""
import threading

from hy3.core.ids import ulid, _CROCKFORD


def test_length_and_charset():
    """A ULID is 26 chars drawn from the Crockford base32 alphabet."""
    u = ulid()
    assert len(u) == 26
    assert all(c in _CROCKFORD for c in u)


def test_unique():
    """Two generated ULIDs are distinct."""
    assert ulid() != ulid()


def test_monotonic_and_sortable():
    """Generated-in-order ULIDs sort lexicographically (timestamp dominant)."""
    ids = [ulid() for _ in range(2000)]
    assert ids == sorted(ids)


def test_monotonic_under_threading():
    """Concurrent generation still yields unique, sortable ids."""
    out = []

    def worker():
        for _ in range(500):
            out.append(ulid())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == len(set(out))
    assert out == sorted(out)
