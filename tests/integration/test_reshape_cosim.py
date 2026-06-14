"""AR-4: reshaped operand co-sim — the column-major contract against real RTL.

Skipped (not failed) without Verilator/cocotb, per §8.2.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"
MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"


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


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("AR-4")
def test_24x1_to_8x3_element_alignment(tmp_path: Path) -> None:
    from pipeforge.core.codegen.emitter import generate_sv
    from pipeforge.core.cosim.runner import run_cosim

    # x is a 24x1 reshaped to 8x3 then multiplied elementwise. The cosim drives
    # the elements as column-major lanes; every lane's output must match the
    # golden model bit-for-bit, so any mismatch refers to the same physical
    # (row, col) element on both sides. The DUT is generated, so its reshape
    # relabel and delay-matching are exactly the cost model's (AR-4/AR-5).
    src = (FIXTURES / "reshape.m").read_text(encoding="utf-8")
    audit = audit_source(src, "reshape.m", CostModel(16, 12))
    generated = tmp_path / "gen_reshape.sv"
    generated.write_text(generate_sv(audit, "gen_reshape"), encoding="utf-8")
    needed = [
        "fixedp.sv",
        "elem_smul.sv",
        "smul.sv",
        "smul_raw.sv",
        "norm.sv",
        "pipe.sv",
        "valid.sv",
    ]
    result = run_cosim(
        audit,
        dut_sv=generated,
        dut_module="gen_reshape",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / name for name in needed],
        include_dirs=[MATLIB_RTL],
        vector_count=24,
    )
    assert result.passed, result.log[-3000:]
    assert all(o.passed for o in result.outputs)
