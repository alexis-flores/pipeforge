"""UI-10: intentional empty and loading states."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.findings import Finding
from pipeforge.core.dse.sweep import SweepPoint
from pipeforge.gui.views.dse_view import DseView
from pipeforge.gui.widgets.findings_table import FindingsTable
from pipeforge.gui.workspace import Workspace


@pytest.mark.req("UI-10")
def test_zero_findings_shows_clean_affirmation(qtbot: QtBot) -> None:
    table = FindingsTable()
    qtbot.addWidget(table)
    table.set_findings([], audited=True)
    assert not table.affirmation.isHidden()  # clean-pipeline affirmation shown
    assert table.affirmation.objectName() == "success"  # in the success token
    # findings present -> affirmation hidden
    table.set_findings([Finding("CSE", 1, 4, "m", "fix", node="n001")])
    assert table.affirmation.isHidden()


@pytest.mark.req("UI-10")
def test_dse_sweep_shows_live_pareto(qtbot: QtBot) -> None:
    view = DseView(Workspace())
    qtbot.addWidget(view)
    view.begin_live()
    assert view.table.rowCount() == 0  # clean start, not frozen
    view.add_partial_point(SweepPoint(16, 12, 30, 5, 1, 0.02, 0.01, 70.0))
    assert view.table.rowCount() == 1  # fills as results arrive
    view.add_partial_point(SweepPoint(20, 14, 40, 5, 1, 0.005, 0.002, 84.0))
    assert view.table.rowCount() == 2
    assert len(view._front) >= 1  # the Pareto front updates live
