"""Formal hooks tests (FV-1, FV-2)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.cosim.formal import (
    FormalUnavailable,
    check_formal_tools,
    write_formal_project,
)
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.ranges.interval import Interval

CM = CostModel(16, 12)
FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"


@pytest.mark.req("FV-1")
def test_formal_project_generation(tmp_path: Path) -> None:
    src = (FIXTURES / "sample.m").read_text(encoding="utf-8")
    audit = audit_source(src, "sample.m", CM)
    sby = write_formal_project(
        audit,
        dut_sv=FIXTURES / "sample.sv",
        dut_module="cosim_sample",
        work_dir=tmp_path,
        input_ranges={"a": Interval(-1.0, 1.0)},
    )
    assert sby.is_file()
    wrapper = (tmp_path / "formal_top.sv").read_text(encoding="utf-8")
    latency = audit.total_latency
    # valid-propagation delay equals the computed latency (FV-1)
    assert f"valid_ref[{latency - 1}]" in wrapper
    assert "assert (valid_N == valid_ref" in wrapper
    # RP-1 input assumption rendered as SVA assume
    assert "assume property" in wrapper
    assert f"{-(1 << CM.scale)}" in wrapper  # -1.0 at scale 12
    sby_text = sby.read_text(encoding="utf-8")
    assert "mode bmc" in sby_text
    assert "formal_top" in sby_text


@pytest.mark.req("FV-2")
def test_missing_tools_disable_formal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    with pytest.raises(FormalUnavailable, match="keeps working"):
        check_formal_tools()
