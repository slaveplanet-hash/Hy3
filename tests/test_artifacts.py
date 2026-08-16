"""Artifact store tests: content-addressed dedup (one file, many rows)."""
import os
import tempfile

from hy3.core import artifacts as A
from hy3.core import session as S


def test_same_bytes_one_file_two_rows(store):
    """Writing identical bytes twice -> one file on disk, two artifact rows."""
    sess = S.create(store, "g")
    data = b"x" * 2048 + b"hy3-artifact"
    a1 = A.put(store, data, kind="report", session_id=sess.id)
    a2 = A.put(store, data, kind="report", session_id=sess.id)

    assert a1.sha256 == a2.sha256
    assert a1.path == a2.path
    assert a1.id != a2.id  # distinct rows

    files = os.listdir(os.path.dirname(a1.path))
    assert len(files) == 1  # exactly one file
    assert os.path.exists(a1.path)
    assert len(store.list_artifacts(sess.id)) == 2


def test_path_put_dedups_against_bytes(store):
    """A file-path put of already-stored content reuses the same file."""
    sess = S.create(store, "g")
    data = b"shared content blob"
    a1 = A.put(store, data, kind="log", session_id=sess.id)

    p = os.path.join(tempfile.mkdtemp(), "f.bin")
    open(p, "wb").write(data)
    a2 = A.put(store, p, kind="log", session_id=sess.id)

    assert a1.path == a2.path
    assert len(store.list_artifacts(sess.id)) == 2
