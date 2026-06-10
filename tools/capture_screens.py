"""Capture docs/screens/ artifacts of the default theme (Phase 3 gate)."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace


def main() -> int:
    out_dir = Path(__file__).parent.parent / "docs" / "screens"
    out_dir.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).parent.parent / "tests" / "fixtures"

    app = QApplication(sys.argv)
    themes = ThemeManager(app)
    themes.apply("gruvbox-dark-soft")
    window = MainWindow(Workspace(), themes)
    window.show()
    window.open_path(fixtures / "example.m")
    app.processEvents()

    shots = {
        "audit": "01-audit-gruvbox-dark-soft.png",
        "visualizer": "02-visualizer-gruvbox-dark-soft.png",
        "settings": "03-settings-gruvbox-dark-soft.png",
    }
    for view, fname in shots.items():
        window.show_view(view)
        app.processEvents()
        window.grab().save(str(out_dir / fname), "PNG")
        print(f"saved {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
