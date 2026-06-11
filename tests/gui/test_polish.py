"""Phase 8 GUI polish tests: command palette, slack overlay, bisection rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.widgets.palette import CommandPalette
from pipeforge.gui.workspace import Workspace

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    win = MainWindow(Workspace(), ThemeManager(app))
    qtbot.addWidget(win)
    win.show()
    return win


@pytest.mark.req("UI-4")
def test_command_palette_filters_and_runs(window: MainWindow, qtbot: QtBot) -> None:
    palette = CommandPalette(window)
    qtbot.addWidget(palette)
    palette.set_commands(window.palette_commands())  # type: ignore[arg-type]
    all_commands = palette.visible_commands()
    assert "Open file…" in all_commands
    assert any(c.startswith("Go to") for c in all_commands)
    assert any(c.startswith("Theme:") for c in all_commands)
    palette.search.setText("go codegen")
    assert palette.visible_commands() == ["Go to Codegen"]
    palette.listing.setCurrentRow(0)
    palette._run_selected()
    assert window.current_view_name() == "codegen"


@pytest.mark.req("VZ-1")
def test_slack_overlay_toggle(window: MainWindow) -> None:
    window.open_path(FIXTURES / "example.m")
    from pipeforge.gui.views.visualizer_view import VisualizerView

    viz = window.views["visualizer"]
    assert isinstance(viz, VisualizerView)
    viz.slack_btn.setChecked(True)
    assert viz.timeline._slack  # populated from compute_slack
    audit = window.workspace.audit
    assert audit is not None
    critical = {n.nid for n in audit.critical_path()}
    for nid in critical:
        if nid in viz.timeline._slack:
            assert viz.timeline._slack[nid] == 0  # critical path has zero slack
    viz.slack_btn.setChecked(False)
    assert not viz.timeline._slack


@pytest.mark.req("BI-3")
def test_timeline_renders_bisection_states(window: MainWindow) -> None:
    window.open_path(FIXTURES / "normalize3d.m")
    from pipeforge.gui.views.visualizer_view import VisualizerView

    viz = window.views["visualizer"]
    assert isinstance(viz, VisualizerView)
    audit = window.workspace.audit
    assert audit is not None
    nodes = [s.root for s in audit.dag.statements]
    status = {nodes[0]: "ok", nodes[1]: "bad"}
    dimmed = frozenset(nodes[2:])
    viz.timeline.set_bisection(status, dimmed)
    viz.timeline.repaint()  # paints green/red/dimmed without error
    assert viz.timeline._status[nodes[1]] == "bad"


@pytest.mark.req("UI-6")
def test_findings_table_sorts_filters_and_clicks_through(window: MainWindow, qtbot: QtBot) -> None:
    window.open_path(FIXTURES / "example.m")
    from pipeforge.gui.views.audit_view import AuditView

    view = window.views["audit"]
    assert isinstance(view, AuditView)
    table = view.findings._table
    total = table.rowCount()
    assert total >= 7
    # filter by tag
    view.findings._filter.setCurrentText("CDIV")
    assert table.rowCount() == 2
    view.findings._filter.setCurrentText("All tags")
    assert table.rowCount() == total
    # sort by line number column
    table.sortItems(1)
    nums = [int(table.item(r, 1).text()) for r in range(total)]
    assert nums == sorted(nums)
    # click-through to the DAG node (shared IDs)
    view.findings._filter.setCurrentText("RECIP")
    with qtbot.waitSignal(window.workspace.selectionChanged, timeout=1000):
        view.findings._activate(0, 0)
    assert window.workspace.selected_node
