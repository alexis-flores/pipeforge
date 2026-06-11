"""MATLAB bridge GUI tests (M5): refresh flow, inspector live info, settings."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from pipeforge.core.frontend.varinfo import FiFormat, VarInfo, WorkspaceSnapshot
from pipeforge.gui.main_window import MainWindow
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace

FIXTURES = Path(__file__).parent.parent / "fixtures"


def demo_snapshot() -> WorkspaceSnapshot:
    s = WorkspaceSnapshot(matlab_version="test", timestamp="2026-06-11 00:00:00")
    s.variables["cfg.gain"] = VarInfo(
        name="cfg.gain", class_name="double", size=(1, 1), values=(0.5,), vmin=0.5, vmax=0.5
    )
    s.variables["x"] = VarInfo(
        name="x",
        class_name="double",
        size=(1, 3),
        values=(0.25, -0.5, 0.125),
        vmin=-0.5,
        vmax=0.25,
    )
    s.variables["offset"] = VarInfo(
        name="offset",
        class_name="embedded.fi",
        size=(1, 1),
        fi=FiFormat(18, 14),
        values=(0.0625,),
        vmin=0.0625,
        vmax=0.0625,
    )
    return s


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    win = MainWindow(Workspace(), ThemeManager(app))
    qtbot.addWidget(win)
    win.show()
    script = tmp_path / "demo_gui.m"
    script.write_text("y = cfg.gain * x + offset;\n", encoding="utf-8")
    win.open_path(script)
    return win


def test_refresh_reaudits_with_snapshot(
    window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeforge.services import matlab_bridge

    monkeypatch.setattr(matlab_bridge, "take_snapshot", lambda *a, **kw: demo_snapshot())
    with qtbot.waitSignal(window.workspace.auditChanged, timeout=4000):
        window.workspace.refresh_from_matlab()
    assert window.workspace.snapshot is not None
    audit = window.workspace.audit
    assert audit is not None
    # the fi mismatch surfaced as a FORMAT finding through the GUI path
    assert any(f.tag == "FORMAT" for f in audit.findings)
    assert "snapshot of 3 variables" in window.console.toPlainText()


def test_inspector_shows_live_matlab_info(window: MainWindow, qtbot: QtBot) -> None:
    window.workspace.snapshot = demo_snapshot()
    window.workspace.rerun()
    audit = window.workspace.audit
    assert audit is not None
    x_node = next(n for n in audit.dag.inputs() if n.label == "x")
    window.workspace.select_node(x_node.nid)
    text = window.inspector_label.text()
    assert "MATLAB: double 1x3" in text
    assert "0.25" in text  # value preview
    offset_node = next(n for n in audit.dag.inputs() if n.label == "offset")
    window.workspace.select_node(offset_node.nid)
    assert "fi 18/14" in window.inspector_label.text()


def test_refresh_failure_is_a_toast(
    window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeforge.services import matlab_bridge

    def boom(*_a: object, **_kw: object) -> WorkspaceSnapshot:
        raise matlab_bridge.MatlabUnavailable("container down — start matlab-sandbox")

    monkeypatch.setattr(matlab_bridge, "take_snapshot", boom)
    with qtbot.waitSignal(window.workspace.problem, timeout=4000):
        window.workspace.refresh_from_matlab()
    assert "container down" in window.toast.text()


def test_opening_other_file_clears_snapshot(window: MainWindow, tmp_path: Path) -> None:
    window.workspace.snapshot = demo_snapshot()
    other = tmp_path / "other.m"
    other.write_text("z = a + b;\n", encoding="utf-8")
    window.open_path(other)
    assert window.workspace.snapshot is None


def test_settings_matlab_round_trip(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from pipeforge.gui.views.settings_view import SettingsView
    from pipeforge.services.matlab_bridge import MatlabConfig

    view = window.views["settings"]
    assert isinstance(view, SettingsView)
    view.matlab_command_edit.setText("docker exec matlab matlab")
    view.matlab_setup_edit.setText(str(tmp_path / "setup.mat"))
    view._save_matlab()
    cfg = MatlabConfig.load()
    assert cfg.command == ["docker", "exec", "matlab", "matlab"]
    assert cfg.setup == tmp_path / "setup.mat"


def test_workspace_view_lists_snapshot_variables(window: MainWindow) -> None:
    from pipeforge.gui.views.matlab_view import MatlabView

    view = window.views["golden"]
    assert isinstance(view, MatlabView)
    window.workspace.snapshot = demo_snapshot()
    window.workspace.snapshotChanged.emit(window.workspace.snapshot)
    names = {view.table.item(r, 0).text() for r in range(view.table.rowCount())}
    assert names == {"cfg.gain", "x", "offset"}
    # fi column populated for the fixed-point variable
    by_name = {
        view.table.item(r, 0).text(): view.table.item(r, 3).text()
        for r in range(view.table.rowCount())
    }
    assert by_name["offset"] == "18/14"
    assert by_name["x"] == ""
    assert "3 variables" in view.meta.text()
    # filter narrows
    view.filter_edit.setText("cfg")
    assert view.table.rowCount() == 1


def test_workspace_view_row_click_selects_dag_node(window: MainWindow, qtbot: QtBot) -> None:
    from pipeforge.gui.views.matlab_view import MatlabView

    view = window.views["golden"]
    assert isinstance(view, MatlabView)
    window.workspace.snapshot = demo_snapshot()
    window.workspace.rerun()
    window.workspace.snapshotChanged.emit(window.workspace.snapshot)
    row = next(
        r for r in range(view.table.rowCount()) if view.table.item(r, 0).text() == "cfg.gain"
    )
    with qtbot.waitSignal(window.workspace.selectionChanged, timeout=1000):
        view._on_row(row, 0)
    audit = window.workspace.audit
    assert audit is not None
    assert audit.dag.nodes[window.workspace.selected_node].label == "cfg.gain"


def test_mat_alone_refresh_no_script(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open only a .mat — refresh snapshots it with script=None."""
    from pipeforge.services import matlab_bridge

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    win = MainWindow(Workspace(), ThemeManager(app))
    qtbot.addWidget(win)
    win.show()
    params = tmp_path / "params.mat"
    params.write_bytes(b"MATLAB 5.0")
    win.open_path(params)
    assert win.workspace.mat_path == params
    assert win.workspace.m_path is None

    captured: dict[str, object] = {}

    def fake_take(script, setup=None, **_kw):  # type: ignore[no-untyped-def]
        captured["script"] = script
        captured["setup"] = setup
        return demo_snapshot()

    monkeypatch.setattr(matlab_bridge, "take_snapshot", fake_take)
    with qtbot.waitSignal(win.workspace.snapshotChanged, timeout=4000):
        win.workspace.refresh_from_matlab()
    assert captured["script"] is None
    assert captured["setup"] == params
    from pipeforge.gui.views.matlab_view import MatlabView

    view = win.views["golden"]
    assert isinstance(view, MatlabView)
    assert view.table.rowCount() == 3  # browseable with no .m open


