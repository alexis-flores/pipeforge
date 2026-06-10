"""Interval and affine arithmetic for range propagation (RP-1, RP-2)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import count


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise ValueError(f"empty interval [{self.lo}, {self.hi}]")

    def __contains__(self, x: float) -> bool:
        return self.lo <= x <= self.hi

    @property
    def max_abs(self) -> float:
        return max(abs(self.lo), abs(self.hi))

    def add(self, o: Interval) -> Interval:
        return Interval(self.lo + o.lo, self.hi + o.hi)

    def sub(self, o: Interval) -> Interval:
        return Interval(self.lo - o.hi, self.hi - o.lo)

    def neg(self) -> Interval:
        return Interval(-self.hi, -self.lo)

    def abs_(self) -> Interval:
        if 0.0 in self:
            return Interval(0.0, self.max_abs)
        return Interval(min(abs(self.lo), abs(self.hi)), self.max_abs)

    def mul(self, o: Interval) -> Interval:
        products = (self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi)
        return Interval(min(products), max(products))

    def square(self) -> Interval:
        a = self.abs_()
        return Interval(a.lo * a.lo, a.hi * a.hi)

    def div(self, o: Interval) -> Interval:
        """Division; a divisor interval containing 0 yields an unbounded result."""
        if 0.0 in o:
            return Interval(-math.inf, math.inf)
        inv = Interval(1.0 / o.hi, 1.0 / o.lo)
        return self.mul(inv)

    def sqrt(self) -> Interval:
        lo = math.sqrt(max(self.lo, 0.0))
        hi = math.sqrt(max(self.hi, 0.0))
        return Interval(lo, hi)

    def max_(self, o: Interval) -> Interval:
        return Interval(max(self.lo, o.lo), max(self.hi, o.hi))

    def min_(self, o: Interval) -> Interval:
        return Interval(min(self.lo, o.lo), min(self.hi, o.hi))

    def hull(self, o: Interval) -> Interval:
        return Interval(min(self.lo, o.lo), max(self.hi, o.hi))


_noise_ids = count(1)


@dataclass(frozen=True)
class Affine:
    """Affine form x0 + Σ xi·εi, εi ∈ [-1, 1] (RP-2).

    Linear operations are exact (correlations preserved — `x - x` is 0,
    unlike intervals); multiplication adds one fresh noise term bounding
    the nonlinear residue.
    """

    center: float
    terms: dict[int, float] = field(default_factory=dict)

    @classmethod
    def from_interval(cls, iv: Interval) -> Affine:
        if math.isinf(iv.lo) or math.isinf(iv.hi):
            return cls(0.0, {next(_noise_ids): math.inf})
        mid = (iv.hi + iv.lo) / 2.0
        rad = (iv.hi - iv.lo) / 2.0
        if rad == 0.0:
            return cls(mid, {})
        return cls(mid, {next(_noise_ids): rad})

    @property
    def radius(self) -> float:
        return sum(abs(v) for v in self.terms.values())

    def to_interval(self) -> Interval:
        r = self.radius
        return Interval(self.center - r, self.center + r)

    def _combine(self, o: Affine, sign: float) -> dict[int, float]:
        out = dict(self.terms)
        for k, v in o.terms.items():
            out[k] = out.get(k, 0.0) + sign * v
        return {k: v for k, v in out.items() if v != 0.0}

    def add(self, o: Affine) -> Affine:
        return Affine(self.center + o.center, self._combine(o, 1.0))

    def sub(self, o: Affine) -> Affine:
        return Affine(self.center - o.center, self._combine(o, -1.0))

    def neg(self) -> Affine:
        return Affine(-self.center, {k: -v for k, v in self.terms.items()})

    def scale(self, c: float) -> Affine:
        return Affine(self.center * c, {k: v * c for k, v in self.terms.items()})

    def mul(self, o: Affine) -> Affine:
        center = self.center * o.center
        terms: dict[int, float] = {}
        for k, v in self.terms.items():
            terms[k] = terms.get(k, 0.0) + o.center * v
        for k, v in o.terms.items():
            terms[k] = terms.get(k, 0.0) + self.center * v
        residue = self.radius * o.radius
        if residue:
            terms[next(_noise_ids)] = residue
        return Affine(center, {k: v for k, v in terms.items() if v != 0.0})

    def square(self) -> Affine:
        return self.mul(self)

    # nonlinear ops fall back through the interval hull
    def via_interval(self, fn: str, other: Affine | None = None) -> Affine:
        iv = self.to_interval()
        if fn == "sqrt":
            return Affine.from_interval(iv.sqrt())
        if fn == "abs":
            return Affine.from_interval(iv.abs_())
        if other is not None:
            ov = other.to_interval()
            if fn == "div":
                return Affine.from_interval(iv.div(ov))
            if fn == "max":
                return Affine.from_interval(iv.max_(ov))
            if fn == "min":
                return Affine.from_interval(iv.min_(ov))
        raise ValueError(f"unsupported affine op {fn!r}")
