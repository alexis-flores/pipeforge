"""AR-2: every DAG node carries a shape; propagation rules are pinned."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, build_dag
from pipeforge.core.frontend.parser import parse_program

CM = CostModel(16, 12)


def _dag(src: str) -> Dag:
    assigns, _ = parse_program(src)
    builder, problems = build_dag(assigns, CM)
    assert problems == []
    return builder.dag


def _signal(dag: Dag, name: str) -> tuple[int, int]:
    return next(n.shape for n in dag.nodes.values() if n.signal == name)


@pytest.mark.req("AR-2")
def test_scalar_shape_is_1x1() -> None:
    dag = _dag("y = a + b;")
    # absent shape info, every operand is scalar (1, 1)
    assert all(n.shape == (1, 1) for n in dag.nodes.values())


@pytest.mark.req("AR-2")
def test_elementwise_preserves_shape() -> None:
    # reshape seeds a known non-scalar shape; an elementwise op preserves it
    dag = _dag("v = reshape(x, 4, 1);\ny = v + v;")
    assert _signal(dag, "v") == (4, 1)
    assert _signal(dag, "y") == (4, 1)


@pytest.mark.req("AR-2")
def test_reduction_collapses_shape() -> None:
    # norm() reduces a vector to a scalar regardless of input shape
    dag = _dag("v = reshape(x, 3, 1);\nn = norm(v);")
    assert _signal(dag, "v") == (3, 1)
    assert _signal(dag, "n") == (1, 1)
