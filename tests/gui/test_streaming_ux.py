"""GUI tests for the streaming/projects cycle: timeline zoom/find/badges,
sidecar restore, and the audit Optimize button plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtWidgets import QApplication, QTableWidgetItem
from pytestqt.qtbot import QtBot

from pipeforge.gui.main_window import MainWindow
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


def test_timeline_zoom_scales_geometry(window: MainWindow) -> None:
    from pipeforge.gui.views.visualizer_view import VisualizerView

    window.open_path(FIXTURES / "normalize3d.m")
    viz = window.views["visualizer"]
    assert isinstance(viz, VisualizerView)
    w0 = viz.timeline.minimumWidth()
    viz.timeline.set_zoom(2.0)
    assert viz.timeline.zoom == 2.0
    assert viz.timeline.minimumWidth() > w0
    viz.timeline.set_zoom(0.01)
    assert viz.timeline.zoom == 0.25  # clamped


def test_timeline_find_selects_and_cycles(window: MainWindow) -> None:
    from pipeforge.gui.views.visualizer_view import VisualizerView

    window.open_path(FIXTURES / "normalize3d.m")
    viz = window.views["visualizer"]
    assert isinstance(viz, VisualizerView)
    viz.find_edit.setText("ux")
    viz._find_next()
    nid = window.workspace.selected_node
    assert nid
    audit = window.workspace.audit
    assert audit is not None
    node = audit.dag.nodes[nid]
    assert "ux" in (node.signal or node.label).lower()


def test_range_flags_badge_the_timelines(window: MainWindow) -> None:
    from pipeforge.gui.views.ranges_view import RangesView

    window.open_path(FIXTURES / "normalize3d.m")
    view = window.views["ranges"]
    assert isinstance(view, RangesView)
    for r in range(view.inputs_table.rowCount()):
        view.inputs_table.setItem(r, 1, QTableWidgetItem("-1"))
        view.inputs_table.setItem(r, 2, QTableWidgetItem("1"))
    view.run_propagation()
    from pipeforge.gui.views.audit_view import AuditView

    audit_view = window.views["audit"]
    assert isinstance(audit_view, AuditView)
    # near-zero divisors exist for x,y,z in [-1,1]: hazard badges must be set
    assert audit_view.timeline._hazard


def test_sidecar_restores_ranges_and_format(window: MainWindow, tmp_path: Path) -> None:
    m = tmp_path / "design.m"
    m.write_text("y = a ./ b;\n", encoding="utf-8")
    window.workspace.sidecar_enabled = True  # tmp files: safe to persist
    window.open_path(m)
    from pipeforge.gui.views.ranges_view import RangesView

    view = window.views["ranges"]
    assert isinstance(view, RangesView)
    for r in range(view.inputs_table.rowCount()):
        view.inputs_table.setItem(r, 1, QTableWidgetItem("0.5"))
        view.inputs_table.setItem(r, 2, QTableWidgetItem("2"))
    view.run_propagation()
    window.workspace.set_format(18, 14)
    sidecar = tmp_path / "design.pipeforge.toml"
    assert sidecar.is_file()

    # a fresh workspace restores everything from the sidecar
    ws2 = Workspace()
    ws2.sidecar_enabled = True
    win2 = MainWindow(ws2, window.themes)
    win2.open_path(m)
    assert (ws2.width, ws2.scale) == (18, 14)
    assert ws2.project_ranges == {"a": (0.5, 2.0), "b": (0.5, 2.0)}
    ranges2 = win2.views["ranges"]
    assert isinstance(ranges2, RangesView)
    item = ranges2.inputs_table.item(0, 1)
    assert item is not None and item.text() == "0.5"  # prefilled from the sidecar


def test_open_never_creates_sidecar(window: MainWindow, tmp_path: Path) -> None:
    m = tmp_path / "plain.m"
    m.write_text("y = a + b;\n", encoding="utf-8")
    window.workspace.sidecar_enabled = True
    window.open_path(m)
    window.workspace.set_format(20, 16)  # update-only: no sidecar exists yet
    assert not (tmp_path / "plain.pipeforge.toml").exists()


def test_mat_open_builds_static_snapshot_no_matlab(window: MainWindow, tmp_path: Path) -> None:
    import numpy as np
    import scipy.io as sio

    mat = tmp_path / "params.mat"
    sio.savemat(str(mat), {"A": np.eye(3) * 0.5, "v": np.array([[1.0], [2.0], [3.0]])})
    window.open_path(mat)
    snap = window.workspace.snapshot
    assert snap is not None and snap.get("A") is not None  # no MATLAB involved
    assert window.matlab_chip.text().startswith(".mat ✓")
    # a .m opened afterwards audits shape-aware immediately
    m = tmp_path / "model.m"
    m.write_text("y = A * v;\n", encoding="utf-8")
    window.open_path(m)
    audit = window.workspace.audit
    assert audit is not None
    assert audit.census.get("matmul") == 1


def test_optimize_button_enabled_with_findings(window: MainWindow) -> None:
    from pipeforge.gui.views.audit_view import AuditView

    view = window.views["audit"]
    assert isinstance(view, AuditView)
    assert not view.optimize_btn.isEnabled()
    window.open_path(FIXTURES / "normalize3d.m")  # RECIP findings exist
    assert view.optimize_btn.isEnabled()
