"""CLI cosim surfacing: backend selection + JSON reporting (TL-1/CS-6 via CLI).

Skipped (not failed) without Verilator/cocotb, per §8.2.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pipeforge.cli import main

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"
MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
_NEEDED = ["fixedp.sv", "smul.sv", "smul_raw.sv", "norm.sv", "add.sv", "pipe.sv", "valid.sv"]


def _cocotb() -> bool:
    try:
        import cocotb  # noqa: F401

        return True
    except ImportError:
        return False


requires_tools = pytest.mark.skipif(
    shutil.which("verilator") is None or not _cocotb(),
    reason="co-simulation tools absent (verilator/cocotb) — skipped per §8.2",
)


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("TL-1")
def test_cli_cosim_native_backend_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sources: list[str] = []
    for n in _NEEDED:
        sources += ["--source", str(MATLIB_RTL / n)]
    argv = [
        "cosim",
        str(FIXTURES / "sample.m"),
        "--sv",
        str(FIXTURES / "sample.sv"),
        "--top",
        "cosim_sample",
        *sources,
        "--include",
        str(MATLIB_RTL),
        "--vectors",
        "32",
        "--backend",
        "verilator",
        "--json",
        "--work-dir",
        str(tmp_path / "w"),
    ]
    code = main(argv)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["passed"] is True
    assert payload["harness_backend"] == "verilator"  # native path reported via CLI
