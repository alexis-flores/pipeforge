"""Verilator-gated end-to-end checks for the streaming cycle:

SD-1 a generated FIR (delay taps) is bit-exact vs the stateful golden model;
FN-1 a script whose pipeline lives in local functions survives the whole
generate→simulate→match loop.

Skipped (not failed) without Verilator, per §8.2.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.codegen.emitter import generate_sv
from pipeforge.core.cosim.runner import run_cosim
from pipeforge.core.costmodel.model import CostModel

MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)

requires_verilator = pytest.mark.skipif(
    shutil.which("verilator") is None,
    reason="Verilator absent — skipped per §8.2",
)


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("SD-1")
def test_fir_with_delay_taps_bit_exact(tmp_path: Path) -> None:
    src = "x1 = delay(x);\nx2 = delay(x1);\ny = 0.5 .* x + 0.25 .* x1 + 0.25 .* x2;\n"
    audit = audit_source(src, "fir3.m", CM)
    dut = tmp_path / "fir3.sv"
    dut.write_text(generate_sv(audit, "fir3"), encoding="utf-8")
    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="fir3",
        work_dir=tmp_path / "work",
        include_dirs=[MATLIB_RTL],
        vector_count=96,
        backend="verilator",
    )
    assert result.passed, result.log[-2000:]


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("FN-1")
def test_local_functions_survive_the_whole_loop(tmp_path: Path) -> None:
    src = "s = smooth(a .* b);\n\nfunction y = smooth(x)\n  y = 0.5 .* x + 0.5 .* delay(x);\nend\n"
    audit = audit_source(src, "smoothed.m", CM)
    assert not audit.skipped
    dut = tmp_path / "smoothed.sv"
    dut.write_text(generate_sv(audit, "smoothed"), encoding="utf-8")
    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="smoothed",
        work_dir=tmp_path / "work",
        include_dirs=[MATLIB_RTL],
        vector_count=64,
        backend="verilator",
    )
    assert result.passed, result.log[-2000:]
