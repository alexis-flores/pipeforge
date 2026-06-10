"""nkMatlib pipelined cost model (AU-1, C4).

The nkMatlib README (github.com/nklabs/matlib) is the single source of truth
for operator latencies. Everything here is derived from WIDTH and SCALE at
runtime; no latency number is hard-coded anywhere else in PipeForge
(enforced by an architecture test).
"""

from __future__ import annotations

from dataclasses import dataclass

#: nkMatlib modules that contain a divider (highlighted in the census, AU-2).
DIVIDER_MODULES: frozenset[str] = frozenset(
    {"elem_sdiv", "elem_sinv", "matunscale", "elem_sdiv_by_row"}
)

#: Known MATLAB functions -> nkMatlib module (FE-1; extensible via config).
KNOWN_FUNCS: dict[str, str] = {
    "sqrt": "elem_usqrt",
    "abs": "elem_abs",
    "max": "elem_smax",
    "min": "elem_smin",
    "norm": "rootsqr",
    "sumsqr": "sumsqr",
    "cross": "crossp",
    "dot": "matmul",
    "vecnorm": "vecnormrows",
    "transpose": "transp",
    "ones": "elem_same",
    "zeros": "elem_same",
}


@dataclass(frozen=True)
class CostModel:
    """Operator latencies for a given fixed-point format.

    WIDTH = total bits, SCALE = fractional bits, LEFT = WIDTH - SCALE.
    """

    width: int = 16
    scale: int = 12

    def __post_init__(self) -> None:
        if self.width <= 0 or self.scale < 0 or self.scale >= self.width:
            raise ValueError(f"invalid fixedp parameters WIDTH={self.width} SCALE={self.scale}")

    @property
    def left(self) -> int:
        return self.width - self.scale

    @property
    def add_lat(self) -> int:
        return 1

    @property
    def mul_lat(self) -> int:
        return 4

    @property
    def div_lat(self) -> int:
        return self.width + self.scale

    @property
    def sqrt_lat(self) -> int:
        return self.width - self.left // 2

    @property
    def matmul_lat(self) -> int:
        return self.mul_lat + 1

    @property
    def sumsqr_lat(self) -> int:
        return self.mul_lat + 1

    @property
    def rootsqr_lat(self) -> int:
        return self.sqrt_lat + self.sumsqr_lat

    @property
    def crossp_lat(self) -> int:
        return self.mul_lat + 1

    def _table(self) -> dict[str, int]:
        return {
            "": 0,  # wiring (index/range/concat): no instance
            "input": 0,
            "const": 0,
            "matadd": self.add_lat,
            "matsub": self.add_lat,
            "matadd3": self.add_lat,
            "matadd3b1": self.add_lat,
            "matadd3b2": self.add_lat,
            "elem_neg": 1,
            "elem_abs": 1,
            "elem_smax": 1,
            "elem_smin": 1,
            "elem_rshift": 1,
            "elem_smul": self.mul_lat,
            "elem_ssqr": self.mul_lat,
            "elem_sdiv": self.div_lat,
            "elem_sdiv_by_row": self.div_lat,
            "elem_sinv": self.div_lat,
            "elem_usqrt": self.sqrt_lat,
            "matmul": self.matmul_lat,
            "matscale": self.mul_lat,
            "matunscale": self.div_lat,
            "sumsqr": self.sumsqr_lat,
            "rootsqr": self.rootsqr_lat,
            "crossp": self.crossp_lat,
            "vecnormrows": self.rootsqr_lat,
            "vecnormcols": self.rootsqr_lat,
            "transp": 0,
            "elem_same": 0,
            "elem_snorm": 0,
            "selcols": 0,
            "selrows": 0,
            "pipe": 1,  # `PIPE matching delay: 1 cycle per stage crossed
        }

    def latency_of(self, module: str) -> int:
        """Latency in cycles of one nkMatlib module instance."""
        table = self._table()
        if module not in table:
            raise KeyError(f"unknown nkMatlib module: {module}")
        return table[module]

    def known_modules(self) -> frozenset[str]:
        return frozenset(self._table())

    def is_divider(self, module: str) -> bool:
        return module in DIVIDER_MODULES

    def summary(self) -> dict[str, int]:
        """Named latencies for report headers."""
        return {
            "ADD": self.add_lat,
            "MUL": self.mul_lat,
            "DIV": self.div_lat,
            "SQRT": self.sqrt_lat,
            "MATMUL": self.matmul_lat,
            "SUMSQR": self.sumsqr_lat,
            "ROOTSQR": self.rootsqr_lat,
            "CROSSP": self.crossp_lat,
        }
