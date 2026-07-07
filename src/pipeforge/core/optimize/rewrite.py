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

#: value-identity signature: (canonical text, ((var, def-version), ...))
Sig = tuple[str, tuple[tuple[str, int], ...]]


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


def _balance_terms(terms: list[Expr], span: Span) -> Expr:
    """Pairwise-fold terms into a balanced '+' tree (depth ceil(log2 n))."""
    level = list(terms)
    while len(level) > 1:
        nxt: list[Expr] = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(Bin("+", level[i], level[i + 1], span))
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0]


def subst_var(e: Expr, var: str, value: int) -> Expr:
    """Replace Var(var) with the literal (loop-iteration substitution)."""

    def rw(x: Expr) -> Expr:
        if isinstance(x, Var) and x.name == var:
            return Num(float(value), x.span)
        return x

    return _map_expr(e, rw)


def balance_loops(src: str) -> tuple[str, list[Rewrite]]:
    """LP-2: replace constant accumulator loops with balanced adder trees.

    ``for k = a:b; T = T + <expr(k)>; end`` becomes pairwise partial-sum
    statements plus one final ``T = T + <root>`` — the running sum's chain
    depth drops from N adds to ceil(log2 N) + 1, and wrap addition makes the
    reassociation bit-exact. Loops that do not match the pattern are left
    for the frontend unroller (they still become correct chains).
    """
    from pipeforge.core.costmodel.model import KNOWN_FUNCS
    from pipeforge.core.frontend.ast import expr_vars
    from pipeforge.core.frontend.lexer import MatlabSyntaxError, Tok, tokenize
    from pipeforge.core.frontend.loops import MAX_ITERATIONS, _find_end, constant_header
    from pipeforge.core.frontend.parser import ExprParser, split_statements

    try:
        toks = tokenize(src)
    except MatlabSyntaxError:
        return src, []
    stmts = split_statements(toks)
    rewrites: list[Rewrite] = []
    edits: list[tuple[int, int, str]] = []
    i = 0
    counter = 0
    while i < len(stmts):
        stmt = stmts[i]
        word = stmt[0].text if stmt and stmt[0].kind == "ID" else ""
        header = constant_header(stmt) if word == "for" else None
        if header is None:
            i += 1
            continue
        end_idx = _find_end(stmts, i)
        if end_idx is None:
            i += 1
            continue
        var, values = header
        body = stmts[i + 1 : end_idx]
        i_next = end_idx + 1
        if len(body) != 1 or not (2 <= len(values) <= MAX_ITERATIONS):
            i = i_next
            continue
        # body must be exactly:  T = T + <expr>   (or  T = <expr> + T)
        b = body[0]
        if len(b) < 3 or b[0].kind != "ID" or b[1].text != "=":
            i = i_next
            continue
        target = b[0].text
        parser = ExprParser(
            [*b[2:], Tok("EOF", "", b[0].line, 0, b[-1].pos)], src, frozenset(KNOWN_FUNCS)
        )
        try:
            rhs = parser.parse_expr()
        except MatlabSyntaxError:
            i = i_next
            continue
        if not (isinstance(rhs, Bin) and rhs.op == "+"):
            i = i_next
            continue
        if isinstance(rhs.left, Var) and rhs.left.name == target:
            term = rhs.right
        elif isinstance(rhs.right, Var) and rhs.right.name == target:
            term = rhs.left
        else:
            i = i_next
            continue
        if target in expr_vars(term):
            i = i_next
            continue
        counter += 1
        terms = [subst_var(term, var, v) for v in values]
        # emit pairwise partial sums as named statements, then fold into T
        lines: list[str] = []
        level: list[str] = [canon(t) for t in terms]
        depth = 0
        while len(level) > 1:
            depth += 1
            nxt: list[str] = []
            for j in range(0, len(level) - 1, 2):
                name = f"pf_bal{counter}_{depth}_{j // 2}"
                lines.append(f"{name} = {level[j]} + {level[j + 1]}; % pipeforge: BALANCE")
                nxt.append(name)
            if len(level) % 2:
                nxt.append(level[-1])
            level = nxt
        lines.append(f"{target} = {target} + {level[0]}; % pipeforge: BALANCE")
        region_start = src.rfind("\n", 0, stmt[0].pos) + 1
        region_end = stmts[end_idx][-1].pos + len(stmts[end_idx][-1].text)
        import math

        rewrites.append(
            Rewrite(
                "BALANCE",
                stmt[0].line,
                f"accumulator loop over {len(values)} terms -> balanced adder tree "
                f"(depth {math.ceil(math.log2(len(values)))} + 1, was {len(values)}; "
                "bit-exact for wrap addition)",
            )
        )
        edits.append((region_start, region_end, "\n".join(lines)))
        i = i_next
    out = src
    for start, end, text in sorted(edits, reverse=True):
        out = out[:start] + text + out[end:]
    return out, rewrites


