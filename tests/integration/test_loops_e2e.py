"""Verilator-gated end-to-end for loop support (LP-1/LP-2/LN-1):

an unrolled Newton refinement, a lane-parallel map loop, and a BALANCE-
optimized dot-product accumulator all generate RTL that matches the golden
model bit-for-bit. Skipped (not failed) without Verilator, per §8.2.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.codegen.emitter import generate_sv
from pipeforge.core.cosim.runner import run_cosim
from pipeforge.core.cosim.stimulus import generate_ranged_stimulus
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.fxp.fx import FxFormat

MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)
FMT = FxFormat(16, 12)

requires_verilator = pytest.mark.skipif(
    shutil.which("verilator") is None,
    reason="Verilator absent — skipped per §8.2",
)


def _cosim(src: str, module: str, tmp_path: Path, vectors=None, count: int = 48):
    audit = audit_source(src, f"{module}.m", CM)
    assert not audit.skipped
    dut = tmp_path / f"{module}.sv"
    dut.write_text(generate_sv(audit, module), encoding="utf-8")
    return run_cosim(
        audit,
        dut_sv=dut,
        dut_module=module,
        work_dir=tmp_path / "work",
        include_dirs=[MATLIB_RTL],
        vectors=vectors,
        vector_count=count,
        backend="verilator",
    )


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("LP-1")
def test_unrolled_newton_bit_exact(tmp_path: Path) -> None:
    src = "x = a .* 0.5 + 0.5;\nfor k = 1:3\n  x = 0.5 .* (x + a ./ x);\nend\ny = x;\n"
    vectors = generate_ranged_stimulus(["a"], FMT, {"a": (0.25, 1.0)}, count=48)
    result = _cosim(src, "newton3", tmp_path, vectors=vectors)
    assert result.passed, result.log[-2000:]


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("LN-1")
def test_map_loop_lanes_bit_exact(tmp_path: Path) -> None:
    src = "for k = 1:3\n  y(k) = x(k) .* g(k);\nend\n"
    result = _cosim(src, "lanes3", tmp_path, count=32)
    assert result.passed, result.log[-2000:]
    assert {o.name for o in result.outputs} == {"y_1", "y_2", "y_3"}


@pytest.mark.tool("verilator")
@requires_verilator
@pytest.mark.req("LP-2")
def test_balanced_dot_product_bit_exact_vs_chain(tmp_path: Path) -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "acc = b;\nfor k = 1:8\n  acc = acc + x(k) .* g(k);\nend\ny = acc;\n"
    opt = optimize_source(src, CM, vectors=8)
    assert any(r.tag == "BALANCE" for r in opt.rewrites)
    result = _cosim(opt.source, "dot8", tmp_path, count=48)
    assert result.passed, result.log[-2000:]
    audit = audit_source(opt.source, "dot8.m", CM)
    assert audit.total_latency == opt.latency_after  # the tree's shallower depth
