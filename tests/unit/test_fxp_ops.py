"""Bit-exact operator tests (FX-1, FX-2) with hypothesis property suites (FX-5).

Each property runs >= 200 randomized cases (Phase 2 gate).
"""

from __future__ import annotations

import math

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from pipeforge.core.fxp import ops
from pipeforge.core.fxp.fx import Fx, FxFormat, from_float, to_float, to_signed, wrap

FMT = FxFormat(16, 12)
FORMATS = [FxFormat(16, 12), FxFormat(18, 14), FxFormat(12, 8), FxFormat(20, 12)]

raw16 = st.integers(min_value=0, max_value=(1 << 16) - 1)
fmt_st = st.sampled_from(FORMATS)


def raws(fmt: FxFormat) -> st.SearchStrategy[int]:
    return st.integers(min_value=0, max_value=fmt.mask)


@pytest.mark.req("FX-1")
class TestFxType:
    def test_round_trip_exact_values(self) -> None:
        for v in [0.0, 1.0, -1.0, 0.5, -0.25, 3.75, -7.5]:
            assert to_float(from_float(v, FMT), FMT) == v

    def test_tofixed_rounds_to_nearest(self) -> None:
        # 0.0001 is below half an LSB (LSB = 2^-12); rounds to 0
        assert from_float(0.0001, FMT) == 0
        # half an LSB rounds away from zero
        half_lsb = 0.5 / (1 << 12)
        assert from_float(half_lsb, FMT) == 1
        assert from_float(-half_lsb, FMT) == wrap(-1, 16)

    def test_fx_wrapper(self) -> None:
        x = Fx.from_value(-1.5, FMT)
        assert x.value == -1.5
        assert x.signed == -(3 << 11)
        assert 0 <= x.raw <= FMT.mask


@pytest.mark.req("FX-5")
class TestWrapConsistency:
    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f), raws(f))))
    @settings(max_examples=300, deadline=None)
    def test_add_sub_wrap(self, t: tuple[FxFormat, int, int]) -> None:
        fmt, a, b = t
        s = ops.add(a, b, fmt)
        assert to_signed(s, fmt.width) == to_signed(
            wrap(to_signed(a, fmt.width) + to_signed(b, fmt.width), fmt.width), fmt.width
        )
        assert ops.sub(s, b, fmt) == a  # add then sub round-trips exactly

    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f))))
    @settings(max_examples=300, deadline=None)
    def test_neg_involution(self, t: tuple[FxFormat, int]) -> None:
        fmt, a = t
        assert ops.neg(ops.neg(a, fmt), fmt) == a

    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f))))
    @settings(max_examples=300, deadline=None)
    def test_abs_nonnegative_or_wrapped_min(self, t: tuple[FxFormat, int]) -> None:
        fmt, a = t
        r = ops.abs_(a, fmt)
        if a == fmt.min_raw:  # |most negative| wraps to itself (abs.sv)
            assert r == fmt.min_raw
        else:
            assert to_signed(r, fmt.width) == abs(to_signed(a, fmt.width))


@pytest.mark.req("FX-2")
class TestSmul:
    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f), raws(f))))
    @settings(max_examples=300, deadline=None)
    def test_smul_is_floored_full_product(self, t: tuple[FxFormat, int, int]) -> None:
        fmt, a, b = t
        expect = wrap((to_signed(a, fmt.width) * to_signed(b, fmt.width)) >> fmt.scale, fmt.width)
        assert ops.smul(a, b, fmt) == expect

    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f), raws(f))))
    @settings(max_examples=200, deadline=None)
    def test_smul_commutes(self, t: tuple[FxFormat, int, int]) -> None:
        fmt, a, b = t
        assert ops.smul(a, b, fmt) == ops.smul(b, a, fmt)


@pytest.mark.req("FX-5")
class TestSdiv:
    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f), raws(f))))
    @settings(max_examples=300, deadline=None)
    def test_sdiv_truncates_toward_zero(self, t: tuple[FxFormat, int, int]) -> None:
        fmt, a, b = t
        sa, sb = to_signed(a, fmt.width), to_signed(b, fmt.width)
        if sb == 0:
            return
        q = abs(sa << fmt.scale) // abs(sb)
        if (sa < 0) != (sb < 0):
            q = -q
        assert ops.sdiv(a, b, fmt) == wrap(q, fmt.width)

    def test_divide_by_zero_is_hardware_faithful(self) -> None:
        # non-restoring loop with M=0: all-ones quotient (docs/fxp_semantics.md)
        q, r = ops.udiv_raw(5, 0, 8)
        assert q == 0xFF
        assert r == 5

    @given(fmt_st.flatmap(lambda f: st.tuples(st.just(f), raws(f))))
    @settings(max_examples=200, deadline=None)
    def test_sinv_matches_sdiv_of_one(self, t: tuple[FxFormat, int]) -> None:
        fmt, a = t
        sa = to_signed(a, fmt.width)
        if sa == 0:
            return
        # 1/a truncated toward zero: (1.0 at scale 2S) / (|a| at scale S) -> scale S
        expect = (1 << (2 * fmt.scale)) // abs(sa)
        if sa < 0:
            expect = -expect
        assert ops.sinv(a, fmt) == wrap(expect, fmt.width)


