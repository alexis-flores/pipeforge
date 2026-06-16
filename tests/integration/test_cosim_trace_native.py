"""CS-8: native VCD-trace bisection localizes a bug with no probe ports.

The verilator-native backend dumps a VCD and reconstructs stage-aligned per-node
streams by the cost-model naming convention (``<signal>_<ready>``), so a failing
hand-written/non-probed DUT is still localized. Needs only Verilator (no cocotb).

Skipped (not failed) without Verilator, per §8.2.
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

requires_verilator = pytest.mark.skipif(
    shutil.which("verilator") is None,
    reason="Verilator absent — skipped per §8.2",
)

_NEEDED = [
    "fixedp.sv",
    "elem_smul.sv",
    "smul.sv",
    "smul_raw.sv",
    "norm.sv",
    "matadd.sv",
    "matsub.sv",
    "add.sv",
    "sub.sv",
    "pipe.sv",
    "valid.sv",
]


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("CS-8")
def test_native_trace_bisection_localizes_wrong_math(tmp_path: Path) -> None:
    from pipeforge.core.codegen.emitter import generate_sv
    from pipeforge.core.cosim.runner import run_cosim

    src = "prod = a .* b;\ny = prod + c;"
    audit = audit_source(src, "dut.m", CM)
    prod_nid = audit.dag.statements[0].root
    y_nid = audit.dag.statements[1].root

    # inject a wrong-math bug at the 'y' stage: matadd -> matsub
    broken = generate_sv(audit, "dut").replace("matadd i_matadd_y_5", "matsub i_matadd_y_5")
    assert "matsub i_matadd_y_5" in broken
    dut = tmp_path / "dut_broken.sv"
    dut.write_text(broken, encoding="utf-8")

    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="dut",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / n for n in _NEEDED],
        include_dirs=[MATLIB_RTL],
        vector_count=24,
        backend="verilator",
        bisect_on_failure=True,  # no probes — trace fallback must localize it
    )

    assert result.harness_backend == "verilator"
    assert not result.passed
    # the bug was localized from the VCD trace, not probe ports
    assert result.capture_backend == "trace"
    assert result.bisect_report is not None
    report = result.bisect_report
    assert report.diverged
    assert report.node == y_nid  # first divergent stage is 'y', not 'prod'
    assert report.classification == "wrong-math"
    # prod's stream was reconstructed and matched the golden model
    assert {v.nid: v.status for v in report.verdicts}[prod_nid] == "ok"
    assert {v.nid: v.status for v in report.verdicts}[y_nid] == "bad"
