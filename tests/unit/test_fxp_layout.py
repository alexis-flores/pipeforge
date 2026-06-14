"""AR-3: golden-model column-major layout and reshape as a value-preserving remap."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.fxp.evaluator import evaluate_fixed, evaluate_float
from pipeforge.core.fxp.fx import FxFormat, from_float

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)


def _reshape_nid(src: str) -> tuple[object, str]:
    assigns, _ = parse_program(src)
    builder, problems = build_dag(assigns, CM)
    assert problems == []
    dag = builder.dag
    nid = next(n.nid for n in dag.nodes.values() if n.module == "reshape")
    return dag, nid


@pytest.mark.req("AR-3")
def test_golden_column_major_layout() -> None:
    # a 6-element vector flattened column-major: column c is the c-th block of
    # `rows` elements, so element (row, col) lives at flat index col*rows + row.
    vals = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    dag, nid = _reshape_nid("y = reshape(x, 2, 3);")
    out = evaluate_fixed(dag, {"x": list(vals)}, FMT)[nid]
    assert out == [from_float(v, FMT) for v in vals]  # flat order preserved
    rows = 2
    # column-major indexing recovers the intended physical elements
    assert out[1 * rows + 0] == from_float(vals[2], FMT)  # (row 0, col 1) -> 1.5
    assert out[2 * rows + 1] == from_float(vals[5], FMT)  # (row 1, col 2) -> 3.0


@pytest.mark.req("AR-3")
def test_reshape_is_value_preserving_zero_latency() -> None:
    vals = [1.0, -2.0, 0.25, 0.75]
    dag, nid = _reshape_nid("y = reshape(x, 2, 2);")
    node = dag.nodes[nid]
    operand = dag.nodes[node.args[0]]
    assert node.lat == 0 and node.ready == operand.ready  # no latency, no stage

    fixed = evaluate_fixed(dag, {"x": list(vals)}, FMT)
    assert fixed[nid] == fixed[operand.nid]  # identical bits, no arithmetic
    flt = evaluate_float(dag, {"x": list(vals)}, FMT)
    assert flt[nid] == flt[operand.nid]
