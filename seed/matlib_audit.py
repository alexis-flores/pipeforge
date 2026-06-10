#!/usr/bin/env python3
"""matlib_audit — static latency auditor for MATLAB DSP scripts targeting nkMatlib.

Parses a MATLAB script (assignment/expression subset), builds a dataflow DAG,
schedules it against the nkMatlib pipelined cost model, and reports:

  * per-statement ready times and the total critical-path latency
  * the dominant dependency chain
  * an operator-instance census with divider count highlighted
  * optimization findings: RECIP, CDIV, SERDIV, POW, CSE, FUSE, FEEDBACK

Latency model of record: nkMatlib README (github.com/nklabs/matlib).
All latencies are derived from WIDTH/SCALE at runtime, never hard-coded.

Usage:
    matlib_audit.py [-w WIDTH] [-s SCALE] [--json] file.m
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from typing import Callable, NamedTuple, Optional, Union

VERSION = "1.0"

# ---------------------------------------------------------------------------
# Cost model (nkMatlib README is the model of record)
# ---------------------------------------------------------------------------


class CostModel:
    """nkMatlib operator latencies derived from WIDTH and SCALE."""

    def __init__(self, width: int = 16, scale: int = 12) -> None:
        if width <= 0 or scale < 0 or scale >= width:
            raise ValueError(f"invalid fixedp parameters WIDTH={width} SCALE={scale}")
        self.width = width
        self.scale = scale

    @property
    def left(self) -> int:
        return self.width - self.scale

    @property
    def add_lat(self) -> int:
        return 1

    @property
    def mul_lat(self) -> int:
        return 4

    @property
    def div_lat(self) -> int:
        return self.width + self.scale

    @property
    def sqrt_lat(self) -> int:
        return self.width - self.left // 2

    @property
    def matmul_lat(self) -> int:
        return self.mul_lat + 1

    @property
    def sumsqr_lat(self) -> int:
        return self.mul_lat + 1

    @property
    def rootsqr_lat(self) -> int:
        return self.sqrt_lat + self.sumsqr_lat

    @property
    def crossp_lat(self) -> int:
        return self.mul_lat + 1

    def latency_of(self, module: str) -> int:
        """Latency of an nkMatlib module instance."""
        table: dict[str, int] = {
            "": 0,  # wiring (index/range/concat), no instance
            "input": 0,
            "const": 0,
            "matadd": self.add_lat,
            "matsub": self.add_lat,
            "matadd3": self.add_lat,
            "matadd3b1": self.add_lat,
            "matadd3b2": self.add_lat,
            "elem_neg": 1,
            "elem_abs": 1,
            "elem_smax": 1,
            "elem_smin": 1,
            "elem_rshift": 1,
            "elem_smul": self.mul_lat,
            "elem_ssqr": self.mul_lat,
            "elem_sdiv": self.div_lat,
            "elem_sinv": self.div_lat,
            "elem_usqrt": self.sqrt_lat,
            "matmul": self.matmul_lat,
            "matscale": self.mul_lat,
            "matunscale": self.div_lat,
            "sumsqr": self.sumsqr_lat,
            "rootsqr": self.rootsqr_lat,
            "crossp": self.crossp_lat,
            "vecnormrows": self.rootsqr_lat,
            "vecnormcols": self.rootsqr_lat,
            "transp": 0,
            "elem_same": 0,
            "elem_snorm": 0,
            "selcols": 0,
            "selrows": 0,
        }
        if module not in table:
            raise KeyError(f"unknown nkMatlib module: {module}")
        return table[module]

    def is_divider(self, module: str) -> bool:
        return module in ("elem_sdiv", "elem_sinv", "matunscale", "elem_sdiv_by_row")

    def summary(self) -> dict[str, int]:
        return {
            "ADD": self.add_lat,
            "MUL": self.mul_lat,
            "DIV": self.div_lat,
            "SQRT": self.sqrt_lat,
            "MATMUL": self.matmul_lat,
            "SUMSQR": self.sumsqr_lat,
            "ROOTSQR": self.rootsqr_lat,
            "CROSSP": self.crossp_lat,
        }


# Known MATLAB functions -> nkMatlib module (extensible via config).
KNOWN_FUNCS: dict[str, str] = {
    "sqrt": "elem_usqrt",
    "abs": "elem_abs",
    "max": "elem_smax",
    "min": "elem_smin",
    "norm": "rootsqr",
    "sumsqr": "sumsqr",
    "cross": "crossp",
    "dot": "matmul",
    "vecnorm": "vecnormrows",
    "transpose": "transp",
    "ones": "elem_same",
    "zeros": "elem_same",
}


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class Tok(NamedTuple):
    kind: str  # NUM ID OP STR NEWLINE EOF
    text: str
    line: int
    col: int
    pos: int


class MatlabSyntaxError(Exception):
    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


_TWO_CHAR_OPS = (".*", "./", ".\\", ".^", ".'", "==", "~=", "<=", ">=", "&&", "||")
_ONE_CHAR_OPS = "+-*/\\^'()[]{},;:<>=&|~@"


def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    i = 0
    line = 1
    col = 1
    n = len(text)

    def prev_significant() -> Optional[Tok]:
        return toks[-1] if toks and toks[-1].kind != "NEWLINE" else None

    while i < n:
        ch = text[i]
        if ch == "\n":
            toks.append(Tok("NEWLINE", "\n", line, col, i))
            i += 1
            line += 1
            col = 1
            continue
        if ch in " \t\r":
            i += 1
            col += 1
            continue
        if ch == "%":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("...", i):
            while i < n and text[i] != "\n":
                i += 1
            if i < n:  # swallow the newline: continuation
                i += 1
                line += 1
                col = 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            while j < n and (text[j].isdigit() or text[j] == "."):
                j += 1
            if j < n and text[j] in "eE":
                k = j + 1
                if k < n and text[k] in "+-":
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            toks.append(Tok("NUM", text[i:j], line, col, i))
            col += j - i
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            toks.append(Tok("ID", text[i:j], line, col, i))
            col += j - i
            i = j
            continue
        two = text[i : i + 2]
        if two in _TWO_CHAR_OPS:
            toks.append(Tok("OP", two, line, col, i))
            i += 2
            col += 2
            continue
        if ch == "'":
            prev = prev_significant()
            if prev is not None and (
                prev.kind in ("ID", "NUM") or (prev.kind == "OP" and prev.text in (")", "]", "'"))
            ):
                toks.append(Tok("OP", "'", line, col, i))
                i += 1
                col += 1
                continue
            j = i + 1
            while j < n and text[j] != "\n":
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j >= n or text[j] != "'":
                raise MatlabSyntaxError("unterminated string literal", line)
            toks.append(Tok("STR", text[i : j + 1], line, col, i))
            col += j + 1 - i
            i = j + 1
            continue
        if ch in _ONE_CHAR_OPS:
            toks.append(Tok("OP", ch, line, col, i))
            i += 1
            col += 1
            continue
        raise MatlabSyntaxError(f"unexpected character {ch!r}", line)
    toks.append(Tok("EOF", "", line, col, i))
    return toks


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class Num:
    value: float
    span: Span


@dataclass(frozen=True)
class Var:
    name: str
    span: Span


@dataclass(frozen=True)
class ColonAtom:
    span: Span


@dataclass(frozen=True)
class Str:
    text: str
    span: Span


@dataclass(frozen=True)
class Index:
    name: str
    args: tuple["Expr", ...]
    span: Span


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple["Expr", ...]
    span: Span


@dataclass(frozen=True)
class Bin:
    op: str
    left: "Expr"
    right: "Expr"
    span: Span


@dataclass(frozen=True)
class Un:
    op: str
    operand: "Expr"
    span: Span


@dataclass(frozen=True)
class Trans:
    operand: "Expr"
    span: Span


@dataclass(frozen=True)
class Mat:
    elems: tuple["Expr", ...]
    span: Span


Expr = Union[Num, Var, ColonAtom, Str, Index, Call, Bin, Un, Trans, Mat]


def canon(e: Expr) -> str:
    """Canonical text of an expression, used for CSE/RECIP grouping."""
    if isinstance(e, Num):
        v = e.value
        return str(int(v)) if v == int(v) else repr(v)
    if isinstance(e, Var):
        return e.name
    if isinstance(e, ColonAtom):
        return ":"
    if isinstance(e, Str):
        return e.text
    if isinstance(e, Index):
        return f"{e.name}({', '.join(canon(a) for a in e.args)})"
    if isinstance(e, Call):
        return f"{e.name}({', '.join(canon(a) for a in e.args)})"
    if isinstance(e, Bin):
        return f"({canon(e.left)} {e.op} {canon(e.right)})"
    if isinstance(e, Un):
        return f"({e.op}{canon(e.operand)})"
    if isinstance(e, Trans):
        return f"({canon(e.operand)}')"
    if isinstance(e, Mat):
        return f"[{', '.join(canon(x) for x in e.elems)}]"
    raise TypeError(f"unknown expr: {e!r}")


# ---------------------------------------------------------------------------
# Parser (recursive descent)
# ---------------------------------------------------------------------------

_ADDITIVE = ("+", "-")
_MULTIPLICATIVE = ("*", ".*", "/", "./", "\\", ".\\")
_POWER = ("^", ".^")
_UNSUPPORTED_BIN = ("==", "~=", "<=", ">=", "<", ">", "&", "|", "&&", "||")


class ExprParser:
    def __init__(self, toks: list[Tok], src: str) -> None:
        self.toks = toks
        self.src = src
        self.pos = 0

    def peek(self) -> Tok:
        return self.toks[self.pos]

    def next(self) -> Tok:
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def expect(self, text: str) -> Tok:
        t = self.peek()
        if t.kind != "OP" or t.text != text:
            raise MatlabSyntaxError(f"expected {text!r}, found {t.text!r}", t.line)
        return self.next()

    def at_op(self, *texts: str) -> bool:
        t = self.peek()
        return t.kind == "OP" and t.text in texts

    def done(self) -> bool:
        return self.peek().kind == "EOF"

    def _span(self, start: Tok, end: Tok) -> Span:
        return Span(start.pos, end.pos + len(end.text), start.line)

    # expr := range
    def parse_expr(self) -> Expr:
        e = self.parse_range()
        t = self.peek()
        if t.kind == "OP" and t.text in _UNSUPPORTED_BIN:
            raise MatlabSyntaxError(f"unsupported operator {t.text!r}", t.line)
        return e

    # range := additive (':' additive){0,2}
    def parse_range(self) -> Expr:
        first = self.peek()
        e = self.parse_additive()
        while self.at_op(":"):
            self.next()
            rhs = self.parse_additive()
            e = Bin(":", e, rhs, Span(first.pos, self.toks[self.pos - 1].pos, first.line))
        return e

    def parse_additive(self) -> Expr:
        first = self.peek()
        e = self.parse_multiplicative()
        while self.at_op(*_ADDITIVE):
            op = self.next().text
            rhs = self.parse_multiplicative()
            end = self.toks[self.pos - 1]
            e = Bin(op, e, rhs, self._span(first, end))
        return e

    def parse_multiplicative(self) -> Expr:
        first = self.peek()
        e = self.parse_unary()
        while self.at_op(*_MULTIPLICATIVE):
            op = self.next().text
            rhs = self.parse_unary()
            end = self.toks[self.pos - 1]
            e = Bin(op, e, rhs, self._span(first, end))
        return e

    def parse_unary(self) -> Expr:
        t = self.peek()
        if t.kind == "OP" and t.text in ("-", "+", "~"):
            if t.text == "~":
                raise MatlabSyntaxError("unsupported operator '~'", t.line)
            self.next()
            operand = self.parse_unary()
            end = self.toks[self.pos - 1]
            if t.text == "+":
                return operand
            return Un("-", operand, self._span(t, end))
        return self.parse_power()

    def parse_power(self) -> Expr:
        first = self.peek()
        e = self.parse_postfix()
        if self.at_op(*_POWER):
            op = self.next().text
            rhs = self.parse_unary()  # right side may carry unary minus
            end = self.toks[self.pos - 1]
            e = Bin(op, e, rhs, self._span(first, end))
        return e

    def parse_postfix(self) -> Expr:
        first = self.peek()
        e = self.parse_atom()
        while self.at_op("'", ".'"):
            t = self.next()
            e = Trans(e, self._span(first, t))
        return e

    def parse_atom(self) -> Expr:
        t = self.peek()
        if t.kind == "NUM":
            self.next()
            return Num(float(t.text), Span(t.pos, t.pos + len(t.text), t.line))
        if t.kind == "STR":
            raise MatlabSyntaxError("string literals are not supported", t.line)
        if t.kind == "ID":
            self.next()
            if self.at_op("("):
                self.next()
                args = self.parse_args()
                close = self.expect(")")
                span = self._span(t, close)
                if t.text in KNOWN_FUNCS:
                    return Call(t.text, tuple(args), span)
                return Index(t.text, tuple(args), span)
            return Var(t.text, Span(t.pos, t.pos + len(t.text), t.line))
        if t.kind == "OP" and t.text == "(":
            self.next()
            e = self.parse_expr()
            self.expect(")")
            return e
        if t.kind == "OP" and t.text == "[":
            self.next()
            elems: list[Expr] = []
            while not self.at_op("]"):
                if self.done():
                    raise MatlabSyntaxError("unterminated matrix literal", t.line)
                elems.append(self.parse_expr())
                while self.at_op(",", ";"):
                    self.next()
            close = self.next()
            return Mat(tuple(elems), self._span(t, close))
        if t.kind == "OP" and t.text == ":":
            self.next()
            return ColonAtom(Span(t.pos, t.pos + 1, t.line))
        raise MatlabSyntaxError(f"unexpected token {t.text!r}", t.line)

    def parse_args(self) -> list[Expr]:
        args: list[Expr] = []
        if self.at_op(")"):
            return args
        while True:
            args.append(self.parse_expr())
            if self.at_op(","):
                self.next()
                continue
            return args


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass
class Assign:
    target: str
    indexed: bool
    rhs: Expr
    line: int
    span: Span
    in_loop: bool


@dataclass
class Skipped:
    line: int
    reason: str


def split_statements(toks: list[Tok]) -> list[list[Tok]]:
    """Split a token stream into statements at top-level newlines/semicolons."""
    stmts: list[list[Tok]] = []
    cur: list[Tok] = []
    depth = 0
    for t in toks:
        if t.kind == "OP" and t.text in "([{":
            depth += 1
        elif t.kind == "OP" and t.text in ")]}":
            depth = max(0, depth - 1)
        if (t.kind == "NEWLINE" or (t.kind == "OP" and t.text in (";", ","))) and depth == 0:
            if cur:
                stmts.append(cur)
                cur = []
            continue
        if t.kind == "EOF":
            break
        if t.kind == "NEWLINE":
            continue  # newline inside brackets: soft
        cur.append(t)
    if cur:
        stmts.append(cur)
    return stmts


def parse_program(src: str) -> tuple[list[Assign], list[Skipped]]:
    assigns: list[Assign] = []
    skipped: list[Skipped] = []
    try:
        toks = tokenize(src)
    except MatlabSyntaxError as exc:
        return [], [Skipped(exc.line, exc.message)]
    block_stack: list[str] = []  # 'for' | 'other'

    for stmt in split_statements(toks):
        first = stmt[0]
        line = first.line
        words = first.text if first.kind == "ID" else ""
        try:
            if words == "end":
                if block_stack:
                    block_stack.pop()
                else:
                    skipped.append(Skipped(line, "stray 'end'"))
                continue
            if words == "for":
                # for ID = expr — bind nothing; loop var becomes an input
                if len(stmt) < 4 or stmt[1].kind != "ID" or stmt[2].text != "=":
                    raise MatlabSyntaxError("malformed for header", line)
                p = ExprParser([*stmt[3:], Tok("EOF", "", line, 0, stmt[-1].pos)], src)
                p.parse_expr()
                if not p.done():
                    raise MatlabSyntaxError("malformed for header", line)
                block_stack.append("for")
                continue
            if words in ("if", "while", "elseif", "switch"):
                block_stack.append("other")
                skipped.append(Skipped(line, f"unsupported construct: {words}"))
                continue
            if words in ("else", "otherwise", "case"):
                skipped.append(Skipped(line, f"unsupported construct: {words}"))
                continue
            if words in ("function", "return", "break", "continue", "global", "persistent"):
                skipped.append(Skipped(line, f"unsupported construct: {words}"))
                continue

            # assignment: TARGET = expr
            eq = None
            depth = 0
            for idx, t in enumerate(stmt):
                if t.kind == "OP" and t.text in "([{":
                    depth += 1
                elif t.kind == "OP" and t.text in ")]}":
                    depth -= 1
                elif t.kind == "OP" and t.text == "=" and depth == 0:
                    eq = idx
                    break
            if eq is None:
                raise MatlabSyntaxError("expression statement (no assignment)", line)
            lhs = stmt[:eq]
            if not lhs:
                raise MatlabSyntaxError("missing assignment target", line)
            if lhs[0].kind == "OP" and lhs[0].text == "[":
                raise MatlabSyntaxError("multiple assignment is not supported", line)
            if lhs[0].kind != "ID":
                raise MatlabSyntaxError("assignment target must be an identifier", line)
            indexed = len(lhs) > 1
            rhs_toks = stmt[eq + 1 :]
            if not rhs_toks:
                raise MatlabSyntaxError("missing right-hand side", line)
            p = ExprParser(
                [*rhs_toks, Tok("EOF", "", line, 0, stmt[-1].pos + len(stmt[-1].text))], src
            )
            rhs = p.parse_expr()
            if not p.done():
                t = p.peek()
                raise MatlabSyntaxError(f"unexpected token {t.text!r}", t.line)
            span = Span(stmt[0].pos, stmt[-1].pos + len(stmt[-1].text), line)
            assigns.append(
                Assign(lhs[0].text, indexed, rhs, line, span, in_loop="for" in block_stack)
            )
        except MatlabSyntaxError as exc:
            skipped.append(Skipped(exc.line, exc.message))
    return assigns, skipped


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------


@dataclass
class Node:
    nid: str
    module: str  # nkMatlib module, or 'input'/'const'/'' (wiring)
    op: str  # human label of the operation
    lat: int
    ready: int
    args: list[str]
    line: int
    label: str  # canonical expression text
    signal: str = ""  # lhs name when this node is a statement root
    span: Optional[Span] = None


@dataclass
class StmtInfo:
    line: int
    target: str
    ready: int
    lat: int
    root: str


@dataclass
class Dag:
    nodes: dict[str, Node] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    statements: list[StmtInfo] = field(default_factory=list)
    feedbacks: list[tuple[str, int, int]] = field(default_factory=list)  # (var, line, ii)

    def add(self, node: Node) -> Node:
        self.nodes[node.nid] = node
        self.order.append(node.nid)
        return node


class DagBuilder:
    def __init__(self, cm: CostModel) -> None:
        self.cm = cm
        self.dag = Dag()
        self.env: dict[str, str] = {}  # var -> defining node id
        self.counter = 0
        self.div_nodes: list[tuple[Node, Expr, Expr]] = []  # (node, dividend, divisor)
        self.pow_expansions: list[tuple[int, str, int, int]] = []  # (line, base, exp, naive)
        self.cur_line = 0

    def new_id(self) -> str:
        self.counter += 1
        return f"n{self.counter:03d}"

    def leaf(self, module: str, label: str, span: Optional[Span]) -> Node:
        # Reuse one leaf per distinct input/const label.
        for nid in self.dag.order:
            n = self.dag.nodes[nid]
            if n.module == module and n.label == label:
                return n
        node = Node(
            self.new_id(), module, module, 0, 0, [], self.cur_line, label, span=span
        )
        return self.dag.add(node)

    def op_node(
        self, module: str, op: str, args: list[Node], label: str, span: Optional[Span]
    ) -> Node:
        lat = self.cm.latency_of(module)
        ready = max((a.ready for a in args), default=0) + lat
        node = Node(
            self.new_id(),
            module,
            op,
            lat,
            ready,
            [a.nid for a in args],
            self.cur_line,
            label,
            span=span,
        )
        return self.dag.add(node)

    def build_expr(self, e: Expr) -> Node:
        if isinstance(e, Num):
            return self.leaf("const", canon(e), e.span)
        if isinstance(e, Var):
            if e.name in self.env:
                return self.dag.nodes[self.env[e.name]]
            return self.leaf("input", e.name, e.span)
        if isinstance(e, ColonAtom):
            return self.leaf("const", ":", e.span)
        if isinstance(e, Str):
            return self.leaf("const", e.text, e.span)
        if isinstance(e, Index):
            args = [self.build_expr(a) for a in e.args]
            base = (
                self.dag.nodes[self.env[e.name]]
                if e.name in self.env
                else self.leaf("input", e.name, e.span)
            )
            return self.op_node("", "index", [base, *args], canon(e), e.span)
        if isinstance(e, Call):
            module = KNOWN_FUNCS[e.name]
            args = [self.build_expr(a) for a in e.args]
            return self.op_node(module, e.name, args, canon(e), e.span)
        if isinstance(e, Mat):
            elems = [self.build_expr(x) for x in e.elems]
            return self.op_node("", "concat", elems, canon(e), e.span)
        if isinstance(e, Un):
            operand = self.build_expr(e.operand)
            return self.op_node("elem_neg", "neg", [operand], canon(e), e.span)
        if isinstance(e, Trans):
            operand = self.build_expr(e.operand)
            return self.op_node("transp", "transpose", [operand], canon(e), e.span)
        if isinstance(e, Bin):
            return self.build_bin(e)
        raise TypeError(f"unknown expr: {e!r}")

    def build_bin(self, e: Bin) -> Node:
        op = e.op
        if op == ":":
            left = self.build_expr(e.left)
            right = self.build_expr(e.right)
            return self.op_node("", "range", [left, right], canon(e), e.span)
        if op in ("^", ".^"):
            return self.build_pow(e)
        if op in ("+", "-"):
            left = self.build_expr(e.left)
            right = self.build_expr(e.right)
            module = "matadd" if op == "+" else "matsub"
            return self.op_node(module, op, [left, right], canon(e), e.span)
        if op in ("*", ".*"):
            left = self.build_expr(e.left)
            right = self.build_expr(e.right)
            return self.op_node("elem_smul", op, [left, right], canon(e), e.span)
        if op in ("/", "./", "\\", ".\\"):
            left = self.build_expr(e.left)
            right = self.build_expr(e.right)
            if op in ("\\", ".\\"):
                left, right = right, left
                dividend_ast: Expr = e.right
                divisor_ast: Expr = e.left
            else:
                dividend_ast = e.left
                divisor_ast = e.right
            node = self.op_node("elem_sdiv", "/", [left, right], canon(e), e.span)
            self.div_nodes.append((node, dividend_ast, divisor_ast))
            return node
        raise MatlabSyntaxError(f"unsupported operator {op!r}", e.span.line)

    def build_pow(self, e: Bin) -> Node:
        if not isinstance(e.right, Num) or e.right.value != int(e.right.value):
            raise MatlabSyntaxError(
                "only constant integer exponents are supported", e.span.line
            )
        exp = int(e.right.value)
        if exp < 2:
            raise MatlabSyntaxError(
                "only integer exponents >= 2 are supported", e.span.line
            )
        base = self.build_expr(e.left)
        base_label = canon(e.left)
        # Naive left-to-right multiply chain; the POW finding suggests better.
        acc = base
        for k in range(2, exp + 1):
            label = f"({base_label}^{k})"
            acc = self.op_node("elem_smul", ".*", [acc, base], label, e.span)
        self.pow_expansions.append((e.span.line, base_label, exp, exp - 1))
        return acc

    def feedback_path_lat(self, root: Node, target_nid: str) -> Optional[int]:
        """Latency of the longest path from a use of target_nid up to root."""
        memo: dict[str, Optional[int]] = {}

        def walk(nid: str) -> Optional[int]:
            if nid == target_nid:
                return 0
            if nid in memo:
                return memo[nid]
            node = self.dag.nodes[nid]
            best: Optional[int] = None
            for a in node.args:
                sub = walk(a)
                if sub is not None:
                    cand = sub + node.lat
                    if best is None or cand > best:
                        best = cand
            memo[nid] = best
            return best

        return walk(root.nid)

    def build_assign(self, a: Assign) -> None:
        self.cur_line = a.line
        rhs_vars = _expr_vars(a.rhs)
        self_ref = a.target in rhs_vars
        base = _stmt_base(self, a.rhs)
        root = self.build_expr(a.rhs)
        if root.signal == "" and not root.args and root.module in ("input", "const"):
            # alias like `y = x`: wrap in a zero-latency wire node for naming
            root = self.op_node("", "wire", [root], canon(a.rhs), a.span)
        if self_ref:
            prior = self.env.get(a.target)
            use_nid = prior if prior is not None else None
            if use_nid is None:
                # self-reference to an undefined var: it appeared as an input leaf
                for nid in self.dag.order:
                    n = self.dag.nodes[nid]
                    if n.module == "input" and n.label == a.target:
                        use_nid = nid
                        break
            ii = self.feedback_path_lat(root, use_nid) if use_nid is not None else None
            self.dag.feedbacks.append((a.target, a.line, ii if ii is not None else root.ready))
        root.signal = a.target
        self.env[a.target] = root.nid
        self.dag.statements.append(
            StmtInfo(a.line, a.target, root.ready, root.ready - base, root.nid)
        )


def _stmt_base(builder: DagBuilder, rhs: Expr) -> int:
    """Ready time of the latest-arriving operand referenced by a statement."""
    base = 0
    for name in _expr_vars(rhs):
        if name in builder.env:
            base = max(base, builder.dag.nodes[builder.env[name]].ready)
    return base


def _expr_vars(e: Expr) -> set[str]:
    out: set[str] = set()
    if isinstance(e, Var):
        out.add(e.name)
    elif isinstance(e, Index):
        out.add(e.name)
        for a in e.args:
            out |= _expr_vars(a)
    elif isinstance(e, Call):
        for a in e.args:
            out |= _expr_vars(a)
    elif isinstance(e, Bin):
        out |= _expr_vars(e.left) | _expr_vars(e.right)
    elif isinstance(e, Un):
        out |= _expr_vars(e.operand)
    elif isinstance(e, Trans):
        out |= _expr_vars(e.operand)
    elif isinstance(e, Mat):
        for x in e.elems:
            out |= _expr_vars(x)
    return out


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    tag: str
    line: int
    savings: int  # estimated cycles of pipeline depth removed (aggregate)
    message: str
    suggestion: str


def find_findings(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    dag = builder.dag

    # RECIP: several divisions share one divisor
    by_divisor: dict[str, list[tuple[Node, Expr]]] = {}
    for node, _dividend, divisor in builder.div_nodes:
        if isinstance(divisor, Num):
            continue
        by_divisor.setdefault(canon(divisor), []).append((node, divisor))
    for div_label, group in sorted(by_divisor.items(), key=lambda kv: kv[1][0][0].line):
        if len(group) < 2:
            continue
        k = len(group)
        line = min(n.line for n, _ in group)
        findings.append(
            Finding(
                "RECIP",
                line,
                (k - 1) * (cm.div_lat - cm.mul_lat),
                f"{k} divisions share divisor '{div_label}'",
                f"compute r = 1/{div_label} once (elem_sinv) and multiply by r "
                f"(elem_smul): {k - 1} fewer dividers, "
                f"{(k - 1) * (cm.div_lat - cm.mul_lat)} cycles of divider depth removed",
            )
        )

    # CDIV: division by a constant
    for node, _dividend, divisor in builder.div_nodes:
        if not isinstance(divisor, Num):
            continue
        c = divisor.value
        if c != 0 and c == int(c) and (int(c) & (int(c) - 1)) == 0 and int(c) > 0:
            shift = int(math.log2(int(c)))
            findings.append(
                Finding(
                    "CDIV",
                    node.line,
                    cm.div_lat - 1,
                    f"division by power-of-two constant {canon(divisor)}",
                    f"replace with elem_rshift by {shift}: saves {cm.div_lat - 1} cycles "
                    f"and one divider",
                )
            )
        else:
            findings.append(
                Finding(
                    "CDIV",
                    node.line,
                    cm.div_lat - cm.mul_lat,
                    f"division by constant {canon(divisor)}",
                    f"multiply by the constant 1/{canon(divisor)} (elem_smul): "
                    f"saves {cm.div_lat - cm.mul_lat} cycles and one divider",
                )
            )

    # SERDIV: serial division chains a/b/c
    for node, dividend, _divisor in builder.div_nodes:
        if isinstance(dividend, Bin) and dividend.op in ("/", "./"):
            findings.append(
                Finding(
                    "SERDIV",
                    node.line,
                    cm.div_lat - cm.mul_lat,
                    "serial division chain",
                    f"multiply the divisors and divide once: saves "
                    f"{cm.div_lat - cm.mul_lat} cycles and one divider",
                )
            )

    # POW: expanded integer powers
    for line, base_label, exp, naive_muls in builder.pow_expansions:
        if exp == 2:
            findings.append(
                Finding(
                    "POW",
                    line,
                    0,
                    f"square of '{base_label}'",
                    "use elem_ssqr (same latency, one operand port)",
                )
            )
        else:
            bin_muls = (exp.bit_length() - 1) + (bin(exp).count("1") - 1)
            savings = (naive_muls - bin_muls) * cm.mul_lat
            findings.append(
                Finding(
                    "POW",
                    line,
                    savings,
                    f"'{base_label}' raised to the {exp} by a multiply chain "
                    f"({naive_muls} multipliers)",
                    f"use binary exponentiation via elem_ssqr ({bin_muls} multipliers): "
                    f"saves {savings} cycles",
                )
            )

    # CSE: identical subexpressions computed more than once
    by_label: dict[str, list[Node]] = {}
    for nid in dag.order:
        n = dag.nodes[nid]
        if n.args and n.module not in ("", "input", "const"):
            by_label.setdefault(n.label, []).append(n)
    for label, group in sorted(by_label.items(), key=lambda kv: kv[1][0].line):
        if len(group) < 2:
            continue
        k = len(group)
        lat = group[0].lat
        findings.append(
            Finding(
                "CSE",
                group[0].line,
                (k - 1) * lat,
                f"'{label}' is computed {k} times "
                f"(lines {', '.join(str(n.line) for n in group)})",
                f"compute once and `PIPE the result: removes {k - 1} "
                f"{group[0].module} instance(s)",
            )
        )

    # FUSE: chained adds/subs fusable into matadd3 variants
    consumers: dict[str, int] = {}
    for nid in dag.order:
        for a in dag.nodes[nid].args:
            consumers[a] = consumers.get(a, 0) + 1
    for nid in dag.order:
        n = dag.nodes[nid]
        if n.module not in ("matadd", "matsub") or not n.args:
            continue
        inner = dag.nodes[n.args[0]]
        if inner.module not in ("matadd", "matsub") or consumers.get(inner.nid, 0) != 1:
            continue
        if inner.module == "matadd" and n.module == "matadd":
            fused = "matadd3"
        elif inner.module == "matadd" and n.module == "matsub":
            fused = "matadd3b1"
        elif inner.module == "matsub" and n.module == "matsub":
            fused = "matadd3b2"
        else:
            continue  # (a-b)+c: no direct 3-input module
        findings.append(
            Finding(
                "FUSE",
                n.line,
                cm.add_lat,
                f"chained adds '{n.label}'",
                f"fuse into one {fused}: saves {cm.add_lat} cycle of pipeline depth",
            )
        )

    # FEEDBACK
    for var, line, ii in dag.feedbacks:
        findings.append(
            Finding(
                "FEEDBACK",
                line,
                0,
                f"'{var}' feeds back into itself: loop initiation interval is "
                f"{ii} cycles",
                "a new iteration can start only every "
                f"{ii} cycles; shorten the feedback path or restructure the recurrence",
            )
        )

    findings.sort(key=lambda f: (f.line, f.tag))
    return findings


# ---------------------------------------------------------------------------
# Audit driver and reports
# ---------------------------------------------------------------------------


@dataclass
class Audit:
    filename: str
    cm: CostModel
    dag: Dag
    findings: list[Finding]
    skipped: list[Skipped]

    @property
    def census(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for nid in self.dag.order:
            n = self.dag.nodes[nid]
            if n.module in ("", "input", "const"):
                continue
            out[n.module] = out.get(n.module, 0) + 1
        return dict(sorted(out.items()))

    @property
    def divider_count(self) -> int:
        return sum(v for k, v in self.census.items() if self.cm.is_divider(k))

    @property
    def total_latency(self) -> int:
        return max((s.ready for s in self.dag.statements), default=0)

    def critical_path(self) -> list[Node]:
        if not self.dag.statements:
            return []
        root_id = max(self.dag.statements, key=lambda s: (s.ready, -s.line)).root
        chain: list[Node] = []
        nid: Optional[str] = root_id
        while nid is not None:
            node = self.dag.nodes[nid]
            chain.append(node)
            if not node.args:
                nid = None
            else:
                nid = max(node.args, key=lambda a: self.dag.nodes[a].ready)
        chain.reverse()
        return chain


def audit_file(src: str, filename: str, cm: CostModel) -> Audit:
    assigns, skipped = parse_program(src)
    builder = DagBuilder(cm)
    for a in assigns:
        try:
            builder.build_assign(a)
        except MatlabSyntaxError as exc:
            skipped.append(Skipped(exc.line, exc.message))
    skipped.sort(key=lambda s: s.line)
    findings = find_findings(builder, cm)
    return Audit(filename, cm, builder.dag, findings, skipped)


def _short(label: str, width: int = 38) -> str:
    return label if len(label) <= width else label[: width - 1] + "…"


def render_text(audit: Audit) -> str:
    cm = audit.cm
    lines: list[str] = []
    lines.append(f"matlib_audit {VERSION} — nkMatlib latency audit")
    lines.append(f"file: {audit.filename}")
    lines.append(f"fixedp: WIDTH={cm.width} SCALE={cm.scale} LEFT={cm.left}")
    lat = cm.summary()
    lines.append(
        "latencies: "
        + " ".join(f"{k}={v}" for k, v in lat.items())
    )
    lines.append("")
    lines.append("== statements ==")
    if audit.dag.statements:
        for s in audit.dag.statements:
            lines.append(
                f"  line {s.line:>3}  {s.target:<12} ready @ {s.ready:>4}  (+{s.lat})"
            )
    else:
        lines.append("  (none)")
    lines.append("")
    chain = audit.critical_path()
    lines.append(f"== critical path ==  total {audit.total_latency} cycles")
    for node in chain:
        mod = node.module if node.module else "wire"
        plus = f"+{node.lat}" if node.lat else ""
        lines.append(
            f"  @ {node.ready:>4}  line {node.line:>3}  {_short(node.label):<38} "
            f"{mod:<12} {plus}"
        )
    lines.append("")
    census = audit.census
    total = sum(census.values())
    lines.append(
        f"== operator census ==  ({total} instances, {audit.divider_count} dividers)"
    )
    if census:
        for mod, count in census.items():
            marker = "   << divider" if cm.is_divider(mod) else ""
            lines.append(f"  {mod:<14} x {count}{marker}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("== findings ==")
    if audit.findings:
        for f in audit.findings:
            lines.append(f"  [{f.tag:<8}] line {f.line}: {f.message}")
            lines.append(f"             -> {f.suggestion}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("== skipped ==")
    if audit.skipped:
        for s in audit.skipped:
            lines.append(f"  line {s.line}: {s.reason}")
    else:
        lines.append("  (none)")
    lines.append("")
    return "\n".join(lines)


def render_json(audit: Audit) -> str:
    cm = audit.cm
    chain = audit.critical_path()
    payload = {
        "tool": "matlib_audit",
        "version": VERSION,
        "file": audit.filename,
        "width": cm.width,
        "scale": cm.scale,
        "left": cm.left,
        "latencies": cm.summary(),
        "statements": [
            {"line": s.line, "target": s.target, "ready": s.ready, "lat": s.lat, "root": s.root}
            for s in audit.dag.statements
        ],
        "critical_path": {
            "total": audit.total_latency,
            "chain": [
                {
                    "id": n.nid,
                    "cycle": n.ready,
                    "line": n.line,
                    "label": n.label,
                    "module": n.module,
                    "lat": n.lat,
                }
                for n in chain
            ],
        },
        "census": audit.census,
        "instances": sum(audit.census.values()),
        "dividers": audit.divider_count,
        "findings": [
            {
                "tag": f.tag,
                "line": f.line,
                "savings": f.savings,
                "message": f.message,
                "suggestion": f.suggestion,
            }
            for f in audit.findings
        ],
        "skipped": [{"line": s.line, "reason": s.reason} for s in audit.skipped],
        "nodes": [
            {
                "id": n.nid,
                "module": n.module,
                "op": n.op,
                "lat": n.lat,
                "ready": n.ready,
                "args": n.args,
                "line": n.line,
                "signal": n.signal,
                "label": n.label,
            }
            for n in (audit.dag.nodes[nid] for nid in audit.dag.order)
        ],
    }
    return json.dumps(payload, indent=2)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Static latency audit of MATLAB scripts against the nkMatlib cost model"
    )
    parser.add_argument("file", help="MATLAB script (.m)")
    parser.add_argument("-w", "--width", type=int, default=16, help="fixedp WIDTH (default 16)")
    parser.add_argument("-s", "--scale", type=int, default=12, help="fixedp SCALE (default 12)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)
    try:
        src = open(args.file, encoding="utf-8").read()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cm = CostModel(args.width, args.scale)
    import os

    audit = audit_file(src, os.path.basename(args.file), cm)
    print(render_json(audit) if args.json else render_text(audit), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
