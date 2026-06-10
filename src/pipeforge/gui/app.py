"""GUI entry point (`pipeforge`)."""

from __future__ import annotations

import sys


def main() -> int:  # pragma: no cover - exercised manually / by smoke test parts
    from PyQt6.QtWidgets import QApplication

    from pipeforge.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("PipeForge")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
