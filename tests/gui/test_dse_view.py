"""DSE view tests (DSE-2): point presentation and the adopt action."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from pipeforge.core.dse.sweep import SweepPoint
from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.views.dse_view import DseView
from pipeforge.gui.workspace import Workspace


def _point(w: int, s: int, lat: int, err: float) -> SweepPoint:
    return SweepPoint(
        width=w,
        scale=s,
        latency=lat,
        instances=5,
        dividers=1,
        max_abs_error=err,
        rms_error=err / 2,
        sqnr_db=42.0,
    )


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    win = MainWindow(Workspace(), ThemeManager(app))
    qtbot.addWidget(win)
    win.show()
    return win


@pytest.mark.req("DSE-2")
def test_adopt_updates_workspace_format(window: MainWindow, qtbot: QtBot) -> None:
    view = window.views["dse"]
    assert isinstance(view, DseView)
    points = [_point(16, 12, 30, 0.01), _point(20, 16, 40, 0.001)]
    view.set_points(points)
    assert view.table.rowCount() == 2
    with qtbot.waitSignal(window.workspace.formatChanged, timeout=1000):
        view.adopt(points[1])
    assert (window.workspace.width, window.workspace.scale) == (20, 16)
    assert window.format_chip.text() == "20/16"  # status bar chip reacts (UI-2)


@pytest.mark.req("DSE-2")
def test_pareto_rows_marked_and_selectable(window: MainWindow) -> None:
    view = window.views["dse"]
    assert isinstance(view, DseView)
    dominated = _point(24, 16, 50, 0.02)  # dominated by both others
    view.set_points([_point(16, 12, 30, 0.01), _point(20, 16, 40, 0.001), dominated])
    stars = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert stars.count("★") == 2
    view.table.selectRow(0)
    assert view.selected_point() is not None
    assert view.adopt_btn.isEnabled()


def test_run_without_file_shows_problem(window: MainWindow, qtbot: QtBot) -> None:
    view = window.views["dse"]
    assert isinstance(view, DseView)
    with qtbot.waitSignal(window.workspace.problem, timeout=1000):
        view._run()
