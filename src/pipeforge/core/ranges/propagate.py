"""Range propagation through the DAG (RP-1, RP-2, RP-3)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, Node
from pipeforge.core.ranges.interval import Affine, Interval


class RangeError(ValueError):
    """Range analysis cannot handle a DAG construct or is missing an input."""


@dataclass(frozen=True)
class NodeRange:
    nid: str
    signal: str
    interval: Interval
    integer_bits: int  # LEFT bits needed (incl. sign) for this range
    overflow_risk: bool  # exceeds the configured WIDTH/SCALE
    near_zero_divisor: bool  # divide-by-near-zero hazard at this node
    method: str  # 'interval' | 'affine' (RP-2 labeling)


@dataclass
class RangeReport:
    method: str
    fmt_width: int
    fmt_scale: int
    nodes: dict[str, NodeRange]

    @property
    def overflow_nodes(self) -> list[NodeRange]:
        return [n for n in self.nodes.values() if n.overflow_risk]

    @property
    def hazard_nodes(self) -> list[NodeRange]:
        return [n for n in self.nodes.values() if n.near_zero_divisor]

    @property
    def required_left(self) -> int:
        finite = [n.integer_bits for n in self.nodes.values() if n.integer_bits < 64]
        return max(finite, default=1)


def integer_bits_needed(iv: Interval) -> int:
    """LEFT (integer+sign) bits needed to hold the interval without overflow."""
    m = iv.max_abs
    if math.isinf(m):
        return 64
    if m < 1.0:
        return 1  # sign bit only
    return math.floor(math.log2(m)) + 2  # magnitude bits + sign


def _near_zero(divisor: Interval, fmt_lsb: float, guard_lsbs: int = 4) -> bool:
    eps = fmt_lsb * guard_lsbs
    return divisor.lo <= eps and divisor.hi >= -eps


def propagate(
    dag: Dag,
    input_ranges: dict[str, Interval],
    cm: CostModel,
    method: str = "interval",
) -> RangeReport:
    """Propagate user-declared input ranges through every node (RP-1).

    method='affine' (RP-2) keeps linear correlations; results are labeled.
    """
    if method not in ("interval", "affine"):
        raise RangeError(f"unknown method {method!r}")
    lsb = 2.0**-cm.scale
    fmt_max = (2 ** (cm.width - 1) - 1) * lsb
    fmt_min = -(2 ** (cm.width - 1)) * lsb

    ivals: dict[str, Interval] = {}
    affs: dict[str, Affine] = {}
    out: dict[str, NodeRange] = {}

    def store(node: Node, iv: Interval, hazard: bool = False) -> None:
        ivals[node.nid] = iv
        overflow = iv.hi > fmt_max or iv.lo < fmt_min
        out[node.nid] = NodeRange(
            nid=node.nid,
            signal=node.signal or node.label,
            interval=iv,
            integer_bits=integer_bits_needed(iv),
            overflow_risk=overflow,
            near_zero_divisor=hazard,
            method=method,
        )

    for nid in dag.order:
        node = dag.nodes[nid]
        hazard = False
        if node.module == "input":
            if node.label not in input_ranges:
                raise RangeError(f"no range declared for input '{node.label}'")
            iv = input_ranges[node.label]
            if method == "affine":
                affs[nid] = Affine.from_interval(iv)
        elif node.module == "const":
            try:
                v = float(node.label)
            except ValueError as exc:
                raise RangeError(f"non-numeric const '{node.label}'") from exc
            iv = Interval(v, v)
            if method == "affine":
                affs[nid] = Affine(v, {})
        else:
            iv, hazard = _apply(node, ivals, affs, method, lsb)
        store(node, iv, hazard)
    return RangeReport(method=method, fmt_width=cm.width, fmt_scale=cm.scale, nodes=out)


def _apply(
    node: Node,
    ivals: dict[str, Interval],
    affs: dict[str, Affine],
    method: str,
    lsb: float,
) -> tuple[Interval, bool]:
    args = [ivals[a] for a in node.args]
    mod = node.module
    hazard = False
    use_affine = method == "affine" and all(a in affs for a in node.args)

    if mod == "" or mod in ("transp", "elem_same", "elem_snorm", "selcols", "selrows"):
        iv = args[0] if args else Interval(0.0, 0.0)
        if len(args) > 1:  # concat/range: hull of elements
            for other in args[1:]:
                iv = iv.hull(other)
        if use_affine and node.args:
            affs[node.nid] = affs[node.args[0]]
        return iv, hazard

    if use_affine:
        a0 = affs[node.args[0]]
        a1 = affs[node.args[1]] if len(node.args) > 1 else None
        result_aff: Affine | None = None
        if mod == "matadd" and a1 is not None:
            result_aff = a0.add(a1)
        elif mod == "matsub" and a1 is not None:
            result_aff = a0.sub(a1)
        elif mod == "elem_neg":
            result_aff = a0.neg()
        elif mod == "elem_smul" and a1 is not None:
            result_aff = a0.mul(a1)
        elif mod == "elem_ssqr":
            result_aff = a0.square()
        if result_aff is not None:
            affs[node.nid] = result_aff
            return result_aff.to_interval(), hazard
        # nonlinear: fall through to intervals, dropping correlations

    a = args[0]
    if mod in ("matadd", "matadd3", "matadd3b1", "matadd3b2"):
        iv = a
        for i, other in enumerate(args[1:], start=1):
            negate = (mod == "matadd3b1" and i == 2) or (mod == "matadd3b2" and i >= 1)
            iv = iv.sub(other) if negate else iv.add(other)
    elif mod == "matsub":
        iv = a.sub(args[1])
    elif mod == "elem_neg":
        iv = a.neg()
    elif mod == "elem_abs":
        iv = a.abs_()
    elif mod in ("elem_smul", "matscale"):
        iv = a.mul(args[1])
    elif mod == "elem_ssqr":
        iv = a.square()
    elif mod in ("elem_sdiv", "matunscale"):
        hazard = _near_zero(args[1], lsb)
        iv = a.div(args[1])
    elif mod == "elem_sinv":
        hazard = _near_zero(a, lsb)
        iv = Interval(1.0, 1.0).div(a)
    elif mod == "elem_usqrt":
        iv = a.sqrt()
    elif mod == "elem_smax":
        iv = a.max_(args[1])
    elif mod == "elem_smin":
        iv = a.min_(args[1])
    elif mod == "elem_rshift":
        iv = a  # conservative: shift only reduces magnitude
    elif mod == "sumsqr":
        iv = a.square()  # vector width unknown: per-element bound
    elif mod in ("rootsqr", "vecnormrows", "vecnormcols"):
        iv = a.square().sqrt()
    elif mod == "matmul":
        iv = a.mul(args[1])
    elif mod == "crossp":
        prod = a.mul(args[1])
        iv = prod.sub(prod.neg())  # u*v - w*x bound
    else:
        raise RangeError(f"no range rule for module '{mod}'")
    if use_affine:
        affs[node.nid] = Affine.from_interval(iv)
    return iv, hazard


@dataclass(frozen=True)
class FormatRecommendation:
    width: int
    scale: int
    left: int
    rationale: str
    validated_sqnr_db: float  # empirical FX-4 check (RP-3)
    meets_budget: bool


def recommend_format(
    dag: Dag,
    input_ranges: dict[str, Interval],
    cm: CostModel,
    error_budget: float,
    validate_vectors: int = 64,
) -> FormatRecommendation:
    """Recommend WIDTH/SCALE meeting an absolute error budget, then verify
    empirically with a fixed-vs-float run (RP-3)."""
    report = propagate(dag, input_ranges, cm, method="interval")
    left = report.required_left
    if left % 2:
        left += 1  # usqrt.sv shifts by LEFT/2: LEFT must be even for correct scaling
    depth = max(1, len([n for n in dag.order if dag.nodes[n].args]))
    # truncation error compounds roughly linearly with operator depth
    scale = max(1, math.ceil(math.log2(depth / error_budget)))
    width = left + scale

    import random

    from pipeforge.core.fxp.evaluator import compare_outputs
    from pipeforge.core.fxp.fx import FxFormat

    rng = random.Random(99)
    fmt = FxFormat(width, scale)
    worst = math.inf
    meets = True
    inputs = [n.label for n in dag.inputs()]
    for _ in range(validate_vectors):
        vec = {name: rng.uniform(input_ranges[name].lo, input_ranges[name].hi) for name in inputs}
        stats = compare_outputs(dag, {k: [v] for k, v in vec.items()}, fmt)
        for s in stats.values():
            if not math.isfinite(s.max_abs_error):
                continue
            if math.isfinite(s.sqnr_db):
                worst = min(worst, s.sqnr_db)
            if s.max_abs_error > error_budget:
                meets = False
    return FormatRecommendation(
        width=width,
        scale=scale,
        left=left,
        rationale=(
            f"LEFT={left} covers the propagated ranges; SCALE={scale} targets "
            f"|error| <= {error_budget} over ~{depth} chained operators"
        ),
        validated_sqnr_db=worst if math.isfinite(worst) else math.inf,
        meets_budget=meets,
    )


def ranges_from_snapshot(dag: Dag, snapshot: object) -> dict[str, Interval]:
    """Empirical input ranges from live MATLAB min/max (MATLAB bridge M4).

    Only inputs present in the snapshot are returned; declared ranges can
    still override or fill the gaps.
    """
    from pipeforge.core.frontend.varinfo import WorkspaceSnapshot

    if not isinstance(snapshot, WorkspaceSnapshot):
        return {}
    out: dict[str, Interval] = {}
    for node in dag.inputs():
        info = snapshot.get(node.label)
        if info is not None and info.vmin is not None and info.vmax is not None:
            out[node.label] = Interval(info.vmin, info.vmax)
    return out