@pytest.mark.req("FX-5")
class TestUsqrt:
    @given(
        fmt_st.flatmap(lambda f: st.tuples(st.just(f), st.integers(0, (1 << (f.width - 1)) - 1)))
    )
    @settings(max_examples=400, deadline=None)
    def test_usqrt_equals_isqrt_of_prescaled(self, t: tuple[FxFormat, int]) -> None:
        fmt, a = t
        assert ops.usqrt(a, fmt) == math.isqrt(a << fmt.scale)

    @given(
        fmt_st.flatmap(
            lambda f: st.tuples(
                st.just(f),
                st.integers(0, (1 << (f.width - 1)) - 2),
                st.integers(1, 1 << (f.width - 2)),
            )
        )
    )
    @settings(max_examples=300, deadline=None)
    def test_usqrt_monotone(self, t: tuple[FxFormat, int, int]) -> None:
        fmt, a, delta = t
        b = min(a + delta, (1 << (fmt.width - 1)) - 1)
        assert ops.usqrt(a, fmt) <= ops.usqrt(b, fmt)


@pytest.mark.req("FX-5")
class TestSnorm:
    @given(raw16)
    @settings(max_examples=300, deadline=None)
    def test_snorm_round_trip_within_precision(self, a: int) -> None:
        # widen scale and width, then come back: must be lossless
        src = FxFormat(16, 12)
        dst = FxFormat(24, 18)
        up = ops.snorm(a, src, dst)
        back = ops.snorm(up, dst, src)
        assert back == a

    @given(raw16)
    @settings(max_examples=300, deadline=None)
    def test_snorm_scale_down_floors(self, a: int) -> None:
        src = FxFormat(16, 12)
        dst = FxFormat(16, 8)
        got = ops.snorm(a, src, dst)
        expect = wrap(to_signed(a, 16) >> 4, 16)  # arithmetic shift = floor
        assert got == expect


class TestVectorOps:
    def test_sumsqr_wraps_like_rtl(self) -> None:
        # products renormalized first, then W-bit wrapped sum (sumsqr.sv)
        fmt = FMT
        big = from_float(7.9, fmt)
        vec = [big, big, big]
        expect = 0
        for x in vec:
            expect = wrap(expect + ops.ssqr(x, fmt), fmt.width)
        assert ops.sumsqr(vec, fmt) == expect

    def test_rootsqr_3_4_5(self) -> None:
        fmt = FMT
        v = [from_float(0.3, fmt), from_float(0.4, fmt)]
        r = to_float(ops.rootsqr(v, fmt), fmt)
        assert abs(r - 0.5) < 0.002

    def test_crossp_unit_vectors(self) -> None:
        fmt = FMT
        x = [from_float(v, fmt) for v in (1.0, 0.0, 0.0)]
        y = [from_float(v, fmt) for v in (0.0, 1.0, 0.0)]
        z = [to_float(r, fmt) for r in ops.crossp(x, y, fmt)]
        assert z == [0.0, 0.0, 1.0]

    def test_matmul_identity(self) -> None:
        fmt = FMT
        one = from_float(1.0, fmt)
        zero = 0
        ident = [[one, zero], [zero, one]]
        m = [[from_float(0.5, fmt), from_float(1.5, fmt)], [from_float(-2.0, fmt), one]]
        assert ops.matmul(ident, m, fmt) == m

    def test_smax_smin(self) -> None:
        fmt = FMT
        a = from_float(-1.0, fmt)
        b = from_float(0.5, fmt)
        assert ops.smax(a, b, fmt) == b
        assert ops.smin(a, b, fmt) == a

    def test_rshift_logical(self) -> None:
        fmt = FMT
        a = wrap(-4096, 16)  # -1.0: sign bit set
        assert ops.rshift(a, 1, fmt) == (a & fmt.mask) >> 1  # zero-filled
