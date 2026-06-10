"""CS-4: end-to-end self-test — skipped (not failed) without Verilator (§8.2)."""

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
@pytest.mark.req("CS-4")
def test_known_good_pair_passes_cosim(tmp_path: Path) -> None:
    from pipeforge.core.cosim.runner import run_cosim

    src = (FIXTURES / "sample.m").read_text(encoding="utf-8")
    audit = audit_source(src, "sample.m", CostModel(16, 12))
    needed = ["fixedp.sv", "smul.sv", "smul_raw.sv", "norm.sv", "add.sv", "pipe.sv", "valid.sv"]
    result = run_cosim(
        audit,
        dut_sv=FIXTURES / "sample.sv",
        dut_module="cosim_sample",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / name for name in needed],
        include_dirs=[MATLIB_RTL],
        vector_count=128,
    )
    assert result.passed, result.log[-3000:]
    assert all(o.passed for o in result.outputs)
    payload = result.to_payload()
    assert payload["passed"] is True


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("CG-3")
def test_generated_rtl_passes_cosim(tmp_path: Path) -> None:
    """Full loop closure: parse -> generate -> simulate -> match (CG-3)."""
    from pipeforge.core.codegen.emitter import generate_sv
    from pipeforge.core.cosim.runner import run_cosim

    src = (FIXTURES / "sample.m").read_text(encoding="utf-8")
    audit = audit_source(src, "sample.m", CostModel(16, 12))
    generated = tmp_path / "gen_sample.sv"
    generated.write_text(generate_sv(audit, "gen_sample"), encoding="utf-8")
    needed = [
        "fixedp.sv",
        "elem_smul.sv",
        "smul.sv",
        "smul_raw.sv",
        "norm.sv",
        "matadd.sv",
        "add.sv",
        "pipe.sv",
        "valid.sv",
    ]
    result = run_cosim(
        audit,
        dut_sv=generated,
        dut_module="gen_sample",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / name for name in needed],
        include_dirs=[MATLIB_RTL],
        vector_count=128,
    )
    assert result.passed, result.log[-3000:]
