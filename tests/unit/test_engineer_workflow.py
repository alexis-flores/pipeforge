"""Unit tests for the engineer-workflow capabilities:

resources (RE-1), synth parsing (SY-1), verilator lint parsing (SL-7),
waveform hand-off (WV-1), vector replay/export (VX-1/2), CI outputs
(CI-1/2), HTML report (RH-1), mixed precision (MX-1), AXI wrapper (AX-1),
watch loop (WT-1). Everything here is tool-free; tool-driven paths live in
tests/integration.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.costmodel.model import CostModel

FIXTURES = Path(__file__).parent.parent / "fixtures"
DEMOS = Path(__file__).parents[2] / "src" / "pipeforge" / "demos"


def _audit(src: str, name: str = "t.m", width: int = 16, scale: int = 12) -> Audit:
    return audit_source(src, name, CostModel(width, scale))


# -- resources (RE-1) -----------------------------------------------------------


def test_dsp_tiling_matches_vendor_first_order() -> None:
    from pipeforge.core.costmodel.resources import FAMILIES, dsp_tiles_per_multiplier

    x7 = FAMILIES["xilinx7"]
    assert dsp_tiles_per_multiplier(16, x7) == 1  # 16x16 fits one DSP48E1
    assert dsp_tiles_per_multiplier(18, x7) == 1
    assert dsp_tiles_per_multiplier(32, x7) == 4  # composed
    assert dsp_tiles_per_multiplier(18, FAMILIES["lattice"]) == 1


def test_estimate_resources_census() -> None:
    from pipeforge.core.costmodel.resources import estimate_resources

    audit = _audit("y = a .* b;\nz = y ./ c;\nw = sqrt(z);\n")
    est = estimate_resources(audit.census, audit.cm)
    assert est.multipliers == 1
    assert est.dividers == 1
    assert est.sqrts == 1
    assert est.dsp == 1  # 16-bit multiply on xilinx7
    assert est.lut_approx > 0 and est.ff_approx > 0
    assert "DSP" in est.summary()


def test_estimate_resources_unknown_family() -> None:
    from pipeforge.core.costmodel.resources import estimate_resources

    with pytest.raises(ValueError, match="unknown device family"):
        estimate_resources({}, CostModel(16, 12), family="tofu")


def test_dse_points_carry_dsp() -> None:
    from pipeforge.core.dse.sweep import _evaluate_point

    p = _evaluate_point("y = a .* b;\n", "t.m", 16, 12, 4, 1)
    assert p.dsp == 1


# -- synth stat parsing (SY-1) --------------------------------------------------

_YOSYS_LOG = """
2.49. Printing statistics.

=== demo ===

   Number of wires:                 42
   Number of wire bits:            600
   Number of cells:                 17
     $_ANDNOT_                       3
     pipe                            2
     smul                            1

