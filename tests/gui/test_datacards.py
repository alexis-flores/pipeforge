"""WS-8: the Workspace data cards — visual browsing of snapshot data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio

pytest.importorskip("pytestqt")
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    win = MainWindow(Workspace(), ThemeManager(app))
    qtbot.addWidget(win)
    win.show()
    return win


@pytest.fixture
def showcase_mat(tmp_path: Path) -> Path:
    path = tmp_path / "showcase.mat"
    sio.savemat(
        str(path),
        {
            "sig": np.sin(np.linspace(0, 10, 200)),
            "A": np.eye(4) * 0.5,
            "cfg": {"gain": 0.75, "label": "hi"},
        },
    )
    return path


def test_cards_render_per_variable(window: MainWindow, showcase_mat: Path) -> None:
    from pipeforge.gui.views.matlab_view import MatlabView

    window.open_path(showcase_mat)
    view = window.views["golden"]
    assert isinstance(view, MatlabView)
    # numeric variables get cards (char cfg.label carries no numeric value but
    # still appears with an em-dash placeholder — it IS in the snapshot? no:
    # char fields are excluded from static snapshots entirely)
    view.cards.resize(800, 600)
    pixmap = view.cards.grab()  # paints without crashing, non-trivial content
    assert pixmap.width() > 0
    names = {v.name for v in view.cards._vars}
    assert names == {"sig", "A", "cfg.gain"}


def test_card_click_selects_matching_node(window: MainWindow, tmp_path: Path) -> None:
    from pipeforge.gui.views.matlab_view import MatlabView

    mat = tmp_path / "d.mat"
    sio.savemat(str(mat), {"a": 0.5, "b": 0.25})
    window.open_path(mat)
    m = tmp_path / "d.m"
    m.write_text("y = a .* b;\n", encoding="utf-8")
    window.open_path(m)
    view = window.views["golden"]
    assert isinstance(view, MatlabView)
    view.cards.variableClicked.emit("a")
    audit = window.workspace.audit
    assert audit is not None
    node = audit.dag.nodes[window.workspace.selected_node]
    assert node.label == "a"


def test_cards_filter_follows_search(window: MainWindow, showcase_mat: Path) -> None:
    from pipeforge.gui.views.matlab_view import MatlabView

    window.open_path(showcase_mat)
    view = window.views["golden"]
    assert isinstance(view, MatlabView)
    view.filter_edit.setText("cfg")
    assert {v.name for v in view.cards._vars} == {"cfg.gain"}


def test_cards_hit_testing(window: MainWindow, showcase_mat: Path) -> None:
    from pipeforge.gui.views.matlab_view import MatlabView

    window.open_path(showcase_mat)
    view = window.views["golden"]
    assert isinstance(view, MatlabView)
    view.cards.resize(800, 600)
    view.cards.grab()  # populates card rects
    rect, name = view.cards._rects[0]
    assert view.cards.card_at(rect.center().x(), rect.center().y()) == name
    assert view.cards.card_at(1.0, 1.0) == ""  # the gap between cards
