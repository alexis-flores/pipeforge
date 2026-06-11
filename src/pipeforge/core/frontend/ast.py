"""MATLAB expression AST with exact source spans (FE-1, FE-4)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """Exact character range of an AST node in the original source (FE-4)."""

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
class Field:
    """Struct-field access, e.g. ``cfg.gains.kp`` (grammar extension).

    ``base`` is the root variable; ``path`` the field chain. The dotted
    name is the canonical/lookup key; a live MATLAB snapshot can resolve
    its type and value.
    """

    base: str
    path: tuple[str, ...]
    span: Span

    @property
    def dotted(self) -> str:
        return ".".join((self.base, *self.path))


@dataclass(frozen=True)
class Index:
    """Array-index atom, e.g. ``n(:,1)`` — treated as an opaque operand."""

    name: str
    args: tuple[Expr, ...]
    span: Span


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Expr, ...]
    span: Span


@dataclass(frozen=True)
class Bin:
    op: str
    left: Expr
    right: Expr
    span: Span


@dataclass(frozen=True)
class Un:
    op: str
    operand: Expr
    span: Span


@dataclass(frozen=True)
class Trans:
    operand: Expr
    span: Span


@dataclass(frozen=True)
class Mat:
    elems: tuple[Expr, ...]
    span: Span


Expr = Num | Var | ColonAtom | Str | Field | Index | Call | Bin | Un | Trans | Mat


def canon(e: Expr) -> str:
    """Canonical text of an expression; the key for CSE/RECIP grouping."""
    if isinstance(e, Num):
        v = e.value
        return str(int(v)) if v == int(v) else repr(v)
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Field):
        return e.dotted
    if isinstance(e, ColonAtom):
        return ":"
    if isinstance(e, Str):
        return e.text
    if isinstance(e, (Index, Call)):
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


def expr_vars(e: Expr) -> set[str]:
    """All variable names referenced by an expression (def-use links, FE-2)."""
    out: set[str] = set()
    if isinstance(e, Var):
        out.add(e.name)
    elif isinstance(e, Field):
        out.add(e.base)  # def-use tracks the root struct variable
    elif isinstance(e, Index):
        out.add(e.name.split(".")[0])  # dotted-indexed: root variable
        for a in e.args:
            out |= expr_vars(a)
    elif isinstance(e, Call):
        for a in e.args:
            out |= expr_vars(a)
    elif isinstance(e, Bin):
        out |= expr_vars(e.left) | expr_vars(e.right)
    elif isinstance(e, (Un, Trans)):
        out |= expr_vars(e.operand)
    elif isinstance(e, Mat):
        for x in e.elems:
            out |= expr_vars(x)
    return out