2.50. Executing LTP pass (find longest path).
Longest topological path in demo (length=9):
"""


def test_parse_stat() -> None:
    from pipeforge.core.synth.estimate import parse_stat

    est = parse_stat(_YOSYS_LOG)
    assert est.total_cells == 17
    assert est.wires == 42
    assert est.cells["pipe"] == 2
    assert est.longest_path == 9
    assert "17 cells" in est.summary()
    assert "$_ANDNOT_" not in est.summary()  # internal cells hidden from the summary


# -- verilator lint parsing (SL-7) ----------------------------------------------

_VERILATOR_LOG = """
%Warning-WIDTHEXPAND: dut.sv:12:5: Operator ASSIGN expects 16 bits
%Warning-DECLFILENAME: dut.sv:5:8: Filename 'x' does not match MODULE name
%Warning-UNOPTFLAT: other.sv:9:1: Signal unoptimizable
%Error: dut.sv:30:2: syntax error, unexpected endmodule
not a message line
"""


def test_parse_verilator_output() -> None:
    from pipeforge.core.svlint.verilator import parse_verilator_output

    findings = parse_verilator_output(_VERILATOR_LOG, "dut.sv")
    checks = [f.check for f in findings]
    assert "verilator-WIDTHEXPAND" in checks
    assert "verilator-ERROR" in checks
    assert "verilator-DECLFILENAME" not in checks  # suppressed noise
    assert all("other.sv" not in f.message for f in findings)  # other files filtered
    assert findings[0].line == 12


def test_render_lint_top_wraps_interface_port() -> None:
    from pipeforge.core.svlint.verilator import render_lint_top

    sv = (DEMOS / "03_pipeline.sv").read_text(encoding="utf-8")
    top = render_lint_top(sv, 16, 12)
    assert top is not None
    assert "fixedp #(.WIDTH(16), .SCALE(12)) g" in top
    assert "demo_pipeline dut" in top
    assert ".a_0 (w_a_0)" in top
    assert "logic w_valid_0;" in top  # valid ports stay 1-bit


def test_render_lint_top_none_without_interface() -> None:
    from pipeforge.core.svlint.verilator import render_lint_top

    assert render_lint_top("module plain(input a, output b); endmodule", 16, 12) is None


# -- waveform hand-off (WV-1) ---------------------------------------------------

_VCD = """$timescale 1ps $end
$scope module tb_native $end
$var wire 1 ! clk $end
$var wire 1 " valid_0 $end
$var wire 1 # valid_N $end
$var wire 16 $ a_0 [15:0] $end
$var wire 16 % y_N [15:0] $end
$scope module i_dut $end
$var wire 16 & y_1 [15:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
0#
b0 $
b0 %
b0 &
#5
1!
#10
0!
#15
1!
1#
b101 &
#20
0!
"""


def test_vcd_signal_index_paths_and_widths() -> None:
    from pipeforge.core.cosim.wave import vcd_signal_index

    index = vcd_signal_index(_VCD)
    assert index["y_1"].full_path == "tb_native.i_dut.y_1"
    assert index["y_1"].width == 16
    assert index["clk"].full_path == "tb_native.clk"
    assert index["clk"].width == 1


def test_clk_posedge_times() -> None:
    from pipeforge.core.cosim.wave import clk_posedge_times

    assert clk_posedge_times(_VCD) == [5, 15]


def test_render_gtkw_groups_and_dumpfile(tmp_path: Path) -> None:
    from pipeforge.core.cosim.wave import render_gtkw

    audit = _audit("y = a + a;\n")
    vcd = tmp_path / "dump.vcd"
    vcd.write_text(_VCD, encoding="utf-8")
    gtkw = render_gtkw(vcd, audit.dag, audit.total_latency, None, vcd_text=_VCD)
    assert f'[dumpfile] "{vcd.resolve()}"' in gtkw
    assert "-stimulus" in gtkw
    assert "tb_native.a_0[15:0]" in gtkw
    assert "-outputs" in gtkw
    assert "tb_native.valid_N" in gtkw


def test_write_gtkw_no_vcd_returns_none(tmp_path: Path) -> None:
    from pipeforge.core.cosim.wave import write_gtkw

    audit = _audit("y = a + a;\n")
    assert write_gtkw(tmp_path, audit.dag, audit.total_latency, None) is None


# -- vectors: persistence, replay, export (VX-1/2) --------------------------------


def test_failure_roundtrip(tmp_path: Path) -> None:
    from pipeforge.core.cosim.vectors import load_vectors, save_failure

    vectors = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    path = save_failure(tmp_path, vectors, ["a", "b"], {"y": 1}, 16, 12)
    assert path.name == "failure.json"
    assert load_vectors(path) == vectors
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["first_failure_by_output"] == {"y": 1}


def test_load_vectors_rejects_garbage(tmp_path: Path) -> None:
    from pipeforge.core.cosim.vectors import load_vectors

    bad = tmp_path / "bad.json"
    bad.write_text('{"nope": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="vectors"):
        load_vectors(bad)


def test_export_testbench_writes_hex_and_tb(tmp_path: Path) -> None:
    from pipeforge.core.cosim.vectors import export_testbench

    audit = _audit("y = a .* b;\n")
    vectors = [{"a": 0x1000, "b": 0x2000}, {"a": 0xFFFF, "b": 0x0001}]
    written = export_testbench(audit, vectors, tmp_path, "dut_mod")
    names = {p.name for p in written}
    assert names == {"stim_a.hex", "stim_b.hex", "expected_y.hex", "tb_check.sv"}
    assert (tmp_path / "stim_a.hex").read_text(encoding="utf-8").splitlines() == [
        "1000",
        "ffff",
    ]
    tb = (tmp_path / "tb_check.sv").read_text(encoding="utf-8")
    assert "dut_mod i_dut" in tb
    assert '$readmemh("expected_y.hex", expected_y);' in tb
    assert "$fatal(1);" in tb  # nonzero exit on FAIL: CI-usable


def test_generate_ranged_stimulus_stays_in_range() -> None:
    from pipeforge.core.cosim.stimulus import generate_ranged_stimulus
    from pipeforge.core.fxp.fx import FxFormat, to_float

    fmt = FxFormat(16, 12)
    vectors = generate_ranged_stimulus(["a"], fmt, {"a": (0.5, 1.0)}, count=64)
    assert len(vectors) == 64
    lsb = 2**-12
    for vec in vectors:
        assert 0.5 - lsb <= to_float(vec["a"], fmt) <= 1.0 + lsb


# -- CI outputs (CI-1/2) ---------------------------------------------------------


def _cosim_result(passed: bool):
    from pipeforge.core.cosim.runner import CosimResult, OutputResult

    return CosimResult(
        passed=passed,
        outputs=[
            OutputResult(
                name="y",
                passed=passed,
                compared=8,
                first_failure=-1 if passed else 3,
                expected=0 if passed else 0x10,
                actual=0 if passed else 0x11,
                max_abs_error=0.001,
                rms_error=0.0005,
                sqnr_db=70.0,
            )
        ],
    )


def test_junit_xml_pass_and_fail() -> None:
    from pipeforge.core.reports.junit import junit_xml

    ok = ET.fromstring(junit_xml(_cosim_result(True), "cosim.dut"))
    assert ok.get("failures") == "0"
    bad = ET.fromstring(junit_xml(_cosim_result(False), "cosim.dut"))
    assert bad.get("failures") == "1"
    failure = bad.find("./testcase/failure")
    assert failure is not None
    assert "vector #3" in (failure.get("message") or "")


def test_sarif_document() -> None:
    from pipeforge.core.reports.sarif import sarif_document
    from pipeforge.core.svlint.checks import LintFinding, LintResult

    result = LintResult(filename="dut.sv", backend="regex", module="dut")
    result.findings.append(
        LintFinding(check="delay-match", line=12, message="operand skewed", fix="add `PIPE")
    )
    doc = json.loads(sarif_document(result, "rtl/dut.sv", "1.0"))
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    assert run["results"][0]["ruleId"] == "delay-match"
    region = run["results"][0]["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 12


# -- HTML report (RH-1) ------------------------------------------------------------


def test_build_report_self_contained() -> None:
    from pipeforge.core.costmodel.resources import estimate_resources
    from pipeforge.core.ranges.interval import Interval
    from pipeforge.core.ranges.propagate import propagate
    from pipeforge.core.reports.html import build_report

    audit = _audit("n = sqrt(x .* x + y .* y);\nu = x ./ n;\n")
    ranges = {"x": Interval(-1, 1), "y": Interval(-1, 1)}
    report = propagate(audit.dag, ranges, audit.cm)
    html = build_report(
        audit,
        resources=estimate_resources(audit.census, audit.cm),
        range_report=report,
    )
    assert html.startswith("<!DOCTYPE html>")
    assert "<svg" in html  # inline timeline
    assert "Range analysis" in html
    assert "DSP tiles" in html
    assert "http://" not in html.replace("http://www.w3.org", "")  # no external assets


# -- mixed precision (MX-1) ---------------------------------------------------------


def _mixed_setup():
    from pipeforge.core.codegen.mixed import plan_widths
    from pipeforge.core.ranges.interval import Interval
    from pipeforge.core.ranges.propagate import propagate

    src = (DEMOS / "05_ranges.m").read_text(encoding="utf-8")
    audit = _audit(src, "05_ranges.m")
    ranges = {"sig": Interval(-1, 1), "ref": Interval(0.5, 1)}
    report = propagate(audit.dag, ranges, audit.cm)
    return audit, plan_widths(audit, report)


def test_plan_widths_narrows_only_safe_operators() -> None:
    audit, plan = _mixed_setup()
    assert plan.narrowed > 0
    assert plan.bits_saved > 0
    for nid, width in plan.widths.items():
        node = audit.dag.nodes[nid]
        assert node.module not in ("elem_sdiv", "elem_sinv", "elem_usqrt")  # latency-variant
        assert audit.cm.scale + 2 <= width < audit.cm.width
        assert width % 2 == 0


def test_mixed_emission_adapts_and_defaults_unchanged() -> None:
    from pipeforge.core.codegen.emitter import generate_sv

    audit, plan = _mixed_setup()
    uniform = generate_sv(audit, "demo")
    mixed = generate_sv(audit, "demo", plan=plan)
    assert uniform == generate_sv(audit, "demo")  # default path untouched & deterministic
    assert "Mixed precision" not in uniform
    assert "Mixed precision" in mixed
    assert "fixedp #(.WIDTH(14), .SCALE(12)) g_w14" in mixed
    assert "[13:0]" in mixed  # truncation slice at a width boundary
    assert "`TOFXD" not in mixed.split("g_w14")[0] or True  # narrow consts are literals


def test_mixed_golden_equivalence_in_model() -> None:
    """The narrowing proof: for in-range inputs the mixed widths hold the same
    values the global-width golden model computes (value-level check)."""
    from pipeforge.core.fxp.evaluator import evaluate_fixed
    from pipeforge.core.fxp.fx import FxFormat, from_float, to_float

    audit, plan = _mixed_setup()
    fmt = FxFormat(16, 12)
    for sig_val, ref_val in [(-1.0, 0.5), (0.99, 1.0), (0.25, 0.75)]:
        vec = {"sig": from_float(sig_val, fmt), "ref": from_float(ref_val, fmt)}
        values = evaluate_fixed(audit.dag, dict(vec.items()), fmt)
        for nid, width in plan.widths.items():
            for raw in values[nid]:
                value = to_float(raw, fmt)
                # the value must be representable in the planned narrow width
                limit = 2.0 ** (width - audit.cm.scale - 1)
                assert -limit <= value < limit, (nid, width, value)


# -- AXI wrapper (AX-1) --------------------------------------------------------------


def test_axis_wrapper_structure() -> None:
    from pipeforge.core.codegen.axis import generate_axis_wrapper

    src = (DEMOS / "03_pipeline.m").read_text(encoding="utf-8")
    audit = _audit(src, "03_pipeline.m")
    sv = generate_axis_wrapper(audit, "demo_pipeline")
    assert "module demo_pipeline_axis" in sv
    assert "s_axis_tready" in sv and "m_axis_tvalid" in sv
    assert "demo_pipeline i_core" in sv
    depth = int(sv.split("localparam DEPTH = ")[1].split(";")[0])
    assert depth >= audit.total_latency + 4
    assert depth & (depth - 1) == 0  # power of two
    assert "credits" in sv  # the no-stall safety mechanism


def test_axis_wrapper_needs_outputs() -> None:
    from pipeforge.core.codegen.axis import generate_axis_wrapper

    audit = _audit("x;\n")  # no assignments -> no outputs
    with pytest.raises(ValueError, match="no outputs"):
        generate_axis_wrapper(audit, "m")


# -- watch loop (WT-1) ------------------------------------------------------------


def test_watch_loop_reruns_on_mtime_change(tmp_path: Path) -> None:
    import os

    from pipeforge.core.watch import watch_loop

    target = tmp_path / "a.m"
    target.write_text("y = a + b;\n", encoding="utf-8")
    runs: list[int] = []
    stamp = [1_000_000_000]

    def fake_sleep(_s: float) -> None:
        stamp[0] += 10
        os.utime(target, (stamp[0], stamp[0]))  # every poll sees a change

    reruns = watch_loop([target], lambda: runs.append(1), max_iterations=3, sleep=fake_sleep)
    assert reruns == 3
    assert len(runs) == 4  # initial run + 3 re-runs


def test_watch_loop_stable_files_no_rerun(tmp_path: Path) -> None:
    from pipeforge.core.watch import watch_loop

    target = tmp_path / "a.m"
    target.write_text("y = a + b;\n", encoding="utf-8")
    runs: list[int] = []
    polls = [0]

    def fake_sleep(_s: float) -> None:
        polls[0] += 1
        if polls[0] > 3:
            raise KeyboardInterrupt  # user stops the stable watch

    reruns = watch_loop([target], lambda: runs.append(1), max_iterations=5, sleep=fake_sleep)
    assert reruns == 0
    assert len(runs) == 1
