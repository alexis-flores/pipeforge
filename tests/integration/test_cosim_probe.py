"""CS-7: probe ports captured into an Observations dict keyed by node id.

Skipped (not failed) without Verilator/cocotb, per §8.2.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"
MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)


def _cocotb_available() -> bool:
    try:
        import cocotb  # noqa: F401

        return True
    except ImportError:
        return False


requires_tools = pytest.mark.skipif(
    shutil.which("verilator") is None or not _cocotb_available(),
    reason="co-simulation tools absent (verilator/cocotb) — skipped per §8.2",
)

_NEEDED = [
    "fixedp.sv",
    "elem_smul.sv",
    "smul.sv",
    "smul_raw.sv",
    "norm.sv",
    "matadd.sv",
    "add.sv",
    "pipe.sv",
    "valid.sv",
]


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("CS-7")
def test_observations_captured_from_probes(tmp_path: Path) -> None:
    from pipeforge.core.bisect.engine import golden_intermediates
    from pipeforge.core.codegen.emitter import generate_sv
    from pipeforge.core.cosim.runner import run_cosim
    from pipeforge.core.fxp.fx import FxFormat

    src = "prod = a .* b;\ny = prod + c;"
    audit = audit_source(src, "sample.m", CM)
    prod_nid = audit.dag.statements[0].root
    probes = [prod_nid]

    dut = tmp_path / "gen_probed.sv"
    dut.write_text(generate_sv(audit, "gen_probed", probes=probes), encoding="utf-8")
    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="gen_probed",
        work_dir=tmp_path / "cosim",
        extra_sources=[MATLIB_RTL / n for n in _NEEDED],
        include_dirs=[MATLIB_RTL],
        vector_count=32,
        probes=probes,
    )
    assert result.passed, result.log[-3000:]
    assert result.capture_backend == "probe"
    # Observations are keyed by node id and match the golden intermediates
    assert prod_nid in result.observations
    fmt = FxFormat(CM.width, CM.scale)
    vectors = [{k: v for k, v in vec.items()} for vec in _read_vectors(tmp_path / "cosim")]
    golden = golden_intermediates(audit.dag, vectors, fmt)
    n = len(result.observations[prod_nid])
    assert result.observations[prod_nid] == golden[prod_nid][:n]


def _read_vectors(work_dir: Path) -> list[dict[str, int]]:
    import json

    return json.loads((work_dir / "stimulus.json").read_text())["vectors"]
