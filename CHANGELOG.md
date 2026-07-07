# Changelog

## 0.2.0 — 2026-07-06

The "engineers' workflow" release: PipeForge now closes the loop from MATLAB
to waveform viewer, CI gate, and integration-ready RTL — and got a star. ✵

### Language & frontend
- **Local functions** (FN-1): scripts may define `function out = name(args) … end`
  after the body; calls inline hygienically at every call site (nested calls
  supported; recursion and non-self-contained bodies are reported per-statement).
- **`delay(x)` unit delay** (SD-1): z⁻¹ state for streaming filters (FIR taps,
  moving averages). Stateful golden-model evaluation threads through cosim,
  bisection, DSE, and the oracle; generated RTL is bit-exact under Verilator.
  A runnable MATLAB stub is documented (persistent-variable `delay.m`).
- **Indexing/field/range wiring in codegen** (WR-1): pass-through semantics the
  auditor and golden model already used; only multi-element concatenation
  remains an explicit error.

### Optimization
- **`pipeforge-cli optimize`** (OP-1): applies the auditor's rewrites —
  RECIP, CDIV, SERDIV, POW, CSE — to the MATLAB *source* (readable output,
  `% pipeforge:` markers, untouched lines byte-identical) with the critical-path
  delta and an honest per-output accuracy comparison. Also in the Audit view.
- **Mixed-precision codegen** (MX-1, since the previous cycle): `codegen
  --mixed` narrows range-proven operators; verify with `cosim --range`.

### Verification & debug
- **Waveform hand-off** (WV-1): failing traced runs write `divergence.gtkw` —
  GTKWave opens with the divergent stage pre-loaded, cursor on the failing cycle.
- **Failure replay** (VX-1) and **standalone testbench export** (VX-2).
- **Verilator lint backend** (SL-7), **auto backend selection** (TL-2: cocotb
  when importable, else the Verilator-native harness), and a cocotb 2.x
  waves/trace fix.

### Projects & CI
- **`.pipeforge.toml` design sidecar** (PJ-1): ranges, format, cosim config,
  and device family persist next to the `.m`; the GUI restores them on open.
- **`pipeforge-cli ci design.pipeforge.toml`** (PJ-2): the whole configured
  gate — audit, ranges, lint, cosim — in one command with JUnit/SARIF outputs.
- JUnit XML (CI-1), SARIF (CI-2), HTML design-review report (RH-1),
  `--watch` mode (WT-1), yosys synth estimate (SY-1), device resource
  estimates (RE-1), AXI-Stream wrapper generation (AX-1).

### GUI
- Welcome screen, menu bar, workflow-ordered labeled sidebar, Ranges view,
  recent files, drag-and-drop (previous cycle); this cycle adds timeline
  **Ctrl+wheel zoom**, **type-to-find**, range **overflow/÷0 badges** on the
  bars, and project-sidecar restore for ranges and cosim configuration.

### Cosmetics
- `pipeforge-cli` greets interactive terminals with a big ✵. Pipes, CI, and
  tests never see it (`PIPEFORGE_BANNER=0/1` overrides).

## 0.1.0 — 2026-06

Initial baseline per PF-SRS-001 Rev A: audit, golden model, co-simulation,
bisection, linter, codegen, ranges, DSE, MATLAB bridge, mapping, GUI.