def test_sidebar_shows_workspace_label(window: MainWindow) -> None:
    assert window.nav_buttons["golden"].accessibleName() == "Workspace"


class TestSyncIndicators:
    def test_chip_busy_then_fresh(
        self, window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pipeforge.services import matlab_bridge

        monkeypatch.setattr(matlab_bridge, "snapshot_auto", lambda *a, **kw: demo_snapshot())
        assert not window.matlab_chip.isVisible()
        with qtbot.waitSignal(window.workspace.refreshFinished, timeout=4000):
            window.workspace.refresh_from_matlab()
            assert "⟳" in window.matlab_chip.text()  # busy state immediately
            assert window.matlab_chip.objectName() == "chipBusy"
        qtbot.waitUntil(lambda: "✓" in window.matlab_chip.text(), timeout=2000)
        assert "3 vars" in window.matlab_chip.text()
        assert window.matlab_chip.objectName() == "chip"
        assert "MATLAB snapshot updated" in window.toast.text()

    def test_refresh_button_disabled_in_flight(
        self, window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time as time_mod

        from pipeforge.gui.views.matlab_view import MatlabView
        from pipeforge.services import matlab_bridge

        def slow(*_a: object, **_kw: object) -> WorkspaceSnapshot:
            time_mod.sleep(0.3)
            return demo_snapshot()

        monkeypatch.setattr(matlab_bridge, "snapshot_auto", slow)
        view = window.views["golden"]
        assert isinstance(view, MatlabView)
        with qtbot.waitSignal(window.workspace.refreshFinished, timeout=4000):
            window.workspace.refresh_from_matlab()
            assert not view.refresh_btn.isEnabled()
            assert view.refresh_btn.text() == "Refreshing…"
        qtbot.waitUntil(lambda: view.refresh_btn.isEnabled(), timeout=2000)

    def test_file_change_marks_stale_without_autosync(
        self, window: MainWindow, qtbot: QtBot, tmp_path: Path
    ) -> None:
        window.workspace.snapshot = demo_snapshot()
        window.workspace.snapshotChanged.emit(window.workspace.snapshot)
        assert window.workspace.m_path is not None
        with qtbot.waitSignal(window.workspace.snapshotStale, timeout=4000):
            window.workspace.m_path.write_text("y = cfg.gain * x + offset + 1;\n", encoding="utf-8")
        assert window.workspace.stale
        qtbot.waitUntil(lambda: "stale" in window.matlab_chip.text(), timeout=2000)
        assert window.matlab_chip.objectName() == "chipWarn"

    def test_file_change_autorefreshes_when_warm(
        self, window: MainWindow, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pipeforge.services import matlab_bridge, matlab_session

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        cfg = matlab_bridge.MatlabConfig(command=["sh"], warm=True, auto_refresh=True)
        cfg.save()
        monkeypatch.setattr(matlab_session, "server_alive", lambda: True)
        monkeypatch.setattr(matlab_bridge, "snapshot_auto", lambda *a, **kw: demo_snapshot())
        window.workspace.snapshot = demo_snapshot()
        assert window.workspace.m_path is not None
        with qtbot.waitSignal(window.workspace.refreshFinished, timeout=4000):
            window.workspace.m_path.write_text("y = cfg.gain * x + offset + 2;\n", encoding="utf-8")
        assert not window.workspace.stale  # auto-refresh replaced, not staled

    def test_settings_warm_toggles_persist_and_gate(
        self, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from pipeforge.gui.views.settings_view import SettingsView
        from pipeforge.services.matlab_bridge import MatlabConfig

        view = window.views["settings"]
        assert isinstance(view, SettingsView)
        monkeypatch.setattr(window.workspace, "start_warm_session", lambda: None)
        monkeypatch.setattr(window.workspace, "stop_warm_session", lambda: None)
        assert not view.autosync_check.isEnabled()  # gated until warm
        view.warm_check.setChecked(True)
        assert view.autosync_check.isEnabled()
        view.autosync_check.setChecked(True)
        cfg = MatlabConfig.load()
        assert cfg.warm and cfg.auto_refresh
        view.warm_check.setChecked(False)
        cfg = MatlabConfig.load()
        assert not cfg.warm and not cfg.auto_refresh  # autosync forced off too
