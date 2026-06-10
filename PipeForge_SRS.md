# Software Requirements Specification

## PipeForge — MATLAB-to-nkMatlib FPGA Pipeline Workbench

| Field | Value |
|---|---|
| Document ID | PF-SRS-001 |
| Revision | A |
| Date | 2026-06-10 |
| Status | Baseline — approved for implementation |
| Classification | Unclassified // Personal project (no ITAR/export-controlled content shall be committed to this repository) |
| Author | A. Flores |
| Implementing agent | Claude Code |

### Revision History

| Rev | Date | Description |
|---|---|---|
| A | 2026-06-10 | Initial baseline |

---

## 1. Introduction

### 1.1 Purpose

This SRS defines the requirements for **PipeForge**, a desktop application (PyQt6) that audits, verifies, visualizes, and generates fixed-point FPGA pipeline implementations of MATLAB DSP code targeting the **nkMatlib** SystemVerilog library (github.com/nklabs/matlib). It is the binding specification for an AI coding agent (Claude Code) implementing the system. Where this document and agent judgment conflict, this document wins; where this document is silent, the agent shall choose the simplest implementation that passes the verification gates in §7.

### 1.2 Scope

PipeForge unifies eight capabilities into one application:

1. **Latency Audit** — static analysis of MATLAB scripts against the nkMatlib pipelined cost model (critical path, operator/area census, optimization findings).
2. **Golden Model** — a bit-exact Python fixed-point model of nkMatlib operator semantics.
3. **Co-Simulation** — automated three-way equivalence checking: float MATLAB reference ↔ bit-exact fixed-point model ↔ SystemVerilog RTL under Verilator.
4. **Mismatch Bisection** — automatic localization of the first divergent pipeline stage when RTL ≠ golden model.
5. **Pipeline Linter** — static SystemVerilog checks for nkMatlib convention violations (delay matching, stage suffixes, valid-chain integrity, reset discipline).
6. **Code Generation** — emission of nkMatlib SystemVerilog skeletons (operator instances + all `PIPE`/valid bookkeeping) from a MATLAB dataflow graph.
7. **Range & Precision Analysis** — interval/affine propagation through the dataflow graph; per-stage WIDTH/SCALE recommendation; overflow and divide-by-near-zero flags.
8. **Design-Space Exploration** — WIDTH/SCALE parameter sweeps producing error-vs-latency-vs-area Pareto fronts.

Out of scope: synthesis/place-and-route, timing closure, vendor toolchain integration (Vivado), floating-point RTL, MATLAB language features beyond the expression/assignment subset defined in §4.1, and any network services (the application is fully offline).

### 1.3 Definitions and Acronyms

| Term | Definition |
|---|---|
| nkMatlib | Pipelined fixed-point SystemVerilog matrix/vector library; throughput 1 result/clock; latency = dataflow critical path |
| WIDTH / SCALE / LEFT | Fixed-point total bits / fractional bits / integer bits (WIDTH − SCALE) |
| DIV_LAT, MUL_LAT, SQRT_LAT | nkMatlib operator latencies: WIDTH+SCALE, 4, WIDTH−LEFT/2 respectively |
| DAG | Directed acyclic dataflow graph extracted from MATLAB assignments |
| Golden model | Bit-exact software reference whose outputs must equal RTL outputs exactly |
| SQNR | Signal-to-quantization-noise ratio (dB), used for float↔fixed comparison |
| Gate | A phase exit criterion that must pass before the next phase begins |
| SHALL / SHOULD / MAY | RFC 2119 requirement levels |

### 1.4 References

- R1. nkMatlib README and source, github.com/nklabs/matlib (operator latency model of record)
- R2. `seed/matlib_audit.py` — existing, working latency auditor (parser, cost model, findings engine). **This file is provided and SHALL be the starting point for the core engine, refactored, not rewritten.**
- R3. Gruvbox color scheme specification (morhetz/gruvbox)
- R4. Verilator, cocotb, pyslang/Verible, Yosys/SymbiYosys documentation (external tools, all optional at runtime per §2.4)

