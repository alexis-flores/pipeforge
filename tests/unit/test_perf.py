"""Performance tests (NF-1)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.audit.report import render_json, render_text
from pipeforge.core.costmodel.model import CostModel

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.mark.perf
@pytest.mark.req("NF-1")
def test_audit_500_statements_under_one_second() -> None:
    src = (FIXTURES / "gen500.m").read_text(encoding="utf-8")
    start = time.perf_counter()
    audit = audit_source(src, "gen500.m", CostModel(16, 12))
    render_text(audit)
    render_json(audit)
    elapsed = time.perf_counter() - start
    assert len(audit.dag.statements) == 500
    assert elapsed < 1.0, f"audit took {elapsed:.3f}s (NF-1 budget: 1s)"


@pytest.mark.perf
@pytest.mark.req("NF-2")
def test_golden_model_throughput() -> None:
    """>= 100k operator evaluations per second (NF-2, bit-exactness preserved)."""
    from pipeforge.core.frontend.dag import build_dag
    from pipeforge.core.frontend.parser import parse_program
    from pipeforge.core.fxp.evaluator import evaluate_fixed
    from pipeforge.core.fxp.fx import FxFormat

    src = (FIXTURES / "gen500.m").read_text(encoding="utf-8")
    assigns, _ = parse_program(src)
    builder, _ = build_dag(assigns, CostModel(16, 12))
    dag = builder.dag
    fmt = FxFormat(16, 12)
    inputs = {n.label: 0.25 for n in dag.inputs()}
    op_nodes = sum(1 for nid in dag.order if dag.nodes[nid].args)
    runs = 40
    start = time.perf_counter()
    for _ in range(runs):
        evaluate_fixed(dag, dict(inputs), fmt)
    elapsed = time.perf_counter() - start
    rate = op_nodes * runs / elapsed
    assert rate >= 100_000, f"golden model at {rate:,.0f} op-evals/s (NF-2 floor: 100k)"
