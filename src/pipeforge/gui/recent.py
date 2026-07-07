"""Recently opened files, persisted alongside the theme choice (NF-7).

Stored as a path list under the ``recentFiles`` key of the same
``settings.json`` the ThemeManager uses, so deleting the config directory
still yields a clean first run.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeforge.gui.theme.manager import config_dir

MAX_RECENT = 10


def _settings_path() -> Path:
    return config_dir() / "settings.json"


def _read() -> dict[str, object]:
    path = _settings_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def load_recent() -> list[Path]:
    """Recent files, most recent first, silently dropping ones that vanished."""
    raw = _read().get("recentFiles", [])
    if not isinstance(raw, list):
        return []
    return [Path(p) for p in raw if isinstance(p, str) and Path(p).is_file()]


def clear_recent() -> None:
    """Empty the recent-files list (File → Open Recent → Clear)."""
    data = _read()
    data["recentFiles"] = []
    try:
        settings = _settings_path()
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def add_recent(path: Path) -> list[Path]:
    """Record one opened file; returns the updated list (never raises)."""
    entries = [str(path)] + [str(p) for p in load_recent() if p != path]
    entries = entries[:MAX_RECENT]
    data = _read()
    data["recentFiles"] = entries
    try:
        settings = _settings_path()
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
    return [Path(p) for p in entries]
