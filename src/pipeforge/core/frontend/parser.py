"""Recursive-descent MATLAB statement/expression parser (FE-1, FE-3, FE-5).

Unparseable statements are recorded with line and reason and never abort
the file (FE-3). Simple ``for`` loops are tracked for feedback detection
(FE-5); other control flow is skipped-and-reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pipeforge.core.costmodel.model import KNOWN_FUNCS
from pipeforge.core.frontend.ast import (
    Bin,
    ColonAtom,
    Expr,
    Field,
    Index,
    Mat,
    Num,
    Span,
    Trans,
    Un,
    Var,
)
from pipeforge.core.frontend.ast import (
    Call as CallNode,
)
from pipeforge.core.frontend.lexer import MatlabSyntaxError, Tok, tokenize

if TYPE_CHECKING:
    from pipeforge.core.frontend.loops import UnrollNote

ADDITIVE = ("+", "-")
MULTIPLICATIVE = ("*", ".*", "/", "./", "\\", ".\\")
POWER = ("^", ".^")
UNSUPPORTED_BIN = ("==", "~=", "<=", ">=", "<", ">", "&", "|", "&&", "||")


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


class ExprParser:
    def __init__(self, toks: list[Tok], src: str, known_funcs: frozenset[str]) -> None:
        self.toks = toks
        self.src = src
        self.known_funcs = known_funcs
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

    def parse_expr(self) -> Expr:
        e = self.parse_range()
        t = self.peek()
        if t.kind == "OP" and t.text in UNSUPPORTED_BIN:
            raise MatlabSyntaxError(f"unsupported operator {t.text!r}", t.line)
        return e

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
        while self.at_op(*ADDITIVE):
            op = self.next().text
            rhs = self.parse_multiplicative()
            e = Bin(op, e, rhs, self._span(first, self.toks[self.pos - 1]))
        return e

    def parse_multiplicative(self) -> Expr:
        first = self.peek()
        e = self.parse_unary()
        while self.at_op(*MULTIPLICATIVE):
            op = self.next().text
            rhs = self.parse_unary()
            e = Bin(op, e, rhs, self._span(first, self.toks[self.pos - 1]))
        return e

    def parse_unary(self) -> Expr:
        t = self.peek()
        if t.kind == "OP" and t.text in ("-", "+", "~"):
            if t.text == "~":
                raise MatlabSyntaxError("unsupported operator '~'", t.line)
            self.next()
            operand = self.parse_unary()
            if t.text == "+":
                return operand
            return Un("-", operand, self._span(t, self.toks[self.pos - 1]))
        return self.parse_power()

    def parse_power(self) -> Expr:
        first = self.peek()
        e = self.parse_postfix()
        if self.at_op(*POWER):
            op = self.next().text
            rhs = self.parse_unary()  # the exponent may carry a unary minus
            e = Bin(op, e, rhs, self._span(first, self.toks[self.pos - 1]))
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
            # struct-field chain: a.b.c (grammar extension; see docs)
            path: list[str] = []
            last = t
            while self.at_op(".") and self.toks[self.pos + 1].kind == "ID":
                self.next()
                last = self.next()
                path.append(last.text)
            if self.at_op("("):
                self.next()
                args = self.parse_args()
                close = self.expect(")")
                span = self._span(t, close)
                if not path and t.text in self.known_funcs:
                    return CallNode(t.text, tuple(args), span)
                dotted = ".".join((t.text, *path))
                return Index(dotted, tuple(args), span)
            if path:
                return Field(t.text, tuple(path), self._span(t, last))
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


def _const_index_target(lhs: list[Tok]) -> str | None:
    """`y ( 3 )` or `y ( 2 , 3 )` -> the lane key 'y(3)' / 'y(2, 3)' (LN-1).

    Matches the canonical Index text exactly, so lane writes and lane reads
    resolve to the same definition. Non-constant indices return None (legacy
    whole-variable assignment).
    """
    if len(lhs) < 4 or lhs[1].text != "(" or lhs[-1].text != ")":
        return None
    nums: list[str] = []
    expect_num = True
    for t in lhs[2:-1]:
        if expect_num and t.kind == "NUM":
            try:
                v = float(t.text)
            except ValueError:
                return None
            if v != int(v) or int(v) < 1:
                return None
            nums.append(str(int(v)))
            expect_num = False
        elif not expect_num and t.kind == "OP" and t.text == ",":
            expect_num = True
        else:
            return None
    if expect_num or not nums or len(nums) > 2:
        return None
    return f"{lhs[0].text}({', '.join(nums)})"


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


def parse_program(
    src: str,
    known_funcs: frozenset[str] | None = None,
    unroll: bool = True,
    unroll_log: list[UnrollNote] | None = None,
) -> tuple[list[Assign], list[Skipped]]:
    """Parse a MATLAB script into assignments plus a skipped-statement list.

    Constant-bound `for` loops unroll into their iterations first (LP-1);
    `unroll=False` keeps the legacy one-iteration + FEEDBACK interpretation
    (the golden files pin that mode). `unroll_log` collects UnrollNote records
    for the UNROLL audit finding.
    """
    funcs = known_funcs if known_funcs is not None else frozenset(KNOWN_FUNCS)
    assigns: list[Assign] = []
    skipped: list[Skipped] = []
    try:
        toks = tokenize(src)
    except MatlabSyntaxError as exc:
        return [], [Skipped(exc.line, exc.message)]
    block_stack: list[str] = []  # 'for' | 'other'

    statements = split_statements(toks)
    if unroll:
        from pipeforge.core.frontend.loops import expand_constant_loops

        expansion = expand_constant_loops(statements)
        statements = expansion.statements
        skipped.extend(expansion.problems)
        if unroll_log is not None:
            unroll_log.extend(expansion.notes)

    for stmt in statements:
        first = stmt[0]
        line = first.line
        word = first.text if first.kind == "ID" else ""
        try:
            if word == "end":
                if block_stack:
                    block_stack.pop()
                else:
                    skipped.append(Skipped(line, "stray 'end'"))
                continue
            if word == "for":
                if len(stmt) < 4 or stmt[1].kind != "ID" or stmt[2].text != "=":
                    raise MatlabSyntaxError("malformed for header", line)
                p = ExprParser([*stmt[3:], Tok("EOF", "", line, 0, stmt[-1].pos)], src, funcs)
                p.parse_expr()
                if not p.done():
                    raise MatlabSyntaxError("malformed for header", line)
                block_stack.append("for")
                continue
            if word in ("if", "while", "elseif", "switch"):
                block_stack.append("other")
                skipped.append(Skipped(line, f"unsupported construct: {word}"))
                continue
            if word in ("else", "otherwise", "case"):
                skipped.append(Skipped(line, f"unsupported construct: {word}"))
                continue
            if word in ("function", "return", "break", "continue", "global", "persistent"):
                skipped.append(Skipped(line, f"unsupported construct: {word}"))
                continue

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
            target = lhs[0].text
            if indexed:
                lane = _const_index_target(lhs)
                if lane is not None:
                    target = lane  # y(2) = … defines the lane 'y(2)' (LN-1)
            rhs_toks = stmt[eq + 1 :]
            if not rhs_toks:
                raise MatlabSyntaxError("missing right-hand side", line)
            p = ExprParser(
                [*rhs_toks, Tok("EOF", "", line, 0, stmt[-1].pos + len(stmt[-1].text))],
                src,
                funcs,
            )
            rhs = p.parse_expr()
            if not p.done():
                t = p.peek()
                raise MatlabSyntaxError(f"unexpected token {t.text!r}", t.line)
            span = Span(stmt[0].pos, stmt[-1].pos + len(stmt[-1].text), line)
            assigns.append(Assign(target, indexed, rhs, line, span, in_loop="for" in block_stack))
        except MatlabSyntaxError as exc:
            skipped.append(Skipped(exc.line, exc.message))
    return assigns, skipped
