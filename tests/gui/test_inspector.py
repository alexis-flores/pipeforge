"""UI-7 / WS-6: structured node inspector (not a full-file dump)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.workspace.mat_loader import WorkspaceTree, WsField
from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace

SRC = "alpha = a .* b;\nbeta = c + d;\ngamma = alpha ./ beta;"


def _window(qtbot: QtBot) -> MainWindow:
    win = MainWindow(Workspace(), ThemeManager(None))
    qtbot.addWidget(win)
    return win


@pytest.mark.req("UI-7")
def test_node_selection_shows_structured_facts(qtbot: QtBot, tmp_path: Path) -> None:
    win = _window(qtbot)
    m = tmp_path / "d.m"
    m.write_text(SRC, encoding="utf-8")
    win.open_path(m)
    alpha = win.workspace.audit.dag.statements[0].root
    win.workspace.select_node(alpha)

    text = win.inspector_label.text()
    assert "kind:" in text
    assert "latency:" in text and "ready @ cycle" in text
    assert "slack" in text  # UI-7 adds slack to the facts
    assert "line 1:" in text and "alpha" in text  # originating source line


@pytest.mark.req("UI-7")
def test_inspector_not_full_file_dump(qtbot: QtBot, tmp_path: Path) -> None:
    win = _window(qtbot)
    m = tmp_path / "d.m"
    m.write_text(SRC, encoding="utf-8")
    win.open_path(m)
    alpha = win.workspace.audit.dag.statements[0].root
    win.workspace.select_node(alpha)
    # local context only: a distant statement's text is not in the inspector
    assert "gamma" not in win.inspector_label.text()


@pytest.mark.req("UI-11")
def test_inspector_collapsible_and_persisted(qtbot: QtBot) -> None:
    ws = Workspace()
    win = MainWindow(ws, ThemeManager(None))
    qtbot.addWidget(win)
    assert not win.inspector.isHidden()  # expanded by default
    win.toggle_inspector()
    assert win.inspector.isHidden()  # collapsed, reclaiming space
    assert win.workspace.inspector_collapsed is True
    # the collapsed state persists into a new window built on the same workspace
    win2 = MainWindow(ws, ThemeManager(None))
    qtbot.addWidget(win2)
    assert win2.inspector.isHidden()


@pytest.mark.req("WS-6")
def test_software_field_value_shape_format_shown(qtbot: QtBot, tmp_path: Path) -> None:
    win = _window(qtbot)
    m = tmp_path / "d.m"
    m.write_text("y = cfg.gain .* x;", encoding="utf-8")
    win.open_path(m)
    # a loaded .mat tree supplies the software field facts (WS-6)
    win.workspace.software_tree = WorkspaceTree(
        "params.mat", "v5", {"cfg.gain": WsField("cfg.gain", (1, 1), (0.5,), "double")}
    )
    gain_nid = next(n.nid for n in win.workspace.audit.dag.inputs() if n.label == "cfg.gain")
    win.workspace.select_node(gain_nid)
    text = win.inspector_label.text()
    assert "software.cfg.gain" in text
    assert "double" in text and "1x1" in text and "0.5" in text
