"""GUI tests for the upgraded capability views (Linter, Codegen, Cosim, Bisection)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.bisect.engine import BisectReport, NodeVerdict
from pipeforge.core.cosim.runner import CosimResult, OutputResult
from pipeforge.core.costmodel.model import CostModel
from pipeforge.gui.views.bisection_view import BisectionView
from pipeforge.gui.views.codegen_view import CodegenView
from pipeforge.gui.views.cosim_view import CosimView
from pipeforge.gui.views.linter_view import LinterView
from pipeforge.gui.workspace import Workspace

FIX = Path(__file__).parent.parent / "fixtures"
CM = CostModel(16, 12)


@pytest.mark.req("SL-3")
def test_linter_view_shows_findings(qtbot: QtBot) -> None:
    ws = Workspace()
    view = LinterView(ws)
    qtbot.addWidget(view)
    ws.sv_path = FIX / "svlint" / "bad_missing_pipe.sv"
    view.relint()
    assert view.table.rowCount() > 0  # convention violations listed
    assert "finding" in view.summary.text()


@pytest.mark.req("CG-1")
def test_codegen_view_generates_and_lints_clean(qtbot: QtBot, tmp_path: Path) -> None:
    ws = Workspace()
    view = CodegenView(ws)
    qtbot.addWidget(view)
    m = tmp_path / "d.m"
    m.write_text("prod = a .* b;\ny = prod + c;", encoding="utf-8")
    ws.m_path = m
    ws.auditChanged.emit(audit_source(m.read_text(), "d.m", CM))
    assert "module" in view.source.toPlainText()  # generated SV shown
    assert "lints clean" in view.summary.text()
    assert view.save_btn.isEnabled()


@pytest.mark.req("CS-3")
def test_cosim_view_renders_result_and_broadcasts(qtbot: QtBot, tmp_path: Path) -> None:
    ws = Workspace()
    ws.sv_path = tmp_path / "d.sv"
    view = CosimView(ws)
    qtbot.addWidget(view)
    received: list[object] = []
    ws.cosimFinished.connect(received.append)
    result = CosimResult(
        passed=True,
        outputs=[OutputResult("y", True, 32, -1, 0, 0, 1e-4, 5e-5, 78.0)],
        harness_backend="verilator",
    )
    view._on_finished(result)
    assert "PASS" in view.results.text() and "verilator" in view.results.text()
    assert received == [result]  # broadcast to the Bisection view


@pytest.mark.req("BI-3")
def test_bisection_view_marks_divergence(qtbot: QtBot) -> None:
    ws = Workspace()
    ws.audit = audit_source("prod = a .* b;\ny = prod + c;", "d.m", CM)
    view = BisectionView(ws)
    qtbot.addWidget(view)
    prod = ws.audit.dag.statements[0].root
    y = ws.audit.dag.statements[1].root
    report = BisectReport(
        diverged=True,
        node=y,
        classification="wrong-math",
        message="stage 'y' produces wrong values",
        verdicts=[NodeVerdict(prod, "ok"), NodeVerdict(y, "bad")],
    )
    view.show_result(CosimResult(passed=False, bisect_report=report))
    assert view.timeline._status.get(y) == "bad"  # first divergent stage marked
    assert view.timeline._status.get(prod) == "ok"
    assert "wrong values" in view.summary.text()
