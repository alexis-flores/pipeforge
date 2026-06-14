"""VZ-4: orthogonal edge routing with selection-driven emphasis."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.widgets.timeline import TimelineWidget

CM = CostModel(16, 12)
SRC = "prod = a .* b;\ny = prod + c;"


def _widget(qtbot: QtBot) -> tuple[TimelineWidget, object]:
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source(SRC, "s.m", CM)
    w.set_layout(layout_for_audit(audit))
    return w, audit


@pytest.mark.req("VZ-4")
def test_edges_routed_and_faded(qtbot: QtBot) -> None:
    w, _ = _widget(qtbot)
    a, b = w._layout.edges[0]  # type: ignore[union-attr]
    pts = w.route_edge(a, b)
    assert len(pts) == 4  # orthogonal: two box-avoiding bends
    assert pts[1][0] == pts[2][0]  # the vertical segment is axis-aligned
    # nothing selected -> no edge is emphasized
    assert w.active_edges() == []


@pytest.mark.req("VZ-4")
def test_selected_node_edges_brighten(qtbot: QtBot) -> None:
    w, audit = _widget(qtbot)
    prod = audit.dag.statements[0].root
    w.set_selected(prod)
    active = w.active_edges()
    assert active  # the selected node's fan-in/out are emphasized
    assert all(prod in (a, b) for a, b in active)
    # an edge not touching the selection is not emphasized
    assert all(not w.edge_active(a, b) for a, b in w._layout.edges if prod not in (a, b))  # type: ignore[union-attr]
