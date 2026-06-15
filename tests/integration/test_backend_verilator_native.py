"""TL-1: the Verilator-native harness is bit-identical to the cocotb path.

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
CM = CostModel(16, 12)
_NEEDED = ["fixedp.sv", "smul.sv", "smul_raw.sv", "norm.sv", "add.sv", "pipe.sv", "valid.sv"]


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
@pytest.mark.req("TL-1")
def test_native_backend_bit_identical_to_cocotb(tmp_path: Path) -> None:
    from pipeforge.core.cosim.runner import run_cosim

    src = (FIXTURES / "sample.m").read_text(encoding="utf-8")
    audit = audit_source(src, "sample.m", CM)
    sources = [MATLIB_RTL / n for n in _NEEDED]

    common = dict(
        dut_sv=FIXTURES / "sample.sv",
        dut_module="cosim_sample",
        extra_sources=sources,
        include_dirs=[MATLIB_RTL],
        vector_count=64,
    )
    cocotb_res = run_cosim(audit, work_dir=tmp_path / "cocotb", backend="cocotb", **common)
    native_res = run_cosim(audit, work_dir=tmp_path / "native", backend="verilator", **common)

    assert cocotb_res.harness_backend == "cocotb"
    assert native_res.harness_backend == "verilator"
    assert cocotb_res.passed and native_res.passed, native_res.log[-3000:]
    # the two backends agree bit-for-bit on every output stream
    cocotb_out = {o.name: (o.passed, o.compared) for o in cocotb_res.outputs}
    native_out = {o.name: (o.passed, o.compared) for o in native_res.outputs}
    assert cocotb_out == native_out
