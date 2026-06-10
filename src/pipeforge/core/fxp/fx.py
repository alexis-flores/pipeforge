"""Fixed-point value type mirroring nkMatlib's `fixedp` semantics (FX-1).

A value is a WIDTH-bit two's-complement bit pattern with SCALE fractional
bits. The raw bit pattern is the ground truth (it is what the RTL carries);
floats are only views. See docs/fxp_semantics.md for RTL citations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FxFormat:
    """WIDTH/SCALE pair; LEFT = WIDTH - SCALE (fixedp.sv)."""

    width: int
    scale: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.scale < 0 or self.scale >= self.width:
            raise ValueError(f"invalid format WIDTH={self.width} SCALE={self.scale}")

    @property
    def left(self) -> int:
        return self.width - self.scale

    @property
    def mask(self) -> int:
        return (1 << self.width) - 1

    @property
    def min_raw(self) -> int:
        """Most negative representable raw (as a bit pattern)."""
        return 1 << (self.width - 1)

    @property
    def max_signed(self) -> int:
        return (1 << (self.width - 1)) - 1

    @property
    def min_signed(self) -> int:
        return -(1 << (self.width - 1))


def wrap(value: int, width: int) -> int:
    """Truncate to a width-bit two's-complement bit pattern (overflow wraps)."""
    return value & ((1 << width) - 1)


def to_signed(raw: int, width: int) -> int:
    """Interpret a width-bit pattern as a signed integer."""
    raw &= (1 << width) - 1
    if raw >> (width - 1):
        return raw - (1 << width)
    return raw


def from_float(x: float, fmt: FxFormat) -> int:
    """Float -> raw bits, as `TOFIXED` does (macros.svh:69).

    SystemVerilog real-to-longint conversion rounds to the nearest integer
    with ties away from zero (IEEE 1800 §6.12.2), then the cast to WIDTH
    bits wraps.
    """
    scaled = x * float(1 << fmt.scale)
    # round half away from zero
    if scaled >= 0:
        as_int = int(scaled + 0.5)
    else:
        as_int = -int(-scaled + 0.5)
    return wrap(as_int, fmt.width)


def to_float(raw: int, fmt: FxFormat) -> float:
    """Raw bits -> float, as `TOFLOAT` does (macros.svh)."""
    return to_signed(raw, fmt.width) / float(1 << fmt.scale)


@dataclass(frozen=True)
class Fx:
    """A fixed-point value: raw bit pattern plus its format."""

    raw: int
    fmt: FxFormat

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", self.raw & self.fmt.mask)

    @classmethod
    def from_value(cls, x: float, fmt: FxFormat) -> Fx:
        return cls(from_float(x, fmt), fmt)

    @property
    def signed(self) -> int:
        return to_signed(self.raw, self.fmt.width)

    @property
    def value(self) -> float:
        return to_float(self.raw, self.fmt)

    def __repr__(self) -> str:
        return f"Fx({self.value}, raw=0x{self.raw:x}, {self.fmt.width}/{self.fmt.scale})"
