"""VZ-7: cursor value overlay (golden + RTL, mismatches in the error token)."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.widgets.timeline import TimelineWidget

CM = CostModel(16, 12)


def _widget(qtbot: QtBot):
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    w.set_layout(layout_for_audit(audit))
    return w, audit


@pytest.mark.req("VZ-7")
def test_cursor_shows_golden_and_rtl_values(qtbot: QtBot) -> None:
    w, audit = _widget(qtbot)
    prod = audit.dag.statements[0].root
    w.set_overlay({prod: 100}, {prod: 100})
    box = w._layout.boxes[prod]  # type: ignore[union-attr]
    w.set_cursor_cycle(box.end)  # cursor over the prod bar
    rows = w.overlay_at_cursor()
    assert any(
        nid == prod and g == 100 and r == 100 and not mismatch for nid, g, r, mismatch in rows
    )


@pytest.mark.req("VZ-7")
def test_mismatch_rendered_in_error_token(qtbot: QtBot) -> None:
    w, audit = _widget(qtbot)
    prod = audit.dag.statements[0].root
    w.set_overlay({prod: 100}, {prod: 99})  # golden != rtl
    box = w._layout.boxes[prod]  # type: ignore[union-attr]
    w.set_cursor_cycle(box.end)
    row = next(r for r in w.overlay_at_cursor() if r[0] == prod)
    assert row[3] is True  # mismatch flagged
    assert w.value_token(row[3]) == "error"
    assert w.value_token(False) == "textPrimary"
