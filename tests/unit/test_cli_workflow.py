"""CLI surface tests for the engineer-workflow commands (tool-free paths)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pipeforge.cli import main

DEMOS = Path(__file__).parents[2] / "src" / "pipeforge" / "demos"


def test_audit_resources_flag(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["audit", str(DEMOS / "02_normalize3d.m"), "--resources"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "== resources ==" in out
    assert "DSP (xilinx7)" in out


def test_audit_resources_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["audit", str(DEMOS / "02_normalize3d.m"), "--resources", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resources"]["family"] == "xilinx7"
    assert payload["resources"]["dsp"] >= 1


def test_report_writes_html(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "review.html"
    rc = main(
        [
            "report",
            str(DEMOS / "02_normalize3d.m"),
            "-o",
            str(out),
            "--range",
            "x=-1:1",
            "--range",
            "y=-1:1",
            "--range",
            "z=-1:1",
        ]
    )
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html and "Range analysis" in html


def test_export_tb_writes_collateral(tmp_path: Path) -> None:
    rc = main(
        [
            "export-tb",
            str(DEMOS / "03_pipeline.m"),
            "-o",
            str(tmp_path),
            "-m",
            "demo_pipeline",
            "--vectors",
            "8",
        ]
    )
    assert rc == 0
    assert (tmp_path / "tb_check.sv").is_file()
    assert len((tmp_path / "stim_a.hex").read_text(encoding="utf-8").splitlines()) == 8


def test_lint_sarif_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sarif = tmp_path / "lint.sarif"
    rc = main(["lint", str(DEMOS / "04_lint_bugs.sv"), "--sarif", str(sarif)])
    assert rc == 1  # findings present -> nonzero for CI gating
    doc = json.loads(sarif.read_text(encoding="utf-8"))
    assert doc["runs"][0]["results"]  # the planted bugs annotate lines


def test_codegen_axis_emits_wrapper(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "dp.sv"
    rc = main(
        ["codegen", str(DEMOS / "03_pipeline.m"), "-m", "demo_pipeline", "--axis", "-o", str(out)]
    )
    assert rc == 0
    wrapper = tmp_path / "dp_axis.sv"
    assert wrapper.is_file()
    assert "demo_pipeline_axis" in wrapper.read_text(encoding="utf-8")


def test_codegen_mixed_requires_ranges(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["codegen", str(DEMOS / "05_ranges.m"), "--mixed"])
    assert rc == 2
    assert "--range" in capsys.readouterr().err


def test_codegen_mixed_narrows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "codegen",
            str(DEMOS / "05_ranges.m"),
            "-m",
            "demo",
            "--mixed",
            "--range",
            "sig=-1:1",
            "--range",
            "ref=0.5:1",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "narrowed" in captured.err
    assert "Mixed precision" in captured.out


def test_cosim_replay_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "cosim",
            str(DEMOS / "03_pipeline.m"),
            "--sv",
            str(DEMOS / "03_pipeline.sv"),
            "--top",
            "demo_pipeline",
            "--replay",
            "/nonexistent/failure.json",
        ]
    )
    assert rc == 2
    assert "cannot replay" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("yosys") is None, reason="yosys absent — skipped per §8.2")
@pytest.mark.tool("yosys")
def test_synth_plain_verilog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "adder.sv").write_text(
        "module adder(input [7:0] a, input [7:0] b, output [8:0] y);\n"
        "assign y = a + b;\nendmodule\n",
        encoding="utf-8",
    )
    rc = main(["synth", str(tmp_path / "adder.sv"), "--top", "adder"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "synth estimate adder" in out
    assert "cells" in out