# -- the transform pipeline --------------------------------------------------------


@dataclass
class _Stmt:
    assign: Assign
    rhs: Expr
    changed: bool = False
    idx: int = 0
    frozen: bool = False  # unrolled iterations share one source span (LP-1):
    # rewriting one would rewrite the loop body for *all* iterations — skip
    hoisted: list[tuple[str, Expr, str]] = field(default_factory=list)  # (name, expr, tag)


class _Optimizer:
    def __init__(self, assigns: list[Assign]) -> None:
        self.stmts = [_Stmt(a, a.rhs, idx=i) for i, a in enumerate(assigns)]
        span_counts: dict[tuple[int, int], int] = {}
        for st in self.stmts:
            key = (st.assign.span.start, st.assign.span.end)
            span_counts[key] = span_counts.get(key, 0) + 1
        for st in self.stmts:
            st.frozen = span_counts[(st.assign.span.start, st.assign.span.end)] > 1
        # def-versions per statement: the same spelling ('n') after a
        # reassignment is a *different* value — RECIP/CSE must not merge
        # occurrences across a redefinition of any referenced variable
        self.versions: list[dict[str, int]] = []
        current: dict[str, int] = {}
        for st in self.stmts:
            self.versions.append(dict(current))
            current[st.assign.target] = current.get(st.assign.target, 0) + 1
        self.rewrites: list[Rewrite] = []
        self.counter = 0

    def _active(self) -> list[_Stmt]:
        return [st for st in self.stmts if not st.frozen]

    def _sig(self, st: _Stmt, e: Expr) -> Sig:
        """Value-identity signature of an expression at a statement: its text
        plus the def-version of every variable it reads."""
        from pipeforge.core.frontend.ast import expr_vars

        versions = self.versions[st.idx]
        return (canon(e), tuple(sorted((v, versions.get(v, 0)) for v in expr_vars(e))))

    def _fresh(self, hint: str) -> str:
        self.counter += 1
        safe = re.sub(r"\W+", "", hint)[:12] or "t"
        return f"pf_{safe}_{self.counter}"

    # SERDIV: (a / b) / c  ->  a / (b * c): one divider instead of two in series
    def serdiv(self) -> None:
        for st in self._active():

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
        by_divisor: dict[Sig, int] = {}
        for st in self._active():

            def count(e: Expr, st: _Stmt = st) -> Expr:
                if isinstance(e, Bin) and e.op in _DIV_OPS and not isinstance(e.right, Num):
                    key = self._sig(st, e.right)
                    by_divisor[key] = by_divisor.get(key, 0) + 1
                return e

            _map_expr(st.rhs, count)
        shared = {k for k, n in by_divisor.items() if n >= 2}
        temps: dict[Sig, str] = {}
        for st in self._active():

            def rw(e: Expr, st: _Stmt = st) -> Expr:
                if isinstance(e, Bin) and e.op in _DIV_OPS and not isinstance(e.right, Num):
                    key = self._sig(st, e.right)
                    if key not in shared:
                        return e
                    if key not in temps:
                        temp = self._fresh(key[0])
                        temps[key] = temp
                        st.hoisted.append(
                            (temp, Bin("./", _num(1.0, e.span), e.right, e.span), "RECIP")
                        )
                        self.rewrites.append(
                            Rewrite(
                                "RECIP",
                                st.assign.line,
                                f"compute {temp} = 1 ./ {key[0]} once; "
                                f"{by_divisor[key]} divisions become multiplies",
                            )
                        )
                    st.changed = True
                    return Bin(".*", e.left, Var(temps[key], e.span), e.span)
                return e

            st.rhs = _map_expr(st.rhs, rw)

    # CDIV: division by a nonzero constant -> multiply by its reciprocal
    def cdiv(self) -> None:
        for st in self._active():

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
        for st in self._active():

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
        counts: dict[Sig, int] = {}
        for st in self._active():
            local: dict[str, int] = {}
            _count_subexprs(st.rhs, local)
            for text, n in local.items():
                # signature = text + def-versions: reassignment splits groups
                key = (text, self._sig_text(st, text))
                counts[key] = counts.get(key, 0) + n
        # largest first so nested repeats collapse into the outermost hoist
        shared = sorted(
            (k for k, n in counts.items() if n >= 2), key=lambda k: len(k[0]), reverse=True
        )
        temps: dict[Sig, str] = {}
        for key in shared:
            text = key[0]
            if any(key != other and text in other[0] for other in temps):
                continue  # already inside a hoisted larger expression
            for st in self._active():
                hit: list[Expr] = []

                def find(e: Expr, st: _Stmt = st, key: Sig = key, hit: list[Expr] = hit) -> Expr:
                    if (
                        isinstance(e, Bin)
                        and not hit
                        and canon(e) == key[0]
                        and self._sig_text(st, canon(e), e) == key[1]
                    ):
                        hit.append(e)
                    return e

                _map_expr(st.rhs, find)
                if not hit:
                    continue
                if key not in temps:
                    name = self._fresh(text)
                    temps[key] = name
                    st.hoisted.append((name, hit[0], "CSE"))
                    self.rewrites.append(
                        Rewrite(
                            "CSE",
                            st.assign.line,
                            f"{text} computed {counts[key]}x — hoisted as {name}",
                        )
                    )
                temp = temps[key]

                def rw(e: Expr, st: _Stmt = st, key: Sig = key, temp: str = temp) -> Expr:
                    if (
                        isinstance(e, Bin)
                        and canon(e) == key[0]
                        and self._sig_text(st, canon(e), e) == key[1]
                    ):
                        return Var(temp, e.span)
                    return e

                new_rhs = _map_expr(st.rhs, rw)
                if canon(new_rhs) != canon(st.rhs):
                    st.rhs = new_rhs
                    st.changed = True

    def _sig_text(self, st: _Stmt, text: str, e: Expr | None = None) -> tuple[tuple[str, int], ...]:
        """Def-version signature for a subexpression's variables at st."""
        import re as _re

        versions = self.versions[st.idx]
        names = set(_re.findall(r"[A-Za-z_]\w*", text)) if e is None else None
        if e is not None:
            from pipeforge.core.frontend.ast import expr_vars

            names = expr_vars(e)
        return tuple(sorted((v, versions.get(v, 0)) for v in (names or set())))

    # BALANCE (single statement): a + b + c + d parses left-deep (depth n-1);
    # rebuild as a balanced tree (depth ceil(log2 n)). Wrap addition is
    # associative bit-exactly, so this is a free depth win (LP-2).
    def balance_chains(self) -> None:
        import math

        def leaves(e: Expr) -> list[Expr] | None:
            if isinstance(e, Bin) and e.op == "+":
                left = leaves(e.left) or [e.left]
                right = leaves(e.right) or [e.right]
                return left + right
            return None

        def depth(e: Expr) -> int:
            if isinstance(e, Bin) and e.op == "+":
                return 1 + max(depth(e.left), depth(e.right))
            return 0

        for st in self._active():

            def rw(e: Expr, st: _Stmt = st) -> Expr:
                terms = leaves(e) if isinstance(e, Bin) and e.op == "+" else None
                if not terms or len(terms) < 4:
                    return e
                best = math.ceil(math.log2(len(terms)))
                if depth(e) <= best:
                    return e
                balanced = _balance_terms(terms, e.span)
                st.changed = True
                self.rewrites.append(
                    Rewrite(
                        "BALANCE",
                        st.assign.line,
                        f"{len(terms)}-term addition chain: depth {depth(e)} -> "
                        f"{best} (bit-exact for wrap addition)",
                    )
                )
                return balanced

            # bottom-up mapping would re-balance subtrees first; apply at the
            # top level only so the whole chain restructures in one step
            st.rhs = rw(st.rhs)


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