### 1.5 Seed Assets

The repository SHALL begin with `seed/matlib_audit.py` (MATLAB tokenizer, recursive-descent expression parser, DAG latency scheduler, cost model, findings: RECIP/CDIV/SERDIV/POW/CSE/FUSE/FEEDBACK) and `seed/example.m`. Phase 1 consists of refactoring this seed into the package architecture of §3 **without behavioral regression**, enforced by golden-file tests captured before refactoring begins.

---

## 2. Overall Description

### 2.1 Product Perspective

Standalone desktop application. Layered architecture: a pure-Python, GUI-free **core engine** (importable as a library and usable from a CLI) wrapped by a PyQt6 **presentation layer**. Every capability SHALL be fully exercisable without the GUI; the GUI is a view over the engine, never the home of logic. External EDA tools (Verilator, cocotb, slang, Yosys) are invoked as subprocesses when present and degrade gracefully when absent.

### 2.2 User Characteristics

Single primary user: an embedded/FPGA engineer fluent in MATLAB, SystemVerilog, and fixed-point arithmetic. No onboarding flows, tutorials, or telemetry. Keyboard-first operation is expected.

### 2.3 Operating Environment

- OS: Linux (primary: Arch, Ubuntu 22.04+) and macOS (Apple Silicon). Windows is not a target.
- Python ≥ 3.11. PyQt6. Plotting: pyqtgraph. Graph layout: graphviz (`dot`) if present, else built-in layered fallback.
- Installation: `pip install -e .` in a venv; single entry point `pipeforge` (GUI) and `pipeforge-cli` (headless).

### 2.4 Constraints

- C1. The core engine SHALL have zero Qt imports (enforced by an architecture test, §8.5).
- C2. All external tools are OPTIONAL at runtime. Missing tools SHALL disable the dependent feature with an explanatory, actionable message — never a crash, never a hidden no-op.
- C3. No network access at runtime. No telemetry.
- C4. The nkMatlib latency model (R1) is the single source of truth for operator costs; all numbers SHALL be derived from WIDTH/SCALE at runtime, never hard-coded.
- C5. The repository SHALL contain no proprietary or export-controlled material; sample inputs are synthetic or from public sources.

### 2.5 Assumptions

- A1. Input MATLAB is script-style straight-line DSP code (assignments, expressions, simple loops); full MATLAB semantics are not required.
- A2. RTL under test follows nkMatlib conventions (R1): `_nn` stage suffixes, `PIPE` macros, valid chains, `fixedp` interface `g`.

---

## 3. System Architecture

### 3.1 Layering

