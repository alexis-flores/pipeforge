"""DAG evaluation: bit-exact fixed-point and float64 reference (FX-3, FX-4).

Values are vectors (lists); scalars are length-1 vectors. Every intermediate
signal is returned keyed by DAG node ID, so co-simulation and bisection can
compare any pipeline stage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pipeforge.core.frontend.dag import Dag, Node
from pipeforge.core.fxp import ops
from pipeforge.core.fxp.fx import FxFormat, from_float, to_float, wrap

FixedVec = list[int]
FloatVec = list[float]


class EvalError(ValueError):
    """A DAG node cannot be evaluated (missing input, bad shape, opaque op)."""


def _broadcast(a: list[int] | list[float], b: list[int] | list[float]) -> int:
    if len(a) == len(b):
        return len(a)
    if len(a) == 1 or len(b) == 1:
        return max(len(a), len(b))
    raise EvalError(f"shape mismatch: {len(a)} vs {len(b)}")


def _elem(v: list[int], i: int) -> int:
    return v[i] if len(v) > 1 else v[0]


def _felem(v: list[float], i: int) -> float:
    return v[i] if len(v) > 1 else v[0]


def evaluate_fixed(
    dag: Dag, inputs: dict[str, FixedVec | float | list[float]], fmt: FxFormat
) -> dict[str, FixedVec]:
    """Evaluate every node bit-exactly. Float inputs are converted TOFIXED-style.

    Returns raw bit-pattern vectors keyed by node ID (FX-3).
    """
    values: dict[str, FixedVec] = {}
    for nid in dag.order:
        node = dag.nodes[nid]
        values[nid] = _eval_fixed_node(node, values, inputs, fmt)
    return values


def _coerce_fixed(value: FixedVec | float | list[float], fmt: FxFormat) -> FixedVec:
    if isinstance(value, (int, float)):
        if isinstance(value, int):
            return [wrap(value, fmt.width)]
        return [from_float(value, fmt)]
    out: FixedVec = []
    for x in value:
        out.append(wrap(x, fmt.width) if isinstance(x, int) else from_float(x, fmt))
    return out


def _eval_fixed_node(
    node: Node,
    values: dict[str, FixedVec],
    inputs: dict[str, FixedVec | float | list[float]],
    fmt: FxFormat,
) -> FixedVec:
    if node.module == "input":
        if node.label not in inputs:
            raise EvalError(f"no value provided for input '{node.label}'")
        return _coerce_fixed(inputs[node.label], fmt)
    if node.module == "const":
        try:
            return [from_float(float(node.label), fmt)]
        except ValueError as exc:
            raise EvalError(f"non-numeric const '{node.label}'") from exc
    return apply_fixed(node, [values[a] for a in node.args], fmt)


def apply_fixed(node: Node, args: list[FixedVec], fmt: FxFormat) -> FixedVec:
    """Recompute one non-leaf node from explicit argument values.

    Shared by the evaluator and bisection (which replays a stage with
    shifted operand streams to classify delay-skew bugs, BI-2).
    """
    mod = node.module
    if mod == "":
        # wiring: index/range/concat/wire — pass-through semantics
        if node.op == "concat":
            return [x for v in args for x in v]
        return args[0]
    if mod in ("matadd", "matsub"):
        a, b = args
        n = _broadcast(a, b)
        fn = ops.add if mod == "matadd" else ops.sub
        return [fn(_elem(a, i), _elem(b, i), fmt) for i in range(n)]
    if mod == "elem_neg":
        return [ops.neg(x, fmt) for x in args[0]]
    if mod == "elem_abs":
        return [ops.abs_(x, fmt) for x in args[0]]
    if mod in ("elem_smax", "elem_smin"):
        a, b = args
        n = _broadcast(a, b)
        fn = ops.smax if mod == "elem_smax" else ops.smin
        return [fn(_elem(a, i), _elem(b, i), fmt) for i in range(n)]
    if mod in ("elem_smul", "matscale"):
        a, b = args
        n = _broadcast(a, b)
        return [ops.smul(_elem(a, i), _elem(b, i), fmt) for i in range(n)]
    if mod == "elem_ssqr":
        return [ops.ssqr(x, fmt) for x in args[0]]
    if mod in ("elem_sdiv", "matunscale"):
        a, b = args
        n = _broadcast(a, b)
        return [ops.sdiv(_elem(a, i), _elem(b, i), fmt) for i in range(n)]
    if mod == "elem_sinv":
        return [ops.sinv(x, fmt) for x in args[0]]
    if mod == "elem_usqrt":
        return [ops.usqrt(x, fmt) for x in args[0]]
    if mod == "elem_rshift":
        a, b = args
        n = _broadcast(a, b)
        return [ops.rshift(_elem(a, i), _elem(b, i), fmt) for i in range(n)]
    if mod == "sumsqr":
        return [ops.sumsqr(args[0], fmt)]
    if mod in ("rootsqr", "vecnormrows", "vecnormcols"):
        return [ops.rootsqr(args[0], fmt)]
    if mod == "crossp":
        return ops.crossp(args[0], args[1], fmt)
    if mod == "matmul":
        return [ops.dotprod(args[0], args[1], fmt)]
    if mod in ("transp", "elem_same", "elem_snorm", "selcols", "selrows"):
        return args[0]
    raise EvalError(f"cannot evaluate module '{mod}' (node {node.nid})")


def evaluate_float(
    dag: Dag, inputs: dict[str, FixedVec | float | list[float]], fmt: FxFormat
) -> dict[str, FloatVec]:
    """Float64 reference evaluation of the same DAG (the 'MATLAB' answer, FX-4).

    Fixed-point raw-int inputs are interpreted in the given format so both
    evaluations see the same stimulus.
    """
    values: dict[str, FloatVec] = {}
    for nid in dag.order:
        node = dag.nodes[nid]
        values[nid] = _eval_float_node(node, values, inputs, fmt)
    return values


def _coerce_float(value: FixedVec | float | list[float], fmt: FxFormat) -> FloatVec:
    if isinstance(value, (int, float)):
        if isinstance(value, int):
            return [to_float(value, fmt)]
        return [float(value)]
    return [to_float(x, fmt) if isinstance(x, int) else float(x) for x in value]


def _eval_float_node(
    node: Node,
    values: dict[str, FloatVec],
    inputs: dict[str, FixedVec | float | list[float]],
    fmt: FxFormat,
) -> FloatVec:
    if node.module == "input":
        if node.label not in inputs:
            raise EvalError(f"no value provided for input '{node.label}'")
        return _coerce_float(inputs[node.label], fmt)
    if node.module == "const":
        return [float(node.label)]
    args = [values[a] for a in node.args]
    mod = node.module
    if mod == "":
        if node.op == "concat":
            return [x for v in args for x in v]
        return args[0]
    if mod in ("matadd", "matsub"):
        a, b = args
        n = _broadcast(a, b)
        sign = 1.0 if mod == "matadd" else -1.0
        return [_felem(a, i) + sign * _felem(b, i) for i in range(n)]
    if mod == "elem_neg":
        return [-x for x in args[0]]
    if mod == "elem_abs":
        return [abs(x) for x in args[0]]
    if mod in ("elem_smax", "elem_smin"):
        a, b = args
        n = _broadcast(a, b)
        fn = max if mod == "elem_smax" else min
        return [fn(_felem(a, i), _felem(b, i)) for i in range(n)]
    if mod in ("elem_smul", "matscale"):
        a, b = args
        n = _broadcast(a, b)
        return [_felem(a, i) * _felem(b, i) for i in range(n)]
    if mod == "elem_ssqr":
        return [x * x for x in args[0]]
    if mod in ("elem_sdiv", "matunscale"):
        a, b = args
        n = _broadcast(a, b)
        return [_felem(a, i) / _felem(b, i) if _felem(b, i) != 0.0 else math.inf for i in range(n)]
    if mod == "elem_sinv":
        return [1.0 / x if x != 0.0 else math.inf for x in args[0]]
    if mod == "elem_usqrt":
        return [math.sqrt(x) if x >= 0 else math.nan for x in args[0]]
    if mod == "elem_rshift":
        a, b = args
        n = _broadcast(a, b)
        return [_felem(a, i) / (2.0 ** _felem(b, i)) for i in range(n)]
    if mod == "sumsqr":
        return [sum(x * x for x in args[0])]
    if mod in ("rootsqr", "vecnormrows", "vecnormcols"):
        return [math.sqrt(sum(x * x for x in args[0]))]
    if mod == "crossp":
        a, b = args
        return [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
    if mod == "matmul":
        return [sum(x * y for x, y in zip(args[0], args[1], strict=True))]
    if mod in ("transp", "elem_same", "elem_snorm", "selcols", "selrows"):
        return args[0]
    raise EvalError(f"cannot evaluate module '{mod}' (node {node.nid})")


# ---------------------------------------------------------------------------
# Error statistics (FX-4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorStats:
    max_abs_error: float
    rms_error: float
    sqnr_db: float
    samples: int


def error_stats(reference: list[float], measured: list[float]) -> ErrorStats:
    """Float-reference vs fixed-point error metrics: max abs, RMS, SQNR (dB)."""
    if len(reference) != len(measured):
        raise ValueError("length mismatch")
    finite = [(r, m) for r, m in zip(reference, measured, strict=True) if math.isfinite(r)]
    if not finite:
        return ErrorStats(math.nan, math.nan, math.nan, 0)
    errs = [m - r for r, m in finite]
    max_abs = max(abs(e) for e in errs)
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    sig_power = sum(r * r for r, _ in finite)
    err_power = sum(e * e for e in errs)
    if err_power == 0.0:
        sqnr = math.inf
    elif sig_power == 0.0:
        sqnr = -math.inf
    else:
        sqnr = 10.0 * math.log10(sig_power / err_power)
    return ErrorStats(max_abs, rms, sqnr, len(finite))


def compare_outputs(
    dag: Dag,
    inputs: dict[str, FixedVec | float | list[float]],
    fmt: FxFormat,
) -> dict[str, ErrorStats]:
    """Run both evaluations and report per-output error statistics (FX-4)."""
    fixed = evaluate_fixed(dag, inputs, fmt)
    ref = evaluate_float(dag, inputs, fmt)
    out: dict[str, ErrorStats] = {}
    for node in dag.outputs():
        measured = [to_float(x, fmt) for x in fixed[node.nid]]
        out[node.signal or node.nid] = error_stats(ref[node.nid], measured)
    return out
