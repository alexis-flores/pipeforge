"""Stimulus generation for co-simulation (CS-1a, CS-5).

Corner cases first (zeros, ±max, ±1 LSB, sign boundaries), then hazard-targeted
vectors derived from a RangeReport (CS-5), then seeded random vectors —
deterministic for a given (inputs, format, count, seed).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from pipeforge.core.fxp.fx import FxFormat, from_float, wrap

if TYPE_CHECKING:
    from pipeforge.core.frontend.dag import Dag
    from pipeforge.core.ranges.propagate import RangeReport

Vector = dict[str, int]  # input name -> raw bit pattern

#: a divisor operand within ±GUARD_LSBS·LSB of zero is a near-zero hazard (RP-1).
GUARD_LSBS = 4


def corner_values(fmt: FxFormat) -> list[int]:
    """The raw corner patterns every input should see."""
    w = fmt.width
    return [
        0,  # zero
        1,  # +1 LSB
        wrap(-1, w),  # -1 LSB
        fmt.max_signed,  # +max
        fmt.min_raw,  # most negative
        wrap(fmt.min_raw + 1, w),  # -max
        1 << fmt.scale,  # +1.0
        wrap(-(1 << fmt.scale), w),  # -1.0
        (1 << (w - 1)) - (1 << fmt.scale),  # near +max, integer part boundary
        wrap(1 << (w - 2), w),  # mid-range positive (sign boundary -1 bit)
    ]


def generate_stimulus(
    inputs: list[str],
    fmt: FxFormat,
    count: int = 256,
    seed: int = 2024,
    extra: list[Vector] | None = None,
) -> list[Vector]:
    """Corner-case + (optional) hazard-targeted + randomized vectors (CS-1a/CS-5).

    `extra` (e.g. :func:`generate_hazard_targeted` output) is merged immediately
    after the corner block and before the random fill, per CS-5.
    """
    vectors: list[Vector] = []
    corners = corner_values(fmt)
    # all-same corners
    for value in corners:
        vectors.append(dict.fromkeys(inputs, value))
    # rotated corners so unequal operands hit boundaries together
    for shift in range(1, min(len(inputs), 4) + 1):
        for base in (0, 3, 4):
            vec = {
                name: corners[(base + i * shift) % len(corners)] for i, name in enumerate(inputs)
            }
            vectors.append(vec)
    if extra:  # hazard-targeted vectors come after corners, before random (CS-5)
        vectors.extend(extra)
    rng = random.Random(seed)
    while len(vectors) < count:
        vectors.append({name: rng.randrange(0, 1 << fmt.width) for name in inputs})
    return vectors[:count]


#: supported valid-driving cadences (CS-6).
CADENCES = ("continuous", "gapped", "single", "restart")


def valid_schedule(count: int, cadence: str = "continuous", seed: int = 2024) -> list[bool]:
    """A per-cycle valid_0 schedule with exactly `count` feed cycles (CS-6).

    True presents the next vector; False is a bubble. The golden comparison
    stays valid-gated and cycle-aligned under every cadence because valid_N
    tracks valid_0 through the same pipeline delay.
    """
    if cadence not in CADENCES:
        raise ValueError(f"unknown cadence {cadence!r}")
    if count <= 0:
        return []
    if cadence == "continuous":
        return [True] * count
    if cadence == "single":  # one bubble between every valid
        sched: list[bool] = []
        for _ in range(count):
            sched.extend((True, False))
        return sched
    if cadence == "restart":  # a burst, an idle gap, then restart
        half = max(1, count // 2)
        return [True] * half + [False] * 4 + [True] * (count - half)
    # gapped: deterministic random bubbles
    rng = random.Random(seed)
    out: list[bool] = []
    fed = 0
    while fed < count:
        out.append(True)
        fed += 1
        if rng.random() < 0.4:
            out.extend([False] * rng.randint(1, 2))
    return out


def _input_leaves(dag: Dag, nid: str, seen: set[str] | None = None) -> list[str]:
    """Input-node labels feeding a node (the lanes that drive it)."""
    seen = seen if seen is not None else set()
    if nid in seen:
        return []
    seen.add(nid)
    node = dag.nodes[nid]
    if node.module == "input":
        return [node.label]
    labels: list[str] = []
    for arg in node.args:
        for label in _input_leaves(dag, arg, seen):
            if label not in labels:
                labels.append(label)
    return labels


def generate_hazard_targeted(
    dag: Dag, fmt: FxFormat, report: RangeReport, seed: int = 2024
) -> list[Vector]:
    """Vectors that exercise the hazards the range analysis already found (CS-5).

    For each near-zero divisor hazard, drive the divisor's operand lanes toward
    the guard band (±GUARD_LSBS·LSB); for each overflow-risk node, drive its
    operand lanes to the values that maximize that node's magnitude. Fully
    deterministic for a given (DAG, format, RangeReport, seed).
    """
    inputs = [n.label for n in dag.inputs()]
    input_iv = {
        n.label: report.nodes[n.nid].interval for n in dag.inputs() if n.nid in report.nodes
    }

    def baseline() -> Vector:
        vec: Vector = {}
        for name in inputs:
            iv = input_iv.get(name)
            mid = 0.0 if iv is None else (iv.lo + iv.hi) / 2.0
            vec[name] = from_float(mid, fmt)
        return vec

    vectors: list[Vector] = []
    for hz in report.hazard_nodes:
        node = dag.nodes[hz.nid]
        divisor = (
            node.args[1]
            if node.module in ("elem_sdiv", "matunscale") and len(node.args) > 1
            else node.args[0]
        )
        vec = baseline()
        for name in _input_leaves(dag, divisor):
            if name in vec:
                vec[name] = GUARD_LSBS  # raw value inside the guard band
        vectors.append(vec)
    for ov in report.overflow_nodes:
        vec = baseline()
        for name in _input_leaves(dag, ov.nid):
            iv = input_iv.get(name)
            if iv is not None and name in vec:
                extreme = iv.hi if abs(iv.hi) >= abs(iv.lo) else iv.lo
                vec[name] = from_float(extreme, fmt)
        vectors.append(vec)
    return vectors


def generate_stimulus_with_samples(
    inputs: list[str],
    fmt: FxFormat,
    samples: dict[str, list[float]],
    count: int = 256,
    seed: int = 2024,
) -> list[Vector]:
    """Corners first, then real workspace samples lane-by-lane, then random.

    `samples` carries float values per input (e.g. from a MATLAB snapshot);
    shorter streams repeat cyclically so every lane stays populated.
    """
    from pipeforge.core.fxp.fx import from_float

    vectors = generate_stimulus(inputs, fmt, count=count, seed=seed)
    streams = {name: vals for name, vals in samples.items() if vals}
    if not streams:
        return vectors
    lanes = max(len(v) for v in streams.values())
    corner_count = sum(1 for _ in corner_values(fmt)) + 1  # keep the corner block
    real: list[Vector] = []
    for i in range(min(lanes, max(count - corner_count, 0))):
        vec: Vector = {}
        for name in inputs:
            vals = streams.get(name)
            if vals:
                vec[name] = from_float(vals[i % len(vals)], fmt)
            else:
                vec[name] = vectors[(corner_count + i) % count][name]
        real.append(vec)
    merged = vectors[:corner_count] + real
    fill_from = len(merged)
    merged.extend(vectors[fill_from:count])
    return merged[:count]
