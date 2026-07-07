"""Constant-bound loop unrolling (LP-1).

A `for` loop with a compile-time trip count is not control flow in a streaming
pipeline — it is *structure*: N iterations are N copies in space. This module
expands such loops at the token level (before statement parsing), substituting
the loop variable with each iteration's literal, so the whole toolchain —
audit, ranges, codegen, cosim, optimize — sees the true dataflow.

Loops that cannot unroll (non-constant bounds, over-budget trip counts) pass
through untouched and keep the legacy interpretation: one analyzed iteration
plus the FEEDBACK recurrence finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeforge.core.frontend.lexer import Tok
from pipeforge.core.frontend.parser import Skipped

MAX_ITERATIONS = 1024  # per loop
MAX_STATEMENTS = 10_000  # total after expansion (gen500 is 500; 20x headroom)

_BLOCK_OPENERS = ("for", "if", "while", "switch")


@dataclass
class UnrollNote:
    line: int
    var: str
    count: int


@dataclass
class ExpandResult:
    statements: list[list[Tok]]
    notes: list[UnrollNote] = field(default_factory=list)
    problems: list[Skipped] = field(default_factory=list)


def _num_at(stmt: list[Tok], i: int) -> tuple[int, int] | None:
    """Parse an optionally-negated integer literal at stmt[i]; (value, next_i)."""
    sign = 1
    if i < len(stmt) and stmt[i].kind == "OP" and stmt[i].text == "-":
        sign = -1
        i += 1
    if i < len(stmt) and stmt[i].kind == "NUM":
        try:
            v = float(stmt[i].text)
        except ValueError:
            return None
        if v != int(v):
            return None
        return sign * int(v), i + 1
    return None


def constant_header(stmt: list[Tok]) -> tuple[str, list[int]] | None:
    """`for i = a:b` or `for i = a:s:b` with integer literals -> (var, values)."""
    if len(stmt) < 6 or stmt[0].text != "for" or stmt[1].kind != "ID" or stmt[2].text != "=":
        return None
    var = stmt[1].text
    first = _num_at(stmt, 3)
    if first is None:
        return None
    start, i = first
    if i >= len(stmt) or stmt[i].text != ":":
        return None
    second = _num_at(stmt, i + 1)
    if second is None:
        return None
    mid, i = second
    if i == len(stmt):  # a:b
        step, stop = 1, mid
    elif stmt[i].text == ":":  # a:s:b
        third = _num_at(stmt, i + 1)
        if third is None:
            return None
        step = mid
        stop, i = third
        if i != len(stmt):
            return None
    else:
        return None
    if step == 0:
        return None
    values = list(range(start, stop + (1 if step > 0 else -1), step))
    return var, values


def _substitute(stmts: list[list[Tok]], var: str, value: int) -> list[list[Tok]]:
    """Replace loop-variable IDs with the iteration literal.

    Skips struct-field positions (`a.i`) and regions where an inner loop
    shadows the same variable name.
    """
    out: list[list[Tok]] = []
    shadow = 0
    for stmt in stmts:
        word = stmt[0].text if stmt and stmt[0].kind == "ID" else ""
        if shadow:
            if word in _BLOCK_OPENERS:
                shadow += 1
            elif word == "end":
                shadow -= 1
            out.append(list(stmt))
            continue
        if word == "for" and len(stmt) > 1 and stmt[1].kind == "ID" and stmt[1].text == var:
            shadow = 1  # the inner loop redefines var: leave its region alone
            out.append(list(stmt))
            continue
        new: list[Tok] = []
        for k, t in enumerate(stmt):
            after_dot = k > 0 and stmt[k - 1].kind == "OP" and stmt[k - 1].text == "."
            if t.kind == "ID" and t.text == var and not after_dot:
                new.append(Tok("NUM", str(value), t.line, t.col, t.pos))
            else:
                new.append(t)
        out.append(new)
    return out


def _find_end(stmts: list[list[Tok]], start: int) -> int | None:
    """Index of the `end` statement matching the block opener at `start`."""
    depth = 1
    j = start + 1
    while j < len(stmts):
        word = stmts[j][0].text if stmts[j] and stmts[j][0].kind == "ID" else ""
        if word in _BLOCK_OPENERS:
            depth += 1
        elif word == "end":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return None


def expand_constant_loops(stmts: list[list[Tok]], budget: int = MAX_STATEMENTS) -> ExpandResult:
    """Unroll every constant-bound `for` (recursively; nested loops multiply)."""
    result = ExpandResult(statements=[])
    i = 0
    while i < len(stmts):
        stmt = stmts[i]
        word = stmt[0].text if stmt and stmt[0].kind == "ID" else ""
        header = constant_header(stmt) if word == "for" else None
        if header is None:
            result.statements.append(stmt)
            i += 1
            continue
        end_idx = _find_end(stmts, i)
        if end_idx is None:  # malformed: let the parser report it
            result.statements.append(stmt)
            i += 1
            continue
        var, values = header
        body = stmts[i + 1 : end_idx]
        if len(values) > MAX_ITERATIONS:
            result.problems.append(
                Skipped(
                    stmt[0].line,
                    f"loop over {len(values)} iterations exceeds the unroll budget "
                    f"({MAX_ITERATIONS}); analyzed as a recurrence instead",
                )
            )
            result.statements.extend(stmts[i : end_idx + 1])  # legacy path
            i = end_idx + 1
            continue
        expanded: list[list[Tok]] = []
        overflow = False
        for value in values:
            inner = expand_constant_loops(_substitute(body, var, value), budget)
            result.notes.extend(inner.notes)
            result.problems.extend(inner.problems)
            expanded.extend(inner.statements)
            if len(result.statements) + len(expanded) > budget:
                overflow = True
                break
        if overflow:
            result.problems.append(
                Skipped(
                    stmt[0].line,
                    f"unrolling exceeds the statement budget ({budget}); "
                    "analyzed as a recurrence instead",
                )
            )
            result.statements.extend(stmts[i : end_idx + 1])
        else:
            result.notes.append(UnrollNote(stmt[0].line, var, len(values)))
            result.statements.extend(expanded)
        i = end_idx + 1
    return result
