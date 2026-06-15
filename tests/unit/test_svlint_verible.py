"""TL-2: optional Verible CST backend for the linter.

Skipped (not failed) without Verible, per §8.2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.svlint.parse import parse_sv, verible_available

requires_verible = pytest.mark.skipif(
    not verible_available(),
    reason="verible-verilog-syntax not installed — skipped per §8.2",
)

SAMPLE = (Path(__file__).parent.parent / "fixtures" / "cosim" / "sample.sv").read_text(
    encoding="utf-8"
)


@pytest.mark.tool("verible")
@requires_verible
@pytest.mark.req("TL-2")
def test_verible_cst_backend_parses_convention_file() -> None:
    module, backend = parse_sv(SAMPLE, backend="verible")
    assert backend == "verible"
    assert module.name == "cosim_sample"
    assert any(i.module == "smul" for i in module.instances)


@pytest.mark.tool("verible")
@requires_verible
@pytest.mark.req("TL-2")
def test_verible_backend_reported() -> None:
    _module, backend = parse_sv(SAMPLE, backend="verible")
    assert backend == "verible"  # selection follows the SL-1 reporting pattern
