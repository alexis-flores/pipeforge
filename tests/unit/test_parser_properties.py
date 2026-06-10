"""Property-based parser tests (Phase 1 gate): canonical round-trip."""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from pipeforge.core.frontend.ast import canon
from pipeforge.core.frontend.parser import parse_program

_names = st.sampled_from(["x", "y", "z", "alpha", "b2", "n", "acc"])
_numbers = st.integers(min_value=0, max_value=999).map(float)


def _exprs(depth: int = 3) -> st.SearchStrategy[str]:
    leaf = st.one_of(
        _names,
        _numbers.map(lambda v: str(int(v))),
        _names.map(lambda n: f"sqrt({n})"),
        _names.map(lambda n: f"abs({n})"),
    )
    if depth == 0:
        return leaf
    sub = _exprs(depth - 1)
    binop = st.sampled_from(["+", "-", ".*", "./", "*", "/"])
    return st.one_of(
        leaf,
        st.tuples(sub, binop, sub).map(lambda t: f"({t[0]} {t[1]} {t[2]})"),
        sub.map(lambda e: f"(-{e})"),
    )


@given(_exprs())
@settings(max_examples=300, deadline=None)
def test_parse_canon_roundtrip_is_stable(expr: str) -> None:
    """canon(parse(e)) is a fixed point: parsing its own output reproduces it."""
    assigns1, skipped1 = parse_program(f"q = {expr};")
    assert not skipped1
    c1 = canon(assigns1[0].rhs)
    assigns2, skipped2 = parse_program(f"q = {c1};")
    assert not skipped2
    assert canon(assigns2[0].rhs) == c1


@given(_exprs())
@settings(max_examples=200, deadline=None)
def test_parser_never_crashes(expr: str) -> None:
    parse_program(f"q = {expr};\nr = q + 1;")
