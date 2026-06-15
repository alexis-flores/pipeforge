"""RP-4 / RP-5: measured ranges and measured-tightened recommendation."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.frontend.varinfo import VarInfo, WorkspaceSnapshot
from pipeforge.core.ranges.interval import Interval
from pipeforge.core.ranges.propagate import (
    MEASURED_NOTE,
    measured_ranges,
    recommend_format,
    three_way_ranges,
)

CM = CostModel(16, 12)


def _dag(src: str):
    assigns, _ = parse_program(src)
    return build_dag(assigns, CM)[0].dag


def _snapshot(**vals: tuple[float, ...]) -> WorkspaceSnapshot:
    s = WorkspaceSnapshot(matlab_version="test")
    for name, v in vals.items():
        s.variables[name] = VarInfo(
            name=name, class_name="double", size=(1, len(v)), values=v, vmin=min(v), vmax=max(v)
        )
    return s


@pytest.mark.req("RP-4")
def test_measured_range_from_snapshot() -> None:
    dag = _dag("y = a + b;")
    snap = _snapshot(a=(0.1, 0.2), b=(0.0, 0.1))
    measured = measured_ranges(dag, snap, CM)
    y_nid = dag.statements[0].root
    iv = measured[y_nid]
    assert iv.lo == pytest.approx(0.1) and iv.hi == pytest.approx(0.3)


@pytest.mark.req("RP-4")
def test_three_way_declared_affine_measured_labeled() -> None:
    dag = _dag("y = a .* b;")
    declared = {"a": Interval(-8.0, 8.0), "b": Interval(-8.0, 8.0)}
    snap = _snapshot(a=(0.25, 0.5), b=(0.25, 0.5))
    comp = three_way_ranges(dag, declared, CM, snap)
    y_nid = dag.statements[0].root
    row = comp[y_nid]
    # all three methods present and the measured one is honestly labeled
    assert row.declared.hi == pytest.approx(64.0)  # ±8 * ±8
    assert row.measured is not None and row.measured.hi <= 0.25
    assert row.measured_note == MEASURED_NOTE == "observed, not proven"


@pytest.mark.req("RP-5")
def test_measured_tightens_recommendation_labeled_observed() -> None:
    dag = _dag("y = a .* b;")
    declared = {"a": Interval(-8.0, 8.0), "b": Interval(-8.0, 8.0)}
    snap = _snapshot(a=(0.25, 0.5), b=(0.25, 0.5))
    static = recommend_format(dag, declared, CM, 0.01)
    measured = recommend_format(dag, declared, CM, 0.01, snapshot=snap, use_measured=True)
    assert not static.empirical
    assert measured.empirical  # flagged as empirically derived
    assert measured.left < static.left  # tighter bit allocation
    assert "observed, not proven" in measured.rationale


@pytest.mark.req("RP-5")
def test_static_only_mode_stays_conservative() -> None:
    dag = _dag("y = a .* b;")
    declared = {"a": Interval(-8.0, 8.0), "b": Interval(-8.0, 8.0)}
    snap = _snapshot(a=(0.25,), b=(0.25,))
    rec = recommend_format(dag, declared, CM, 0.01, snapshot=snap, use_measured=False)
    assert not rec.empirical  # ignores the snapshot; covers the full declared range
    assert rec.left >= 8
