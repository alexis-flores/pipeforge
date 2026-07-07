"""Apply the auditor's findings as source-to-source rewrites (OP-1).

The findings engine produces mechanical rewrites (RECIP, CDIV, SERDIV, POW,
CSE); this module applies them to the MATLAB text itself, so the output is a
readable `.m` the user owns — not an opaque transformed graph. Untouched
statements keep their original text byte-for-byte (span surgery); rewritten
statements carry a `% pipeforge:` comment naming the rule.

Honesty contract: RECIP/CDIV/SERDIV/POW change fixed-point *rounding* (that
is where the cycles come from), so the result is numerically close but not
bit-identical. The report therefore states, per output, the worst
fixed-vs-fixed delta against the original and both versions' float-reference
SQNR — the optimized pipeline is usually *more* accurate (fewer sequential
roundings), but the numbers say so explicitly rather than asking for trust.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.ast import Bin, Expr, Num, Span, Var, canon
from pipeforge.core.frontend.parser import Assign, parse_program

_DIV_OPS = ("/", "./")


@dataclass(frozen=True)
class Rewrite:
    tag: str
    line: int
    description: str


@dataclass
class OutputAccuracy:
    name: str
    max_delta: float  # worst |optimized - original| (fixed vs fixed, as floats)
    sqnr_before_db: float  # float-reference SQNR of the original
    sqnr_after_db: float  # ... and of the optimized version


@dataclass
class OptimizeResult:
    source: str
    rewrites: list[Rewrite] = field(default_factory=list)
    latency_before: int = 0
    latency_after: int = 0
    dividers_before: int = 0  # RECIP/CDIV wins are often area (dividers), and
    dividers_after: int = 0  # can even *cost* latency when divisions ran in parallel
    accuracy: list[OutputAccuracy] = field(default_factory=list)
    note: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.rewrites)


# -- AST helpers -----------------------------------------------------------------


def _map_expr(e: Expr, fn: Callable[[Expr], Expr]) -> Expr:
    from pipeforge.core.frontend.ast import Call, Index, Mat, Trans, Un

    if isinstance(e, Bin):
        e = Bin(e.op, _map_expr(e.left, fn), _map_expr(e.right, fn), e.span)
    elif isinstance(e, Un):
        e = Un(e.op, _map_expr(e.operand, fn), e.span)
    elif isinstance(e, Trans):
        e = Trans(_map_expr(e.operand, fn), e.span)
    elif isinstance(e, Call):
        e = Call(e.name, tuple(_map_expr(a, fn) for a in e.args), e.span)
    elif isinstance(e, Index):
        e = Index(e.name, tuple(_map_expr(a, fn) for a in e.args), e.span)
    elif isinstance(e, Mat):
        e = Mat(tuple(_map_expr(x, fn) for x in e.elems), e.span)
    return fn(e)


def _count_subexprs(e: Expr, counts: dict[str, int]) -> None:
    from pipeforge.core.frontend.ast import Call, Trans, Un

    if isinstance(e, Bin) and e.op != ":":
        counts[canon(e)] = counts.get(canon(e), 0) + 1
        _count_subexprs(e.left, counts)
        _count_subexprs(e.right, counts)
    elif isinstance(e, (Un, Trans)):
        _count_subexprs(e.operand, counts)
    elif isinstance(e, Call):
        for a in e.args:
            _count_subexprs(a, counts)


def _num(value: float, span: Span) -> Num:
    return Num(value, span)


# -- the transform pipeline --------------------------------------------------------


@dataclass
class _Stmt:
    assign: Assign
    rhs: Expr
    changed: bool = False
    hoisted: list[tuple[str, Expr, str]] = field(default_factory=list)  # (name, expr, tag)


class _Optimizer:
    def __init__(self, assigns: list[Assign]) -> None:
        self.stmts = [_Stmt(a, a.rhs) for a in assigns]
        self.rewrites: list[Rewrite] = []
        self.counter = 0

    def _fresh(self, hint: str) -> str:
        self.counter += 1
        safe = re.sub(r"\W+", "", hint)[:12] or "t"
        return f"pf_{safe}_{self.counter}"

    # SERDIV: (a / b) / c  ->  a / (b * c): one divider instead of two in series
    def serdiv(self) -> None:
        for st in self.stmts:

            def rw(e: Expr, st: _Stmt = st) -> Expr:
                if (
                    isinstance(e, Bin)
                    and e.op in _DIV_OPS
                    and isinstance(e.left, Bin)
                    and e.left.op in _DIV_OPS
                ):
                    inner = e.left
                    merged = Bin(
                        "./",
                        inner.left,
                        Bin(".*", inner.right, e.right, e.span),
                        e.span,
                    )
                    st.changed = True
                    self.rewrites.append(
                        Rewrite(
                            "SERDIV",
                            st.assign.line,
                            f"{canon(e)} -> {canon(merged)} (one divider, not two in series)",
                        )
                    )
                    return merged
                return e

            st.rhs = _map_expr(st.rhs, rw)

    # RECIP: k>=2 divisions by the same non-constant divisor -> one 1/x + multiplies
    def recip(self) -> None:
        by_divisor: dict[str, int] = {}
        for st in self.stmts:

            def count(e: Expr) -> Expr:
                if isinstance(e, Bin) and e.op in _DIV_OPS and not isinstance(e.right, Num):
                    key = canon(e.right)
                    by_divisor[key] = by_divisor.get(key, 0) + 1
                return e

            _map_expr(st.rhs, count)
        shared = {k for k, n in by_divisor.items() if n >= 2}
        temps: dict[str, str] = {}
        for st in self.stmts:
            first_use = [k for k in shared if k not in temps]

            def rw(e: Expr, st: _Stmt = st, first_use: list[str] = first_use) -> Expr:
                if isinstance(e, Bin) and e.op in _DIV_OPS and not isinstance(e.right, Num):
                    key = canon(e.right)
                    if key not in shared:
                        return e
                    if key not in temps:
                        temp = self._fresh(key)
                        temps[key] = temp
                        st.hoisted.append(
                            (temp, Bin("./", _num(1.0, e.span), e.right, e.span), "RECIP")
                        )
                        self.rewrites.append(
                            Rewrite(
                                "RECIP",
                                st.assign.line,
                                f"compute {temp} = 1 ./ {key} once; "
                                f"{by_divisor[key]} divisions become multiplies",
                            )
                        )
                    st.changed = True
                    return Bin(".*", e.left, Var(temps[key], e.span), e.span)
                return e

            st.rhs = _map_expr(st.rhs, rw)

    # CDIV: division by a nonzero constant -> multiply by its reciprocal
    def cdiv(self) -> None:
        for st in self.stmts:

            def rw(e: Expr, st: _Stmt = st) -> Expr:
                if (
                    isinstance(e, Bin)
                    and e.op in _DIV_OPS
                    and isinstance(e.right, Num)
                    and e.right.value != 0.0
                ):
                    st.changed = True
                    self.rewrites.append(
                        Rewrite(
                            "CDIV",
                            st.assign.line,
                            f"{canon(e)} -> multiply by {1.0 / e.right.value!r} (no divider)",
                        )
                    )
                    return Bin(".*", e.left, _num(1.0 / e.right.value, e.span), e.span)
                return e

            st.rhs = _map_expr(st.rhs, rw)

    # POW: x^k (k>=3) -> binary exponentiation via hoisted squares
    def pow_(self) -> None:
        for st in self.stmts:

            def rw(e: Expr, st: _Stmt = st) -> Expr:
                if not (
                    isinstance(e, Bin)
                    and e.op in ("^", ".^")
                    and isinstance(e.right, Num)
                    and e.right.value == int(e.right.value)
                    and int(e.right.value) >= 3
                ):
                    return e
                k = int(e.right.value)
                base: Expr = e.left
                if not isinstance(base, (Var, Num)):
                    name = self._fresh(canon(base))
                    st.hoisted.append((name, base, "POW"))
                    base = Var(name, e.span)
                squares: list[Expr] = [base]
                while (1 << len(squares)) <= k:
                    prev = squares[-1]
                    name = self._fresh(f"{canon(base)}sq{len(squares)}")
                    st.hoisted.append((name, Bin(".*", prev, prev, e.span), "POW"))
                    squares.append(Var(name, e.span))
                terms = [squares[i] for i in range(len(squares)) if k & (1 << i)]
                result = terms[0]
                for t in terms[1:]:
                    result = Bin(".*", result, t, e.span)
                st.changed = True
                naive = k - 1
                used = len(squares) - 1 + len(terms) - 1
                self.rewrites.append(
                    Rewrite(
                        "POW",
                        st.assign.line,
                        f"{canon(e)}: binary exponentiation ({used} multiplies instead of {naive})",
                    )
                )
                return result

            st.rhs = _map_expr(st.rhs, rw)

    # CSE: a composite subexpression computed in >=2 statements -> hoist once
    def cse(self) -> None:
        counts: dict[str, int] = {}
        for st in self.stmts:
            _count_subexprs(st.rhs, counts)
        # largest first so nested repeats collapse into the outermost hoist
        shared = sorted((k for k, n in counts.items() if n >= 2), key=len, reverse=True)
        temps: dict[str, str] = {}
        for key in shared:
            if any(key != other and key in other for other in temps):
                continue  # already inside a hoisted larger expression
            for st in self.stmts:
                hit: list[Expr] = []

                def find(e: Expr, key: str = key, hit: list[Expr] = hit) -> Expr:
                    if isinstance(e, Bin) and canon(e) == key and not hit:
                        hit.append(e)
                    return e

                _map_expr(st.rhs, find)
                if not hit:
                    continue
                if key not in temps:
                    name = self._fresh(key)
                    temps[key] = name
                    st.hoisted.append((name, hit[0], "CSE"))
                    self.rewrites.append(
                        Rewrite(
                            "CSE",
                            st.assign.line,
                            f"{key} computed {counts[key]}x — hoisted as {name}",
                        )
                    )
                temp = temps[key]

                def rw(e: Expr, key: str = key, temp: str = temp) -> Expr:
                    if isinstance(e, Bin) and canon(e) == key:
                        return Var(temp, e.span)
                    return e

                new_rhs = _map_expr(st.rhs, rw)
                if canon(new_rhs) != canon(st.rhs):
                    st.rhs = new_rhs
                    st.changed = True


# -- source surgery ------------------------------------------------------------------


def _render(src: str, stmts: list[_Stmt]) -> str:
    """Rebuild the source: rewritten statements replaced in place, hoisted
    temps inserted on the lines above them, everything else byte-identical."""
    edits: list[tuple[int, int, str]] = []  # (start, end, replacement)
    for st in stmts:
        if not st.changed and not st.hoisted:
            continue
        span = st.assign.span
        line_start = src.rfind("\n", 0, span.start) + 1
        indent = src[line_start : span.start]
        indent = indent if indent.strip() == "" else ""
        prefix = "".join(
            f"{indent}{name} = {canon(expr)}; % pipeforge: {tag}\n"
            for name, expr, tag in st.hoisted
        )
        end = span.end
        if st.changed and end < len(src) and src[end] == ";":
            end += 1  # swallow the trailing ';' so the comment lands after it
            stmt_text = f"{st.assign.target} = {canon(st.rhs)}; % pipeforge: rewritten"
        elif st.changed:
            stmt_text = f"{st.assign.target} = {canon(st.rhs)} % pipeforge: rewritten"
        else:
            stmt_text = src[span.start : span.end]
        edits.append((line_start, end, f"{prefix}{indent}{stmt_text}"))
    out = src
    for start, end, text in sorted(edits, reverse=True):
        # the original tail after the span (e.g. the trailing ';') is preserved
        out = out[:start] + text + out[end:]
    return out


# -- accuracy comparison ----------------------------------------------------------------


def _compare(src_before: str, src_after: str, cm: CostModel, vectors: int) -> list[OutputAccuracy]:
    import random

    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.fxp.evaluator import error_stats, evaluate_fixed, evaluate_float
    from pipeforge.core.fxp.fx import FxFormat, to_float

    before = audit_source(src_before, "before.m", cm)
    after = audit_source(src_after, "after.m", cm)
    fmt = FxFormat(cm.width, cm.scale)
    outs_before = {n.signal: n.nid for n in before.dag.outputs() if n.signal}
    outs_after = {n.signal: n.nid for n in after.dag.outputs() if n.signal}
    common = sorted(set(outs_before) & set(outs_after))
    inputs = sorted({n.label for n in before.dag.inputs()})
    rng = random.Random(7)
    state_bx: dict[str, list[int]] = {}
    state_ax: dict[str, list[int]] = {}
    state_bf: dict[str, list[float]] = {}
    deltas: dict[str, float] = dict.fromkeys(common, 0.0)
    ref: dict[str, list[float]] = {k: [] for k in common}
    meas_b: dict[str, list[float]] = {k: [] for k in common}
    meas_a: dict[str, list[float]] = {k: [] for k in common}
    for _ in range(vectors):
        vec = {name: rng.uniform(-1.0, 1.0) for name in inputs}
        vb = evaluate_fixed(before.dag, dict(vec), fmt, state=state_bx)
        va = evaluate_fixed(after.dag, dict(vec), fmt, state=state_ax)
        fb = evaluate_float(before.dag, dict(vec), fmt, state=state_bf)
        for name in common:
            b = to_float(vb[outs_before[name]][0], fmt)
            a = to_float(va[outs_after[name]][0], fmt)
            deltas[name] = max(deltas[name], abs(a - b))
            ref[name].append(fb[outs_before[name]][0])
            meas_b[name].append(b)
            meas_a[name].append(a)
    out = []
    for name in common:
        out.append(
            OutputAccuracy(
                name=name,
                max_delta=deltas[name],
                sqnr_before_db=error_stats(ref[name], meas_b[name]).sqnr_db,
                sqnr_after_db=error_stats(ref[name], meas_a[name]).sqnr_db,
            )
        )
    return out


def optimize_source(src: str, cm: CostModel, vectors: int = 64) -> OptimizeResult:
    """Apply RECIP/CDIV/SERDIV/POW/CSE rewrites to MATLAB source (OP-1).

    Operates on the script's own statements (local function bodies are left
    as written — their calls still inline at audit time). Returns the original
    source unchanged when nothing applies or when the rewrite would not
    actually reduce the critical path.
    """
    from pipeforge.core.audit.engine import audit_source

    assigns, _skipped = parse_program(src)
    opt = _Optimizer(assigns)
    opt.serdiv()
    opt.recip()
    opt.cdiv()
    opt.pow_()
    opt.cse()
    result = OptimizeResult(source=src, rewrites=opt.rewrites)
    before = audit_source(src, "before.m", cm)
    result.latency_before = result.latency_after = before.total_latency
    result.dividers_before = result.dividers_after = before.divider_count
    if not opt.rewrites:
        result.note = "no applicable rewrites"
        return result
    new_src = _render(src, opt.stmts)
    after = audit_source(new_src, "after.m", cm)
    if len(after.skipped) > len(before.skipped):
        result.rewrites = []
        result.note = "rewritten source failed to re-parse cleanly; keeping the original"
        return result
    result.source = new_src
    result.latency_after = after.total_latency
    result.dividers_after = after.divider_count
    result.accuracy = _compare(src, new_src, cm, vectors)
    return result
