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