```
┌─────────────────────────────────────────────────────────┐
│ pipeforge.gui        PyQt6 views, theming, workspace    │
├─────────────────────────────────────────────────────────┤
│ pipeforge.services   long-running jobs (QRunnable/      │
│                      subprocess orchestration, caching) │
├─────────────────────────────────────────────────────────┤
│ pipeforge.core       pure Python, no Qt:                │
│   frontend/   MATLAB tokenizer, parser, AST, DAG        │
│   costmodel/  nkMatlib latency & area model             │
│   audit/      findings engine (RECIP, CDIV, …)          │
│   fxp/        bit-exact fixed-point golden model        │
│   cosim/      stimulus gen, Verilator/cocotb harness    │
│   bisect/     divergence localization                   │
│   svlint/     SystemVerilog convention linter           │
│   codegen/    nkMatlib SV emitter                       │
│   ranges/     interval & affine arithmetic propagation  │
│   dse/        sweep driver, Pareto extraction           │
│   viz/        DAG layout (graphviz adapter + fallback)  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Repository Layout

```
pipeforge/
├── pyproject.toml            # deps, entry points, tool config (ruff, mypy, pytest)
├── seed/                     # provided assets (read-only reference)
├── src/pipeforge/
│   ├── core/...              # per §3.1
│   ├── services/
│   ├── gui/
│   │   ├── theme/            # token engine, gruvbox-dark-soft.json, others
│   │   ├── views/            # one module per capability
│   │   └── widgets/          # shared components
│   └── cli.py
├── tests/
│   ├── unit/                 # mirrors src tree
│   ├── golden/               # captured reference outputs (audit reports, codegen)
│   ├── integration/
│   └── gui/                  # pytest-qt
└── docs/
```

### 3.3 Data Flow

`*.m` file → frontend → **DAG (the central data structure)** → consumed by audit, codegen, ranges, dse, viz, cosim. The DAG type SHALL carry: per-node operator kind, mapped nkMatlib module, latency, ready-time, source line, and stable node IDs used consistently across all eight capabilities (a node selected in the visualizer is the same node named in an audit finding, a codegen instance, and a bisection report).

---

## 4. Functional Requirements

Each requirement carries: **ID**, statement, **Priority** (P0 = must ship, P1 = should ship, P2 = stretch), **Verification** (T = automated test, D = scripted demo, I = inspection, A = analysis). Phase mapping appears in §7.

### 4.1 MATLAB Frontend (FE)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FE-1 | The system SHALL parse MATLAB assignments containing: numeric literals, identifiers, array-index atoms (e.g. `n(:,1)` treated as opaque operands), operators `+ - * / \ .* ./ .\ ^ .^`, unary minus, transpose `'`/`.'`, parentheses, line continuations `...`, comments `%`, and calls to the known-function set of seed R2 (extensible via config). | P0 | T |
| FE-2 | The system SHALL build a DAG per file with variable def-use links across statements and SHALL detect self-referencing assignments (feedback). | P0 | T |
| FE-3 | Unparseable statements SHALL be reported with line number and reason in a "skipped" list; parsing SHALL never abort the file. | P0 | T |
| FE-4 | The frontend SHALL preserve exact source spans for every AST node so GUI views can highlight the originating MATLAB text. | P0 | T |
| FE-5 | The frontend SHOULD support simple `for` loops by unrolled or symbolic-trip-count analysis sufficient for feedback detection. | P1 | T |

### 4.2 Cost Model & Latency Audit (AU)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| AU-1 | The cost model SHALL compute, from WIDTH and SCALE: MUL_LAT=4, DIV_LAT=WIDTH+SCALE, SQRT_LAT=WIDTH−LEFT/2, MATMUL_LAT, SUMSQR_LAT, ROOTSQR_LAT, CROSSP_LAT, and unit/zero-latency ops, exactly as in R1/R2. | P0 | T |
| AU-2 | The auditor SHALL compute per-statement ready times, total critical-path latency, the dominant dependency chain, and an operator-instance census with divider count highlighted. | P0 | T |
| AU-3 | The auditor SHALL emit the seed finding set — RECIP, CDIV (incl. power-of-two → shift), SERDIV, POW, CSE, FUSE, FEEDBACK — each with line, estimated cycle savings, and a concrete rewrite suggestion. | P0 | T |
| AU-4 | Audit output SHALL be available as: structured Python objects, JSON, plain-text report, and the GUI view (AU findings link to FE-4 source spans and to viz nodes). | P0 | T |
| AU-5 | Golden-file tests SHALL pin the audit of `seed/example.m` (text and JSON) byte-for-byte modulo a version header. | P0 | T |

### 4.3 Bit-Exact Fixed-Point Golden Model (FX)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FX-1 | The fxp package SHALL implement a `Fx` value type (2's-complement, parameterized WIDTH/SCALE) and operator functions mirroring nkMatlib semantics: add, sub, neg, abs, smul, ssqr, sdiv, sinv, usqrt, smax, smin, rshift, snorm format conversion (truncation toward zero), matmul, sumsqr, rootsqr, crossp. | P0 | T |
| FX-2 | Rounding, truncation, overflow/wrap behavior of each operator SHALL match the nkMatlib RTL bit-for-bit. Where R1 is ambiguous, the behavior SHALL be determined from nkMatlib source and documented in `docs/fxp_semantics.md`, with the cited SV file/line for each decision. | P0 | T, I |
| FX-3 | The system SHALL evaluate any frontend DAG with the golden model given named input vectors, returning every intermediate signal (keyed by DAG node ID) plus outputs. | P0 | T |
| FX-4 | The system SHALL also evaluate the DAG in float64 (the "MATLAB reference") and report per-output error statistics vs the fixed-point run: max abs error, RMS error, SQNR (dB). | P0 | T |
| FX-5 | Property-based tests (hypothesis) SHALL verify algebraic invariants on randomized inputs (e.g., wrap consistency, `sdiv(a,b)` truncation direction, `usqrt` monotonicity, `snorm` round-trip within precision). | P0 | T |

### 4.4 Co-Simulation Harness (CS)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| CS-1 | The system SHALL generate, from a DAG: (a) randomized + corner-case stimulus vectors (zeros, ±max, ±1 LSB, sign boundaries), (b) a cocotb testbench driving the user's RTL top with valid-signal pacing, (c) a comparison script asserting RTL outputs == golden-model outputs bit-for-bit with cycle alignment derived from the cost model. | P0 | T, D |
| CS-2 | Verilator presence SHALL be auto-detected; absence disables CS with an actionable message (C2). All Verilator/cocotb invocations run as subprocesses with captured logs shown in the GUI console. | P0 | T |
| CS-3 | A co-sim run SHALL produce a machine-readable result: pass/fail per output, first failing vector index, and (on pass) float-vs-fixed error statistics per FX-4. | P0 | T |
| CS-4 | The repo SHALL include one end-to-end self-test: a small known-good nkMatlib-style SV module + matching `.m` file that passes co-sim in CI when Verilator is available, and is skipped (not failed) when it is not. | P0 | T |

### 4.5 Mismatch Bisection (BI)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| BI-1 | On co-sim failure, the system SHALL localize the first divergent DAG stage by comparing RTL intermediate signals (via generated probes or VCD extraction) against golden-model intermediates (FX-3), reporting: node ID, nkMatlib instance name, cycle, expected vs actual values, and whether inputs to that stage matched. | P0 | T, D |
| BI-2 | The bisection report SHALL distinguish "wrong math at stage X" from "stage X inputs skewed by N cycles" (delay-matching bug), since the latter is the dominant real-world failure mode. | P0 | T |
| BI-3 | The GUI SHALL render bisection results on the DAG view: matched nodes green, first-divergent node red, downstream nodes dimmed. | P1 | D |

### 4.6 SystemVerilog Pipeline Linter (SL)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| SL-1 | The linter SHALL parse SystemVerilog using pyslang if installed, else a documented regex/structural fallback sufficient for nkMatlib-convention files (instances, `PIPE` macros, suffixes). The active backend SHALL be reported. | P0 | T |
| SL-2 | The linter SHALL verify, per operator instance: all data inputs arrive at the same pipeline stage, where each signal's stage = source stage + Σ(module latencies along its path), using the same cost model as AU-1. Violations report both signals, their computed arrival stages, and the required `PIPE` fix. | P0 | T |
| SL-3 | The linter SHALL check: `_nn` suffix consistency with computed stages; valid-chain delay == data-path delay; valid flip-flops reset while data pipes are unreset (SRL inference); instance naming `i_<module>_<signal>_<stage>`. Each check individually suppressible. | P0 | T |
| SL-4 | Lint findings SHALL carry file/line and SHALL be cross-referenced to DAG nodes when a matching `.m` file is loaded (shared node IDs, §3.3). | P1 | T |

### 4.7 Code Generation (CG)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| CG-1 | The system SHALL emit a complete nkMatlib SystemVerilog module from a DAG: `fixedp` port `g`, `_0` inputs / `_N` outputs, one operator instance per node with conventional naming, and **all** `PIPE`/valid matching delays computed automatically from the cost model. | P0 | T |
| CG-2 | Generated code SHALL pass the system's own linter (SL-2/SL-3) with zero findings — enforced as a unit test on every codegen golden file. | P0 | T |
| CG-3 | Generated code for the CS-4 sample SHALL pass co-simulation against the golden model (full loop closure: parse → generate → simulate → match). | P0 | T |
| CG-4 | Codegen SHALL be deterministic (stable ordering) and covered by golden-file tests. | P0 | T |
| CG-5 | The generator SHOULD optionally apply audit rewrites (e.g., RECIP fusion, CDIV→shift) behind per-finding toggles, regenerating with the optimization applied. | P1 | T, D |

### 4.8 Range & Precision Analysis (RP)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| RP-1 | Given user-declared input ranges, the system SHALL propagate intervals through the DAG and report per node: value range, required integer bits, overflow risk at the configured WIDTH/SCALE, and divide-by-near-zero hazards (denominator interval containing or adjacent to 0). | P0 | T |
| RP-2 | The system SHOULD additionally support affine arithmetic for tighter correlated bounds, selectable per analysis run, with results clearly labeled by method. | P1 | T |
| RP-3 | The system SHALL recommend per-stage WIDTH/SCALE (or `elem_snorm` insertion points) meeting a user-specified error budget, and SHALL validate the recommendation empirically via an FX-4 run on random stimulus. | P1 | T |

### 4.9 Design-Space Exploration (DSE)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| DSE-1 | The system SHALL sweep user-defined WIDTH/SCALE grids, computing for each point: critical-path latency, operator census (incl. dividers), and float-vs-fixed error metrics (FX-4) on a fixed stimulus set; runs execute in parallel worker processes with progress reporting and cancellation. | P0 | T, D |
| DSE-2 | The system SHALL extract and plot the Pareto front (error vs latency vs divider count), with point selection revealing the full configuration and a one-click "adopt this WIDTH/SCALE" action that updates the workspace. | P0 | T, D |
| DSE-3 | Sweep results SHALL be cached on disk keyed by (file hash, config) and exportable as CSV/JSON. | P1 | T |

### 4.10 Visualization (VZ)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| VZ-1 | The system SHALL render the DAG with: node labels (signal, module, latency), critical path emphasized, per-node slack shown on demand, dividers visually distinct, and a horizontal pipeline-stage timeline (cycle ruler) as the primary layout axis. | P0 | T, D |
| VZ-2 | Selection SHALL be synchronized across views: clicking a node highlights its MATLAB source line, audit findings, lint findings, codegen instance, and bisection status (shared IDs, §3.3). | P0 | D |
| VZ-3 | Graphviz `dot` SHALL be used for layout when present; otherwise a built-in longest-path layered layout SHALL be used (C2). Export to SVG/PNG. | P0 | T |

### 4.11 Formal Verification Hooks (FV)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FV-1 | The system SHOULD generate SymbiYosys project files asserting: valid-propagation delay equals the computed latency, and no-overflow under RP-1 input assumptions (SVA `assume`/`assert`), for user-selected small modules. | P2 | T, D |
| FV-2 | Yosys/SymbiYosys absence SHALL disable FV per C2. | P2 | T |

---

## 5. GUI Requirements (UI)

### 5.1 Design Language

The interface SHALL follow an "Apple-grade restraint" standard: one idea per screen, generous whitespace on an 8 px spacing grid, depth conveyed by the theme's surface ladder (background → surface → elevated) rather than borders or skeuomorphic chrome, motion limited to 120–180 ms ease-out transitions, and **exactly one signature element** — the **pipeline timeline**: a horizontal cycle ruler that appears in the Audit, Visualizer, and Bisection views, rendering every signal as a bar from its inputs-ready cycle to its output-ready cycle, with the critical path glowing in the theme's red and dividers in orange. Everything else stays quiet so the timeline carries the product's identity.

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| UI-1 | Main window: left icon sidebar (eight capabilities + Settings), central workspace, bottom status bar (active file, WIDTH/SCALE chip, external-tool availability dots), collapsible right inspector for selection details. No menu-bar-driven workflows; the sidebar is the navigation model. | P0 | D, T |
| UI-2 | A global file/project context: opening a `.m` (and optionally a matching `.sv`) populates all views; WIDTH/SCALE are workspace-level settings every view reacts to live. | P0 | T |
| UI-3 | Long-running work (co-sim, sweeps) SHALL run off the GUI thread with progress, cancellation, and a collapsible console streaming subprocess logs. The GUI SHALL never freeze > 100 ms. | P0 | T |
| UI-4 | Keyboard-first: ⌘/Ctrl-O open, ⌘/Ctrl-1…9 switch views, ⌘/Ctrl-R re-run current analysis, ⌘/Ctrl-K command palette (P1). All interactive elements reachable by Tab with visible focus rings. | P0 (palette P1) | D, T |
| UI-5 | Interface copy SHALL use sentence case, active voice, and name user-domain concepts ("Re-run audit", "Adopt 18/14") — never internal mechanics ("Execute DAG job"). Errors state what happened and the next action; empty states say how to begin. | P0 | I |
| UI-6 | Findings tables SHALL support sorting, filtering by tag, and click-through to source span and DAG node (VZ-2). | P0 | D, T |

### 5.2 Theming (TH)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| TH-1 | All colors SHALL flow from a JSON theme file of named semantic tokens → generated QSS + pyqtgraph styles. No hex literal may appear outside theme files (enforced by an architecture test, §8.5). | P0 | T |
| TH-2 | **Default theme: Gruvbox Dark Soft**, with the exact palette and semantic mapping of Appendix A. | P0 | T, D |
| TH-3 | Bundled alternates: Gruvbox Dark Hard, Gruvbox Light, and a high-contrast theme. Users MAY add themes by dropping JSON files in the config directory; malformed themes fail validation with a clear message and fall back to default. | P0 | T |
| TH-4 | Theme switching SHALL apply live (no restart) and persist across sessions. | P0 | T |
| TH-5 | Semantic token set SHALL include at minimum: bg, surface, surfaceElevated, border, textPrimary, textSecondary, textDisabled, accent, accentMuted, success, warning, error, criticalPath, divider (op), selection, focusRing, console{Bg,Fg}. Charts and the DAG view consume the same tokens. | P0 | T |
| TH-6 | Typography: system UI font stack (SF Pro on macOS, Cantarell/Inter on Linux) for chrome; a monospace stack (JetBrains Mono → Menlo → DejaVu Sans Mono fallback) for code, reports, and the console. Type scale: 11/13/15/20 px with two weights. | P0 | I, D |

---

## 6. Non-Functional Requirements (NF)

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| NF-1 | Audit + DAG render of a 500-statement MATLAB file SHALL complete < 1 s on a 2023 laptop. | P0 | T |
| NF-2 | Golden-model evaluation throughput ≥ 100k operator evaluations/s (vectorize with NumPy where it does not compromise bit-exactness; bit-exactness always wins). | P1 | T |
| NF-3 | Cold start to interactive window < 2 s. | P1 | T |
| NF-4 | Crash-free handling of malformed inputs: fuzzed MATLAB/SV input SHALL never raise an unhandled exception to the GUI (global handler logs + non-modal toast). | P0 | T |
| NF-5 | Type-checked (mypy --strict on `core/`), linted (ruff), formatted (ruff format) — clean at every gate. | P0 | T |
| NF-6 | Test coverage: `core/` ≥ 90 % lines, overall ≥ 80 %, measured in CI. | P0 | T |
| NF-7 | All user-visible state (workspace, theme, recent files, sweep cache) stored under platform config dir; deleting it yields a clean first run. | P1 | T |

---

## 7. Development Plan and Verification Gates

Implementation SHALL proceed in the phases below, **strictly in order**. A phase is complete only when its **Gate** passes; the gate command for every phase is:

```
ruff check . && ruff format --check . && mypy src/pipeforge/core \
  && pytest -q --cov=src/pipeforge --cov-fail-under=<phase threshold>
