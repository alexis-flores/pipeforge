"""Dataflow DAG — the central data structure (§3.3, FE-2).

Every PipeForge capability consumes this graph: a node selected in the
visualizer is the same node named in an audit finding, a codegen instance,
and a bisection report. Node IDs are stable (creation order).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.ast import (
    Bin,
    Call,
    ColonAtom,
    Expr,
    Field,
    Index,
    Mat,
    Num,
    Span,
    Str,
    Trans,
    Un,
    Var,
    canon,
    expr_vars,
)
from pipeforge.core.frontend.lexer import MatlabSyntaxError
from pipeforge.core.frontend.parser import Assign, Skipped


def port_name(label: str) -> str:
    """RTL-safe port name for an input label.

    Dotted struct fields and constant-index lanes both flatten:
    ``cfg.gain`` -> ``cfg_gain``, ``x(3)`` -> ``x_3``, ``m(2, 3)`` -> ``m_2_3``.
    """
    out = label.replace(".", "_").replace(", ", "_").replace(",", "_")
    return out.replace("(", "_").replace(")", "").strip("_")


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
    span: Span | None = None
    shape: tuple[int, int] = (1, 1)  # (rows, cols); known only with a snapshot


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

    def consumers(self) -> dict[str, int]:
        """Number of consumers per node id."""
        out: dict[str, int] = {}
        for nid in self.order:
            for a in self.nodes[nid].args:
                out[a] = out.get(a, 0) + 1
        return out

    def inputs(self) -> list[Node]:
        """External input leaves in creation order."""
        return [self.nodes[i] for i in self.order if self.nodes[i].module == "input"]

    def outputs(self) -> list[Node]:
        """Pipeline outputs: final variable definitions nothing else consumes.

        Mirrors the nkMatlib convention that only terminal signals become
        ``_N`` ports. Falls back to the last statement if everything is
        consumed.
        """
        last_def: dict[str, str] = {}
        for s in self.statements:
            last_def[s.target] = s.root
        consumed = self.consumers()
        # dedupe: `s = y` aliases both targets to one node — one port, not two
        outs = list(dict.fromkeys(nid for nid in last_def.values() if consumed.get(nid, 0) == 0))
        if not outs and self.statements:
            outs = [self.statements[-1].root]
        return [self.nodes[nid] for nid in outs]


class DagBuilder:
    """Builds the DAG from parsed assignments with def-use links (FE-2).

    With a live MATLAB :class:`WorkspaceSnapshot`, leaf shapes come from the
    real workspace and `*`/`/` map shape-aware (matmul/matscale/matunscale);
    without one, every shape is scalar and behavior is bit-identical to the
    static analysis (golden files pin it).
    """

    def __init__(self, cm: CostModel, snapshot: object | None = None) -> None:
        from pipeforge.core.frontend.varinfo import WorkspaceSnapshot

        self.cm = cm
        self.snapshot: WorkspaceSnapshot | None = (
            snapshot if isinstance(snapshot, WorkspaceSnapshot) else None
        )
        self.dag = Dag()
        self.env: dict[str, str] = {}  # var -> defining node id
        self.counter = 0
        self.div_nodes: list[tuple[Node, Expr, Expr]] = []  # (node, dividend, divisor)
        self.pow_expansions: list[tuple[int, str, int, int]] = []  # (line, base, exp, naive)
        self.cur_line = 0
        self._leaf_cache: dict[tuple[str, str], str] = {}

    def new_id(self) -> str:
        self.counter += 1
        return f"n{self.counter:03d}"

    def leaf(self, module: str, label: str, span: Span | None) -> Node:
        key = (module, label)
        cached = self._leaf_cache.get(key)
        if cached is not None:
            return self.dag.nodes[cached]
        shape = (1, 1)
        if module == "input" and self.snapshot is not None:
            info = self.snapshot.get(label)
            if info is not None:
                shape = info.shape2d
        node = Node(
            self.new_id(), module, module, 0, 0, [], self.cur_line, label, span=span, shape=shape
        )
        self._leaf_cache[key] = node.nid
        return self.dag.add(node)

    def op_node(
        self,
        module: str,
        op: str,
        args: list[Node],
        label: str,
        span: Span | None,
        shape: tuple[int, int] | None = None,
    ) -> Node:
        lat = self.cm.latency_of(module)
        ready = max((a.ready for a in args), default=0) + lat
        if shape is None:  # elementwise default: broadcast
            shape = (
                max((a.shape[0] for a in args), default=1),
                max((a.shape[1] for a in args), default=1),
            )
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
            shape=shape,
        )
        return self.dag.add(node)

    def build_expr(self, e: Expr) -> Node:
        if isinstance(e, Num):
            return self.leaf("const", canon(e), e.span)
        if isinstance(e, Var):
            if e.name in self.env:
                return self.dag.nodes[self.env[e.name]]
            return self.leaf("input", e.name, e.span)
        if isinstance(e, Field):
            dotted = e.dotted
            if dotted in self.env:
                return self.dag.nodes[self.env[dotted]]
            if e.base in self.env:
                # field of a struct defined earlier: wiring off its def node
                base = self.dag.nodes[self.env[e.base]]
                return self.op_node("", "field", [base], dotted, e.span)
            return self.leaf("input", dotted, e.span)
        if isinstance(e, ColonAtom):
            return self.leaf("const", ":", e.span)
        if isinstance(e, Str):
            return self.leaf("const", e.text, e.span)
        if isinstance(e, Index):
            key = canon(e)  # 'x(3)' — matches constant-index lane targets (LN-1)
            if key in self.env:
                return self.dag.nodes[self.env[key]]
            const_lanes = e.args and all(
                isinstance(a, Num) and a.value == int(a.value) and a.value >= 1 for a in e.args
            )
            if e.name not in self.env and const_lanes and len(e.args) <= 2:
                # a constant-index read of an undefined vector: one scalar
                # input lane, e.g. x(3) — codegen gets port x_3 (LN-1)
                return self.leaf("input", key, e.span)
            args = [self.build_expr(a) for a in e.args]
            base = (
                self.dag.nodes[self.env[e.name]]
                if e.name in self.env
                else self.leaf("input", e.name, e.span)
            )
            return self.op_node("", "index", [base, *args], canon(e), e.span)
        if isinstance(e, Call):
            from pipeforge.core.costmodel.model import KNOWN_FUNCS

            if e.name == "reshape":
                return self.build_reshape(e)  # dim args are not data edges (AR-1)
            module = KNOWN_FUNCS[e.name]
            args = [self.build_expr(a) for a in e.args]
            shape: tuple[int, int] | None = None
            if module in ("rootsqr", "sumsqr", "matmul", "vecnormrows", "vecnormcols"):
                shape = (1, 1)  # reductions to a scalar
            return self.op_node(module, e.name, args, canon(e), e.span, shape=shape)
        if isinstance(e, Mat):
            elems = [self.build_expr(x) for x in e.elems]
            return self.op_node("", "concat", elems, canon(e), e.span)
        if isinstance(e, Un):
            operand = self.build_expr(e.operand)
            return self.op_node("elem_neg", "neg", [operand], canon(e), e.span)
        if isinstance(e, Trans):
            operand = self.build_expr(e.operand)
            return self.op_node(
                "transp",
                "transpose",
                [operand],
                canon(e),
                e.span,
                shape=(operand.shape[1], operand.shape[0]),
            )
        if isinstance(e, Bin):
            return self.build_bin(e)
        raise TypeError(f"unknown expr: {e!r}")

    def _reshape_dims(self, dim_args: list[Expr], line: int) -> list[int | None]:
        """Constant target dims for a reshape; ``None`` marks an inferred ``[]``."""
        # accept either a single size-vector literal ([r c]) or scalar dims (r, c)
        items: list[Expr] = (
            list(dim_args[0].elems)
            if len(dim_args) == 1 and isinstance(dim_args[0], Mat)
            else dim_args
        )
        dims: list[int | None] = []
        for it in items:
            if isinstance(it, Mat) and not it.elems:
                dims.append(None)  # [] -> inferred dimension
            elif isinstance(it, Num) and it.value == int(it.value):
                dims.append(int(it.value))
            else:
                raise MatlabSyntaxError("reshape dimensions must be constant integers", line)
        return dims

    def build_reshape(self, e: Call) -> Node:
        """reshape(x, r, c) / reshape(x, [r c]) as a zero-cost column-major remap (AR-1).

        Only the operand is a data edge; the dimension arguments are metadata.
        A target whose element count cannot match a *known* source is reported
        via the FE-3 skipped-statement mechanism rather than silently (AR-1).
        """
        if not e.args:
            raise MatlabSyntaxError("reshape requires an operand", e.span.line)
        operand = self.build_expr(e.args[0])
        dims = self._reshape_dims(list(e.args[1:]), e.span.line)
        if len(dims) != 2:
            raise MatlabSyntaxError("reshape: only 2-D targets are supported", e.span.line)
        src_n = operand.shape[0] * operand.shape[1]
        # (1, 1) is the placeholder for "shape unknown" absent a snapshot, so only
        # validate the element count when the source shape is genuinely known.
        src_known = self.snapshot is not None or operand.shape != (1, 1)
        if None in dims:
            if not src_known:
                raise MatlabSyntaxError(
                    "reshape: cannot infer [] dimension without a known source shape",
                    e.span.line,
                )
            prod = 1
            for d in dims:
                if d is not None:
                    prod *= d
            if prod == 0 or src_n % prod != 0:
                raise MatlabSyntaxError(
                    f"reshape target {dims} is incompatible with {src_n} source elements",
                    e.span.line,
                )
            inferred = src_n // prod
            resolved = [inferred if d is None else d for d in dims]
        else:
            resolved = [d for d in dims if d is not None]
        rows, cols = resolved[0], resolved[1]
        if src_known and rows * cols != src_n:
            raise MatlabSyntaxError(
                f"reshape to {rows}x{cols} ({rows * cols} elements) does not match "
                f"source ({src_n} elements)",
                e.span.line,
            )
        return self.op_node("reshape", "reshape", [operand], canon(e), e.span, shape=(rows, cols))

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
            ls, rs = left.shape, right.shape
            if op == "*" and self.snapshot is not None:
                l_scalar = ls == (1, 1)
                r_scalar = rs == (1, 1)
                if not l_scalar and not r_scalar:
                    if ls[1] == rs[0]:  # true matrix product
                        return self.op_node(
                            "matmul", op, [left, right], canon(e), e.span, shape=(ls[0], rs[1])
                        )
                elif l_scalar != r_scalar:  # scalar times matrix
                    mat = rs if l_scalar else ls
                    return self.op_node("matscale", op, [left, right], canon(e), e.span, shape=mat)
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
            module = "elem_sdiv"
            if (
                op == "/"
                and self.snapshot is not None
                and left.shape != (1, 1)
                and right.shape == (1, 1)
            ):
                module = "matunscale"  # matrix / scalar
            node = self.op_node(module, "/", [left, right], canon(e), e.span, shape=left.shape)
            self.div_nodes.append((node, dividend_ast, divisor_ast))
            return node
        raise MatlabSyntaxError(f"unsupported operator {op!r}", e.span.line)

    def build_pow(self, e: Bin) -> Node:
        if not isinstance(e.right, Num) or e.right.value != int(e.right.value):
            raise MatlabSyntaxError("only constant integer exponents are supported", e.span.line)
        exp = int(e.right.value)
        if exp < 2:
            raise MatlabSyntaxError("only integer exponents >= 2 are supported", e.span.line)
        base = self.build_expr(e.left)
        base_label = canon(e.left)
        # Naive left-to-right multiply chain; the POW finding suggests better.
        acc = base
        for k in range(2, exp + 1):
            acc = self.op_node("elem_smul", ".*", [acc, base], f"({base_label}^{k})", e.span)
        self.pow_expansions.append((e.span.line, base_label, exp, exp - 1))
        return acc

    def feedback_path_lat(self, root: Node, target_nid: str) -> int | None:
        """Latency of the longest path from a use of target_nid up to root."""
        memo: dict[str, int | None] = {}

        def walk(nid: str) -> int | None:
            if nid == target_nid:
                return 0
            if nid in memo:
                return memo[nid]
            node = self.dag.nodes[nid]
            best: int | None = None
            for a in node.args:
                sub = walk(a)
                if sub is not None:
                    cand = sub + node.lat
                    if best is None or cand > best:
                        best = cand
            memo[nid] = best
            return best

        return walk(root.nid)

    def stmt_base(self, rhs: Expr) -> int:
        """Ready time of the latest-arriving operand referenced by a statement."""
        base = 0
        for name in expr_vars(rhs):
            if name in self.env:
                base = max(base, self.dag.nodes[self.env[name]].ready)
        return base

    def build_assign(self, a: Assign) -> None:
        self.cur_line = a.line
        self_ref = a.target in expr_vars(a.rhs)
        base = self.stmt_base(a.rhs)
        root = self.build_expr(a.rhs)
        if root.signal == "" and not root.args and root.module in ("input", "const"):
            # alias like `y = x`: wrap in a zero-latency wire node for naming
            root = self.op_node("", "wire", [root], canon(a.rhs), a.span)
        if self_ref:
            prior = self.env.get(a.target)
            use_nid = prior
            if use_nid is None:
                # self-reference to an undefined var: it appeared as an input leaf
                use_nid = self._leaf_cache.get(("input", a.target))
            # a self-reference is a *recurrence* only inside a (non-unrolled)
            # loop or when no prior definition exists (streaming accumulator);
            # with a prior def it is an ordinary chain — unrolled iterations
            # land here and must NOT each report feedback (LP-1)
            if a.in_loop or prior is None:
                ii = self.feedback_path_lat(root, use_nid) if use_nid is not None else None
                self.dag.feedbacks.append((a.target, a.line, ii if ii is not None else root.ready))
        # signal is the RTL-facing identity: lane targets sanitize ('y(1)' ->
        # 'y_1') so emitted SV, harness ports, and trace names agree (LN-1)
        root.signal = port_name(a.target)
        self.env[a.target] = root.nid
        self.dag.statements.append(
            StmtInfo(a.line, a.target, root.ready, root.ready - base, root.nid)
        )


def build_dag(
    assigns: list[Assign], cm: CostModel, snapshot: object | None = None
) -> tuple[DagBuilder, list[Skipped]]:
    """Build the DAG for a parsed program, recording per-statement problems (FE-3)."""
    builder = DagBuilder(cm, snapshot=snapshot)
    problems: list[Skipped] = []
    for a in assigns:
        try:
            builder.build_assign(a)
        except MatlabSyntaxError as exc:
            problems.append(Skipped(exc.line, exc.message))
    return builder, problems
