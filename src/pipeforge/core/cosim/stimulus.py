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
