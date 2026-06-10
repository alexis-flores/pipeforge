"""Range/precision analysis tests (RP-1, RP-2, RP-3) with hypothesis containment."""

from __future__ import annotations

import math

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.ranges.interval import Affine, Interval
from pipeforge.core.ranges.propagate import (
    RangeError,
    integer_bits_needed,
    propagate,
    recommend_format,
)

CM = CostModel(16, 12)


def dag_of(src: str) -> Dag:
    assigns, _ = parse_program(src)
    builder, _ = build_dag(assigns, CM)
    return builder.dag


# -- hypothesis: containment under all interval ops (Phase 7 gate) -----------

vals = st.floats(min_value=-50, max_value=50, allow_nan=False)
ivs = st.tuples(vals, vals).map(lambda t: Interval(min(t), max(t)))


@given(ivs, ivs, st.floats(min_value=0, max_value=1), st.floats(min_value=0, max_value=1))
@settings(max_examples=300, deadline=None)
def test_interval_ops_contain_pointwise_results(
    a: Interval, b: Interval, ta: float, tb: float
) -> None:
    x = a.lo + ta * (a.hi - a.lo)
    y = b.lo + tb * (b.hi - b.lo)
    eps = 1e-9 * (1 + abs(x) + abs(y))
    assert x + y <= a.add(b).hi + eps and x + y >= a.add(b).lo - eps
    assert a.sub(b).lo - eps <= x - y <= a.sub(b).hi + eps
    assert a.mul(b).lo - eps <= x * y <= a.mul(b).hi + eps
    assert a.neg().lo - eps <= -x <= a.neg().hi + eps
    assert a.abs_().lo - eps <= abs(x) <= a.abs_().hi + eps
    assert a.square().lo - eps <= x * x <= a.square().hi + eps
    assert a.max_(b).lo - eps <= max(x, y) <= a.max_(b).hi + eps
    assert a.min_(b).lo - eps <= min(x, y) <= a.min_(b).hi + eps
    div = a.div(b)
    if y != 0:
        q = x / y
        rel = 1e-9 * max(abs(div.lo), abs(div.hi), 1.0)  # fp rounding at extremes
        assert div.lo - eps - rel <= q or math.isinf(div.lo)
        assert q <= div.hi + eps + rel or math.isinf(div.hi)
    if x >= 0:
        assert a.sqrt().lo - eps <= math.sqrt(x) <= a.sqrt().hi + eps


@given(ivs, ivs)
@settings(max_examples=200, deadline=None)
def test_affine_interval_consistency(a: Interval, b: Interval) -> None:
    fa, fb = Affine.from_interval(a), Affine.from_interval(b)
    s = fa.add(fb).to_interval()
    assert s.lo <= a.add(b).lo + 1e-9 or s.lo <= a.add(b).hi
    assert s.hi >= a.add(b).hi - 1e-9
    # x - x is exactly 0 in affine arithmetic (the point of RP-2)
    zero = fa.sub(fa).to_interval()
    assert abs(zero.lo) < 1e-9 and abs(zero.hi) < 1e-9


@pytest.mark.req("RP-1")
class TestPropagate:
    def test_per_node_ranges_and_bits(self) -> None:
        dag = dag_of("s = a + b;\np = a .* b;")
        report = propagate(dag, {"a": Interval(-2.0, 2.0), "b": Interval(0.0, 3.0)}, CM)
        s = report.nodes[dag.statements[0].root]
        assert (s.interval.lo, s.interval.hi) == (-2.0, 5.0)
        p = report.nodes[dag.statements[1].root]
        assert (p.interval.lo, p.interval.hi) == (-6.0, 6.0)
        assert p.integer_bits == integer_bits_needed(Interval(-6.0, 6.0)) == 4

    def test_overflow_flagged_at_configured_format(self) -> None:
        dag = dag_of("y = a .* b;")
        report = propagate(dag, {"a": Interval(0.0, 7.0), "b": Interval(0.0, 7.0)}, CM)
        y = report.nodes[dag.statements[0].root]
        assert y.overflow_risk  # 49 > 7.99 max of (16,12)
        assert report.overflow_nodes

    def test_near_zero_divisor_hazard(self) -> None:
        dag = dag_of("q = a ./ b;")
        report = propagate(dag, {"a": Interval(1.0, 2.0), "b": Interval(-1.0, 1.0)}, CM)
        q = report.nodes[dag.statements[0].root]
        assert q.near_zero_divisor
        safe = propagate(dag, {"a": Interval(1.0, 2.0), "b": Interval(0.5, 1.0)}, CM)
        assert not safe.nodes[dag.statements[0].root].near_zero_divisor

    def test_missing_input_range_is_error(self) -> None:
        dag = dag_of("y = a + b;")
        with pytest.raises(RangeError, match="input 'b'"):
            propagate(dag, {"a": Interval(0.0, 1.0)}, CM)

    def test_sqrt_chain(self) -> None:
        dag = dag_of("n = sqrt(a);")
        report = propagate(dag, {"a": Interval(0.0, 4.0)}, CM)
        n = report.nodes[dag.statements[0].root]
        assert n.interval.hi == pytest.approx(2.0)


@pytest.mark.req("RP-2")
def test_affine_tighter_on_correlated_expression() -> None:
    # y = a - a: affine knows it's 0; intervals say [-2, 2]
    dag = dag_of("y = a - a;")
    ranges = {"a": Interval(-1.0, 1.0)}
    loose = propagate(dag, ranges, CM, method="interval")
    tight = propagate(dag, ranges, CM, method="affine")
    y = dag.statements[0].root
    assert loose.nodes[y].interval.hi == 2.0
    assert tight.nodes[y].interval.hi == pytest.approx(0.0, abs=1e-12)
    assert tight.nodes[y].method == "affine"  # results labeled by method


@pytest.mark.req("RP-3")
def test_recommend_format_meets_budget_empirically() -> None:
    src = "n2 = x .* x + y .* y;\nn = sqrt(n2);"
    audit = audit_source(src, "t.m", CM)
    ranges = {"x": Interval(-1.0, 1.0), "y": Interval(-1.0, 1.0)}
    rec = recommend_format(audit.dag, ranges, CM, error_budget=0.01)
    assert rec.left >= 2  # n2 can reach 2.0
    assert rec.width == rec.left + rec.scale
    assert rec.meets_budget, f"recommendation failed validation: {rec}"
    assert "LEFT" in rec.rationale
