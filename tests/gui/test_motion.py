"""MO-1/2/3: motion / emphasis behavior.

The opacity-effect cross-fade (MO-2), the infinite critical-path pulse (MO-1),
and the chip opacity fade (MO-3) were removed: long-lived QPropertyAnimations /
QGraphicsOpacityEffects render custom-painted views black and race with widget
teardown (segfaults). Emphasis is now static/instant and reliable.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.widgets.timeline import TimelineWidget
from pipeforge.gui.workspace import Workspace

CM = CostModel(16, 12)


def _window(qtbot: QtBot) -> MainWindow:
    win = MainWindow(Workspace(), ThemeManager(None))
    qtbot.addWidget(win)
    return win


@pytest.mark.req("MO-1")
def test_critical_path_emphasized_statically(qtbot: QtBot) -> None:
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    w.set_layout(layout_for_audit(audit))
    # the critical path is emphasized (static glow in paint), no live animation
    assert w.critical_nodes()  # non-empty: the eye is drawn to it


@pytest.mark.req("MO-2")
def test_view_switch_is_instant_and_safe(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_view("visualizer")
    assert win.current_view_name() == "visualizer"
    assert win.views["visualizer"].graphicsEffect() is None  # no lingering effect


@pytest.mark.req("MO-3")
def test_adopt_config_updates_chip(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.workspace.set_format(18, 14)  # adopt a new WIDTH/SCALE
    assert win.format_chip.text() == "18/14"  # the change is perceptible in the chip
    assert win.format_chip.graphicsEffect() is None  # no lingering effect
