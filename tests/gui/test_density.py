"""UI-9: comfortable/compact density toggle, persisting per session."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.views.audit_view import AuditView
from pipeforge.gui.widgets.timeline import TimelineWidget
from pipeforge.gui.workspace import Workspace

CM = CostModel(16, 12)


@pytest.mark.req("UI-9")
def test_density_toggle_changes_sizing(qtbot: QtBot) -> None:
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    w.set_layout(layout_for_audit(audit))

    w.set_density("comfortable")
    comfortable = w._box_rect(0, 1, 1).height()
    w.set_density("compact")
    compact = w._box_rect(0, 1, 1).height()
    assert compact < comfortable  # denser scanning mode
    assert w.density == "compact"


@pytest.mark.req("UI-9")
def test_density_persists_across_session(qtbot: QtBot) -> None:
    ws = Workspace()
    ws.set_density("compact")
    # a view built later in the same session adopts the persisted density
    view = AuditView(ws)
    qtbot.addWidget(view)
    assert view.timeline.density == "compact"
