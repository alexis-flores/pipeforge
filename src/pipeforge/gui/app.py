"""GUI entry point (`pipeforge`) with a global exception guard (NF-4)."""

from __future__ import annotations

import sys
import traceback
from types import TracebackType


def main() -> int:  # pragma: no cover - thin shell; pieces tested via pytest-qt
    from PyQt6.QtWidgets import QApplication

    from pipeforge.gui.main_window import MainWindow
    from pipeforge.gui.theme.manager import ThemeManager
    from pipeforge.gui.workspace import Workspace

    app = QApplication(sys.argv)
    app.setApplicationName("PipeForge")
    app.setOrganizationName("pipeforge")

    themes = ThemeManager(app)
    themes.restore()
    workspace = Workspace()
    window = MainWindow(workspace, themes)

    def excepthook(
        exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> None:
        # NF-4: log, toast, keep running — never an unhandled crash dialog.
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        window.log(text)
        window.toast.show_message(f"Unexpected error: {exc}. Details in the console (Ctrl+`).")

    sys.excepthook = excepthook

    window.show()
    from pathlib import Path

    for arg in sys.argv[1:]:
        path = Path(arg)
        if path.is_file():
            window.open_path(path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
