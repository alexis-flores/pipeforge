"""AR-1: ``reshape`` recognized as a first-class DAG operation."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program

CM = CostModel(16, 12)


@pytest.mark.req("AR-1")
def test_reshape_parsed_as_node() -> None:
    assigns, skipped = parse_program("y = reshape(x, 8, 3);")
    assert skipped == []
    builder, problems = build_dag(assigns, CM)
    assert problems == []
    dag = builder.dag
    reshapes = [n for n in dag.nodes.values() if n.module == "reshape"]
    assert len(reshapes) == 1
    node = reshapes[0]
    assert node.shape == (8, 3)  # target shape recorded (AR-1/AR-2)
    assert node.lat == 0  # pure relabel
    # only the operand is a data edge; the dimension arguments are not
    assert len(node.args) == 1
    operand = dag.nodes[node.args[0]]
    assert operand.module == "input"
    assert operand.label == "x"


@pytest.mark.req("AR-1")
def test_reshape_dim_mismatch_skipped_with_reason() -> None:
    # the inner reshape gives `y` a known 2x3 (=6) shape; reshaping 6 elements
    # to 5x5 (=25) cannot match and must be reported, never silently dropped.
    src = "y = reshape(x, 2, 3);\nz = reshape(y, 5, 5);"
    assigns, _ = parse_program(src)
    builder, problems = build_dag(assigns, CM)
    assert len(problems) == 1
    assert problems[0].line == 2
    assert "reshape" in problems[0].reason
    # the bad statement is skipped, the good one still built
    assert any(n.module == "reshape" and n.shape == (2, 3) for n in builder.dag.nodes.values())
    assert all(n.shape != (5, 5) for n in builder.dag.nodes.values())
