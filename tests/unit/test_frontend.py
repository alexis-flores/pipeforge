"""Frontend tests: FE-1 (grammar), FE-2 (def-use/feedback), FE-3 (skip), FE-4 (spans)."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.ast import Bin, Call, Index, Num, Trans, Un, canon
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.lexer import tokenize
from pipeforge.core.frontend.parser import parse_program

CM = CostModel(16, 12)


def parse_one(src: str):
    assigns, skipped = parse_program(src)
    assert not skipped, f"unexpected skips: {skipped}"
    assert len(assigns) == 1
    return assigns[0]


@pytest.mark.req("FE-1")
class TestGrammar:
    def test_numeric_literals(self) -> None:
        for text, value in [
            ("3", 3.0),
            ("3.5", 3.5),
            ("0.25", 0.25),
            ("1e3", 1000.0),
            ("2.5e-2", 0.025),
        ]:
            a = parse_one(f"y = {text};")
            assert isinstance(a.rhs, Num)
            assert a.rhs.value == value

    def test_all_binary_operators(self) -> None:
        for op in ["+", "-", "*", "/", "\\", ".*", "./", ".\\"]:
            a = parse_one(f"y = a {op} b;")
            assert isinstance(a.rhs, Bin)
            assert a.rhs.op == op

    def test_power_operators(self) -> None:
        for op in ["^", ".^"]:
            a = parse_one(f"y = a {op} 2;")
            assert isinstance(a.rhs, Bin)
            assert a.rhs.op == op

    def test_unary_minus_and_transpose(self) -> None:
        a = parse_one("y = -x;")
        assert isinstance(a.rhs, Un)
        a = parse_one("y = x';")
        assert isinstance(a.rhs, Trans)
        a = parse_one("y = x.';")
        assert isinstance(a.rhs, Trans)

    def test_index_atom_is_opaque(self) -> None:
        a = parse_one("y = n(:,1);")
        assert isinstance(a.rhs, Index)
        assert a.rhs.name == "n"
        assert canon(a.rhs) == "n(:, 1)"

    def test_known_function_call(self) -> None:
        a = parse_one("y = sqrt(x);")
        assert isinstance(a.rhs, Call)
        assert a.rhs.name == "sqrt"

    def test_line_continuation(self) -> None:
        a = parse_one("y = a + ...\n    b;")
        assert isinstance(a.rhs, Bin)

    def test_comments_ignored(self) -> None:
        a = parse_one("y = a + b; % trailing comment")
        assert isinstance(a.rhs, Bin)

    def test_precedence(self) -> None:
        a = parse_one("y = a + b .* c;")
        rhs = a.rhs
        assert isinstance(rhs, Bin)
        assert rhs.op == "+"
        assert isinstance(rhs.right, Bin)
        assert rhs.right.op == ".*"

    def test_parentheses(self) -> None:
        a = parse_one("y = (a + b) .* c;")
        rhs = a.rhs
        assert isinstance(rhs, Bin)
        assert rhs.op == ".*"


@pytest.mark.req("FE-2")
class TestDefUse:
    def test_def_use_links_across_statements(self) -> None:
        assigns, _ = parse_program("t = a + b;\ny = t .* c;")
        builder, problems = build_dag(assigns, CM)
        assert not problems
        dag = builder.dag
        y_root = dag.nodes[dag.statements[1].root]
        t_root = dag.statements[0].root
        assert t_root in y_root.args  # y consumes t's defining node

    def test_self_reference_detected(self) -> None:
        assigns, _ = parse_program("acc = acc + x;")
        builder, _ = build_dag(assigns, CM)
        assert builder.dag.feedbacks
        var, _line, ii = builder.dag.feedbacks[0]
        assert var == "acc"
        assert ii == CM.add_lat

    @pytest.mark.req("FE-5")
    def test_loop_feedback(self) -> None:
        # a non-constant bound cannot unroll: the recurrence interpretation
        # (one iteration + FEEDBACK) applies (LP-1)
        src = "for k = 1:n\n  acc = acc + x;\nend"
        assigns, skipped = parse_program(src)
        assert not skipped
        assert assigns[0].in_loop
        builder, _ = build_dag(assigns, CM)
        assert builder.dag.feedbacks

    def test_constant_loop_unrolls_instead(self) -> None:
        src = "acc = x;\nfor k = 1:8\n  acc = acc + x;\nend"
        assigns, skipped = parse_program(src)
        assert not skipped
        assert len(assigns) == 9  # init + 8 unrolled iterations
        assert not assigns[1].in_loop
        builder, _ = build_dag(assigns, CM)
        assert not builder.dag.feedbacks  # a chain in space, not a recurrence
        legacy, _ = parse_program(src, unroll=False)
        assert legacy[1].in_loop  # legacy mode intact

    def test_feedback_ii_through_divider(self) -> None:
        assigns, _ = parse_program("g0 = g0 / d;")
        builder, _ = build_dag(assigns, CM)
        _, _, ii = builder.dag.feedbacks[0]
        assert ii == CM.div_lat


@pytest.mark.req("FE-3")
class TestSkipAndReport:
    def test_unparseable_statement_skipped_with_line_and_reason(self) -> None:
        src = "y = a + b;\nz = @() 1;\nw = c .* d;"
        assigns, skipped = parse_program(src)
        assert len(assigns) == 2  # parsing never aborts the file
        assert len(skipped) == 1
        assert skipped[0].line == 2

    def test_unsupported_constructs_reported(self) -> None:
        src = "if a > b\n  y = 1;\nend\nz = c + d;"
        assigns, skipped = parse_program(src)
        assert any("if" in s.reason for s in skipped)
        assert len(assigns) == 2  # y and z still parsed

    def test_string_statement_skipped(self) -> None:
        assigns, skipped = parse_program("y = 'hello';\nz = a + b;")
        assert len(skipped) == 1
        assert "string" in skipped[0].reason
        assert len(assigns) == 1

    def test_comparison_operator_skipped(self) -> None:
        assigns, skipped = parse_program("y = a == b;")
        assert not assigns
        assert skipped and "unsupported operator" in skipped[0].reason


@pytest.mark.req("FE-4")
class TestSpans:
    def test_expression_spans_cover_source_text(self) -> None:
        src = "y = alpha + beta;"
        a = parse_one(src)
        rhs = a.rhs
        assert isinstance(rhs, Bin)
        assert src[rhs.left.span.start : rhs.left.span.end] == "alpha"
        assert src[rhs.right.span.start : rhs.right.span.end] == "beta"
        assert src[rhs.span.start : rhs.span.end] == "alpha + beta"

    def test_statement_span(self) -> None:
        src = "first = 1;\nsecond = x + y;"
        assigns, _ = parse_program(src)
        a = assigns[1]
        assert src[a.span.start : a.span.end] == "second = x + y"
        assert a.line == 2

    def test_dag_nodes_carry_spans(self) -> None:
        src = "y = a .* b;"
        assigns, _ = parse_program(src)
        builder, _ = build_dag(assigns, CM)
        root = builder.dag.nodes[builder.dag.statements[0].root]
        assert root.span is not None
        assert src[root.span.start : root.span.end] == "a .* b"


def test_tokenizer_transpose_vs_string() -> None:
    toks = tokenize("y = x';")
    assert any(t.kind == "OP" and t.text == "'" for t in toks)
    toks = tokenize("y = 'str';")
    assert any(t.kind == "STR" for t in toks)
