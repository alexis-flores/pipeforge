"""Canonical user-state locations (NF-7), Qt-free.

Everything PipeForge persists (settings, theme files, sweep cache, MATLAB
snapshots) lives under one config directory; deleting it yields a clean
first run. Files exchanged with the MATLAB container must live under the
user's home (the container shares it), which this directory satisfies.
"""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "pipeforge"
