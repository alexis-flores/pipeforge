"""Code generation tests (CG-1, CG-2, CG-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.codegen.emitter import CodegenError, generate_sv
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.svlint.checks import lint_source

CM = CostModel(16, 12)
FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN = Path(__file__).parent.parent / "golden"

CASES = [
    ("cosim/sample.m", "gen_sample"),
    ("normalize3d.m", "gen_normalize3d"),
    ("rootsqr.m", "gen_rootsqr"),
]


def audit_of(fixture: str) -> Audit:
    src = (FIXTURES / fixture).read_text(encoding="utf-8")
    return audit_source(src, Path(fixture).name, CM)


@pytest.mark.req("CG-4")
@pytest.mark.parametrize(("fixture", "module"), CASES)
def test_golden_files(fixture: str, module: str) -> None:
    sv = generate_sv(audit_of(fixture), module)
    expected = (GOLDEN / f"{module}.sv").read_text(encoding="utf-8")
    assert sv == expected


@pytest.mark.req("CG-4")
@pytest.mark.parametrize(("fixture", "module"), CASES)
def test_deterministic(fixture: str, module: str) -> None:
    assert generate_sv(audit_of(fixture), module) == generate_sv(audit_of(fixture), module)


@pytest.mark.req("CG-2")
@pytest.mark.parametrize(("fixture", "module"), CASES)
def test_generated_code_passes_own_linter(fixture: str, module: str) -> None:
    sv = generate_sv(audit_of(fixture), module)
    result = lint_source(sv, f"{module}.sv", CM)
    assert result.findings == [], [f"{f.check}: {f.message}" for f in result.findings]


@pytest.mark.req("CG-1")
def test_structure_of_generated_module() -> None:
    sv = generate_sv(audit_of("cosim/sample.m"), "gen_sample")
    assert "fixedp g," in sv  # interface port
    assert "input [g.WIDTH-1:0] a_0," in sv  # _0 inputs
    assert "output [g.WIDTH-1:0] y_N" in sv  # _N outputs
    assert "i_elem_smul_prod_4" in sv  # conventional instance naming
    assert "i_matadd_y_5" in sv
    # matching delays computed from the cost model: c must wait MUL_LAT
    assert f".DELAY({CM.mul_lat})" in sv
    assert f"valid #(.WIDTH(1), .DELAY({CM.mul_lat + CM.add_lat}))" in sv


@pytest.mark.req("CG-1")
def test_outputs_aligned_to_final_stage() -> None:
    # p (cycle 4) must be piped to the final stage (cycle 32) alongside q
    src = "p = a .* b;\nq = c ./ d;"
    audit = audit_source(src, "t.m", CM)
    sv = generate_sv(audit, "gen_align")
    assert f"i_pipe_p_{CM.div_lat}" in sv
    result = lint_source(sv, "gen_align.sv", CM)
    assert result.findings == []


def test_constants_use_tofxd() -> None:
    sv = generate_sv(audit_of("example.m"), "gen_example")
    assert "`TOFXD(" in sv


def test_unsupported_construct_is_clear_error() -> None:
    audit = audit_source("y = n(:,1);", "t.m", CM)
    with pytest.raises(CodegenError, match="no nkMatlib mapping"):
        generate_sv(audit, "gen_bad")


def test_empty_dag_is_clear_error() -> None:
    audit = audit_source("", "t.m", CM)
    with pytest.raises(CodegenError, match="no outputs"):
        generate_sv(audit, "gen_empty")
