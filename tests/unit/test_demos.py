"""Packaged demos: index integrity and each demo behaving as labeled."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.ranges.interval import Interval
from pipeforge.core.ranges.propagate import propagate
from pipeforge.core.svlint.checks import lint_source
from pipeforge.demos import demo_dir, load_index

CM = CostModel(16, 12)


def test_index_loads_and_files_exist() -> None:
    entries = load_index()
    assert len(entries) == 7
    ids = [e.demo_id for e in entries]
    assert ids == sorted(ids)  # stable, numbered ordering
    for entry in entries:
        assert entry.description
        assert str(demo_dir()) in entry.command  # {dir} resolved
        assert entry.gui
        for path in entry.paths():
            assert path.is_file(), f"{entry.demo_id}: missing {path}"


@pytest.mark.parametrize(
    "name",
    ["01_findings.m", "02_normalize3d.m", "03_pipeline.m", "05_ranges.m", "06_dse.m"],
)
def test_every_m_demo_audits_cleanly(name: str) -> None:
    src = (demo_dir() / name).read_text(encoding="utf-8")
    audit = audit_source(src, name, CM)
    assert not audit.skipped, f"{name} has skipped statements: {audit.skipped}"
    assert audit.dag.statements


def test_findings_demo_triggers_all_seven() -> None:
    src = (demo_dir() / "01_findings.m").read_text(encoding="utf-8")
    audit = audit_source(src, "01_findings.m", CM)
    tags = {f.tag for f in audit.findings}
    assert tags == {"RECIP", "CDIV", "SERDIV", "POW", "CSE", "FUSE", "FEEDBACK"}


def test_pipeline_pair_lints_clean() -> None:
    sv = (demo_dir() / "03_pipeline.sv").read_text(encoding="utf-8")
    result = lint_source(sv, "03_pipeline.sv", CM)
    assert result.findings == [], [f"{f.check}: {f.message}" for f in result.findings]


def test_lint_bugs_demo_triggers_labeled_findings() -> None:
    sv = (demo_dir() / "04_lint_bugs.sv").read_text(encoding="utf-8")
    result = lint_source(sv, "04_lint_bugs.sv", CM)
    checks = {f.check for f in result.findings}
    assert "delay-match" in checks
    assert "valid-chain" in checks


def test_ranges_demo_flags_hazards() -> None:
    src = (demo_dir() / "05_ranges.m").read_text(encoding="utf-8")
    audit = audit_source(src, "05_ranges.m", CM)
    ranges = {"sig": Interval(-3.0, 3.0), "ref": Interval(-1.0, 1.0)}
    report = propagate(audit.dag, ranges, CM)
    assert report.overflow_nodes, "expected an OVERFLOW RISK at 16/12"
    assert report.hazard_nodes, "expected a NEAR-ZERO DIVISOR hazard"


def test_params_mat_is_a_real_mat_file() -> None:
    header = (demo_dir() / "matlab" / "params.mat").read_bytes()[:64]
    assert header.startswith(b"MATLAB 5.0 MAT-file")


def test_cli_demos_lists_everything(capsys: pytest.CaptureFixture[str]) -> None:
    from pipeforge.cli import main

    assert main(["demos"]) == 0
    out = capsys.readouterr().out
    for entry in load_index():
        assert entry.demo_id in out
        assert "try:" in out
