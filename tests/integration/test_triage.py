"""DX-1: a single triage summary combining equivalence + bisection + inputs."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.bisect.engine import BisectReport
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.diagnostics.triage import triage
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.workspace.reconcile import EXACT, MATCH, FieldVerdict, ReconcileReport

CM = CostModel(16, 12)


@pytest.mark.req("DX-1")
def test_single_summary_combines_equivalence_bisect_inputs() -> None:
    audit = audit_source("prod = a .* b;\ny = prod + c;", "sample.m", CM)
    y_nid = audit.dag.statements[1].root

    # struct equivalence was clean; bisection localized a wrong-math adder
    equiv = ReconcileReport(EXACT, [FieldVerdict("gain", (0.5,), (0.5,), EXACT, MATCH)])
    report = BisectReport(
        diverged=True,
        node=y_nid,
        instance="i_matadd_y_5",
        classification="wrong-math",
        inputs_matched=True,
    )
    cmap = CorrespondenceMap()
    cmap.add_group(y_nid, ["i_matadd_y_5"])

    summary = triage(report, equiv, audit.dag, cmap)
    # one coherent diagnosis, not separate per-panel results
    assert summary.equivalence_clean is True
    assert summary.classification == "wrong-math"
    assert summary.inputs_matched is True
    assert "equivalence clean" in summary.message
    assert "inputs matched" in summary.message
    assert "wrong-math" in summary.message
    assert "y" in summary.localized_op  # reported against the mapped op


@pytest.mark.req("DX-1")
def test_triage_reports_equivalence_drift_and_delay_skew() -> None:
    audit = audit_source("prod = a .* b;\ny = prod + c;", "sample.m", CM)
    y_nid = audit.dag.statements[1].root
    equiv = ReconcileReport(
        EXACT, [FieldVerdict("gain", (0.5,), (0.6,), EXACT, "mismatch", delta=0.1)]
    )
    report = BisectReport(
        diverged=True, node=y_nid, classification="delay-skew", inputs_matched=False, skew_cycles=1
    )
    summary = triage(report, equiv, audit.dag)
    assert summary.equivalence_clean is False
    assert "field mismatch" in summary.message
    assert "delay-skew" in summary.message
    assert "inputs differ" in summary.message
