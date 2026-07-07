"""MATLAB local functions, inlined at call sites (FN-1).

Scripts may define local functions after the script body (standard MATLAB
since R2016b). Each call is inlined hygienically: actuals bind to fresh
prefixed parameter assignments, the body's statements are emitted with every
local renamed, and the call expression becomes the (first) output variable.
Every inlined statement carries the *call site's* line, so findings and the
timeline attribute costs where the user wrote the call.

Deliberate v1 limits, each reported per-statement (FE-3 style, never fatal):
single-output value is used (MATLAB expression-call semantics), bodies must
be self-contained (no globals), recursion is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pipeforge.core.costmodel.model import KNOWN_FUNCS
from pipeforge.core.frontend.ast import (
    Bin,
    Call,
    ColonAtom,
    Expr,
    Field,
    Index,
    Mat,
    Num,
    Str,
    Trans,
    Un,
    Var,
    expr_vars,
)
from pipeforge.core.frontend.parser import Assign, Skipped, parse_program

if TYPE_CHECKING:
    from pipeforge.core.frontend.loops import UnrollNote

MAX_INLINE_DEPTH = 16

_HEADER_RE = re.compile(
    r"^\s*function\s+(?:\[(?P<outs>[^\]]*)\]|(?P<out>\w+))\s*=\s*"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*$"
)
_BLOCK_OPENERS = ("for", "if", "while", "switch", "function")


class InlineError(ValueError):
    def __init__(self, message: str, line: int) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass
class FunctionDef:
    name: str
    params: list[str]
    outs: list[str]
    line: int  # header line (1-based)
    body: list[Assign] = field(default_factory=list)
    body_problems: list[Skipped] = field(default_factory=list)


def _first_word(line: str) -> str:
    stripped = line.strip()
    m = re.match(r"[A-Za-z_]\w*", stripped)
    return m.group(0) if m else ""


def extract_functions(
    src: str, unroll: bool = True, unroll_log: list[UnrollNote] | None = None
) -> tuple[str, dict[str, FunctionDef], list[Skipped]]:
    """Split a script into (script part, local functions, problems).

    Function regions are blanked (not removed) so the script part keeps its
    original line numbers for spans and findings.
    """
    lines = src.splitlines()
    out_lines = list(lines)
    funcs: dict[str, FunctionDef] = {}
    problems: list[Skipped] = []
    i = 0
    while i < len(lines):
        if _first_word(lines[i]) != "function":
            i += 1
            continue
        header_line = i
        m = _HEADER_RE.match(lines[i])
        # find the matching `end` (function bodies may contain for/if blocks)
        depth = 1
        j = i + 1
        while j < len(lines) and depth > 0:
            word = _first_word(lines[j])
            if word in _BLOCK_OPENERS:
                depth += 1
            elif word == "end":
                depth -= 1
            j += 1
        if depth != 0:
            problems.append(Skipped(header_line + 1, "function without a matching 'end'"))
            for k in range(header_line, len(lines)):
                out_lines[k] = ""
            break
        for k in range(header_line, j):
            out_lines[k] = ""
        if m is None:
            problems.append(
                Skipped(
                    header_line + 1,
                    "unsupported function header (need 'function out = name(args)')",
                )
            )
        else:
            outs_raw = m.group("outs")
            outs = (
                [o.strip() for o in outs_raw.split(",") if o.strip()]
                if outs_raw is not None
                else [m.group("out")]
            )
            params = [p.strip() for p in m.group("params").split(",") if p.strip()]
            funcs[m.group("name")] = FunctionDef(
                name=m.group("name"), params=params, outs=outs, line=header_line + 1
            )
        i = j
    # parse bodies once, with every user function callable from every body
    known = frozenset(KNOWN_FUNCS) | set(funcs)
    for fn in funcs.values():
        start = fn.line  # body begins on the line after the header
        # re-pad so body line numbers report near the definition (best effort)
        body_src = "\n" * start + _body_text_of(src, fn)
        fn.body, fn.body_problems = parse_program(
            body_src, known_funcs=known, unroll=unroll, unroll_log=unroll_log
        )
    return "\n".join(out_lines), funcs, problems


def _body_text_of(src: str, fn: FunctionDef) -> str:
    """The body text between the header and its matching end (re-derived)."""
    lines = src.splitlines()
    depth = 1
    j = fn.line  # 0-based index of the line after the header
    start = j
    while j < len(lines) and depth > 0:
        word = _first_word(lines[j])
        if word in _BLOCK_OPENERS:
            depth += 1
        elif word == "end":
            depth -= 1
        j += 1
    return "\n".join(lines[start : j - 1])


def _rename(e: Expr, mapping: dict[str, str]) -> Expr:
    if isinstance(e, Var):
        return Var(mapping.get(e.name, e.name), e.span)
    if isinstance(e, Field):
        return Field(mapping.get(e.base, e.base), e.path, e.span)
    if isinstance(e, Index):
        root, _, rest = e.name.partition(".")
        new_root = mapping.get(root, root)
        name = f"{new_root}.{rest}" if rest else new_root
        return Index(name, tuple(_rename(a, mapping) for a in e.args), e.span)
    if isinstance(e, Call):
        return Call(e.name, tuple(_rename(a, mapping) for a in e.args), e.span)
    if isinstance(e, Bin):
        return Bin(e.op, _rename(e.left, mapping), _rename(e.right, mapping), e.span)
    if isinstance(e, Un):
        return Un(e.op, _rename(e.operand, mapping), e.span)
    if isinstance(e, Trans):
        return Trans(_rename(e.operand, mapping), e.span)
    if isinstance(e, Mat):
        return Mat(tuple(_rename(x, mapping) for x in e.elems), e.span)
    if isinstance(e, (Num, ColonAtom, Str)):
        return e
    raise TypeError(f"unknown expr: {e!r}")


class _Inliner:
    def __init__(self, funcs: dict[str, FunctionDef]) -> None:
        self.funcs = funcs
        self.counter = 0

    def expand_assign(self, a: Assign, depth: int = 0) -> list[Assign]:
        pre: list[Assign] = []
        rhs = self._expand_expr(a.rhs, a, pre, depth)
        return [*pre, Assign(a.target, a.indexed, rhs, a.line, a.span, a.in_loop)]

    def _expand_expr(self, e: Expr, site: Assign, pre: list[Assign], depth: int) -> Expr:
        if isinstance(e, Call) and e.name in self.funcs:
            return self._inline_call(e, site, pre, depth)
        if isinstance(e, Call):
            return Call(
                e.name,
                tuple(self._expand_expr(x, site, pre, depth) for x in e.args),
                e.span,
            )
        if isinstance(e, Bin):
            return Bin(
                e.op,
                self._expand_expr(e.left, site, pre, depth),
                self._expand_expr(e.right, site, pre, depth),
                e.span,
            )
        if isinstance(e, Un):
            return Un(e.op, self._expand_expr(e.operand, site, pre, depth), e.span)
        if isinstance(e, Trans):
            return Trans(self._expand_expr(e.operand, site, pre, depth), e.span)
        if isinstance(e, Mat):
            return Mat(tuple(self._expand_expr(x, site, pre, depth) for x in e.elems), e.span)
        if isinstance(e, Index):
            return Index(
                e.name,
                tuple(self._expand_expr(a, site, pre, depth) for a in e.args),
                e.span,
            )
        return e

    def _inline_call(self, call: Call, site: Assign, pre: list[Assign], depth: int) -> Expr:
        if depth >= MAX_INLINE_DEPTH:
            raise InlineError(
                f"function '{call.name}': inlining exceeds depth {MAX_INLINE_DEPTH} "
                "(recursive functions are not supported)",
                site.line,
            )
        fn = self.funcs[call.name]
        if fn.body_problems:
            first = fn.body_problems[0]
            raise InlineError(
                f"function '{fn.name}' (line {fn.line}) has unsupported statements: {first.reason}",
                site.line,
            )
        if len(call.args) != len(fn.params):
            raise InlineError(
                f"function '{fn.name}' takes {len(fn.params)} argument(s), got {len(call.args)}",
                site.line,
            )
        locals_: set[str] = set(fn.params) | {b.target for b in fn.body}
        if fn.outs[0] not in locals_:
            raise InlineError(
                f"function '{fn.name}' never assigns its output '{fn.outs[0]}'", site.line
            )
        for b in fn.body:
            free = expr_vars(b.rhs) - locals_
            if free:
                raise InlineError(
                    f"function '{fn.name}' uses undefined variable(s): "
                    f"{', '.join(sorted(free))} (bodies must be self-contained)",
                    site.line,
                )
        self.counter += 1
        prefix = f"{fn.name}_x{self.counter}"
        mapping = {name: f"{prefix}_{name}" for name in locals_}
        # bind actuals (already expanded by the caller's post-order walk)
        for param, arg in zip(fn.params, call.args, strict=True):
            arg_expanded = self._expand_expr(arg, site, pre, depth)
            pre.append(
                Assign(mapping[param], False, arg_expanded, site.line, call.span, site.in_loop)
            )
        # body, renamed, at the call site's line — nested calls inline recursively
        for b in fn.body:
            renamed = Assign(
                mapping[b.target],
                b.indexed,
                _rename(b.rhs, mapping),
                site.line,
                call.span,
                site.in_loop or b.in_loop,
            )
            pre.extend(self.expand_assign(renamed, depth + 1))
        return Var(mapping[fn.outs[0]], call.span)


def parse_with_functions(
    src: str, unroll: bool = True, unroll_log: list[UnrollNote] | None = None
) -> tuple[list[Assign], list[Skipped]]:
    """parse_program plus local-function extraction and call-site inlining (FN-1)."""
    script_src, funcs, problems = extract_functions(src, unroll=unroll, unroll_log=unroll_log)
    if not funcs:
        assigns, skipped = parse_program(src, unroll=unroll, unroll_log=unroll_log)
        return assigns, sorted([*skipped, *problems], key=lambda s: s.line)
    known = frozenset(KNOWN_FUNCS) | set(funcs)
    assigns, skipped = parse_program(
        script_src, known_funcs=known, unroll=unroll, unroll_log=unroll_log
    )
    inliner = _Inliner(funcs)
    out: list[Assign] = []
    extra: list[Skipped] = []
    for a in assigns:
        try:
            out.extend(inliner.expand_assign(a))
        except InlineError as exc:
            extra.append(Skipped(exc.line, exc.message))
    return out, sorted([*skipped, *problems, *extra], key=lambda s: s.line)
