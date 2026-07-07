"""GUI test isolation: never touch the developer's real config directory."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_recent_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recent-files persistence goes to a per-test directory, not ~/.config."""
    import pipeforge.gui.recent as recent

    monkeypatch.setattr(recent, "config_dir", lambda: tmp_path / "pipeforge-config")
