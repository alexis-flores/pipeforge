"""BI-4: parse -> generate (with probes) -> simulate -> fail -> localize.

A failing co-sim automatically captures per-node Observations via the probe
backend and runs bisection, attaching the report. Skipped (not failed) without
Verilator/cocotb, per §8.2.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.costmodel.model import CostModel

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"
MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)
SRC = "prod = a .* b;\ny = prod + c;"

_NEEDED = [
    "fixedp.sv",
    "elem_smul.sv",
    "smul.sv",
    "smul_raw.sv",
    "norm.sv",
    "matadd.sv",
    "add.sv",
    "matsub.sv",
    "sub.sv",
    "pipe.sv",
    "valid.sv",
]


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


def _audit_and_probes() -> tuple[Audit, list[str]]:
    audit = audit_source(SRC, "sample.m", CM)
    probes = [audit.dag.statements[0].root, audit.dag.statements[1].root]  # prod, y
    return audit, probes


def _run(tmp_path: Path, broken_sv: str, probes: list[str], audit: Audit):
    from pipeforge.core.cosim.runner import run_cosim

    dut = tmp_path / "dut.sv"
    dut.write_text(broken_sv, encoding="utf-8")
    return run_cosim(
        audit,
        dut_sv=dut,
        dut_module="dut",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / n for n in _NEEDED],
        include_dirs=[MATLIB_RTL],
        vector_count=32,
        probes=probes,
        bisect_on_failure=True,
    )


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("BI-4")
def test_wrong_math_localized_end_to_end(tmp_path: Path) -> None:
    from pipeforge.core.codegen.emitter import generate_sv

    audit, probes = _audit_and_probes()
    good = generate_sv(audit, "dut", probes=probes)
    broken = good.replace("matadd i_matadd", "matsub i_matadd")  # y = prod - c
    assert broken != good

    result = _run(tmp_path, broken, probes, audit)
    assert not result.passed
    assert result.capture_backend == "probe"
    report = result.bisect_report
    assert report is not None and report.diverged
    assert report.node == audit.dag.statements[1].root  # localized to 'y'
    assert report.classification == "wrong-math"
    assert report.inputs_matched


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("BI-4")
def test_delay_skew_localized_end_to_end(tmp_path: Path) -> None:
    from pipeforge.core.codegen.emitter import generate_sv

    audit, probes = _audit_and_probes()
    good = generate_sv(audit, "dut", probes=probes)
    # make operand c arrive one cycle late (a missing-`PIPE-style delay bug)
    broken = good.replace(".DELAY(4))", ".DELAY(5))")
    assert broken != good

    result = _run(tmp_path, broken, probes, audit)
    assert not result.passed
    report = result.bisect_report
    assert report is not None and report.diverged
    assert report.node == audit.dag.statements[1].root  # localized to 'y'
    assert report.classification == "delay-skew"
    assert report.skew_cycles >= 1
