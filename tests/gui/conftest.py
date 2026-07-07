"""GUI test isolation: never touch the developer's real config directory."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_recent_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Recent-files persistence goes to a per-test directory, not ~/.config."""
    import pipeforge.gui.recent as recent

    monkeypatch.setattr(recent, "config_dir", lambda: tmp_path / "pipeforge-config")


@pytest.fixture(autouse=True)
def no_sidecar_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sidecar autosave off by default: GUI tests open shared repo fixtures and
    must never litter .pipeforge.toml next to them (PJ-1). Tests that exercise
    persistence flip the instance attribute back on with tmp files."""
    from pipeforge.gui.workspace import Workspace

    monkeypatch.setattr(Workspace, "sidecar_enabled", False)
