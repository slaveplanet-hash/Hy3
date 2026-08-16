"""Content-addressed artifact store (plan §4: ``artifacts`` table).

Artifacts live on disk under ``<store.root>/data/artifacts/<sha[:2]>/<sha>`` and are
addressed by SHA-256. Writing the same bytes twice writes the file once and creates
a second artifact row pointing at the same path — dedup without copying bytes.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from typing import Any, Optional, Union

from .ids import ulid
from .store import Store, now_ms

Content = Union[bytes, str, "os.PathLike[str]"]


@dataclass
class Artifact:
    """In-memory view of an ``artifacts`` row."""

    id: str
    session_id: str
    sha256: str
    path: str
    kind: str
    bytes: Optional[int]
    created_at: int
    job_id: Optional[str] = None


def _hash_and_size(content: Content) -> tuple[str, int, Optional[str]]:
    """Return (sha256_hex, byte_count, source_path_or_None) for bytes or a file path."""
    hasher = hashlib.sha256()
    if isinstance(content, (str, os.PathLike)):
        total = 0
        with open(content, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                hasher.update(chunk)
                total += len(chunk)
        return hasher.hexdigest(), total, os.path.abspath(content)
    hasher.update(content)
    return hasher.hexdigest(), len(content), None


def _row_to_artifact(row: Any) -> Artifact:
    """Build an ``Artifact`` from a sqlite3.Row."""
    return Artifact(
        id=row["id"],
        session_id=row["session_id"],
        sha256=row["sha256"],
        path=row["path"],
        kind=row["kind"],
        bytes=row["bytes"],
        created_at=row["created_at"],
        job_id=row["job_id"],
    )


def put(
    store: Store,
    content: Content,
    *,
    kind: str,
    session_id: str,
    job_id: Optional[str] = None,
) -> Artifact:
    """Store ``content`` (bytes or a file path) and return its ``Artifact``.

    Deduplicates: if the content hash already exists, the existing file is reused
    and only a new metadata row is written. Never overwrites an existing file.
    """
    sha, size, src_path = _hash_and_size(content)
    existing = store.get_artifact_by_sha(sha)
    if existing is not None:
        target_path = existing["path"]  # reuse the on-disk bytes, no copy
    else:
        target_dir = os.path.join(store.root, "data", "artifacts", sha[:2])
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, sha)
        if src_path is not None and os.path.abspath(src_path) == os.path.abspath(target_path):
            pass  # content already lives at the addressed location
        elif src_path is not None:
            shutil.copyfile(src_path, target_path)
        else:
            with open(target_path, "wb") as out:
                out.write(content)  # type: ignore[arg-type]

    row = {
        "id": ulid(),
        "session_id": session_id,
        "job_id": job_id,
        "sha256": sha,
        "path": target_path,
        "kind": kind,
        "bytes": size,
        "created_at": now_ms(),
    }
    store.insert_artifact(row)
    return _row_to_artifact(row)


def get(store: Store, artifact_id: str) -> Optional[Artifact]:
    """Fetch an artifact by id, or None."""
    row = store.get_artifact(artifact_id)
    return _row_to_artifact(row) if row is not None else None


def get_by_sha(store: Store, sha256: str) -> Optional[Artifact]:
    """Fetch the first artifact with the given content hash, or None."""
    row = store.get_artifact_by_sha(sha256)
    return _row_to_artifact(row) if row is not None else None
