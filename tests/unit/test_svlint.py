"""SystemVerilog linter tests (SL-1…SL-4) over the fixture corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.svlint.checks import (
    ALL_CHECKS,
    LintResult,
    crossref_dag,
    lint_source,
)

CM = CostModel(16, 12)
CORPUS = Path(__file__).parent.parent / "fixtures" / "svlint"

GOOD = ["good_example.sv", "good_scalar.sv", "good_div.sv"]

#: known-bad file -> the one check it must trigger (Phase 4 gate)
BAD = {
    "bad_missing_pipe.sv": "delay-match",
    "bad_wrong_pipe.sv": "delay-match",
    "bad_stage_skew.sv": "delay-match",
    "bad_suffix.sv": "suffix",
    "bad_valid_chain.sv": "valid-chain",
    "bad_valid_chain_div.sv": "valid-chain",
    "bad_valid_unreset.sv": "reset",
    "bad_data_reset.sv": "reset",
    "bad_naming.sv": "naming",
    "bad_unknown.sv": "unknown-module",
}


def lint(name: str, prefer_pyslang: bool = True) -> LintResult:
    text = (CORPUS / name).read_text(encoding="utf-8")
    return lint_source(text, name, CM, prefer_pyslang=prefer_pyslang)


@pytest.mark.req("SL-2")
@pytest.mark.parametrize("name", GOOD)
def test_known_good_files_are_lint_clean(name: str) -> None:
    result = lint(name)
    assert result.findings == [], [f"{f.check}: {f.message}" for f in result.findings]


@pytest.mark.req("SL-3")
@pytest.mark.parametrize(("name", "expected"), sorted(BAD.items()))
def test_known_bad_files_trigger_exactly_their_finding(name: str, expected: str) -> None:
    result = lint(name)
    checks = [f.check for f in result.findings]
    assert checks == [expected], (
        f"{name}: expected exactly one '{expected}', got "
        f"{[(f.check, f.message) for f in result.findings]}"
    )


@pytest.mark.req("SL-2")
def test_delay_match_reports_both_signals_and_fix() -> None:
    result = lint("bad_missing_pipe.sv")
    f = result.findings[0]
    assert "c_0" in f.message
    assert "prod_1" in f.message
    assert "stage 0" in f.message
    assert "stage 4" in f.message
    assert "`PIPE(mul_pipe" in f.fix


@pytest.mark.req("SL-2")
def test_cycle_model_matches_cost_model() -> None:
    result = lint("good_example.sv")
    # matmul output at MATMUL_LAT, add output one later (AU-1 numbers)
    assert result.cycles["prod_1"] == CM.matmul_lat
    assert result.cycles["C_1"] == CM.matmul_lat
    assert result.cycles["result_2"] == CM.matmul_lat + CM.add_lat
    assert result.cycles["valid_N"] == result.cycles["result_N"]


@pytest.mark.req("SL-1")
def test_backend_reported_and_fallback_works() -> None:
    with_pyslang = lint("good_example.sv", prefer_pyslang=True)
    fallback = lint("good_example.sv", prefer_pyslang=False)
    assert fallback.backend == "structural"
    assert with_pyslang.backend in ("pyslang", "structural")
    assert fallback.findings == with_pyslang.findings


@pytest.mark.req("SL-1")
@pytest.mark.parametrize("name", sorted(BAD))
def test_backends_agree_on_corpus(name: str) -> None:
    a = lint(name, prefer_pyslang=True)
    b = lint(name, prefer_pyslang=False)
    assert [f.check for f in a.findings] == [f.check for f in b.findings]


@pytest.mark.req("SL-1")
def test_pyslang_absence_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    # a None entry makes importlib raise ImportError, simulating absence
    monkeypatch.setitem(sys.modules, "pyslang", None)  # type: ignore[arg-type]
    result = lint("good_example.sv", prefer_pyslang=True)
    assert result.backend == "structural"
    assert result.findings == []


@pytest.mark.req("SL-3")
def test_each_check_is_suppressible() -> None:
    for name, check in sorted(BAD.items()):
        text = (CORPUS / name).read_text(encoding="utf-8")
        result = lint_source(text, name, CM, disabled=frozenset({check}))
        assert not result.by_check(check), f"{name}: '{check}' not suppressed"
    assert set(BAD.values()) <= set(ALL_CHECKS)


@pytest.mark.req("SL-4")
def test_findings_crossref_dag_nodes() -> None:
    # matching .m: y = a .* b + c (the bad_missing_pipe data path)
    assigns, _ = parse_program("prod = a .* b;\ny = prod + c;")
    builder, _ = build_dag(assigns, CM)
    result = lint("bad_missing_pipe.sv")
    refs = crossref_dag(result, builder.dag)
    assert refs, "expected the delay-match finding to anchor to a DAG node"
    nid = next(iter(refs.values()))
    # the finding is on instance i_add_y_2, whose signal is 'y'
    assert builder.dag.nodes[nid].signal == "y"


def test_lint_handles_garbage_gracefully() -> None:
    result = lint_source("not verilog at all {{{", "junk.sv", CM)
    assert result.module == ""
    result2 = lint_source("", "empty.sv", CM)
    assert result2.findings == []