def _compare(
    src_before: str,
    src_after: str,
    cm: CostModel,
    vectors: int,
    snapshot: object | None = None,
) -> list[OutputAccuracy]:
    import random

    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.frontend.varinfo import WorkspaceSnapshot
    from pipeforge.core.fxp.evaluator import error_stats, evaluate_fixed, evaluate_float
    from pipeforge.core.fxp.fx import FxFormat, to_float

    before = audit_source(src_before, "before.m", cm, snapshot=snapshot)
    after = audit_source(src_after, "after.m", cm, snapshot=snapshot)
    fmt = FxFormat(cm.width, cm.scale)
    outs_before = {n.signal: n.nid for n in before.dag.outputs() if n.signal}
    outs_after = {n.signal: n.nid for n in after.dag.outputs() if n.signal}
    common = sorted(set(outs_before) & set(outs_after))
    inputs = sorted({n.label for n in before.dag.inputs()})
    rng = random.Random(7)
    # real-data stimulus when the snapshot carries it (WS-7): the accuracy
    # comparison then reflects the values this design actually processes
    streams: dict[str, tuple[float, ...]] = {}
    if isinstance(snapshot, WorkspaceSnapshot):
        for name in inputs:
            info = snapshot.get(name)
            if info is not None and info.values:
                streams[name] = info.values

    def input_value(name: str, i: int) -> float:
        vals = streams.get(name)
        if vals:
            return vals[i % len(vals)]
        return rng.uniform(-1.0, 1.0)

    state_bx: dict[str, list[int]] = {}
    state_ax: dict[str, list[int]] = {}
    state_bf: dict[str, list[float]] = {}
    deltas: dict[str, float] = dict.fromkeys(common, 0.0)
    ref: dict[str, list[float]] = {k: [] for k in common}
    meas_b: dict[str, list[float]] = {k: [] for k in common}
    meas_a: dict[str, list[float]] = {k: [] for k in common}
    for i in range(vectors):
        vec = {name: input_value(name, i) for name in inputs}
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


