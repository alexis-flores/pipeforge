# FX-2 review checklist — fxp vs nkMatlib source

Phase 2 gate item: each operator's semantics doc entry re-read against the
cited SV source before sign-off.

- [x] `from_float` vs `macros.svh` TOFIXED (real→longint rounding + width cast)
- [x] `snorm_raw` vs `norm.sv` / `snorm.sv` all four generate branches
      (scale up/down × width grow/shrink); floor behavior on scale-down noted
      as deviating from the README's "towards 0" wording
- [x] `add`/`sub`/`add3*` vs `add.sv`/`sub.sv`/`matadd3*.sv` (wrap, no saturate)
- [x] `neg`/`abs_` vs `neg.sv`/`abs.sv` (most-negative wrap)
- [x] `smul`/`ssqr` vs `smul.sv`+`smul_raw.sv`+`norm.sv` (full product, floor renorm,
      overflow check disabled under `ifdef junk`)
- [x] `udiv_raw` vs `udiv_raw.sv`+`udiv_step.sv` (non-restoring loop, controlled
      negation, final remainder correction) — verified against Python `//` for
      20 000 random in-range cases and by the divide-by-zero pattern
- [x] `sdiv_raw` vs `sdiv_raw.sv` (sign-magnitude, sign pipes)
- [x] `sdiv` vs `sdiv.sv` (DIVIDEND_SCALE=2S, DIV_WIDTH=W+S, three norms)
- [x] `sinv` vs `sinv.sv` (constant dividend 1.0@2S)
- [x] `usqrt` vs `usqrt.sv`+`sqrt_step.sv` (W+1-bit regs, STEPS=W−LEFT/2,
      q slice) — matches `isqrt(raw<<SCALE)` on 20 000 random cases, 0 mismatches
- [x] `smax`/`smin` vs `smax.sv`/`smin.sv` (signed compare)
- [x] `rshift` vs `elem_rshift.sv` (logical shift)
- [x] `sumsqr`/`matmul`/`dotprod` vs `sumsqr.sv`/`matmul.sv` (renorm-then-wrap
      accumulation order)
- [x] `rootsqr` vs `rootsqr.sv` (sumsqr → usqrt)
- [x] `crossp` vs `crossp.sv` (1-based circular index, wrap subtract)
