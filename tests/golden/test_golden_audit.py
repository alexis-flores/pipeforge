"""Golden-file tests (AU-5, Appendix C).

The references in this directory were captured from the original seed
auditor (`seed/matlib_audit.py`) BEFORE the Phase 1 refactor. The package
engine must reproduce them byte-for-byte modulo the version header.
Diffs are reviewed, never blindly regenerated (§8.1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.audit.report import render_json, render_text
from pipeforge.core.costmodel.model import CostModel

GOLDEN = Path(__file__).parent
FIXTURES = GOLDEN.parent / "fixtures"

CASES = ["example", "normalize3d", "rootsqr", "feedback", "gen500"]


def _audit(name: str):
    src = (FIXTURES / f"{name}.m").read_text(encoding="utf-8")
    # unroll=False: the goldens pin the SEED auditor's interpretation, where a
    # constant-bound loop is one analyzed iteration + a FEEDBACK finding. The
    # LP-1 default (unrolling) is a deliberate semantic upgrade tested in
    # tests/unit; parity with the frozen seed reference stays checkable here.
    return audit_source(src, f"{name}.m", CostModel(16, 12), unroll=False)


@pytest.mark.req("AU-5")
@pytest.mark.parametrize("name", CASES)
def test_text_report_matches_seed_golden(name: str) -> None:
    expected = (GOLDEN / f"{name}_audit.txt").read_text(encoding="utf-8")
    actual = render_text(_audit(name))
    # byte-for-byte modulo the version header (line 1)
    assert actual.splitlines()[1:] == expected.splitlines()[1:]


@pytest.mark.req("AU-5")
@pytest.mark.parametrize("name", CASES)
def test_json_report_matches_seed_golden(name: str) -> None:
    expected = json.loads((GOLDEN / f"{name}_audit.json").read_text(encoding="utf-8"))
    actual = json.loads(render_json(_audit(name)))
    for doc in (expected, actual):
        doc.pop("version", None)
        doc.pop("tool", None)
    assert actual == expected
