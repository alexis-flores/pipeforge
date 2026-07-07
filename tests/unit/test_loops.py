"""LP-1/LP-2/LN-1: constant-loop unrolling, reduction balancing, element lanes."""

from __future__ import annotations

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.parser import parse_program

CM = CostModel(16, 12)


def tags(audit) -> set[str]:
    return {f.tag for f in audit.findings}


# -- unrolling (LP-1) --------------------------------------------------------------


def test_constant_loop_unrolls_with_finding() -> None:
    a = audit_source("x = a;\nfor k = 1:3\n  x = 0.5 .* (x + a ./ x);\nend\n", "t.m", CM)
    assert not a.skipped
    assert "UNROLL" in tags(a)
    assert "FEEDBACK" not in tags(a)  # a chain in space, not a recurrence
    # 3 iterations x (div 28 -> add 1 -> mul 4) = 99 cycles of chained refinement
    assert a.total_latency == 3 * (CM.div_lat + CM.add_lat + CM.mul_lat)


def test_step_and_negative_ranges() -> None:
    assigns, _ = parse_program("s = a;\nfor k = 1:2:7\n  s = s + k;\nend\n")
    # k in 1,3,5,7 -> 4 iterations; constants substituted
    assert len(assigns) == 5
    assigns, _ = parse_program("s = a;\nfor k = 3:-1:1\n  s = s + k;\nend\n")
    assert len(assigns) == 4


def test_nested_loops_multiply() -> None:
    src = "s = a;\nfor i = 1:2\n  for j = 1:3\n    s = s + i .* j;\n  end\nend\n"
    assigns, skipped = parse_program(src)
    assert not skipped
    assert len(assigns) == 7  # init + 2*3


def test_inner_shadowing_same_var() -> None:
    src = "s = a;\nfor k = 1:2\n  for k = 1:2\n    s = s + k;\n  end\nend\n"
    assigns, skipped = parse_program(src)
    assert not skipped
    assert len(assigns) == 5  # inner loop's k is its own


def test_nonconstant_bound_keeps_feedback() -> None:
    a = audit_source("for k = 1:n\n  acc = acc + x;\nend\n", "t.m", CM)
    assert "FEEDBACK" in tags(a)
    assert "UNROLL" not in tags(a)


def test_unroll_budget_reports_and_falls_back() -> None:
    a = audit_source("for k = 1:5000\n  acc = acc + x;\nend\n", "t.m", CM)
    assert any("unroll budget" in s.reason for s in a.skipped)
    assert "FEEDBACK" in tags(a)  # legacy recurrence interpretation kept


def test_loop_var_in_field_position_untouched() -> None:
    # cfg.k is a struct field named k, not the loop variable
    src = "s = a;\nfor k = 1:2\n  s = s + cfg.k;\nend\n"
    a = audit_source(src, "t.m", CM)
    assert not a.skipped
    assert "cfg.k" in {n.label for n in a.dag.inputs()}


# -- element lanes (LN-1) -------------------------------------------------------------


def test_map_loop_becomes_parallel_lanes() -> None:
    a = audit_source("for k = 1:3\n  y(k) = x(k) .* g(k);\nend\n", "t.m", CM)
    assert not a.skipped
    assert {n.label for n in a.dag.inputs()} == {"x(1)", "x(2)", "x(3)", "g(1)", "g(2)", "g(3)"}
    assert a.census.get("elem_smul") == 3  # three parallel lane multipliers
    assert a.total_latency == CM.mul_lat  # parallel, not chained
    outs = {n.signal for n in a.dag.outputs()}
    assert outs == {"y_1", "y_2", "y_3"}  # RTL-safe lane signals


def test_lane_write_then_lane_read() -> None:
    a = audit_source("y(1) = a + b;\nz = y(1) .* c;\n", "t.m", CM)
    assert not a.skipped
    # the read resolves the lane definition, not a phantom whole-vector input
    assert "y" not in {n.label for n in a.dag.inputs()}
    assert a.census == {"elem_smul": 1, "matadd": 1}


def test_snapshot_lane_resolution() -> None:
    from pipeforge.core.frontend.varinfo import VarInfo, WorkspaceSnapshot

    snap = WorkspaceSnapshot()
    snap.variables["x"] = VarInfo(
        name="x", class_name="double", size=(2, 2), values=(1.0, 2.0, 3.0, 4.0)
    )
    lane = snap.get("x(3)")
    assert lane is not None and lane.values == (3.0,)  # linear, column-major
    lane_rc = snap.get("x(2, 2)")
    assert lane_rc is not None and lane_rc.values == (4.0,)
    assert snap.get("x(9)") is None  # out of range: no fake data


# -- balancing (LP-2) -----------------------------------------------------------------


def test_accumulator_loop_balances_bit_exact() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "acc = b;\nfor k = 1:8\n  acc = acc + x(k) .* g(k);\nend\ny = acc;\n"
    result = optimize_source(src, CM, vectors=24)
    assert any(r.tag == "BALANCE" for r in result.rewrites)
    assert result.latency_after < result.latency_before
    # wrap addition is associative: the tree is bit-exact vs the chain
    assert all(a.max_delta == 0.0 for a in result.accuracy)
    assert "pf_bal" in result.source
    reaudit = audit_source(result.source, "opt.m", CM)
    assert not reaudit.skipped


def test_single_statement_chain_balances() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "y = a + b + c + d + e + f + g + h;\n"
    result = optimize_source(src, CM, vectors=8)
    assert any(r.tag == "BALANCE" for r in result.rewrites)
    assert result.latency_after < result.latency_before
    assert all(a.max_delta == 0.0 for a in result.accuracy)


def test_unrolled_nonaccumulator_loop_source_stays_frozen() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    # each iteration divides by a *different* value: no rewrite is valid, and
    # the shared source span must never be edited per-iteration
    src = "x = a;\nfor k = 1:3\n  x = 0.5 .* (x + a ./ x);\nend\n"
    result = optimize_source(src, CM, vectors=8)
    assert result.source == src  # untouched: unrolled spans are frozen


def test_reassignment_blocks_false_recip_and_cse() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    # 'n' is redefined between the divisions: sharing 1/n would be WRONG
    src = "u = x ./ n;\nn = n + 1;\nv = y ./ n;\n"
    result = optimize_source(src, CM, vectors=8)
    assert not any(r.tag == "RECIP" for r in result.rewrites)


def test_findings_no_false_cse_across_unrolled_defs() -> None:
    a = audit_source("x = a;\nfor k = 1:3\n  x = 0.5 .* (x + a ./ x);\nend\n", "t.m", CM)
    assert "CSE" not in tags(a)  # each iteration's (a ./ x) reads a different x
    assert "RECIP" not in tags(a)
