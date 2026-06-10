"""PipeForge main window (UI-1). Phase 0: empty shell for the smoke test."""

from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow

from pipeforge import __version__


class MainWindow(QMainWindow):
    """Top-level window. Views and navigation arrive in Phase 3."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"PipeForge {__version__}")
        self.resize(1280, 800)
