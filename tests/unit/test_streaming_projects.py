"""Unit tests for the streaming/projects cycle:

delay z^-1 state (SD-1), local-function inlining (FN-1), source optimization
(OP-1), project sidecars (PJ-1/2), wiring codegen (WR-1), and the star (BN-1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.fxp.evaluator import evaluate_fixed
from pipeforge.core.fxp.fx import FxFormat, from_float

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)


# -- delay / z^-1 (SD-1) ----------------------------------------------------------


def test_delay_streams_previous_sample() -> None:
    audit = audit_source("y = delay(x);", "t.m", CM)
    (out,) = audit.dag.outputs()
    state: dict = {}
    stream = [from_float(v, FMT) for v in (0.25, 0.5, -0.75)]
    seen = []
    for raw in stream:
        values = evaluate_fixed(audit.dag, {"x": [raw]}, FMT, state=state)
        seen.append(values[out.nid][0])
    assert seen == [0, stream[0], stream[1]]  # zero history, then x[k-1]


def test_delay_is_schedule_neutral() -> None:
    # a z^-1 register must NOT advance the stage: a register that did would be
    # sample-transparent (that is exactly what a `PIPE is)
    audit = audit_source("y = delay(x);", "t.m", CM)
    assert audit.total_latency == 0
    fir = audit_source("y = x + delay(x);", "t.m", CM)
    assert fir.total_latency == 1  # just the add


def test_delay_stateless_evaluation_is_zero_history() -> None:
    audit = audit_source("y = delay(x);", "t.m", CM)
    (out,) = audit.dag.outputs()
    values = evaluate_fixed(audit.dag, {"x": [123]}, FMT)  # no state dict
    assert values[out.nid] == [0]


def test_delay_codegen_registers_without_stage_advance() -> None:
    from pipeforge.core.codegen.emitter import generate_sv

    audit = audit_source("y = x + delay(x);", "t.m", CM)
    sv = generate_sv(audit, "fir1")
    assert "i_delay_" in sv
    assert ".DELAY(1)" in sv
    assert "no stage advance" in sv


def test_delay_rejects_noncontinuous_cadence(tmp_path: Path) -> None:
    from pipeforge.core.cosim.runner import run_cosim

    audit = audit_source("y = x + delay(x);", "t.m", CM)
    with pytest.raises(ValueError, match="continuous cadence"):
        run_cosim(
            audit,
            dut_sv=tmp_path / "dut.sv",
            dut_module="dut",
            work_dir=tmp_path,
            cadence="gapped",
        )


def test_delay_range_is_passthrough_not_affine_aliased() -> None:
    from pipeforge.core.ranges.interval import Interval
    from pipeforge.core.ranges.propagate import propagate

    audit = audit_source("d = x - delay(x);", "t.m", CM)
    report = propagate(audit.dag, {"x": Interval(-1, 1)}, CM, method="affine")
    (out,) = audit.dag.outputs()
    iv = report.nodes[out.nid].interval
    # x - x[k-1] spans [-2, 2]; affine aliasing would wrongly give [0, 0]
    assert iv.lo == -2.0 and iv.hi == 2.0


# -- local functions (FN-1) ----------------------------------------------------------


_FUNC_SRC = """u = norm2(x, y);
s = boost(u);

function n = norm2(a, b)
  n = sqrt(a .* a + b .* b);
end

function y = boost(v)
  y = v .* gain2(v);
end

function g = gain2(w)
  g = w + 0.5;
