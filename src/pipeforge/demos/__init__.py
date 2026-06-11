"""Curated, packaged demos — one minimal example per capability.

Both the CLI (``pipeforge-cli demos``) and the GUI Demos window
(Ctrl+Shift+D) read :func:`load_index`; the files ship inside the package so
pip installs get them too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class DemoEntry:
    demo_id: str
    title: str
    files: tuple[str, ...]  # relative to demo_dir()
    description: str
    command: str  # suggested CLI, with {dir} placeholder resolved
    gui: str  # how to try it in the GUI

    def paths(self) -> list[Path]:
        base = demo_dir()
        return [base / f for f in self.files]


def demo_dir() -> Path:
    """Filesystem location of the packaged demo files."""
    return Path(str(resources.files(__package__)))


def load_index() -> list[DemoEntry]:
    raw = json.loads((demo_dir() / "index.json").read_text(encoding="utf-8"))
    out: list[DemoEntry] = []
    for item in raw:
        out.append(
            DemoEntry(
                demo_id=str(item["id"]),
                title=str(item["title"]),
                files=tuple(str(f) for f in item["files"]),
                description=str(item["description"]),
                command=str(item["command"]).replace("{dir}", str(demo_dir())),
                gui=str(item["gui"]),
            )
        )
    return out
