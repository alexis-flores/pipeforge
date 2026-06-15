"""MO-1/2/3: motion stays within the 120-180ms ease-out budget (5.1)."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.widgets.timeline import TimelineWidget
from pipeforge.gui.workspace import Workspace

BUDGET = range(120, 181)


def _window(qtbot: QtBot) -> MainWindow:
    win = MainWindow(Workspace(), ThemeManager(None))
    qtbot.addWidget(win)
    return win


@pytest.mark.req("MO-1")
def test_critical_path_pulse_within_budget(qtbot: QtBot) -> None:
    w = TimelineWidget()
    qtbot.addWidget(w)
    anim = w.start_pulse()
    assert anim.duration() in BUDGET  # per-cycle within the motion budget
    assert anim.loopCount() == -1  # a continuous low-amplitude pulse


@pytest.mark.req("MO-2")
def test_view_switch_cross_fade(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_view("visualizer")
    assert win._fade_anim.duration() in BUDGET  # cross-fade, not a hard cut


@pytest.mark.req("MO-3")
def test_adopt_config_animates_chip(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.workspace.set_format(18, 14)  # adopt a new WIDTH/SCALE
    assert win._chip_anim.duration() in BUDGET  # the chip change is perceptible
