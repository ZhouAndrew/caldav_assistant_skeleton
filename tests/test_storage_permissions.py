from __future__ import annotations

import os
import stat

import pytest

from caldav_assistant.internal.storage.sqlite import SQLiteStore


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not apply on Windows")
def test_sqlite_state_directory_and_database_are_private(tmp_path):
    state_dir = tmp_path / "state"
    database = state_dir / "assistant.sqlite3"

    SQLiteStore(database).migrate()

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not apply on Windows")
def test_existing_overly_open_state_is_tightened_on_connect(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o755)
    database = state_dir / "assistant.sqlite3"
    database.touch(mode=0o644)
    state_dir.chmod(0o755)
    database.chmod(0o644)

    with SQLiteStore(database).connect():
        pass

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
