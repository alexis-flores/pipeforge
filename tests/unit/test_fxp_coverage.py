"""Cross-checks of fixed vs float evaluation across every DAG operator (FX-3/FX-4)."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, Node, build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.fxp.evaluator import (
    EvalError,
    evaluate_fixed,
    evaluate_float,
)
from pipeforge.core.fxp.fx import FxFormat, to_float

FMT = FxFormat(16, 12)
CM = CostModel(16, 12)

SMALL_INPUTS: dict[str, float | list[float]] = {
    "a": 0.75,
    "b": -0.5,
    "c": 1.25,
    "u": [0.25, -0.5, 0.125],
    "v": [0.5, 0.25, -0.25],
}

# statement, output target, tolerance (LSB = 2^-12; ops compound error)
CASES = [
    ("y = a + b;", 0.001),
    ("y = a - b;", 0.001),
    ("y = -a;", 0.001),
    ("y = abs(b);", 0.001),
    ("y = max(a, b);", 0.001),
    ("y = min(a, b);", 0.001),
    ("y = a .* b;", 0.001),
    ("y = a ./ c;", 0.001),
    ("y = a ^ 2;", 0.001),
    ("y = a ^ 3;", 0.002),
    ("y = sqrt(c);", 0.001),
    ("y = u + v;", 0.001),
    ("y = u .* v;", 0.001),
    ("y = sumsqr(u);", 0.002),
    ("y = norm(u);", 0.002),
    ("y = cross(u, v);", 0.002),
    ("y = dot(u, v);", 0.002),
    ("y = a';", 0.001),
    ("y = [a, b];", 0.001),
    ("y = a \\ c;", 0.005),
]


def _dag(src: str) -> Dag:
    assigns, skipped = parse_program(src)
    assert not skipped, skipped
    builder, problems = build_dag(assigns, CM)
    assert not problems
    return builder.dag


@pytest.mark.req("FX-4")
@pytest.mark.parametrize(("src", "tol"), CASES)
def test_fixed_tracks_float_reference(src: str, tol: float) -> None:
    dag = _dag(src)
    fixed = evaluate_fixed(dag, dict(SMALL_INPUTS), FMT)
    ref = evaluate_float(dag, dict(SMALL_INPUTS), FMT)
    root = dag.statements[-1].root
    measured = [to_float(x, FMT) for x in fixed[root]]
    expected = ref[root]
    assert len(measured) == len(expected)
    for m, r in zip(measured, expected, strict=True):
        assert m == pytest.approx(r, abs=tol), src


def test_division_by_zero_paths() -> None:
    dag = _dag("y = a ./ b;")
    inputs: dict[str, float | list[float]] = {"a": 1.0, "b": 0.0}
    fixed = evaluate_fixed(dag, inputs, FMT)
    ref = evaluate_float(dag, inputs, FMT)
    root = dag.statements[0].root
    assert fixed[root]  # hardware-faithful pattern, no crash
    assert ref[root][0] > 1e300 or ref[root][0] == float("inf")


def test_unknown_module_is_eval_error() -> None:
    dag = Dag()
    dag.add(Node("n001", "input", "input", 0, 0, [], 1, "x"))
    dag.add(Node("n002", "piperam", "?", 1, 1, ["n001"], 1, "?"))
    with pytest.raises(EvalError):
        evaluate_fixed(dag, {"x": 1.0}, FMT)
    with pytest.raises(EvalError):
        evaluate_float(dag, {"x": 1.0}, FMT)


def test_non_numeric_const_is_eval_error() -> None:
    dag = Dag()
    dag.add(Node("n001", "const", "const", 0, 0, [], 1, ":"))
    with pytest.raises(EvalError):
        evaluate_fixed(dag, {}, FMT)


def test_float_eval_negative_sqrt_is_nan() -> None:
    dag = _dag("y = sqrt(b);")
    ref = evaluate_float(dag, {"b": -1.0}, FMT)
    root = dag.statements[0].root
    assert ref[root][0] != ref[root][0]  # NaN


def test_float_sinv_and_rshift_nodes() -> None:
    # elem_sinv/elem_rshift are produced by audit rewrites, not the frontend;
    # build them directly.
    dag = Dag()
    dag.add(Node("n001", "input", "input", 0, 0, [], 1, "x"))
    dag.add(Node("n002", "elem_sinv", "sinv", 28, 28, ["n001"], 1, "(1/x)"))
    dag.add(Node("n003", "const", "const", 0, 0, [], 1, "2"))
    dag.add(Node("n004", "elem_rshift", ">>", 1, 1, ["n001", "n003"], 1, "(x >> 2)"))
    fixed = evaluate_fixed(dag, {"x": 4.0}, FMT)
    assert to_float(fixed["n002"][0], FMT) == pytest.approx(0.25, abs=0.001)
    ref = evaluate_float(dag, {"x": 4.0}, FMT)
    assert ref["n002"][0] == 0.25
    assert ref["n004"][0] == 1.0
    ref0 = evaluate_float(dag, {"x": 0.0}, FMT)
    assert ref0["n002"][0] == float("inf")