end
"""


def test_functions_inline_with_hygienic_names() -> None:
    audit = audit_source(_FUNC_SRC, "t.m", CM)
    assert not audit.skipped
    targets = [s.target for s in audit.dag.statements]
    assert "u" in targets and "s" in targets
    assert any(t.startswith("norm2_x") for t in targets)  # hygienic prefixes
    assert any(t.startswith("gain2_x") for t in targets)  # nested call inlined
    # the inlined sqrt/mul cost lands on the *call site* line
    assert audit.total_latency > CM.sqrt_lat


def test_function_inputs_are_the_call_arguments() -> None:
    audit = audit_source(_FUNC_SRC, "t.m", CM)
    assert {n.label for n in audit.dag.inputs()} == {"x", "y"}


def test_function_recursion_is_reported_not_fatal() -> None:
    src = "y = f(x);\n\nfunction out = f(a)\n  out = f(a) + 1;\nend\n"
    audit = audit_source(src, "t.m", CM)
    assert any("depth" in s.reason for s in audit.skipped)


def test_function_free_variable_is_reported() -> None:
    src = "y = f(x);\n\nfunction out = f(a)\n  out = a + leaked;\nend\n"
    audit = audit_source(src, "t.m", CM)
    assert any("leaked" in s.reason for s in audit.skipped)


def test_function_arity_mismatch_is_reported() -> None:
    src = "y = f(x, x);\n\nfunction out = f(a)\n  out = a;\nend\n"
    audit = audit_source(src, "t.m", CM)
    assert any("argument" in s.reason for s in audit.skipped)


def test_script_without_functions_is_unchanged() -> None:
    from pipeforge.core.frontend.functions import parse_with_functions
    from pipeforge.core.frontend.parser import parse_program

    src = "y = a + b;\nz = y .* 2;\n"
    plain, _ = parse_program(src)
    withf, _ = parse_with_functions(src)
    assert [(a.target, a.line) for a in plain] == [(a.target, a.line) for a in withf]


# -- optimize (OP-1) --------------------------------------------------------------------


def test_optimize_recip_trades_dividers_honestly() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "n = sqrt(x .* x + y .* y);\nu = x ./ n;\nv = y ./ n;\n"
    result = optimize_source(src, CM, vectors=16)
    assert result.changed
    assert any(r.tag == "RECIP" for r in result.rewrites)
    # parallel divisions: RECIP is an *area* win (fewer dividers), and the
    # report must carry both dimensions rather than pretend it is free
    assert result.dividers_after < result.dividers_before
    assert result.accuracy and all(a.max_delta < 0.01 for a in result.accuracy)
    reaudit = audit_source(result.source, "opt.m", CM)
    assert not reaudit.skipped


def test_optimize_reduces_latency_on_serial_chains() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "w = c / d / e;\np = q ^ 4;\n"  # SERDIV + POW: genuine depth wins
    result = optimize_source(src, CM, vectors=8)
    assert result.changed
    assert result.latency_after < result.latency_before


def test_optimize_untouched_lines_stay_byte_identical() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "% keep me  \nk = a .* b;\nu = x ./ n;\nv = y ./ n;\n"
    result = optimize_source(src, CM, vectors=4)
    assert "% keep me  " in result.source
    assert "k = a .* b;" in result.source


def test_optimize_noop_returns_original() -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    src = "y = a + b;\n"
    result = optimize_source(src, CM)
    assert not result.changed
    assert result.source == src


# -- project sidecar (PJ-1/2) ---------------------------------------------------------


def test_project_roundtrip(tmp_path: Path) -> None:
    from pipeforge.core.project import (
        CosimConfig,
        Project,
        load_project,
        save_project,
        sidecar_for,
    )

    p = Project(
        m="model.m",
        sv="rtl/dut.sv",
        width=18,
        scale=14,
        family="ultrascale",
        ranges={"x": (-1.0, 1.0), "y": (0.5, 2.0)},
        cosim=CosimConfig(top="dut", backend="verilator", vectors=64, include=["rtl"]),
    )
    target = sidecar_for(tmp_path / "model.m")
    assert target.name == "model.pipeforge.toml"
    save_project(p, target)
    loaded = load_project(target)
    assert loaded.width == 18 and loaded.family == "ultrascale"
    assert loaded.ranges == {"x": (-1.0, 1.0), "y": (0.5, 2.0)}
    assert loaded.cosim.top == "dut" and loaded.cosim.include == ["rtl"]


def test_load_for_design_absent_or_bad(tmp_path: Path) -> None:
    from pipeforge.core.project import load_for_design, sidecar_for

    m = tmp_path / "model.m"
    assert load_for_design(m) is None
    sidecar_for(m).write_text("this is [ not toml", encoding="utf-8")
    assert load_for_design(m) is None  # malformed: never raises


def test_ci_command_gates_on_ranges(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pipeforge.cli import main

    (tmp_path / "model.m").write_text("energy = 2 .* (sig .* sig);\n", encoding="utf-8")
    sidecar = tmp_path / "model.pipeforge.toml"
    sidecar.write_text('[design]\nm = "model.m"\n\n[ranges]\nsig = [-3.0, 3.0]\n', encoding="utf-8")
    rc = main(["ci", str(sidecar)])
    out = capsys.readouterr().out
    assert rc == 1  # 2*sig^2 at sig=±3 overflows 16/12: the gate must fail
    assert "ranges: FAIL" in out or "overflow" in out
    # widen nothing, shrink the range: the gate passes
    sidecar.write_text('[design]\nm = "model.m"\n\n[ranges]\nsig = [-1.0, 1.0]\n', encoding="utf-8")
    assert main(["ci", str(sidecar)]) == 0


# -- the star (BN-1) ---------------------------------------------------------------


def test_banner_hidden_from_pipes(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeforge.cli import main

    monkeypatch.delenv("PIPEFORGE_BANNER", raising=False)
    main([])
    assert "✵" not in capsys.readouterr().out  # capsys stdout is not a TTY


def test_banner_forced_for_the_star_lover(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeforge.cli import main

    monkeypatch.setenv("PIPEFORGE_BANNER", "1")
    main([])
    out = capsys.readouterr().out
    assert out.count("✵") >= 30  # it had better be BIG
    assert "P I P E F O R G E" in out
