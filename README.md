# PipeForge

**MATLAB-to-nkMatlib FPGA pipeline workbench** — audit, verify, visualize, and
generate fixed-point pipelines targeting the
[nkMatlib](https://github.com/nklabs/matlib) SystemVerilog library.

![Audit view](docs/screens/01-audit-gruvbox-dark-soft.png)

## What it does

| Capability | Where |
|---|---|
| **Latency audit** — critical path, operator census, findings (RECIP, CDIV, SERDIV, POW, CSE, FUSE, FEEDBACK) | GUI Audit view · `pipeforge-cli audit` |
| **Golden model** — bit-exact Python model of nkMatlib semantics (see `docs/fxp_semantics.md`) | library · used everywhere |
| **Co-simulation** — float MATLAB ↔ fixed-point model ↔ RTL under Verilator, bit-for-bit | `pipeforge-cli cosim` |
| **Bisection** — localizes the first divergent pipeline stage; tells *wrong math* from *delay skew* | library · timeline rendering |
| **Pipeline linter** — delay matching, `_nn` suffixes, valid chain, reset discipline, naming | `pipeforge-cli lint` |
| **Code generation** — complete nkMatlib module with all `PIPE`/valid bookkeeping computed | `pipeforge-cli codegen` |
| **Range & precision** — interval/affine propagation, overflow & near-zero-divisor flags, WIDTH/SCALE recommendation | `pipeforge-cli ranges` |
| **Design-space exploration** — parallel WIDTH/SCALE sweeps, Pareto front, one-click adopt | GUI Exploration view · `pipeforge-cli dse` |

The **pipeline timeline** is the signature element: a horizontal cycle ruler where
every signal is a bar from its inputs-ready cycle to its output-ready cycle —
critical path in red, dividers in orange.

## Live MATLAB bridge

PipeForge can query a **real MATLAB session** for variable types, shapes, fixed-point
formats, and values — and the answers change the analysis:

- `pipeforge-cli matlab snapshot dsp.m --setup data.mat` runs your setup (a `.m` to run
  or a `.mat` to load) plus the script in MATLAB and captures every variable, including
  nested struct fields (`cfg.gains.kp`) and the script's own outputs.
- With a snapshot attached (`--snapshot` on `audit`/`ranges`, or **Ctrl+Shift+M** in the
  GUI), `A * B` is costed as a true `matmul`, scalar×matrix becomes `matscale`,
  fi-object format mismatches surface as **FORMAT** findings, input ranges come from
  live min/max, and the inspector shows each node's MATLAB class/size/format/value.
- `pipeforge-cli matlab validate dsp.m --setup data.mat` compares the bit-exact golden
  model against MATLAB's own values, statement by statement (bit-clean / max-error / SQNR).

Snapshots are taken only on explicit refresh (MATLAB startup is slow) and cached
until you retake them. Struct-field access (`a.b.c`) is a documented grammar
extension over the original SRS.

### Portability: pointing PipeForge at *your* MATLAB

The MATLAB location is **per-machine state** (`~/.config/pipeforge/settings.json`),
never part of the repo — clone the project anywhere and each computer keeps its own.
Resolution order:

1. Explicit setting (Settings → MATLAB command, or the settings.json `matlabCommand`)
2. `PIPEFORGE_MATLAB` environment variable (a shell-style command)
3. `matlab` on PATH
4. Standard installs: `/usr/local/MATLAB/R20xx`, `/opt/MATLAB/R20xx`,
   `/Applications/MATLAB_R20xx.app` (newest first)
5. A Distrobox container with "matlab" in its name

On a machine with a normal install, things usually just work. To set up explicitly,
run **`pipeforge-cli matlab detect`** once (or click **Detect** in Settings): it
*actually starts* each candidate until one answers, then saves the winner — this
matters when a binary exists but can't run, e.g. a container-only install whose
directory is visible on the host.

## Install

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pipeforge          # GUI
pipeforge-cli -h   # headless
```

Requires Python ≥ 3.11 and Linux/macOS. External tools are **optional** and
auto-detected (status dots in the GUI): Verilator + cocotb unlock co-simulation,
graphviz `dot` refines DAG layout, pyslang upgrades SV parsing, Yosys/SymbiYosys
unlock the formal hooks. Everything else works without them.

## Quick start

```sh
pipeforge-cli audit seed/example.m                 # latency audit + findings
pipeforge-cli lint mypipe.sv                       # convention check
pipeforge-cli codegen seed/example.m -o gen.sv     # emit nkMatlib skeleton
pipeforge-cli ranges f.m --range x=-1:1 --recommend 0.01
pipeforge-cli dse f.m --widths 12,16,20 --scales 8,12
```

In the GUI: `Ctrl+O` opens a `.m` (a matching `.sv` loads alongside), `Ctrl+1…9`
switch views, `Ctrl+R` re-runs, `Ctrl+K` opens the command palette. WIDTH/SCALE
live in the status bar and every view reacts to changes immediately.

## Development

```sh
make verify        # ruff + mypy --strict(core) + pytest with coverage
QT_QPA_PLATFORM=offscreen pytest -q --rtm-out=docs/rtm.csv   # regenerate the RTM
```

Architecture: a pure-Python, Qt-free core (`src/pipeforge/core/`) wrapped by a
PyQt6 presentation layer; the dataflow DAG is the shared data structure across
all capabilities (the node you click in the visualizer is the node named in an
audit finding, a codegen instance, and a bisection report). The binding
specification is `PipeForge_SRS.md`; per-phase reports live in `docs/phase_reports/`.
