"""Phase 0 gate: empty-window smoke test under the offscreen platform."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import MainWindow


def test_main_window_shows(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
    assert "PipeForge" in window.windowTitle()
