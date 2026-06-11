"""Struct-field grammar tests (MATLAB bridge M2 — documented grammar extension)."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.codegen.emitter import generate_sv
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.ast import Bin, Field, Index, canon, expr_vars
from pipeforge.core.frontend.dag import build_dag, port_name
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.fxp.evaluator import evaluate_fixed
from pipeforge.core.fxp.fx import FxFormat, to_float

CM = CostModel(16, 12)


def parse_one(src: str):
    assigns, skipped = parse_program(src)
    assert not skipped, skipped
    return assigns[0]


class TestGrammar:
    def test_simple_field(self) -> None:
        a = parse_one("y = cfg.gain;")
        assert isinstance(a.rhs, Field)
        assert a.rhs.base == "cfg"
        assert a.rhs.path == ("gain",)
        assert canon(a.rhs) == "cfg.gain"

    def test_nested_chain(self) -> None:
        a = parse_one("k = cfg.gains.kp;")
        rhs = a.rhs
        assert isinstance(rhs, Field)
        assert rhs.dotted == "cfg.gains.kp"

    def test_field_in_expression(self) -> None:
        a = parse_one("y = cfg.gain * x + offset;")
        assert isinstance(a.rhs, Bin)
        assert canon(a.rhs) == "((cfg.gain * x) + offset)"

    def test_field_span_covers_source(self) -> None:
        src = "y = cfg.gain + 1;"
        a = parse_one(src)
        rhs = a.rhs
        assert isinstance(rhs, Bin)
        field = rhs.left
        assert isinstance(field, Field)
        assert src[field.span.start : field.span.end] == "cfg.gain"

    def test_indexed_field_is_opaque_index(self) -> None:
        a = parse_one("y = cfg.taps(3);")
        assert isinstance(a.rhs, Index)
        assert a.rhs.name == "cfg.taps"

    def test_expr_vars_returns_root(self) -> None:
        a = parse_one("y = cfg.gains.kp * x;")
        assert expr_vars(a.rhs) == {"cfg", "x"}

    def test_dotted_assignment_target(self) -> None:
        assigns, skipped = parse_program("cfg.gain = 2;")
        assert not skipped
        assert assigns[0].target == "cfg"
        assert assigns[0].indexed

    def test_dotted_number_still_a_number(self) -> None:
        a = parse_one("y = 0.5;")
        assert canon(a.rhs) == "0.5"

    def test_dotted_ops_unaffected(self) -> None:
        a = parse_one("y = a .* b ./ c;")
        assert canon(a.rhs) == "((a .* b) ./ c)"


class TestDagAndDownstream:
    def test_field_is_input_leaf(self) -> None:
        assigns, _ = parse_program("y = cfg.gain * x;")
        builder, problems = build_dag(assigns, CM)
        assert not problems
        labels = {n.label for n in builder.dag.inputs()}
        assert labels == {"cfg.gain", "x"}

    def test_same_field_reused(self) -> None:
        assigns, _ = parse_program("p = cfg.k * a;\nq = cfg.k * b;")
        builder, _ = build_dag(assigns, CM)
        assert sum(1 for n in builder.dag.inputs() if n.label == "cfg.k") == 1

    def test_audit_runs_with_fields(self) -> None:
        audit = audit_source("y = cfg.gain * x + offset;", "t.m", CM)
        assert not audit.skipped
        assert audit.total_latency == CM.mul_lat + CM.add_lat

    def test_evaluator_takes_dotted_inputs(self) -> None:
        assigns, _ = parse_program("y = cfg.gain * x;")
        builder, _ = build_dag(assigns, CM)
        fmt = FxFormat(16, 12)
        values = evaluate_fixed(builder.dag, {"cfg.gain": 0.5, "x": 0.5}, fmt)
        root = builder.dag.statements[0].root
        assert to_float(values[root][0], fmt) == pytest.approx(0.25, abs=0.001)

    def test_codegen_sanitizes_dotted_ports(self) -> None:
        audit = audit_source("y = cfg.gain * x;", "t.m", CM)
        sv = generate_sv(audit, "gen_fields")
        assert "input [g.WIDTH-1:0] cfg_gain_0," in sv
        code_lines = [ln for ln in sv.splitlines() if not ln.lstrip().startswith("//")]
        assert all("cfg.gain" not in ln for ln in code_lines)  # dotted only in comments
        assert port_name("cfg.gain") == "cfg_gain"

    def test_field_of_defined_struct_links_to_def(self) -> None:
        # cfg redefined mid-script: later field use wires off cfg's def node
        assigns, _ = parse_program("cfg = base + tweak;\ny = cfg.gain * x;")
        builder, _ = build_dag(assigns, CM)
        dag = builder.dag
        field_nodes = [dag.nodes[n] for n in dag.order if dag.nodes[n].op == "field"]
        assert len(field_nodes) == 1
        assert field_nodes[0].args == [dag.statements[0].root]
