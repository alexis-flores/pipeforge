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
        outs = [nid for nid in last_def.values() if consumed.get(nid, 0) == 0]
        if not outs and self.statements:
            outs = [self.statements[-1].root]
        return [self.nodes[nid] for nid in outs]


class DagBuilder:
    """Builds the DAG from parsed assignments with def-use links (FE-2)."""

    def __init__(self, cm: CostModel) -> None:
        self.cm = cm
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
        node = Node(self.new_id(), module, module, 0, 0, [], self.cur_line, label, span=span)
        self._leaf_cache[key] = node.nid
        return self.dag.add(node)

    def op_node(
        self, module: str, op: str, args: list[Node], label: str, span: Span | None
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
            from pipeforge.core.costmodel.model import KNOWN_FUNCS

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
            ii = self.feedback_path_lat(root, use_nid) if use_nid is not None else None
            self.dag.feedbacks.append((a.target, a.line, ii if ii is not None else root.ready))
        root.signal = a.target
        self.env[a.target] = root.nid
        self.dag.statements.append(
            StmtInfo(a.line, a.target, root.ready, root.ready - base, root.nid)
        )


def build_dag(assigns: list[Assign], cm: CostModel) -> tuple[DagBuilder, list[Skipped]]:
    """Build the DAG for a parsed program, recording per-statement problems (FE-3)."""
    builder = DagBuilder(cm)
    problems: list[Skipped] = []
    for a in assigns:
        try:
            builder.build_assign(a)
        except MatlabSyntaxError as exc:
            problems.append(Skipped(exc.line, exc.message))
    return builder, problems
