"""Bit-exact nkMatlib operator semantics (FX-1, FX-2).

Every function here mirrors one nkMatlib RTL module bit-for-bit, including
overflow wrap, truncation direction, and divide-by-zero behavior. Citations
to the defining SV source are in docs/fxp_semantics.md. All functions take
and return raw bit patterns (ints in [0, 2^WIDTH)).
"""

from __future__ import annotations

from pipeforge.core.fxp.fx import FxFormat, to_signed, wrap

# ---------------------------------------------------------------------------
# Format conversion (norm.sv / snorm.sv / elem_snorm.sv)
# ---------------------------------------------------------------------------


def snorm_raw(raw: int, a_width: int, a_scale: int, f_width: int, f_scale: int) -> int:
    """norm.sv generate logic, verbatim: shift then slice/sign-extend.

    Scaling down drops low bits by a bit slice — an arithmetic shift right,
    i.e. rounding toward negative infinity. Width reduction wraps (top bits
    dropped); width extension sign-extends.
    """
    raw &= (1 << a_width) - 1
    if f_scale >= a_scale:
        t_width = a_width + f_scale - a_scale
        tmp = raw << (f_scale - a_scale)
    else:
        shift = a_scale - f_scale
        t_width = a_width - shift
        tmp = raw >> shift
    if t_width >= f_width:
        return tmp & ((1 << f_width) - 1)
    if (tmp >> (t_width - 1)) & 1:  # sign-extend
        tmp |= ((1 << f_width) - 1) ^ ((1 << t_width) - 1)
    return tmp


def snorm(raw: int, src: FxFormat, dst: FxFormat) -> int:
    return snorm_raw(raw, src.width, src.scale, dst.width, dst.scale)


# ---------------------------------------------------------------------------
# Add / sub / neg / abs / max / min / shift (add.sv, sub.sv, neg.sv, abs.sv,
# smax.sv, smin.sv, elem_rshift.sv) — latency-1 wrap arithmetic
# ---------------------------------------------------------------------------


def add(a: int, b: int, fmt: FxFormat) -> int:
    return wrap(a + b, fmt.width)


def sub(a: int, b: int, fmt: FxFormat) -> int:
    return wrap(a - b, fmt.width)


def add3(a: int, b: int, c: int, fmt: FxFormat) -> int:
    return wrap(a + b + c, fmt.width)


def add3b1(a: int, b: int, c: int, fmt: FxFormat) -> int:
    """matadd3b1: a + b - c."""
    return wrap(a + b - c, fmt.width)


def add3b2(a: int, b: int, c: int, fmt: FxFormat) -> int:
    """matadd3b2: a - b - c."""
    return wrap(a - b - c, fmt.width)


def neg(a: int, fmt: FxFormat) -> int:
    return wrap(-a, fmt.width)


def abs_(a: int, fmt: FxFormat) -> int:
    """abs.sv: conditional negate; |min_raw| wraps to itself."""
    if (a >> (fmt.width - 1)) & 1:
        return wrap(-a, fmt.width)
    return a & fmt.mask


def smax(a: int, b: int, fmt: FxFormat) -> int:
    return a if to_signed(a, fmt.width) >= to_signed(b, fmt.width) else b


def smin(a: int, b: int, fmt: FxFormat) -> int:
    return a if to_signed(a, fmt.width) <= to_signed(b, fmt.width) else b


def rshift(a: int, sh: int, fmt: FxFormat) -> int:
    """elem_rshift: unsigned (logical) right shift of the bit pattern."""
    return (a & fmt.mask) >> sh


# ---------------------------------------------------------------------------
# Multiply (smul.sv = smul_raw.sv full product + norm.sv renormalize)
# ---------------------------------------------------------------------------


def smul(a: int, b: int, fmt: FxFormat) -> int:
    """Exact 2W-bit signed product, renormalized (2W,2S) -> (W,S).

    The renormalization is norm.sv: arithmetic shift right by SCALE (floor),
    then wrap to WIDTH bits. Overflow wraps silently (smul.sv's check is
    compiled out under `ifdef junk`).
    """
    prod = to_signed(a, fmt.width) * to_signed(b, fmt.width)
    return wrap(prod >> fmt.scale, fmt.width)


def ssqr(a: int, fmt: FxFormat) -> int:
    """ssqr.sv: smul with both operands tied together."""
    return smul(a, a, fmt)


# ---------------------------------------------------------------------------
# Divide (sdiv.sv -> sdiv_raw.sv -> udiv_raw.sv non-restoring array)
# ---------------------------------------------------------------------------


def udiv_raw(dividend: int, divisor: int, width: int) -> tuple[int, int]:
    """udiv_raw.sv / udiv_step.sv: non-restoring division, bit-faithful.

    Replicating the hardware loop (rather than using Python //) preserves
    exact behavior for divide-by-zero and quotient-overflow cases.
    """
    mask_w = (1 << width) - 1
    mask_2w = (1 << (2 * width)) - 1
    aq = dividend & mask_w  # {W'0, dividend}
    q = 0
    m = divisor & mask_w
    for _ in range(width):
        shift = (aq << 1) & mask_2w
        top = (shift >> width) & mask_w
        if (aq >> (2 * width - 1)) & 1:
            new_top = (top + m) & mask_w
        else:
            new_top = (top + ((~m) & mask_w) + 1) & mask_w
        aq = ((new_top << width) | (shift & mask_w)) & mask_2w
        q = ((q << 1) | (1 - ((aq >> (2 * width - 1)) & 1))) & mask_w
    if (aq >> (2 * width - 1)) & 1:  # final remainder correction
        aq = (aq + (m << width)) & mask_2w
    return q, (aq >> width) & mask_w


