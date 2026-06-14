"""WS-5: extracted I/O vectors as a ground-truth co-simulation oracle.

The bit-exactness gating (float vs fixed-generated reference) is the dominant
correctness risk (§10) and is tested without external tools. The "drive the DUT"
path additionally runs under Verilator when present.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.cosim.oracle import (
    MODE_BIT_EXACT,
    MODE_WITHIN_PRECISION,
    REFERENCE_FIXED,
    REFERENCE_FLOAT,
    oracle_stimulus,
    run_vector_oracle,
)
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.fxp.evaluator import evaluate_fixed
from pipeforge.core.fxp.fx import FxFormat, to_float

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"
MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)
FMT = FxFormat(16, 12)

SRC = "prod = a .* b;\ny = prod + c;"
INPUTS = {
    "a": [0.5, 0.25, -0.75, 1.0],
    "b": [0.5, 2.0, 0.5, -1.0],
    "c": [0.0, 0.125, 0.25, 0.5],
}


def _cocotb_available() -> bool:
    try:
        import cocotb  # noqa: F401

        return True
    except ImportError:
        return False


requires_tools = pytest.mark.skipif(
    shutil.which("verilator") is None or not _cocotb_available(),
    reason="co-simulation tools absent (verilator/cocotb) — skipped per §8.2",
)


def _golden_outputs() -> dict[str, list[float]]:
    """The model's own fixed-point outputs — a fixed-generated reference."""
    audit = audit_source(SRC, "sample.m", CM)
    nid = {n.signal: n.nid for n in audit.dag.outputs() if n.signal}["y"]
    out: list[float] = []
    for i in range(len(INPUTS["a"])):
        vec = {k: v[i] for k, v in INPUTS.items()}
        values = evaluate_fixed(audit.dag, {k: [v] for k, v in vec.items()}, FMT)
        out.append(to_float(values[nid][0], FMT))
    return {"y": out}


@pytest.mark.req("WS-5")
def test_float_reference_reports_within_precision_not_bitexact() -> None:
    audit = audit_source(SRC, "sample.m", CM)
    # a float reference: bit-exactness must NOT be claimed (§10)
    references = {
        "y": [a * b + c for a, b, c in zip(INPUTS["a"], INPUTS["b"], INPUTS["c"], strict=True)]
    }
    result = run_vector_oracle(audit, INPUTS, references, FMT, reference_kind=REFERENCE_FLOAT)
    assert result.mode == MODE_WITHIN_PRECISION
    assert result.passed is None  # no bit-exact verdict against float data
    assert result.bit_exact == {}
    assert "y" in result.outputs  # FX-4 stats are reported instead


@pytest.mark.req("WS-5")
def test_fixedpoint_reference_allows_bitexact_mode() -> None:
    audit = audit_source(SRC, "sample.m", CM)
    references = _golden_outputs()  # declared fixed-point-generated
    result = run_vector_oracle(audit, INPUTS, references, FMT, reference_kind=REFERENCE_FIXED)
    assert result.mode == MODE_BIT_EXACT
    assert result.passed is True  # matches the model bit-for-bit
    assert result.bit_exact["y"] is True


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("WS-5")
def test_io_vectors_drive_cosim_stimulus(tmp_path: Path) -> None:
    import json

    from pipeforge.core.cosim.runner import run_cosim

    audit = audit_source(SRC, "sample.m", CM)
    vectors = oracle_stimulus(INPUTS, FMT)  # ground-truth inputs as stimulus
    needed = ["fixedp.sv", "smul.sv", "smul_raw.sv", "norm.sv", "add.sv", "pipe.sv", "valid.sv"]
    result = run_cosim(
        audit,
        dut_sv=FIXTURES / "sample.sv",
        dut_module="cosim_sample",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / name for name in needed],
        include_dirs=[MATLIB_RTL],
        vectors=vectors,
    )
    assert result.passed, result.log[-3000:]
    # the ground-truth vectors were the ones simulated
    written = json.loads((tmp_path / "cosim" / "stimulus.json").read_text())["vectors"]
    assert written == vectors
