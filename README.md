# PipeForge

**MATLAB-to-nkMatlib FPGA pipeline workbench** — audit, verify, visualize, and
generate fixed-point pipelines targeting the
[nkMatlib](https://github.com/nklabs/matlib) SystemVerilog library.

You write straight-line MATLAB DSP code. PipeForge tells you what that code costs
as an nkMatlib pipeline (cycles, multipliers, dividers), how to make it cheaper,
what every value's range and precision will be, whether your hand-written RTL
matches a bit-exact model — and it can write the SystemVerilog skeleton for you,
with every matching delay computed.

![Audit view](docs/screens/01-audit-gruvbox-dark-soft.png)

---

## Contents

1. [First-time setup](#first-time-setup)
2. [Five-minute tour](#five-minute-tour)
3. [Concepts you need](#concepts-you-need)
4. [The GUI](#the-gui)
5. [Capability guide](#capability-guide)
   - [Latency audit](#1-latency-audit)
   - [Visualizer](#2-visualizer)
   - [Golden model](#3-golden-model)
   - [SystemVerilog linter](#4-systemverilog-linter)
   - [Code generation](#5-code-generation)
   - [Co-simulation](#6-co-simulation)
   - [Mismatch bisection](#7-mismatch-bisection)
   - [Range & precision analysis](#8-range--precision-analysis)
   - [Design-space exploration](#9-design-space-exploration)
   - [Formal hooks](#10-formal-hooks)
   - [Live MATLAB bridge](#11-live-matlab-bridge)
6. [The MATLAB subset PipeForge understands](#the-matlab-subset-pipeforge-understands)
7. [Configuration and files on disk](#configuration-and-files-on-disk)
8. [Development](#development)
9. [Troubleshooting](#troubleshooting)
10. [Known limitations](#known-limitations)

---

## First-time setup

### Requirements

- **Python ≥ 3.11** (3.12 recommended — required if you want co-simulation, since
  cocotb does not yet build on 3.14)
- Linux (Arch / Ubuntu 22.04+) or macOS. Windows is not a target.

### Install

```sh
git clone <this repo> && cd <repo>
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: uv pip install -p .venv -e ".[dev]"
```

That gives you two entry points:

| Command | What it is |
|---|---|
| `pipeforge` | the GUI (optionally pass a `.m` file to open) |
| `pipeforge-cli` | every capability, headless — `pipeforge-cli -h` lists subcommands |

### Optional external tools

Everything below is **optional**. Missing tools disable only their feature, with an
actionable message — nothing crashes, nothing silently no-ops. The GUI status bar
shows one availability dot per tool (hover for what it unlocks and how to install).

| Tool | Unlocks | Install |
|---|---|---|
| Verilator + cocotb | co-simulation, generated-RTL verification | `pacman -S verilator` / `apt install verilator`; `pip install cocotb` |
| graphviz `dot` | nicer DAG row ordering in the Visualizer | `pacman -S graphviz` / `apt install graphviz` |
| pyslang | full SystemVerilog parsing in the linter (otherwise a structural fallback is used) | `pip install pyslang` |
| Yosys + SymbiYosys | running the generated formal projects | distro packages |
| MATLAB | the live workspace bridge | see below |

### Pointing PipeForge at MATLAB (once per machine)

The MATLAB location is **per-machine state** stored in
`~/.config/pipeforge/settings.json` — it is never part of the repo, so every
computer keeps its own. Resolution order:

1. Explicit setting (Settings → MATLAB command, or `matlabCommand` in settings.json)
2. `PIPEFORGE_MATLAB` environment variable (a shell-style command string)
3. `matlab` on PATH
4. Standard installs (`/usr/local/MATLAB/R20xx`, `/opt/MATLAB/R20xx`,
   `/Applications/MATLAB_R20xx.app`), newest release first
5. A Distrobox container with "matlab" in its name

On a machine with a normal install it usually just works. To set it up explicitly:

```sh
pipeforge-cli matlab detect
```

This *launches* each candidate until one actually answers, then saves the winner.
That full launch matters: a MATLAB directory can be visible but unrunnable (e.g. a
container install whose path shows on the host). The GUI equivalent is the
**Detect** button in Settings.

### Verify the install

```sh
pipeforge-cli --version                  # pipeforge 0.1.0
pipeforge-cli audit seed/example.m      # should print a full audit report
make verify                              # lint + type-check + full test suite
```

---

## Five-minute tour

```sh
# 1. What does this MATLAB cost as a pipeline, and how do I make it cheaper?
pipeforge-cli audit seed/example.m

# 2. Generate the nkMatlib SystemVerilog for it
pipeforge-cli codegen tests/fixtures/normalize3d.m -o normalize3d.sv

# 3. Check the generated (or your hand-written) RTL against the conventions
pipeforge-cli lint normalize3d.sv

# 4. Will 16/12 fixed point overflow? Where could a divide blow up?
pipeforge-cli ranges tests/fixtures/normalize3d.m --range x=-1:1 --range y=-1:1 --range z=-1:1

# 5. What WIDTH/SCALE should I pick? Sweep and look at the Pareto front
pipeforge-cli dse tests/fixtures/normalize3d.m --widths 12,16,20 --scales 8,12,14

# 6. Prove RTL == model, bit for bit (needs Verilator + cocotb)
pipeforge-cli cosim tests/fixtures/cosim/sample.m \
    --sv tests/fixtures/cosim/sample.sv --top cosim_sample \
    --include matlib-main/rtl \
    --source matlib-main/rtl/fixedp.sv --source matlib-main/rtl/smul.sv \
    --source matlib-main/rtl/smul_raw.sv --source matlib-main/rtl/norm.sv \
    --source matlib-main/rtl/add.sv --source matlib-main/rtl/pipe.sv \
    --source matlib-main/rtl/valid.sv
```

Or just run `pipeforge`, hit **Ctrl+O**, open `seed/example.m`, and click around.

---

## Demos

A curated demo per capability ships **inside the package** (pip installs get them
too). List them with paths and copy-pasteable commands:

```sh
pipeforge-cli demos
```

In the GUI, press **Ctrl+Shift+D** (or palette → "Open demos…") for the Demos
window: pick one, read what to expect, click **Open in PipeForge**.

| Demo | Shows |
|---|---|
| `01_findings` | all seven audit findings in one small script |
| `02_normalize3d` | the 48-cycle critical path and divider-orange timeline |
| `03_pipeline` (.m + .sv) | clean lint, codegen comparison, bit-exact co-simulation |
| `04_lint_bugs` | a missing-`PIPE` delay-match bug + a wrong valid chain, with exact fixes |
| `05_ranges` | overflow risk, a near-zero divisor, and an *honest* format recommendation (unmet budget until you fix the hazard) |
| `06_dse` | the WIDTH/SCALE latency/error trade and the Pareto front |
| `07_matlab` | live snapshot with dotted struct fields, `.mat`-alone browsing, statement-by-statement validation |

---

## Concepts you need

**nkMatlib** is a pipelined fixed-point SystemVerilog library: throughput is one
result per clock, and the latency of a computation is the length of its dataflow
critical path. Operands that arrive at an operator at different times must be
delay-matched with `PIPE` shift registers — getting those delays wrong is the
classic nkMatlib bug, and most of PipeForge exists to compute, check, or generate
them.

**WIDTH / SCALE** define the fixed-point format: WIDTH total bits, SCALE fractional
bits, LEFT = WIDTH − SCALE integer bits (including sign). They are a
*workspace-level* setting (status-bar chip; default **16/12**, i.e. range ±8 with
~0.00024 resolution). All operator latencies derive from them at runtime:

| Operator | Latency |
|---|---|
| add/sub, abs, neg, max/min | 1 |
| multiply (`smul`, `ssqr`) | 4 |
| matrix multiply, sumsqr, cross | 5 |
| divide (`sdiv`, `sinv`) | WIDTH + SCALE (e.g. 28 at 16/12) |
| square root | WIDTH − LEFT/2 (e.g. 14 at 16/12) |
| `norm` (rootsqr) | sqrt + sumsqr (e.g. 19 at 16/12) |
| format convert, transpose, select | 0 |

Notice dividers dominate everything — which is why several audit findings are about
eliminating them.

**The DAG** is the shared data structure. Your script is parsed into a dataflow
graph; every capability consumes the *same* graph with the *same* node IDs. The
node you click in the Visualizer is the node named in an audit finding, a codegen
instance, a bisection report, and a range row.

**The golden model** is a bit-exact Python re-implementation of nkMatlib's
arithmetic — same truncation directions, same overflow wraps, same divide-by-zero
bit patterns (every decision is cited against the RTL source in
`docs/fxp_semantics.md`). "Passes co-simulation" means the RTL equals this model
bit-for-bit, not "approximately".

---

## The GUI

```
┌──┬────────────────────────────────────────────┬─────────────┐
│  │  Audit                                     │  Inspector  │
│ s│  ┌──────────────────────────────────────┐  │  node info  │
│ i│  │  pipeline timeline (cycle ruler)     │  │  source     │
│ d│  └──────────────────────────────────────┘  │  with span  │
│ e│  findings table (sort / filter / click)    │  highlight  │
│ b│                                            │             │
│ a├────────────────────────────────────────────┤             │
│ r│  console (Ctrl+`)                          │             │
├──┴────────────────────────────────────────────┴─────────────┤
│ file path                     [16/12] ● ● ○ ● ●  tool dots  │
└──────────────────────────────────────────────────────────────┘
```

- **Sidebar**: the eight capabilities + Settings. No menu bar — this is the
  navigation model.
- **Pipeline timeline** (Audit and Visualizer): every signal is a bar from its
  inputs-ready cycle to its output-ready cycle on a horizontal cycle ruler. The
  **critical path glows red**, **dividers are orange**. Click a bar to select that
  node everywhere.
- **Inspector** (right): the selected node's module, latency, ready cycle, related
  findings, live MATLAB info when a snapshot is loaded — and the source file with
  the node's exact originating text highlighted.
- **Workspace context**: opening a `.m` populates *all* views; a same-named `.sv`
  loads alongside automatically; opening a `.mat` makes it the session's MATLAB
  setup (browse it in the Workspace view after a refresh). Changing WIDTH/SCALE
  re-audits everything live.

Keyboard (everything is reachable by Tab as well):

| Keys | Action |
|---|---|
| Ctrl+O | open a `.m` / `.sv` |
| Ctrl+1 … Ctrl+9 | switch view (sidebar order) |
| Ctrl+R | re-run the current analysis |
| Ctrl+K | command palette (type-to-filter every action and theme) |
| Ctrl+` | toggle the console |
| Ctrl+Shift+M | refresh from MATLAB |
| Ctrl+Shift+D | open the Demos window |

**Theming**: Gruvbox Dark Soft by default; Gruvbox Dark Hard, Gruvbox Light, and
High Contrast are bundled. Switch live in Settings (persists). Drop your own JSON
theme into `~/.config/pipeforge/themes/` — malformed themes fail validation with a
clear message and fall back to the default.

---

## Capability guide

### 1. Latency audit

**What it does:** static analysis of a MATLAB script against the nkMatlib cost
model.

```sh
pipeforge-cli audit file.m [-w 16 -s 12] [--json] [--snapshot snap.json]
```

**What you get:**
- per-statement **ready times** (the cycle each value becomes available) and the
  added latency per statement
- the **critical path**: total cycles plus the exact dependency chain that sets it
- an **operator census** with the divider count called out
- **findings** — each with line number, estimated cycle savings, and a concrete
  rewrite:

| Tag | Fires when | Suggested rewrite |
|---|---|---|
| `RECIP` | several divisions share one divisor (`x/n; y/n; z/n`) | compute `1/n` once, multiply — k−1 fewer dividers |
| `CDIV` | division by a constant | multiply by the reciprocal; power-of-two → shift |
| `SERDIV` | serial division chain (`a/b/c`) | multiply divisors, divide once |
| `POW` | integer power as a multiply chain | square-and-multiply |
| `CSE` | identical subexpression computed twice | compute once, `PIPE` it |
| `FUSE` | `a+b+c` style chains | one `matadd3` (saves a stage) |
| `FEEDBACK` | a variable feeds back into itself | reports the loop's initiation interval |
| `FORMAT` | (only with a MATLAB snapshot) a `fi` variable's format ≠ workspace format | insert `elem_snorm` or adopt the fi format |

**Expectations:** auditing is fast (500 statements < 1 s). Statements PipeForge
can't parse are *skipped and listed*, never fatal. Without shape information, `*`
is costed as an elementwise multiply and `/` as a full divide — attach a MATLAB
snapshot to get true `matmul`/`matscale` costing.

### 2. Visualizer

**What it does:** the full DAG on the pipeline timeline.

- x-axis is *cycles*, so horizontal length is honest latency; rows are packed
  (graphviz `dot` refines row order when installed).
- **Show slack** overlays per-node spare cycles (`+N`); critical-path nodes show
  none — they have zero slack by definition.
- **Export SVG / PNG** for documentation; exports use the active theme.

### 3. Golden model

**What it does:** evaluates the DAG two ways — bit-exact fixed point and float64 —
and reports per-output error statistics (max |error|, RMS, SQNR in dB).

This is a library capability (it powers co-sim, validation, recommendation, and
DSE); the most direct way to use it interactively is `pipeforge-cli matlab
validate` (below), which compares it against real MATLAB values.

**What "bit-exact" includes** (all cited to RTL source in
`docs/fxp_semantics.md`): truncation *toward −∞* on renormalization (the nkMatlib
README says "toward 0" — the RTL floors, the RTL wins), truncation toward zero on
division, silent overflow wrap on multiply, per-product renormalization *before*
wrapped summation in `sumsqr`/`matmul`, the all-ones quotient on divide-by-zero,
and the bit-serial square root (note: it needs an **even LEFT** to scale
correctly).

### 4. SystemVerilog linter

**What it does:** checks an nkMatlib-convention `.sv` file using the *same cost
model as the audit* — a lint stage number is directly comparable to an audit ready
time.

```sh
pipeforge-cli lint file.sv [-w 16 -s 12] [--disable CHECK] [--no-pyslang] [--json]
```

Checks (each suppressible via `--disable`):

| Check | Catches |
|---|---|
| `delay-match` | operands reaching an instance at different pipeline stages — reports both signals, their computed stages, and the exact `` `PIPE`` fix |
| `suffix` | `_nn` stage suffixes inconsistent with computed cycles |
| `valid-chain` | valid-signal delay ≠ data-path delay |
| `reset` | valid flip-flops through unreset pipes, or data through reset valid-delays (blocks SRL inference) |
| `naming` | instances not named `i_<module>_<signal>_<stage>` |
| `unknown-module` | instances the cost model can't price |

**Expectations:** exit code 1 when findings exist (CI-friendly). The active parser
backend is reported (`pyslang` or the regex/structural fallback — findings agree
between them on the test corpus). `pipe`/`valid` instances with explicit
`.DELAY(n)` parameters are priced correctly.

### 5. Code generation

**What it does:** emits a complete nkMatlib module from a MATLAB script.

```sh
pipeforge-cli codegen file.m [-m module_name] [-o out.sv]
```

**What you get:** `fixedp` interface port `g`, `_0` inputs / `_N` outputs, one
operator instance per DAG node with conventional naming, constants via `` `TOFXD``,
and **all** matching delays computed for you — operand alignment pipes, alignment
of early outputs to the final stage, and the reset valid chain.

**Guarantees:** output is deterministic, and generated code passes PipeForge's own
linter with zero findings (enforced by tests). The generated module for the sample
pair passes co-simulation against the golden model — the full parse → generate →
simulate → match loop is a CI test.

**Expectations:** opaque constructs (array indexing like `n(:,1)`, concatenation)
raise a clear error naming the line — rewrite without them or extend the
generator. Dotted variables become legal port names (`cfg.gain` → `cfg_gain_0`).

### 6. Co-simulation

**What it does:** drives your RTL under Verilator with valid-paced stimulus and
compares every output against the golden model **bit for bit**.

```sh
pipeforge-cli cosim file.m --sv dut.sv --top module_name \
    --include matlib-main/rtl --source <each nkMatlib .sv the DUT instantiates> \
    [--vectors 256] [--work-dir DIR] [--json]
```

**What happens:** PipeForge generates a plain-port wrapper (so cocotb doesn't have
to drive a SystemVerilog interface), a cocotb testbench, and a stimulus set —
corner cases first (zeros, ±max, ±1 LSB, ±1.0, sign boundaries), then seeded
random. One problem enters the pipe per clock; outputs are collected where
`valid_N` is high; the k-th valid output must equal the golden model's k-th result
exactly.

**What you get:** PASS/FAIL per output; on failure the first failing vector index
with expected/actual raw values; on pass the float-vs-fixed error stats. Exit
codes: 0 pass, 1 fail, 3 tools missing. All build artifacts and logs stay in the
work dir for inspection.

**Expectations:** needs Verilator and cocotb (auto-detected; absence produces an
actionable message, and the test suite *skips* rather than fails). First build of
a DUT takes ~10 s; reruns are faster.

### 7. Mismatch bisection

**What it does:** when RTL ≠ model, localizes the **first divergent pipeline
stage** instead of leaving you staring at a wrong output.

This is a library API (`pipeforge.core.bisect.engine.bisect`): give it the DAG, the
stimulus, and per-node observed RTL streams; it compares them against golden
intermediates (every node, every vector) and reports the first divergent node —
its instance name, cycle, expected vs actual values, and whether its *inputs*
matched.

**The key feature:** it distinguishes **wrong-math** ("this stage computes
incorrectly from correct inputs") from **delay-skew** ("this stage's math is fine
but one operand stream is N cycles late — a missing `` `PIPE``"), by replaying the
stage with shifted operand streams. Delay skew is the dominant real-world nkMatlib
bug. The timeline renders the result: matched nodes green, the first divergent
node red, everything downstream dimmed.

### 8. Range & precision analysis

**What it does:** propagates value ranges through the DAG.

```sh
pipeforge-cli ranges file.m --range x=-1:1 --range n=0.1:4 \
    [--method affine] [--recommend 0.01] [--snapshot snap.json]
```

**What you get, per signal:** the value interval, integer bits required, an
**OVERFLOW RISK** flag when the range exceeds the configured WIDTH/SCALE, and a
**NEAR-ZERO DIVISOR** flag when a denominator's interval touches ±4 LSB of zero
(the normalization `x/norm(v)` pattern flags immediately — the norm *can* be 0).

- `--method affine` keeps linear correlations (`a − a` is exactly 0, where plain
  intervals say ±2) — tighter bounds on correlated expressions; results are
  labeled with the method used.
- `--recommend BUDGET` proposes a WIDTH/SCALE meeting an absolute error budget
  (LEFT from the propagated ranges — forced even for sqrt correctness — SCALE from
  the budget), then **validates it empirically** against the golden model and says
  whether the budget was actually met.
- `--snapshot` fills input ranges from live MATLAB min/max so you don't have to
  declare them.

### 9. Design-space exploration

**What it does:** answers "which WIDTH/SCALE should I use?" with data.

```sh
pipeforge-cli dse file.m [--widths 12,16,20,24] [--scales 8,12,16] \
    [--vectors 64] [--csv out.csv] [--json]
```

Each grid point is evaluated in **parallel worker processes**: critical-path
latency, operator/divider census, and fixed-vs-float error metrics on a fixed
seeded stimulus. The **Pareto front** (minimize error, latency, divider count) is
extracted and printed; dominated points are dropped.

**In the GUI** (Exploration view): set the grids, Run (progress bar + Cancel),
see the scatter (error vs latency, log scale; front points starred), select a
row, **Adopt selected** — the workspace WIDTH/SCALE updates and every view
re-derives live.

**Expectations:** a 3×3 grid at 64 vectors takes a few seconds. Invalid points
(SCALE ≥ WIDTH) are skipped silently.

### 10. Formal hooks

**What it does:** generates a SymbiYosys project (`formal_top.sv` + `project.sby`)
asserting that `valid_N` is exactly the cost-model latency behind `valid_0`
(against a reference shift register), with RP-1 input ranges rendered as SVA
`assume`s. Library API: `pipeforge.core.cosim.formal.write_formal_project`. Running
the project needs Yosys/SymbiYosys; their absence disables the feature with a clear
message.

### 11. Live MATLAB bridge

**What it does:** connects PipeForge to a *real* MATLAB session so analysis runs on
real types, shapes, formats, and values — including nested struct fields.

```sh
pipeforge-cli matlab detect                 # one-time per machine (see setup)
pipeforge-cli matlab probe                  # is MATLAB reachable? which one?
pipeforge-cli matlab snapshot dsp.m --setup data.mat [-o snap.json] [--force]
pipeforge-cli matlab validate dsp.m --setup setup.m [-w 16 -s 12]
```

**The workspace setup** answers "where do `x` and `cfg` come from before the
script runs": either a `.m` script PipeForge runs first (parameters, test
signals) or a `.mat` file it loads. Set it per project in Settings or pass
`--setup`.

**Snapshot** runs setup + script inside MATLAB and captures *every* variable:
class, size, `fi` WordLength/FractionLength, min/max, and values (capped at 4096
elements; min/max always cover the full array). Struct fields come back dotted
(`cfg.filter.taps`). Snapshots are **cached** and only retaken on explicit refresh
(`--force`, the Detect…/Refresh actions) because MATLAB takes seconds to start.

**Inspecting a `.mat` parameter file alone** — no script needed:

```sh
pipeforge-cli matlab snapshot params.mat
```

MATLAB loads the file and PipeForge lists every variable's name (struct fields
dotted), class, size, fi format, and range. In the GUI, the **Workspace** view
(Ctrl+3) is the browser: open a `.mat` with Ctrl+O (it becomes the session's
setup), hit **Refresh from MATLAB**, then sort/filter the variable table; with a
script also open, clicking a row selects the matching DAG node everywhere.

**With a snapshot attached** (`--snapshot` on `audit`/`ranges`, or **Ctrl+Shift+M**
in the GUI):
- `A * B` is costed as a true `matmul`, scalar×matrix as `matscale`,
  matrix/scalar as `matunscale` — latencies and census change accordingly
- `fi` variables whose format differs from the workspace raise **FORMAT** findings
- input ranges come from live min/max
- the Inspector shows each node's MATLAB class/size/format and a value preview

**Validate** is the head-to-head: it feeds MATLAB's own input values through the
bit-exact golden model and compares **statement by statement** against what MATLAB
computed:

```
validate demo.m @ 16/12 — golden model vs MATLAB 26.1.0 (R2026a)
  line   2  y              3 value(s): bit-clean
  line   3  n              1 value(s): max|e| 6.81e-05, SQNR 78.5 dB
```

"bit-clean" means the fixed-point pipeline will reproduce MATLAB exactly for those
values; otherwise you see the quantization cost per statement. Expect exact-
representable arithmetic (±, exact products) to be bit-clean and roots/divides to
sit within an LSB or two at sensible SCALEs.

---

## The MATLAB subset PipeForge understands

Parsed: assignments; numbers (including scientific notation); `+ - * / \ .* ./ .\
^ .^`; unary minus; transpose `'` / `.'`; parentheses; comments `%`; line
continuations `...`; struct-field access `a.b.c`; array-index atoms (`n(:,1)`)
as *opaque operands*; matrix literals `[ ... ]` as opaque concatenation; simple
`for` loops (used for feedback detection); and these functions:

`sqrt abs max min norm sumsqr cross dot vecnorm transpose ones zeros`

Everything else — `if`/`while` bodies, strings, comparisons, unknown functions,
non-constant exponents — is **skipped and reported** with its line and reason.
Skips never abort the analysis; check the "skipped" section of the audit to see
what was ignored.

---

## Configuration and files on disk

Everything user-visible lives under `~/.config/pipeforge/` (XDG-aware). Deleting
the directory yields a clean first run.

| Path | Contents |
|---|---|
| `settings.json` | theme choice, MATLAB command (`matlabCommand`), setup file (`matlabSetup`) |
| `themes/*.json` | your custom themes |
| `matlab_cache/` | cached workspace snapshots (keyed by script/setup mtimes) |
| `matlab_work/` | generated `pf_query.m` + raw snapshot JSON (home-shared with containers) |

Environment variables: `PIPEFORGE_MATLAB` (MATLAB command override),
`XDG_CONFIG_HOME` (relocates the config dir), `QT_QPA_PLATFORM=offscreen`
(headless GUI runs/tests).

---

## Development

```sh
make verify     # ruff check + format check + mypy --strict (core) + pytest with coverage
make rtm        # regenerate docs/rtm.csv and check every P0 requirement has a passing test
make test COV=80
```

Architecture rules, enforced by tests in `tests/unit/test_architecture.py`:

- `src/pipeforge/core/` is pure Python — **zero Qt imports**; the GUI is a view
  over the engine, never the home of logic.
- No hex color literal outside theme JSON; all GUI color flows from semantic
  tokens.
- No hard-coded latency outside `core/costmodel/` — everything derives from
  WIDTH/SCALE.
- Every capability must be exercisable from `pipeforge-cli`.

Tests requiring external tools (Verilator, MATLAB) are marked and **skip with a
visible reason** when the tool is absent; CI runs a tools-installed job so they
execute somewhere. The binding spec is `PipeForge_SRS.md`; per-phase reports live
in `docs/phase_reports/`; `seed/` is the frozen reference auditor whose behavior
the golden files pin.

Handoff state: all SRS phases 0–8 complete and tagged (`phase-N-complete`), full
suite green with every P0 requirement traced to a passing test (`make rtm`), and
the MATLAB bridge + co-simulation verified live (R2026a in distrobox, Verilator
5.048).

---

## Troubleshooting

**"Co-simulation needs external tools that are not available"** — install
Verilator and cocotb *into the project venv* (`pip install cocotb`). cocotb
requires Python ≤ 3.12.

**"No working MATLAB found"** — run `pipeforge-cli matlab detect` and read the
list of candidates it tried; set `PIPEFORGE_MATLAB` or Settings → MATLAB command
if your install is somewhere unusual. For container setups, the command must be
the full wrapper (e.g. `distrobox enter <name> -- /path/to/matlab`).

**MATLAB snapshot times out** — first start of a stopped container plus MATLAB
cold start can approach the 180 s budget; retry once the container is warm.
Check the console (GUI) or stderr (CLI) for MATLAB's own output.

**"snapshot has no values for input(s): …"** during validate — the named
variables don't exist in MATLAB after setup + script. Point `--setup` at the
script/`.mat` that creates them.

**Audit shows `(skipped)` statements you expected to be analyzed** — see
[the subset](#the-matlab-subset-pipeforge-understands); the reason column says
exactly what wasn't supported.

**Linter flags your correct file** — check WIDTH/SCALE first: stage arithmetic
depends on them (`-w/-s` must match the design). Individual checks can be
silenced with `--disable`.

**GUI looks wrong after editing a custom theme** — malformed themes fall back to
the default and the validation error names the offending token.

**One-off build crashes** (GCC internal error under Verilator, rare Qt teardown
segfault) — observed once each on Arch with GCC 16; simply retry before digging.

---

## Known limitations

- **Scalar-lane evaluation**: the golden model evaluates vectors elementwise
  ("lanes"); matrix *costing* is shape-aware with a MATLAB snapshot, but matrix
  *products* are validated as dot products, not full 2-D matmuls.
- Static analysis without a snapshot assumes every `*` is elementwise and every
  variable is scalar-shaped — attach a snapshot for shape truth.
- Bisection consumes observation streams via the library API; automatic VCD
  extraction from a failing co-sim run is not implemented yet.
- Codegen rejects opaque indexing/concatenation rather than guessing.
- One fixed-point format per workspace: mixed `fi` formats are *detected and
  flagged* (FORMAT finding) but not auto-converted mid-pipeline.
- The MATLAB bridge spawns `matlab -batch` per snapshot (seconds); a persistent
  engine is a planned backend behind the same interface.
