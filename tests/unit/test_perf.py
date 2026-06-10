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
