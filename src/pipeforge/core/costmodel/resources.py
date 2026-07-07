"""Device-aware resource estimation (RE-1).

Maps the operator census onto real FPGA resources so the audit and DSE speak
the target's language: DSP blocks (solid — one tile per hardware multiplier,
composed when WIDTH exceeds the tile), and approximate LUTs (rough — iterative
dividers/sqrts and adders scale with WIDTH; the number is an order-of-magnitude
guide, not a synthesis result). Latencies stay the cost model's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pipeforge.core.costmodel.model import DIVIDER_MODULES, CostModel


@dataclass(frozen=True)
class DspTile:
    """One hard multiplier tile: an axb signed multiply."""

    a: int
    b: int


#: Known device families and their DSP tile shapes (signed multiply widths).
FAMILIES: dict[str, DspTile] = {
    "xilinx7": DspTile(25, 18),  # DSP48E1
    "ultrascale": DspTile(27, 18),  # DSP48E2
    "intel": DspTile(27, 27),  # Cyclone V / Arria variable-precision DSP
    "lattice": DspTile(18, 18),  # ECP5 MULT18X18D
}

DEFAULT_FAMILY = "xilinx7"

#: nkMatlib modules that consume hardware multipliers (count per instance).
_MULTIPLIER_COUNT: dict[str, int] = {
    "elem_smul": 1,
    "elem_ssqr": 1,
    "matscale": 1,
    "matmul": 1,  # per-element instance in the scalar subset
    "sumsqr": 1,
    "rootsqr": 1,  # sumsqr feeding usqrt
    "crossp": 2,  # u*v - w*x per element
    "vecnormrows": 1,
    "vecnormcols": 1,
}

#: modules containing an iterative square root (LUT-based, no DSP).
_SQRT_MODULES = frozenset({"elem_usqrt", "rootsqr", "vecnormrows", "vecnormcols"})


@dataclass(frozen=True)
class ResourceEstimate:
    family: str
    dsp: int  # hard multiplier tiles (composed above the tile width)
    lut_approx: int  # rough LUT count — a guide, not a synthesis result
    ff_approx: int  # rough flip-flops (pipeline registers dominate)
    multipliers: int  # logical multipliers before tiling
    dividers: int
    sqrts: int

    def summary(self) -> str:
        return (
            f"≈ {self.dsp} DSP ({self.family}), ≈ {self.lut_approx} LUT, "
            f"≈ {self.ff_approx} FF — {self.multipliers} mul / "
            f"{self.dividers} div / {self.sqrts} sqrt"
        )


def dsp_tiles_per_multiplier(width: int, tile: DspTile) -> int:
    """Hard tiles needed for one widthxwidth signed multiply.

    A multiply wider than the tile is composed of partial products: one tile
    per (axb) partial-product block. Matches vendor inference behavior to
    first order (e.g. 16x16 → 1 DSP48E1, 32x32 → 4).
    """
    return math.ceil(width / tile.a) * math.ceil(width / tile.b)


def estimate_resources(
    census: dict[str, int], cm: CostModel, family: str = DEFAULT_FAMILY
) -> ResourceEstimate:
    """Estimate FPGA resources for an operator census at the given format."""
    if family not in FAMILIES:
        raise ValueError(f"unknown device family {family!r} (know: {', '.join(FAMILIES)})")
    tile = FAMILIES[family]
    w = cm.width
    multipliers = sum(_MULTIPLIER_COUNT.get(mod, 0) * n for mod, n in census.items())
    dividers = sum(n for mod, n in census.items() if mod in DIVIDER_MODULES)
    sqrts = sum(n for mod, n in census.items() if mod in _SQRT_MODULES)
    adders = sum(
        n
        for mod, n in census.items()
        if mod in ("matadd", "matsub", "matadd3", "matadd3b1", "matadd3b2")
    )
    simple = sum(
        n
        for mod, n in census.items()
        if mod in ("elem_neg", "elem_abs", "elem_smax", "elem_smin", "elem_rshift")
    )

    dsp = multipliers * dsp_tiles_per_multiplier(w, tile)
    # rough LUT model: an iterative divider is ~latency subtract-compare stages
    # of WIDTH bits; sqrt similar at half rate; adders ~WIDTH LUTs each.
    lut = (
        dividers * cm.div_lat * w
        + sqrts * cm.sqrt_lat * w
        + adders * w
        + simple * w
        + multipliers * 4 * w  # DSP glue + rounding
    )
    # rough FF model: each pipeline stage registers ~WIDTH bits per live value
    ff = (
        dividers * cm.div_lat * 2 * w
        + sqrts * cm.sqrt_lat * 2 * w
        + (adders + simple) * w
        + multipliers * cm.mul_lat * w
    )
    return ResourceEstimate(
        family=family,
        dsp=dsp,
        lut_approx=lut,
        ff_approx=ff,
        multipliers=multipliers,
        dividers=dividers,
        sqrts=sqrts,
    )
