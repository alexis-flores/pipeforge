"""CS-6: the co-sim self-test passes under a non-continuous valid cadence.

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
@pytest.mark.req("CS-6")
def test_selftest_passes_under_gapped_valid(tmp_path: Path) -> None:
    from pipeforge.core.cosim.runner import run_cosim

    src = (FIXTURES / "sample.m").read_text(encoding="utf-8")
    audit = audit_source(src, "sample.m", CostModel(16, 12))
    needed = ["fixedp.sv", "smul.sv", "smul_raw.sv", "norm.sv", "add.sv", "pipe.sv", "valid.sv"]
    # gapped valids (bubbles between vectors) must still match bit-for-bit, with
    # the comparison valid-gated and cycle-aligned (CS-6).
    result = run_cosim(
        audit,
        dut_sv=FIXTURES / "sample.sv",
        dut_module="cosim_sample",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / name for name in needed],
        include_dirs=[MATLIB_RTL],
        vector_count=64,
        cadence="gapped",
    )
    assert result.passed, result.log[-3000:]
    assert all(o.passed for o in result.outputs)
