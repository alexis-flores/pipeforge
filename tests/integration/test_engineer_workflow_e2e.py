"""End-to-end (Verilator-gated) checks for the engineer-workflow features:

MX-1 mixed-precision RTL is bit-exact vs the golden model under in-range
stimulus; VX-1 failure artifacts persist and replay reproduces; WV-1 the
GTKWave save file points inside the DUT at the divergent stage; AX-1 the
AXI-Stream wrapper elaborates cleanly.

Skipped (not failed) without Verilator, per §8.2.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel

MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)

requires_verilator = pytest.mark.skipif(
    shutil.which("verilator") is None,
    reason="Verilator absent — skipped per §8.2",
)

_SRC = "prod = a .* b;\ny = prod + c;"
_RANGES = {"a": (-1.0, 1.0), "b": (-1.0, 1.0), "c": (-0.5, 0.5)}


def _ranged_vectors(audit, count: int = 48):
    from pipeforge.core.cosim.stimulus import generate_ranged_stimulus
    from pipeforge.core.fxp.fx import FxFormat

    inputs = [n.label for n in audit.dag.inputs()]
    return generate_ranged_stimulus(inputs, FxFormat(CM.width, CM.scale), _RANGES, count=count)


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("MX-1")
def test_mixed_precision_module_bit_exact(tmp_path: Path) -> None:
    from pipeforge.core.codegen.emitter import generate_sv
    from pipeforge.core.codegen.mixed import plan_widths
    from pipeforge.core.cosim.runner import run_cosim
    from pipeforge.core.ranges.interval import Interval
    from pipeforge.core.ranges.propagate import propagate

    audit = audit_source(_SRC, "dut.m", CM)
    report = propagate(audit.dag, {k: Interval(lo, hi) for k, (lo, hi) in _RANGES.items()}, CM)
    plan = plan_widths(audit, report)
    assert plan.narrowed > 0  # the test must actually exercise narrow paths
    sv = generate_sv(audit, "dut_mixed", plan=plan)
    dut = tmp_path / "dut_mixed.sv"
    dut.write_text(sv, encoding="utf-8")
    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="dut_mixed",
        work_dir=tmp_path / "work",
        include_dirs=[MATLIB_RTL],
        vectors=_ranged_vectors(audit),
        backend="verilator",
    )
    assert result.passed, result.log[-2000:]
    assert all(o.passed for o in result.outputs)


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("VX-1")
def test_failure_artifacts_and_replay(tmp_path: Path) -> None:
    from pipeforge.core.codegen.emitter import generate_sv
    from pipeforge.core.cosim.runner import run_cosim
    from pipeforge.core.cosim.vectors import load_vectors

    audit = audit_source(_SRC, "dut.m", CM)
    broken = generate_sv(audit, "dut").replace(".DELAY(4)", ".DELAY(3)")
    assert ".DELAY(3)" in broken  # the c operand arrives one cycle early
    dut = tmp_path / "dut_broken.sv"
    dut.write_text(broken, encoding="utf-8")
    work = tmp_path / "work"
    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="dut",
        work_dir=work,
        include_dirs=[MATLIB_RTL],
        vector_count=48,
        backend="verilator",
        bisect_on_failure=True,
    )
    assert not result.passed
    # VX-1: the exact stimulus persisted, replayable
    assert result.failure_file and Path(result.failure_file).is_file()
    vectors = load_vectors(Path(result.failure_file))
    replay = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="dut",
        work_dir=tmp_path / "work_replay",
        include_dirs=[MATLIB_RTL],
        vectors=vectors,
        backend="verilator",
    )
    assert not replay.passed  # same vectors, same verdict
    assert [o.first_failure for o in replay.outputs] == [o.first_failure for o in result.outputs]
    # WV-1: the save file exists and points inside the DUT at the divergence
    assert result.gtkw_file and Path(result.gtkw_file).is_file()
    gtkw = Path(result.gtkw_file).read_text(encoding="utf-8")
    assert "[dumpfile]" in gtkw
    assert "-divergence @ stage" in gtkw
    assert ".i_dut." in gtkw  # hierarchical paths resolved from the VCD
    assert any(line.startswith("*") for line in gtkw.splitlines())  # cursor set


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("AX-1")
def test_axis_wrapper_elaborates(tmp_path: Path) -> None:
    from pipeforge.core.codegen.axis import generate_axis_wrapper
    from pipeforge.core.codegen.emitter import generate_sv

    audit = audit_source(_SRC, "dut.m", CM)
    (tmp_path / "dut.sv").write_text(generate_sv(audit, "dut"), encoding="utf-8")
    (tmp_path / "dut_axis.sv").write_text(generate_axis_wrapper(audit, "dut"), encoding="utf-8")
    proc = subprocess.run(
        [
            "verilator",
            "--lint-only",
            "--timing",
            f"-I{MATLIB_RTL}",
            "dut_axis.sv",
            "dut.sv",
            "--top-module",
            "dut_axis",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    errors = [line for line in (proc.stdout + proc.stderr).splitlines() if "%Error" in line]
    assert proc.returncode == 0 and not errors, "\n".join(errors) or proc.stderr[-1500:]
