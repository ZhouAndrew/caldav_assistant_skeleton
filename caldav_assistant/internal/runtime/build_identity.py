"""Stable per-process identity for the currently loaded Assistant source tree.

A long-running background daemon keeps Python modules in memory while an editable
installation may be updated on disk.  Compute the source fingerprint once at import
time so an old daemon keeps its old identity even after the files underneath it are
replaced.  A newly started CLI computes the fingerprint from the new files and can
therefore detect the stale process before sending business operations to it.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from ... import __version__


def _source_fingerprint() -> str:
    package_root = Path(__file__).resolve().parents[2]
    digest = sha256()
    digest.update(b"caldav-assistant-runtime-source-v1\0")

    for path in sorted(package_root.rglob("*.py")):
        try:
            relative = path.relative_to(package_root).as_posix()
            content = path.read_bytes()
        except OSError:
            continue
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")

    return digest.hexdigest()


RUNTIME_BUILD_IDENTITY = f"{__version__}+src.{_source_fingerprint()[:24]}"


__all__ = ["RUNTIME_BUILD_IDENTITY"]
