"""UX affordances: welcome screen, menus, recent files, ranges view, dialogs.

These cover the discoverability layer: a new user must be able to find every
capability without reading the README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidgetItem
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import CAPABILITIES, VIEW_SHORTCUTS, MainWindow
from pipeforge.gui.theme.manager import ThemeManager
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


# -- welcome screen -----------------------------------------------------------


def test_welcome_is_the_landing_view(window: MainWindow) -> None:
    assert window.current_view_name() == "welcome"
    # demos are listed as a way in
    assert window.welcome.demo_list.count() > 0


def test_opening_a_file_leaves_welcome_for_audit(window: MainWindow) -> None:
    window.open_path(FIXTURES / "normalize3d.m")
    assert window.current_view_name() == "audit"


def test_opening_a_sv_lands_on_linter(window: MainWindow, tmp_path: Path) -> None:
    sv = tmp_path / "top.sv"
    sv.write_text("module top; endmodule\n", encoding="utf-8")
    window.open_path(sv)
    assert window.current_view_name() == "linter"


def test_recent_files_recorded_and_shown(window: MainWindow) -> None:
    from pipeforge.gui.recent import load_recent

    window.open_path(FIXTURES / "normalize3d.m")
    recent = load_recent()
    assert recent and recent[0].name == "normalize3d.m"
    window.welcome.refresh()
    assert window.welcome.recent_list.count() == 1


# -- menu bar ----------------------------------------------------------------


def test_menu_bar_has_all_top_level_menus(window: MainWindow) -> None:
    bar = window.menuBar()
    assert bar is not None
    titles = [a.text().replace("&", "") for a in bar.actions()]
    assert titles == ["File", "View", "Run", "Help"]


def test_every_capability_has_a_view_menu_action(window: MainWindow) -> None:
    for name, _label, _icon in CAPABILITIES:
        act = window.view_actions[name]
        assert act.shortcut().toString()  # discoverable shortcut on each


def test_recent_menu_fills_after_open(window: MainWindow) -> None:
    window.open_path(FIXTURES / "normalize3d.m")
    window._fill_recent_menu()
    labels = [a.text() for a in window.recent_menu.actions() if a.text()]
    assert "normalize3d.m" in labels
    assert "Clear Menu" in labels


def test_view_menu_shortcut_switches_view(window: MainWindow) -> None:
    window.view_actions["visualizer"].trigger()
    assert window.current_view_name() == "visualizer"


# -- sidebar -----------------------------------------------------------------


def test_sidebar_buttons_carry_visible_labels(window: MainWindow) -> None:
    for name, label, _icon in CAPABILITIES:
        assert label in window.nav_buttons[name].text()  # not icon-only


def test_sidebar_order_is_the_workflow(window: MainWindow) -> None:
    names = [c[0] for c in CAPABILITIES]
    # analysis first, then RTL, then verification, then exploration
    assert names.index("audit") < names.index("ranges") < names.index("codegen")
    assert names.index("codegen") < names.index("linter") < names.index("cosim")
    assert names.index("cosim") < names.index("bisect") < names.index("dse")
    assert set(VIEW_SHORTCUTS) == set(names)


# -- ranges view (RP GUI) ------------------------------------------------------


@pytest.mark.req("RP-1")
def test_ranges_view_propagates_and_flags(window: MainWindow) -> None:
    from pipeforge.gui.views.ranges_view import RangesView

    window.open_path(FIXTURES / "normalize3d.m")
    view = window.views["ranges"]
    assert isinstance(view, RangesView)
    assert view.inputs_table.rowCount() == 3  # x, y, z
    for r in range(3):
        view.inputs_table.setItem(r, 1, QTableWidgetItem("-1"))
        view.inputs_table.setItem(r, 2, QTableWidgetItem("1"))
    view.run_propagation()
    assert view.results_table.rowCount() > 0
    text = view.summary.text()
    assert "LEFT" in text
    # x/y/z ∈ [-1,1] means n can pass near zero: the hazard must be flagged
    assert "hazard" in text


@pytest.mark.req("RP-3")
def test_ranges_view_recommend_and_adopt(window: MainWindow) -> None:
    from pipeforge.gui.views.ranges_view import RangesView

    window.open_path(FIXTURES / "rootsqr.m")
    view = window.views["ranges"]
    assert isinstance(view, RangesView)
    for r in range(view.inputs_table.rowCount()):
        view.inputs_table.setItem(r, 1, QTableWidgetItem("0.5"))
        view.inputs_table.setItem(r, 2, QTableWidgetItem("1"))
    view._recommend()
    assert view._recommended is not None
    assert view.adopt_btn.isEnabled()
    view._adopt()
    assert (window.workspace.width, window.workspace.scale) == view._recommended


def test_ranges_view_incomplete_inputs_message(window: MainWindow) -> None:
    from pipeforge.gui.views.ranges_view import RangesView

    window.open_path(FIXTURES / "normalize3d.m")
    view = window.views["ranges"]
    assert isinstance(view, RangesView)
    view.run_propagation()  # nothing entered
    assert "min and a max" in view.summary.text()


# -- status bar interactivity ---------------------------------------------------


def test_format_dialog_edits_workspace_live(window: MainWindow, qtbot: QtBot) -> None:
    from pipeforge.gui.widgets.format_dialog import FormatDialog

    dialog = FormatDialog(window.workspace, window)
    qtbot.addWidget(dialog)
    dialog.width_spin.setValue(20)
    dialog.scale_spin.setValue(14)
    assert (window.workspace.width, window.workspace.scale) == (20, 14)
    assert window.format_chip.text() == "20/14"
    assert "LEFT = 6" in dialog.left_label.text()


def test_tools_dialog_lists_every_probe(window: MainWindow, qtbot: QtBot) -> None:
    from pipeforge.gui.widgets.tools_dialog import ToolsDialog

    dialog = ToolsDialog(window)
    qtbot.addWidget(dialog)
    assert dialog.table.rowCount() >= 7  # verilator, dot, yosys, sby, cocotb, pyslang, matlab
    # every row states what the tool unlocks
    for r in range(dialog.table.rowCount()):
        item = dialog.table.item(r, 1)
        assert item is not None and item.text()


# -- toast details -------------------------------------------------------------


@pytest.mark.req("NF-4")
def test_problem_toast_click_opens_console(window: MainWindow, qtbot: QtBot) -> None:
    window.workspace.problem.emit("Something went sideways.")
    assert window.toast.isVisible()
    assert "click for details" in window.toast.text()
    assert not window.console_dock.isVisible()
    qtbot.mouseClick(window.toast, Qt.MouseButton.LeftButton)
    assert window.console_dock.isVisible()
    assert "sideways" in window.console.toPlainText()


# -- findings rewrite column ---------------------------------------------------


def test_findings_table_shows_rewrite_column(window: MainWindow) -> None:
    from pipeforge.gui.views.audit_view import AuditView

    window.open_path(FIXTURES / "normalize3d.m")
    view = window.views["audit"]
    assert isinstance(view, AuditView)
    table = view.findings._table
    assert table.columnCount() == 5
    header = table.horizontalHeaderItem(4)
    assert header is not None and header.text() == "Rewrite"
    item = table.item(0, 4)
    assert item is not None and item.text()  # the fix is visible, not tooltip-only


# -- cosim readiness -----------------------------------------------------------


def test_cosim_requirements_gate_the_run_button(window: MainWindow, tmp_path: Path) -> None:
    from pipeforge.gui.views.cosim_view import CosimView

    view = window.views["cosim"]
    assert isinstance(view, CosimView)
    assert not view.run_btn.isEnabled()
    assert "✗" in view.reqs.text()
    window.open_path(FIXTURES / "normalize3d.m")
    sv = tmp_path / "normalize3d.sv"
    sv.write_text("module normalize3d; endmodule\n", encoding="utf-8")
    window.open_path(sv)
    assert view.run_btn.isEnabled()
    assert "✗" not in view.reqs.text()
    assert view.dut_edit.text().endswith("normalize3d.sv")


def test_cosim_hints_follow_selection(window: MainWindow) -> None:
    from pipeforge.gui.views.cosim_view import CosimView

    view = window.views["cosim"]
    assert isinstance(view, CosimView)
    view.backend_combo.setCurrentText("verilator")
    assert "cocotb" in view.backend_hint.text()  # says it does NOT need it
    view.cadence_combo.setCurrentText("gapped")
    assert "idle cycles" in view.cadence_hint.text()


# -- demos navigation ------------------------------------------------------------


def test_demo_open_navigates_to_its_view(window: MainWindow, qtbot: QtBot) -> None:
    from pipeforge.gui.widgets.demos_dialog import DemosDialog

    landed: list[str] = []
    dialog = DemosDialog(window.open_path, window, navigate=landed.append)
    qtbot.addWidget(dialog)
    dialog.listing.setCurrentRow(0)  # 01_findings → audit
    dialog._open_selected()
    assert landed == ["audit"]


def test_welcome_demo_click_opens_and_navigates(window: MainWindow) -> None:
    item = window.welcome.demo_list.item(0)
    assert item is not None
    window.welcome._open_demo_item(item)
    assert window.workspace.m_path is not None
    assert window.current_view_name() == "audit"


# -- drag and drop ----------------------------------------------------------------


def test_drop_opens_supported_files(window: MainWindow) -> None:
    from PyQt6.QtCore import QMimeData, QPoint, QPointF, QUrl
    from PyQt6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(FIXTURES / "normalize3d.m"))])
    event = QDropEvent(
        QPointF(QPoint(10, 10)),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)
    assert window.workspace.m_path is not None
    assert window.workspace.m_path.name == "normalize3d.m"
