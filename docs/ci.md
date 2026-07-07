# Running PipeForge in CI

PipeForge's verification commands are built to gate pull requests: exit codes
are meaningful, lint exports SARIF (GitHub renders it as inline PR
annotations), and co-simulation exports JUnit XML (any CI dashboard renders
it as a test suite).

| Command | Exit 0 | Nonzero | CI artifact |
|---|---|---|---|
| `pipeforge-cli lint dut.sv --sarif lint.sarif` | clean | findings → 1 | SARIF 2.1.0 |
| `pipeforge-cli cosim model.m --sv dut.sv --top dut --backend verilator --junit-xml cosim.xml` | bit-exact | mismatch → 1, tools missing → 3 | JUnit XML |
| `pipeforge-cli ranges model.m --range …` | analyzed | analysis error → 1 | text/JSON |
| `pipeforge-cli report model.m -o report.html …` | written | — | self-contained HTML |

On a failing cosim the work dir also contains `failure.json` (replay the exact
vectors with `--replay`) and, with `--bisect`, `divergence.gtkw` + `dump.vcd`
(open in GTKWave with the failing cycle pre-selected) — upload them as
artifacts so the developer starts from the divergence, not from scratch.

## GitHub Actions example

```yaml
name: rtl-checks
on: [pull_request]

jobs:
  pipeforge:
    runs-on: ubuntu-latest
    permissions:
      security-events: write   # SARIF upload
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: sudo apt-get update && sudo apt-get install -y verilator
      - run: pip install pipeforge  # or: pip install -e .

      - name: Lint RTL (annotates the PR inline)
        run: pipeforge-cli lint rtl/dut.sv --verilator --include matlib-main/rtl --sarif lint.sarif
        continue-on-error: true
      - uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: lint.sarif }

      - name: Co-simulate against the golden model
        run: >
          pipeforge-cli cosim model/dut.m --sv rtl/dut.sv --top dut
          --backend verilator --include matlib-main/rtl
          --bisect --junit-xml cosim.xml

      - name: Publish cosim results
        if: always()
        uses: mikepenz/action-junit-report@v4
        with: { report_paths: cosim.xml }

      - name: Upload failure artifacts (replay file + waveform)
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: cosim-divergence
          path: |
            model/cosim_work/failure.json
            model/cosim_work/divergence.gtkw
            model/cosim_work/**/*.vcd
```

Reproduce a CI failure locally with the uploaded artifact:

```sh
pipeforge-cli cosim model/dut.m --sv rtl/dut.sv --top dut \
  --backend verilator --include matlib-main/rtl \
  --replay failure.json --bisect
gtkwave cosim_work/dump.vcd cosim_work/divergence.gtkw
```
