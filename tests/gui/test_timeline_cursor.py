"""VZ-6: scrubbable cycle cursor with a column highlight across rows."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.widgets.timeline import TimelineWidget

CM = CostModel(16, 12)


@pytest.mark.req("VZ-6")
def test_cursor_scrubs_and_highlights_column(qtbot: QtBot) -> None:
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    w.set_layout(layout_for_audit(audit))

    assert w.cursor_cycle is None
    assert w.cursor_column_rect() is None  # hidden until scrubbed

    w.set_cursor_cycle(3)
    assert w.cursor_cycle == 3
    col = w.cursor_column_rect()
    assert col is not None and col.height() > 0  # spans the rows vertically

    # scrubbing across the ruler maps an x position back to a cycle column
    x5 = w._x(5)
    w.scrub_to_x(x5)
    assert w.cursor_cycle == 5
    assert w.cycle_at_x(x5) == 5
