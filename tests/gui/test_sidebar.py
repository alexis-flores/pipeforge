"""UI-8: legible sidebar items with an unmistakable active indicator."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace


def _window(qtbot: QtBot) -> MainWindow:
    win = MainWindow(Workspace(), ThemeManager(None))
    qtbot.addWidget(win)
    return win


@pytest.mark.req("UI-8")
def test_sidebar_items_have_labels_or_tooltips(qtbot: QtBot) -> None:
    win = _window(qtbot)
    for name, btn in win.nav_buttons.items():
        # individually legible: a tooltip (and accessible name) at minimum
        assert btn.toolTip(), f"{name} has no tooltip"
        assert btn.accessibleName()


@pytest.mark.req("UI-8")
def test_active_item_has_accent_indicator(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_view("visualizer")
    # exactly the active item carries the accent indicator property (UI-8)
    assert win.nav_buttons["visualizer"].property("active") is True
    assert win.nav_buttons["visualizer"].isChecked()
    assert all(
        win.nav_buttons[n].property("active") is False for n in win.nav_buttons if n != "visualizer"
    )
