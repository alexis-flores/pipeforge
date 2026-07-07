# Changelog

## 0.2.2 — 2026-07-07

- **UX-1 action toasts**: every action now answers in the corner — kind-styled
  (✓ success / ✵ info / ⚠ warning / ✕ error), stacking up to three with a
  slide-in, and carrying one-click actions where they help (a failing co-sim
  offers **Bisection ▸**; problems offer **details** → console). Optimize
  reports what it actually did ("Wrote `x_opt.m` — 48→52 cycles, dividers
  3→1"), co-sim PASS/FAIL summarizes per-output results, `.mat` loads confirm
  shape-awareness.
- **UX-2 Activity panel** (Ctrl+J, View → Toggle Activity): a persistent,
  newest-first history of everything done this session — files opened,
  audits (with latency/finding deltas: "(was 48)"), optimizes, generated
  `.sv`/wrappers, co-sim verdicts, range propagation, sidecar writes — each
  with a timestamp, kind dot, and an **Open** button for entries that wrote a
  file. Tabbed with the console; entries mirror to the console log.

## 0.2.1 — 2026-07-07

- **WS-8 Workspace data cards**: the Workspace view's new Data tab renders one
  card per snapshot variable — sparklines (area fill, zero-line, min/max) for
  signals, heatmaps for matrices, large numerals for scalars, class chips —
  custom-painted in the timeline's theme-token language. Cards click-select
  the matching DAG node; the filter box drives cards and table alike.

## 0.2.0 — 2026-07-07

The "engineers' workflow" release: PipeForge now closes the loop from MATLAB
to waveform viewer, CI gate, and integration-ready RTL — and got a star. ✵

### Data-driven analysis, no MATLAB
- **WS-7 static `.mat` snapshots**: `pipeforge-cli mat2json params.mat`
  converts a `.mat` (v5/v7/v7.3, nested structs → dotted names) into the same
  snapshot JSON the live bridge produces — pure Python, no MATLAB. Every
  `--snapshot` flag also accepts a `.mat` directly, and the GUI builds the
  snapshot the moment a `.mat` opens (status chip: `.mat ✓`): shape-aware
  audits (`A * v` → `matmul`), real-data ranges, and `optimize --snapshot`
  comparing accuracy over your actual values. `fi` types still need the live
  bridge (opaque MCOS blobs in `.mat` files).

### Loops become hardware
- **LP-1 constant-loop unrolling**: `for k = 1:N` with literal bounds unrolls
  into pipeline structure automatically (nested/stepped/negative ranges;
  budgeted; UNROLL finding). Non-constant bounds keep the recurrence
  interpretation (FEEDBACK). Findings dedupe by value identity so unrolled
  iterations never produce false RECIP/CSE hits.
- **LN-1 element lanes**: constant indexing is real — `x(3)` is a scalar
  input lane, `y(2) = …` defines lane `y_2`, map loops become parallel
  hardware, and `.mat` snapshots resolve lanes from the base array
  (column-major). Cosim harness/testbench port names sanitize accordingly.
- **LP-2 BALANCE**: `optimize` restructures addition chains and constant
  accumulator loops into balanced adder trees — bit-exact (wrap addition),
  depth N → ⌈log₂N⌉+1. Verilator-proved: unrolled Newton, lane map loops,
  and a balanced 8-tap dot product all cosim bit-exact.
- Fixed en route: a testbench/pipe race where matlib's RAM-backed pipes
  (DELAY>32) dropped the first sample fed on the reset-release edge — the
  generated benches now idle one settle cycle.

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
