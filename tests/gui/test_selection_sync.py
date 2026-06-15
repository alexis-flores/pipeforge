"""VZ-2a: a findings-table row produces a visible coupling cue."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.findings import Finding
from pipeforge.gui.views.audit_view import AuditView
from pipeforge.gui.workspace import Workspace


@pytest.mark.req("VZ-2a")
def test_findings_row_couples_to_timeline_and_source(qtbot: QtBot, tmp_path: Path) -> None:
    ws = Workspace()
    view = AuditView(ws)
    qtbot.addWidget(view)
    m = tmp_path / "d.m"
    m.write_text("prod = a .* b;\ny = prod + c;", encoding="utf-8")
    ws.open_file(m)
    prod = ws.audit.dag.statements[0].root

    view._on_finding(Finding("CSE", 1, 4, "msg", "fix", node=prod))
    # the timeline shows a transient coupling cue on the matching bar...
    assert view.timeline._flash_nid == prod
    # ...and the shared selection drives the source-line highlight
    assert ws.selected_node == prod
