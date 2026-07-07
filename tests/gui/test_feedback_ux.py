"""UX-1/UX-2: toasts answer every action; the Activity panel remembers them."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from PyQt6.QtWidgets import QApplication
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


# -- toasts (UX-1) -----------------------------------------------------------------


def test_toasts_stack_and_cap(window: MainWindow) -> None:
    for i in range(5):
        window.toast.info(f"toast {i}")
    assert len(window.toast._toasts) == 3  # capped; oldest dismissed
    assert window.toast.text() == "toast 4"
    assert window.toast.isVisible()


def test_toast_kinds_style_objectnames(window: MainWindow) -> None:
    window.toast.success("ok")
    window.toast.warning("careful")
    names = [t.objectName() for t in window.toast._toasts]
    assert names == ["toastSuccess", "toastWarning"]


def test_toast_action_runs_on_click(window: MainWindow, qtbot: QtBot) -> None:
    from PyQt6.QtCore import Qt

    from pipeforge.gui.widgets.toast import ToastAction

    hits: list[str] = []
    window.toast.error("failed", action=ToastAction("Bisection", lambda: hits.append("go")))
    qtbot.mouseClick(window.toast, Qt.MouseButton.LeftButton)
    assert hits == ["go"]
    assert not window.toast._toasts  # dismissed by the click


def test_workspace_toast_routing(window: MainWindow) -> None:
    window.workspace.toast("success", "routed through the workspace")
    assert window.toast.text() == "routed through the workspace"
    assert window.toast._toasts[-1].kind == "success"


# -- activity (UX-2) ----------------------------------------------------------------


def test_opening_files_lands_in_activity(window: MainWindow) -> None:
    window.open_path(FIXTURES / "normalize3d.m")
    entries = window.activity.entries()
    titles = [e.title for e in entries]
    assert any(t.startswith("Opened normalize3d.m") for t in titles)
    assert any(t.startswith("Audited normalize3d.m") for t in titles)
    audit_entry = next(e for e in entries if e.title.startswith("Audited"))
    assert "cycles critical path" in audit_entry.detail


def test_audit_entries_record_the_delta(window: MainWindow) -> None:
    window.open_path(FIXTURES / "normalize3d.m")
    before = window.workspace.audit.total_latency
    window.workspace.set_format(20, 16)
    entries = window.activity.entries()
    latest_audit = next(e for e in entries if e.title.startswith("Audited"))
    assert f"(was {before})" in latest_audit.detail  # the running record of change


def test_optimize_posts_toast_and_activity(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QFileDialog

    from pipeforge.gui.views.audit_view import AuditView

    window.open_path(FIXTURES / "normalize3d.m")
    out = tmp_path / "normalize3d_opt.m"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "*.m"))
    )
    view = window.views["audit"]
    assert isinstance(view, AuditView)
    view._optimize()
    assert out.is_file()
    assert "Wrote normalize3d_opt.m" in window.toast.text()
    entry = next(e for e in window.activity.entries() if e.title.startswith("Optimized"))
    assert "RECIP" in entry.detail
    assert entry.path == str(out)  # the Open button knows where it went


def test_cosim_failure_posts_error_with_bisection_action(window: MainWindow) -> None:
    from pipeforge.core.cosim.runner import CosimResult, OutputResult
    from pipeforge.gui.views.cosim_view import CosimView

    window.open_path(FIXTURES / "normalize3d.m")
    view = window.views["cosim"]
    assert isinstance(view, CosimView)
    result = CosimResult(
        passed=False,
        outputs=[
            OutputResult(
                name="y",
                passed=False,
                compared=8,
                first_failure=3,
                expected=1,
                actual=2,
                max_abs_error=0.1,
                rms_error=0.1,
                sqnr_db=1.0,
            )
        ],
    )
    from pipeforge.core.bisect.engine import BisectReport

    result.bisect_report = BisectReport(diverged=True, node="n001", message="x")
    view._notify_result(result)
    toast = window.toast._toasts[-1]
    assert toast.kind == "error"
    assert "vector #3" in toast.message
    assert toast.action is not None and toast.action.label == "Bisection"
    toast.action.run()
    assert window.current_view_name() == "bisect"
    entry = next(e for e in window.activity.entries() if "FAIL" in e.title)
    assert entry.kind == "error"


def test_activity_toggle_and_open_button(window: MainWindow, tmp_path: Path) -> None:
    assert not window.activity_dock.isVisible()
    window.toggle_activity()
    assert window.activity_dock.isVisible()
    m = tmp_path / "thing.m"
    m.write_text("y = a + b;\n", encoding="utf-8")
    window.workspace.log_activity("success", "Made thing", "detail", m)
    entry = window.activity.entries()[0]
    assert entry.path == str(m)