def optimize_source(
    src: str, cm: CostModel, vectors: int = 64, snapshot: object | None = None
) -> OptimizeResult:
    """Apply RECIP/CDIV/SERDIV/POW/CSE/BALANCE rewrites to MATLAB source (OP-1).

    Operates on the script's own statements (local function bodies are left
    as written — their calls still inline at audit time). Constant accumulator
    loops become balanced adder trees (LP-2); other constant loops unroll at
    audit time and are left textually as loops (rewriting one unrolled
    iteration would rewrite them all). Returns the original source unchanged
    when nothing applies.
    """
    from pipeforge.core.audit.engine import audit_source

    before = audit_source(src, "before.m", cm, snapshot=snapshot)
    balanced_src, balance_rewrites = balance_loops(src)
    assigns, _skipped = parse_program(balanced_src)
    opt = _Optimizer(assigns)
    opt.rewrites.extend(balance_rewrites)
    opt.serdiv()
    opt.recip()
    opt.cdiv()
    opt.pow_()
    opt.cse()
    opt.balance_chains()
    result = OptimizeResult(source=src, rewrites=opt.rewrites)
    result.latency_before = result.latency_after = before.total_latency
    result.dividers_before = result.dividers_after = before.divider_count
    if not opt.rewrites:
        result.note = "no applicable rewrites"
        return result
    new_src = _render(balanced_src, opt.stmts)
    after = audit_source(new_src, "after.m", cm, snapshot=snapshot)
    if len(after.skipped) > len(before.skipped):
        result.rewrites = []
        result.note = "rewritten source failed to re-parse cleanly; keeping the original"
        return result
    result.source = new_src
    result.latency_after = after.total_latency
    result.dividers_after = after.divider_count
    result.accuracy = _compare(src, new_src, cm, vectors, snapshot=snapshot)
    return result
