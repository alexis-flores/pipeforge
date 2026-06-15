"""VZ-5: per-op accent bars and 8px-grid row spacing."""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.widgets.timeline import TimelineWidget

CM = CostModel(16, 12)
SRC = "p = a .* b;\nq = a / b;\nr = a + b;\ns = sqrt(a);"


def _widget(qtbot: QtBot) -> TimelineWidget:
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source(SRC, "s.m", CM)
    w.set_layout(layout_for_audit(audit))
    w._audit = audit  # type: ignore[attr-defined]
    return w


def _root(audit, target: str) -> str:
    return next(s.root for s in audit.dag.statements if s.target == target)


@pytest.mark.req("VZ-5")
def test_per_op_accent_bar(qtbot: QtBot) -> None:
    w = _widget(qtbot)
    audit = w._audit  # type: ignore[attr-defined]
    # each operator kind gets a distinct semantic accent token
    assert w.accent_token(_root(audit, "p")) == "accent"  # multiply
    assert w.accent_token(_root(audit, "q")) == "divider"  # divider, unmistakable
    assert w.accent_token(_root(audit, "r")) == "success"  # add
    assert w.accent_token(_root(audit, "s")) == "warning"  # sqrt


@pytest.mark.req("VZ-5")
def test_row_spacing_on_8px_grid(qtbot: QtBot) -> None:
    w = _widget(qtbot)
    assert w.row_pitch() % 8 == 0  # honours the 8px grid with breathing room


@pytest.mark.req("VZ-8")
def test_pipe_delay_registers_rendered_as_bars(qtbot: QtBot) -> None:
    # prod = a.*b (ready @4); y = prod + c needs c delayed 0->4, an explicit
    # PIPE delay register that must show as its own bar.
    w = TimelineWidget()
    qtbot.addWidget(w)
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    w.set_layout(layout_for_audit(audit))
    bars = w.delay_bars()
    assert bars, "expected a delay-register bar for the c operand"
    # a real gap (from_cycle < to_cycle), distinct from operator bars
    assert all(c1 > c0 for _nid, c0, c1, _row in bars)
    assert any(c0 == 0 and c1 == CM.mul_lat for _nid, c0, c1, _row in bars)