```

plus the phase-specific items listed. Each phase SHALL end with a commit tagged `phase-N-complete` and a one-paragraph `docs/phase_reports/N.md` stating what was built, test counts, coverage, and known deviations from this SRS.

| Phase | Scope (requirements) | Phase-specific gate items | Cov. |
|---|---|---|---|
| **0 — Scaffold** | Repo layout (§3.2), pyproject, CI config, CLI stub, theme token engine skeleton (TH-1), architecture tests (§8.5) | Architecture tests green; `pipeforge-cli --version` works; empty-window smoke test under pytest-qt with offscreen platform | 60 % |
| **1 — Core engine** | Refactor seed into `core/frontend`, `core/costmodel`, `core/audit` (FE-1…4, AU-1…5) | Golden files captured from seed **before** refactor and matched after; property tests for parser round-trip; NF-1 perf test | 85 % core |
| **2 — Golden model** | FX-1…5; `docs/fxp_semantics.md` with nkMatlib source citations (FX-2) | Hypothesis property suite ≥ 200 cases/op; semantics doc reviewed against nkMatlib source (checklist committed) | 90 % core |
| **3 — GUI shell + Audit view** | UI-1…6, TH-2…6, VZ-1, VZ-3, AU GUI (AU-4) | pytest-qt: navigation, theme live-switch, findings click-through; screenshot artifacts of Gruvbox Dark Soft default saved to `docs/screens/`; NF-3, NF-4 fuzz test | 80 % |
| **4 — SV linter** | SL-1…4 | Fixture corpus: ≥ 10 known-bad SV files each triggering exactly its intended finding, ≥ 3 known-good files lint-clean; backend fallback test with pyslang absent | 80 % |
| **5 — Co-sim + bisection** | CS-1…4, BI-1…3 | CS-4 end-to-end test (skip-not-fail without Verilator); bisection test: deliberately corrupted RTL fixture localized to the correct stage; delay-skew fixture classified per BI-2 | 80 % |
| **6 — Codegen** | CG-1…5 | CG-2 (own linter clean) and CG-3 (generated RTL passes co-sim) as automated tests; codegen golden files | 80 % |
| **7 — Ranges + DSE** | RP-1…3, DSE-1…3 | Interval-arithmetic property tests (containment under all ops); sweep cancellation test; Pareto correctness test on synthetic data; adopt-action integration test | 80 % |
| **8 — Polish + formal + packaging** | FV-1…2, command palette (UI-4 P1), VZ slack overlay, NF-2/NF-7, README/user docs | Full regression of all prior gates; fresh-clone install-and-run check on Linux; final screenshot set | 80 % |

Regression rule: every gate re-runs **all** previous phases' tests. No phase may weaken an earlier golden file without a written justification in its phase report.

---

## 8. Verification and Test Strategy

### 8.1 Levels

1. **Unit** — pytest, mirroring `src/`; every public function of `core/`.
2. **Property-based** — hypothesis for parser, fxp operators, interval arithmetic.
3. **Golden-file** — audit reports, codegen output, lint reports; diffs reviewed, never blindly regenerated.
4. **Integration** — parse→audit→codegen→lint→cosim loop closure (CG-3 is the keystone).
5. **GUI** — pytest-qt with `QT_QPA_PLATFORM=offscreen`: navigation, theming, threading (UI-3 responsiveness via a stall watchdog), selection sync (VZ-2).
6. **Fuzz** — randomized malformed `.m`/`.sv` inputs against NF-4.

### 8.2 External-Tool Test Policy

Tests requiring Verilator/cocotb/pyslang/Yosys SHALL be marked (`@pytest.mark.tool("verilator")`) and **skip with a visible count** when the tool is absent; CI SHOULD run a job with tools installed so they execute at least somewhere.

### 8.3 Test Data

`tests/fixtures/` SHALL include: the seed example, a 3D-vector-normalization pipeline (the RECIP showcase), a norm/rootsqr case, a feedback accumulator, a 500-statement generated file (NF-1), known-bad SV lint corpus, and the CS-4 known-good module pair.

### 8.4 Continuous Verification

A single `make verify` (or `just verify`) target SHALL run the full gate. Pre-commit hooks run ruff + mypy on changed files. The agent SHALL run `make verify` before declaring any phase complete and paste the summary into the phase report.

### 8.5 Architecture Tests

Automated tests SHALL assert: (a) no module under `core/` imports PyQt6; (b) no hex color literals outside `gui/theme/`; (c) no hard-coded latency constants outside `core/costmodel/` (regex scan with allowlist); (d) `cli.py` exercises every P0 capability headlessly.

---

## 9. Traceability

The requirement tables in §4–§6 constitute the traceability matrix: every requirement carries a verification method, and phase ownership is defined in §7. The agent SHALL maintain `docs/rtm.csv` (requirement ID → test ID(s) → phase → status), regenerated by a script that scans pytest node IDs for `@req("AU-3")`-style markers; the RTM SHALL show no P0 requirement without at least one passing test at Phase 8 exit.

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| nkMatlib semantics ambiguity (rounding, overflow) breaks bit-exactness | FX-2: derive from nkMatlib source, document with citations, lock with property tests; CS-4 hardware-truth check |
| MATLAB parsing scope creep | A1 + FE-3: skip-and-report, never extend grammar mid-phase; grammar extensions are new requirements |
| pyslang availability / SV parsing complexity | SL-1 dual backend; convention-scoped parsing only |
| Verilator absent in dev environment | §8.2 skip policy; pure-Python paths (FX) carry the verification weight |
| GUI thread jank during sweeps | UI-3 watchdog test; all engine calls via services layer |
| Theme system circumvented by inline styles | §8.5(b) architecture test |

---

## Appendix A — Gruvbox Dark Soft: Palette and Semantic Mapping (normative for TH-2)

Base palette (R3):

| Name | Hex | | Name | Hex |
|---|---|---|---|---|
| bg0_soft | `#32302f` | | fg0 | `#fbf1c7` |
| bg0 | `#282828` | | fg1 | `#ebdbb2` |
| bg1 | `#3c3836` | | fg2 | `#d5c4a1` |
| bg2 | `#504945` | | fg3 | `#bdae93` |
| bg3 | `#665c54` | | fg4 | `#a89984` |
| bg4 | `#7c6f64` | | gray | `#928374` |
| red | `#fb4934` / `#cc241d` | | blue | `#83a598` / `#458588` |
| green | `#b8bb26` / `#98971a` | | purple | `#d3869b` / `#b16286` |
| yellow | `#fabd2f` / `#d79921` | | aqua | `#8ec07c` / `#689d6a` |
| orange | `#fe8019` / `#d65d0e` | | | |

