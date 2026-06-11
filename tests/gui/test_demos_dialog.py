"""Demos window tests: listing, detail pane, opening into the workspace."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from pipeforge.demos import load_index
from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.widgets.demos_dialog import DemosDialog
from pipeforge.gui.workspace import Workspace


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    win = MainWindow(Workspace(), ThemeManager(app))
    qtbot.addWidget(win)
    win.show()
    return win


def test_dialog_lists_all_demos(window: MainWindow, qtbot: QtBot) -> None:
    dialog = DemosDialog(window.open_path, window)
    qtbot.addWidget(dialog)
    entries = load_index()
    assert dialog.listing.count() == len(entries)
    dialog.listing.setCurrentRow(1)
    assert entries[1].description.split(":")[0] in dialog.detail.text()
    assert entries[1].command in dialog.command.toPlainText()


def test_open_demo_populates_workspace(window: MainWindow, qtbot: QtBot) -> None:
    dialog = DemosDialog(window.open_path, window)
    qtbot.addWidget(dialog)
    row = next(i for i, e in enumerate(load_index()) if e.demo_id == "02_normalize3d")
    dialog.listing.setCurrentRow(row)
    with qtbot.waitSignal(window.workspace.auditChanged, timeout=2000):
        dialog._open_selected()
    audit = window.workspace.audit
    assert audit is not None
    assert audit.filename == "02_normalize3d.m"
    assert any(f.tag == "RECIP" for f in audit.findings)


def test_pair_demo_opens_both_files(window: MainWindow, qtbot: QtBot) -> None:
    dialog = DemosDialog(window.open_path, window)
    qtbot.addWidget(dialog)
    row = next(i for i, e in enumerate(load_index()) if e.demo_id == "03_pipeline")
    dialog.listing.setCurrentRow(row)
    dialog._open_selected()
    assert window.workspace.m_path is not None
    assert window.workspace.m_path.name == "03_pipeline.m"
    assert window.workspace.sv_path is not None
    assert window.workspace.sv_path.name == "03_pipeline.sv"


def test_shortcut_registered(window: MainWindow) -> None:
    shortcuts = [a.shortcut().toString() for a in window.actions()]
    assert QKeySequence("Ctrl+Shift+D").toString() in shortcuts
    # and the status hint mentions it
    assert "Ctrl+Shift+D" in window.file_label.text()
