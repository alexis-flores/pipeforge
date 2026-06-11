# Phase 9 report — Live MATLAB bridge (post-SRS feature)

Connects PipeForge to a real MATLAB session (R2026a in the `matlab-sandbox` Distrobox
container; command template configurable and persisted, NF-7) and lets live workspace
data **change the analysis**, per the approved plan.

Delivered in five gated steps, each committed:
- **M1 — bridge**: `core/frontend/varinfo.py` (`WorkspaceSnapshot`/`VarInfo` with struct
  recursion, fi numerictypes, value cap + min/max), `services/matlab_bridge.py`
  (generated `pf_query.m` run via `matlab -batch` through distrobox; files exchanged
  under the home-shared config dir, never /tmp; mtime-keyed snapshot cache; actionable
  `MatlabUnavailable` per C2), `pipeforge-cli matlab probe|snapshot`, tools dot.
- **M2 — grammar**: struct-field atoms `a.b.c` across lexer/parser/AST/DAG (input-leaf
  semantics; dotted-indexed `cfg.taps(3)` stays an opaque Index; RTL port names
  sanitize `.`→`_`). **Documented grammar extension** over SRS §4.1 (per §10 the
  grammar is otherwise frozen); all golden files verified byte-identical.
- **M3 — shape/format awareness**: leaf shapes from the snapshot propagate through the
  DAG (`Node.shape`); `*` maps to `matmul`/`matscale` and `/` to `matunscale` by shape;
  transpose swaps shapes; reductions are scalar. fi-format mismatches surface as a new
  **FORMAT** finding anchored to the input node. `snapshot=None` is bit-identical
  (golden suite pins it).
- **M4 — live values**: snapshot values drive the evaluator (`snapshot_inputs`),
  empirical ranges (`ranges_from_snapshot`), and stimulus
  (`generate_stimulus_with_samples`); `compare_to_matlab` validates the golden model
  against MATLAB's own per-statement values (`pipeforge-cli matlab validate`).
- **M5 — GUI**: workspace-held snapshot with threaded refresh (Ctrl+Shift+M, palette,
  UI-3), MATLAB output streamed to the console, inspector shows class/size/fi/value
  preview per node, Settings edits the command template + setup file, snapshot cleared
  on file switch.

Live evidence (real R2026a 26.1.0 through the container): snapshot of 11 variables with
`cfg.filter.taps` resolved and a 6000-element array truncated at 4096 with exact
min/max; `matlab validate demo.m` reports `y = cfg.gain * x + offset` **bit-clean**
across all lanes and `n = norm(x)` within 6.81e-05 (sub-LSB at SCALE 12, SQNR 78.5 dB).

- Tests: 290 passed (full suite incl. 3 live-MATLAB tests that skip per §8.2 when the
  container is absent). ruff + mypy --strict(core): clean. Goldens untouched.
- Constraint note: the bridge is local container IPC through the user's own filesystem —
  C3 ("no network access") is preserved; MATLAB remains an optional tool per C2.
- Known limitations: matrix evaluation is flat-lane (matmul validates as dotprod);
  persistent in-container engine (instant repeated queries) is a designed-for future
  backend behind the same snapshot interface.
