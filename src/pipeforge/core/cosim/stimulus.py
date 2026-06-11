"""Stimulus generation for co-simulation (CS-1a).

Corner cases first (zeros, ±max, ±1 LSB, sign boundaries), then seeded
random vectors — deterministic for a given (inputs, format, count, seed).
"""

from __future__ import annotations

import random

from pipeforge.core.fxp.fx import FxFormat, wrap

Vector = dict[str, int]  # input name -> raw bit pattern


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
    inputs: list[str], fmt: FxFormat, count: int = 256, seed: int = 2024
) -> list[Vector]:
    """Corner-case + randomized vectors for the named DAG inputs (CS-1a)."""
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
    rng = random.Random(seed)
    while len(vectors) < count:
        vectors.append({name: rng.randrange(0, 1 << fmt.width) for name in inputs})
    return vectors[:count]


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
