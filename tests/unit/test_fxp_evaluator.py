"""DAG evaluation tests (FX-3, FX-4)."""

from __future__ import annotations

import math

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.fxp.evaluator import (
    EvalError,
    compare_outputs,
    error_stats,
    evaluate_fixed,
    evaluate_float,
)
from pipeforge.core.fxp.fx import FxFormat, from_float, to_float

FMT = FxFormat(16, 12)
CM = CostModel(16, 12)


def dag_of(src: str) -> Dag:
    assigns, skipped = parse_program(src)
    assert not skipped
    builder, problems = build_dag(assigns, CM)
    assert not problems
    return builder.dag


@pytest.mark.req("FX-3")
class TestEvaluateFixed:
    def test_every_intermediate_returned(self) -> None:
        dag = dag_of("t = a .* b;\nu = t + c;\nv = sqrt(u);")
        values = evaluate_fixed(dag, {"a": 1.5, "b": 2.0, "c": 1.0}, FMT)
        assert set(values) == set(dag.order)  # every node, keyed by ID (FX-3)
        v_root = dag.statements[-1].root
        assert to_float(values[v_root][0], FMT) == pytest.approx(2.0, abs=0.01)

    def test_missing_input_is_clear_error(self) -> None:
        dag = dag_of("y = a + b;")
        with pytest.raises(EvalError, match="input 'b'"):
            evaluate_fixed(dag, {"a": 1.0}, FMT)

    def test_raw_int_inputs_accepted(self) -> None:
        dag = dag_of("y = a + b;")
        raw = from_float(0.5, FMT)
        values = evaluate_fixed(dag, {"a": [raw], "b": [raw]}, FMT)
        y = dag.statements[0].root
        assert to_float(values[y][0], FMT) == 1.0

    def test_vector_norm_pipeline(self) -> None:
        # 0.3/0.4/0.5 triple: sumsqr stays inside the (16,12) range (max ~8)
        dag = dag_of("n = norm(v);")
        values = evaluate_fixed(dag, {"v": [0.3, 0.4]}, FMT)
        n = dag.statements[0].root
        assert to_float(values[n][0], FMT) == pytest.approx(0.5, abs=0.01)

    def test_division_pipeline_bit_exact(self) -> None:
        dag = dag_of("q = a ./ b;")
        values = evaluate_fixed(dag, {"a": -7.0, "b": 2.0}, FMT)
        q = dag.statements[0].root
        assert to_float(values[q][0], FMT) == -3.5


@pytest.mark.req("FX-4")
class TestFloatReference:
    def test_float_eval_matches_math(self) -> None:
        dag = dag_of("y = sqrt(a .* a + b .* b);")
        ref = evaluate_float(dag, {"a": 3.0, "b": 4.0}, FMT)
        y = dag.statements[0].root
        assert ref[y][0] == pytest.approx(5.0)

    def test_compare_outputs_reports_stats(self) -> None:
        dag = dag_of("y = a ./ b;")
        stats = compare_outputs(dag, {"a": 1.0, "b": 3.0}, FMT)
        s = stats["y"]
        assert s.max_abs_error < 2.0 ** (-12 + 1)  # within one LSB
        assert s.sqnr_db > 30

    def test_error_stats_metrics(self) -> None:
        s = error_stats([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert s.max_abs_error == 0.0
        assert s.sqnr_db == math.inf
        s = error_stats([1.0, -1.0], [1.5, -0.5])
        assert s.max_abs_error == 0.5
        assert s.rms_error == 0.5
        assert s.samples == 2

    def test_infinite_reference_excluded(self) -> None:
        s = error_stats([math.inf, 1.0], [100.0, 1.0])
        assert s.samples == 1


def test_feedback_dag_still_evaluates() -> None:
    # one unrolled step: acc_in is an external input
    assigns, _ = parse_program("acc = acc + x;")
    builder, _ = build_dag(assigns, CostModel(16, 12))
    values = evaluate_fixed(builder.dag, {"acc": 1.0, "x": 0.5}, FMT)
    root = builder.dag.statements[0].root
    assert to_float(values[root][0], FMT) == 1.5
