# fxp semantics — nkMatlib RTL citations (FX-2)

Every behavioral decision in `pipeforge.core.fxp` is derived from the nkMatlib
source (`matlib-main/rtl/`). Where the README and the RTL disagree, the RTL wins.

| Decision | Behavior implemented | Source |
|---|---|---|
| Number representation | WIDTH-bit two's complement, SCALE fractional bits; LEFT = WIDTH−SCALE | `fixedp.sv` |
| Float→fixed (`from_float`) | `x * 2^SCALE`, rounded to nearest, ties away from zero, then wrapped to WIDTH | `macros.svh:69` — `TOFIXED` uses SV real→longint conversion (IEEE 1800 §6.12.2 rounds to nearest, ties away from zero), then a width cast that truncates |
| Format conversion (`snorm_raw`) | Scale up: shift left, zero-fill; scale down: bit-slice `a[A_WIDTH-1:A_SCALE-F_SCALE]` = arithmetic right shift, i.e. **floor (toward −∞)**; width shrink wraps, width grow sign-extends | `norm.sv:17-38`, `snorm.sv` (identical generate logic). Note: the README ("rounds towards 0") is inaccurate for negative values; the RTL slices bits, which floors |
| Add/sub | WIDTH-bit wrap, no saturation, latency 1 | `add.sv`, `sub.sv`, `matadd.sv` |
| 3-input adds | `matadd3` = a+b+c, `matadd3b1` = a+b−c, `matadd3b2` = a−b−c, single 1-cycle stage | `matadd3.sv`, `matadd3b1.sv`, `matadd3b2.sv` |
| Negate | two's complement wrap; −(min) wraps to min | `neg.sv` |
| Absolute value | conditional negate on sign bit; `abs(min_raw)` wraps to itself | `abs.sv:30-34` |
| Multiply (`smul`) | exact 2W-bit signed product (`smul_raw.sv`), then `norm` (2W,2S)→(W,S): **floor** shift by SCALE, wrap to WIDTH. Overflow check exists only under `ifdef junk` (disabled) | `smul.sv:36-47`, `smul_raw.sv:44-58` |
| Square (`ssqr`) | `smul(a, a)` | `ssqr.sv` |
| Divide (`sdiv`) | dividend normalized (W,S)→(W+S,2S) (pre-scale by 2^S), divisor (W,S)→(W+S,S); **sign-magnitude**: unsigned non-restoring divide of magnitudes, sign applied afterward ⇒ quotient **truncates toward zero**; result wraps (W+S)→(W) by dropping top bits | `sdiv.sv:36-76`, `sdiv_raw.sv:33-56`, `udiv_raw.sv`, `udiv_step.sv:28-49` |
| Divide by zero | non-restoring loop with M=0 yields all-ones quotient (`2^W−1` pattern) and remainder = dividend; the model replicates the hardware loop bit-for-bit rather than special-casing | `udiv_step.sv` (algorithmic consequence; verified against the loop) |
| Reciprocal (`sinv`) | `sdiv_raw` with dividend constant 1.0 at scale 2S | `sinv.sv:33-58` |
| Square root (`usqrt`) | Meessen bit-serial algorithm: WIDTH−LEFT/2 steps over (WIDTH+1)-bit r/q/b registers; result = `q[WIDTH-1:LEFT/2]` zero-extended. Equals `floor(sqrt(raw · 2^SCALE))` for non-negative inputs (verified exhaustively for small widths) | `usqrt.sv:28-52`, `sqrt_step.sv:103-127` |
| Negative sqrt input | undefined by the RTL (runtime `$display` guard is under `ifdef junk`); the model computes the same loop on the raw bits | `usqrt.sv:36-43` |
| max/min | signed comparison, pass-through of the winning bit pattern | `smax.sv`, `smin.sv` |
| Right shift (`rshift`) | logical (unsigned) shift of the bit pattern | `elem_rshift.sv` (README: "unsigned right-shift") |
| `sumsqr` | each element squared via `ssqr` (renormalized to (W,S) individually), then summed with WIDTH-bit **wrap** — *not* full-precision accumulation | `sumsqr.sv:36-49` |
| `matmul` / `dotprod` | identical pattern: per-product `smul` renormalization, then wrapped W-bit accumulation | `matmul.sv:38-60` |
| `rootsqr` | `usqrt(sumsqr(v))` | `rootsqr.sv` |
| `crossp` | `f[i] = smul(a[i+1],b[i+2]) − smul(a[i+2],b[i+1])` (1-based circular), wrap subtract | `crossp.sv:30-46` |

Latencies are *not* modeled here (they live in `core/costmodel`); fxp computes
the steady-state value each module produces.

## Array layout — the column-major contract (AR-3 / AR-4)

Array-valued operands are stored as a flat list in **MATLAB column-major
(Fortran) order**: column 1 first, then column 2, and so on. For an `R×C`
operand, the element at (1-based) row `r`, column `c` lives at flat index

```
flat = (c - 1) * R + (r - 1)        # 0-based flat index
r - 1 = flat mod R,  c - 1 = flat div R
```

This is the **same order MATLAB uses when it flattens or `reshape`s**, and it
must match how the nkMatlib RTL packs a `[R][C]` (`[R-1:0][C-1:0]`) operand —
the first `R` elements are column 1. `reshape` is therefore a pure index remap:
the flat column-major list is unchanged, so the golden model evaluates it as a
value-preserving pass-through (no arithmetic, no latency, no operator instance).

Because both the golden model and the RTL index by this single rule,
co-simulation and bisection compare element-for-element by physical position: a
reported mismatch at flat index `k` refers to the same `(row, col)` element on
both sides. A `24×1 ↔ 8×3` reshape pair is exercised against real RTL by
`tests/integration/test_reshape_cosim.py` (skipped without Verilator).