def sdiv_raw(dividend: int, divisor: int, width: int) -> tuple[int, int]:
    """sdiv_raw.sv: sign-magnitude wrapper -> quotient truncates toward zero."""
    mask = (1 << width) - 1
    dividend_neg = (dividend >> (width - 1)) & 1
    divisor_neg = (divisor >> (width - 1)) & 1
    dividend_pos = wrap(-dividend, width) if dividend_neg else dividend & mask
    divisor_pos = wrap(-divisor, width) if divisor_neg else divisor & mask
    q_pos, r_pos = udiv_raw(dividend_pos, divisor_pos, width)
    q = wrap(-q_pos, width) if dividend_neg ^ divisor_neg else q_pos
    r = wrap(-r_pos, width) if dividend_neg else r_pos
    return q, r


def sdiv(a: int, b: int, fmt: FxFormat) -> int:
    """sdiv.sv: pre-scale dividend by 2^SCALE into a (W+S)-bit divider."""
    div_width = fmt.width + fmt.scale  # DIV_WIDTH = 2S + W - S
    a_norm = snorm_raw(a, fmt.width, fmt.scale, div_width, 2 * fmt.scale)
    b_norm = snorm_raw(b, fmt.width, fmt.scale, div_width, fmt.scale)
    q, _ = sdiv_raw(a_norm, b_norm, div_width)
    return snorm_raw(q, div_width, fmt.scale, fmt.width, fmt.scale)


def sinv(a: int, fmt: FxFormat) -> int:
    """sinv.sv: 1/a via sdiv_raw with the dividend fixed at 1.0 (scale 2S)."""
    div_width = fmt.width + fmt.scale
    one = 1 << (2 * fmt.scale)
    a_norm = snorm_raw(a, fmt.width, fmt.scale, div_width, fmt.scale)
    q, _ = sdiv_raw(one, a_norm, div_width)
    return snorm_raw(q, div_width, fmt.scale, fmt.width, fmt.scale)


# ---------------------------------------------------------------------------
# Square root (usqrt.sv / sqrt_step.sv — Meessen bit-serial algorithm)
# ---------------------------------------------------------------------------


def usqrt(a: int, fmt: FxFormat) -> int:
    """usqrt.sv: WIDTH-(LEFT/2) steps over (WIDTH+1)-bit registers."""
    w = fmt.width
    half_left = fmt.left // 2
    steps = w - half_left
    mask_w1 = (1 << (w + 1)) - 1
    mask_w = (1 << w) - 1
    r = a & mask_w  # r[0] = {1'd0, a}
    q = 0
    b = 1 << (w - 2)
    for _ in range(steps):
        t = (q + b) & mask_w1
        if r >= t:
            newr = (r - t) & mask_w1
            r = ((newr & mask_w) << 1) & mask_w1
            q = (q + ((b & mask_w) << 1)) & mask_w1
        else:
            r = ((r & mask_w) << 1) & mask_w1
        b >>= 1
    # f = { LEFT/2'0, q[WIDTH-1:LEFT/2] }
    return (q & mask_w) >> half_left


# ---------------------------------------------------------------------------
# Vector reductions (sumsqr.sv, rootsqr.sv, matmul.sv, crossp.sv)
# Products are renormalized to (W,S) individually, THEN summed with W-bit
# wrap — not accumulated at full precision.
# ---------------------------------------------------------------------------


def sumsqr(vec: list[int], fmt: FxFormat) -> int:
    z = 0
    for x in vec:
        z = wrap(z + ssqr(x, fmt), fmt.width)
    return z


def rootsqr(vec: list[int], fmt: FxFormat) -> int:
    return usqrt(sumsqr(vec, fmt), fmt)


def dotprod(a: list[int], b: list[int], fmt: FxFormat) -> int:
    """One element of matmul.sv: sum of renormalized products, W-bit wrap."""
    z = 0
    for x, y in zip(a, b, strict=True):
        z = wrap(z + smul(x, y, fmt), fmt.width)
    return z


def matmul(a: list[list[int]], b: list[list[int]], fmt: FxFormat) -> list[list[int]]:
    rows = len(a)
    inner = len(b)
    cols = len(b[0]) if b else 0
    out: list[list[int]] = []
    for r in range(rows):
        if len(a[r]) != inner:
            raise ValueError("matmul shape mismatch")
        out.append([dotprod(a[r], [b[i][c] for i in range(inner)], fmt) for c in range(cols)])
    return out


def crossp(a: list[int], b: list[int], fmt: FxFormat) -> list[int]:
    """crossp.sv for COLS=3: f[i] = a[i+1]*b[i+2] - a[i+2]*b[i+1] (1-based, wrapped)."""
    n = len(a)
    if n != 3 or len(b) != 3:
        raise ValueError("crossp requires 3-vectors")

    def idx(i: int) -> int:  # 1-based circular as in the RTL
        return i - n if i > n else i

    out: list[int] = []
    for i in range(1, n + 1):
        u = smul(a[idx(i + 1) - 1], b[idx(i + 2) - 1], fmt)
        v = smul(a[idx(i + 2) - 1], b[idx(i + 1) - 1], fmt)
        out.append(sub(u, v, fmt))
    return out