Semantic mapping (bright/neutral pairs: bright for emphasis, neutral for fills):

| Token | Value | Token | Value |
|---|---|---|---|
| bg | `#32302f` | accent | `#8ec07c` |
| surface | `#3c3836` | accentMuted | `#689d6a` |
| surfaceElevated | `#504945` | success | `#b8bb26` |
| border | `#665c54` | warning | `#fabd2f` |
| textPrimary | `#ebdbb2` | error | `#fb4934` |
| textSecondary | `#bdae93` | criticalPath | `#fb4934` |
| textDisabled | `#928374` | divider (op) | `#fe8019` |
| selection | `#504945` | focusRing | `#83a598` |
| consoleBg | `#282828` | consoleFg | `#d5c4a1` |

Chart series order: aqua, blue, yellow, purple, orange, green (bright variants), on `bg0` plot background with `bg2` gridlines.

## Appendix B — External Tool Detection

On startup and on demand (Settings → Tools), probe `verilator --version`, `python -c "import cocotb"`, `python -c "import pyslang"`, `dot -V`, `yosys -V`, `sby --help`. Render availability as status-bar dots (success/textDisabled tokens) with tooltips naming the feature each tool unlocks and the install command for the current OS.

## Appendix C — Seed Code Contract

`seed/matlib_audit.py` is working, tested code. Phase 1 SHALL begin by writing characterization tests against it as-is (its text and JSON output on the fixture corpus), then refactor under those tests. Public behavior changes require updating this SRS first. The seed's CLI behavior SHALL survive verbatim in `pipeforge-cli audit`.

---

*End of PF-SRS-001 Rev A.*
