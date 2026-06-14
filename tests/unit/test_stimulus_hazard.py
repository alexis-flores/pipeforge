"""CS-5: hazard-targeted stimulus driven by the range analysis."""

from __future__ import annotations

import pytest

from pipeforge.core.cosim.stimulus import GUARD_LSBS, generate_hazard_targeted, generate_stimulus
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.fxp.fx import FxFormat, from_float, to_signed
from pipeforge.core.ranges.interval import Interval
from pipeforge.core.ranges.propagate import propagate

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)


def _report(src: str, ranges: dict[str, Interval]):
    assigns, _ = parse_program(src)
    dag = build_dag(assigns, CM)[0].dag
    return dag, propagate(dag, ranges, CM)


@pytest.mark.req("CS-5")
def test_near_zero_divisor_targeted() -> None:
    # b spans zero -> near-zero divisor hazard on a/b
    dag, report = _report("y = a / b;", {"a": Interval(1.0, 2.0), "b": Interval(-1.0, 1.0)})
    assert report.hazard_nodes  # the analysis flagged it
    vectors = generate_hazard_targeted(dag, FMT, report)
    assert vectors
    # at least one vector drives the divisor lane into the guard band
    assert any(abs(to_signed(v["b"], FMT.width)) <= GUARD_LSBS for v in vectors)


@pytest.mark.req("CS-5")
def test_overflow_node_operands_extremized() -> None:
    # 4 * 4 = 16 overflows the ±8 range at 16/12
    dag, report = _report("y = a .* b;", {"a": Interval(-4.0, 4.0), "b": Interval(-4.0, 4.0)})
    assert report.overflow_nodes
    vectors = generate_hazard_targeted(dag, FMT, report)
    extreme = from_float(4.0, FMT)
    # the overflow vector drives both operands to their max-magnitude endpoint
    assert any(v["a"] == extreme and v["b"] == extreme for v in vectors)


@pytest.mark.req("CS-5")
def test_hazard_vectors_deterministic() -> None:
    dag, report = _report("y = a / b;", {"a": Interval(1.0, 2.0), "b": Interval(-1.0, 1.0)})
    first = generate_hazard_targeted(dag, FMT, report, seed=7)
    second = generate_hazard_targeted(dag, FMT, report, seed=7)
    assert first == second
    # merged after corners, before the random fill (CS-5 ordering)
    inputs = [n.label for n in dag.inputs()]
    merged = generate_stimulus(inputs, FMT, count=64, extra=first)
    corner_block = 10 + 3 * min(len(inputs), 4)
    assert merged[corner_block : corner_block + len(first)] == first
