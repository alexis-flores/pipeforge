"""CS-9: co-simulate one mapped operation's sub-DAG in isolation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.codegen.emitter import generate_sv
from pipeforge.core.cosim.modular import sub_audit
from pipeforge.core.costmodel.model import CostModel

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"
MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)
SRC = "prod = a .* b;\ny = prod + c;"


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


@pytest.mark.req("CS-9")
def test_sub_dag_isolates_just_the_operation() -> None:
    # isolating 'prod' drops the downstream adder and the c input entirely
    audit = audit_source(SRC, "sample.m", CM)
    prod_nid = audit.dag.statements[0].root
    sub = sub_audit(audit, prod_nid)
    in_labels = {n.label for n in sub.dag.inputs()}
    assert in_labels == {"a", "b"}  # not c — it is downstream of prod
    sv = generate_sv(sub, "sub_dut")
    assert "elem_smul" in sv and "matadd" not in sv  # just the multiply stage


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("CS-9")
def test_group_isolated_against_sub_dag_golden(tmp_path: Path) -> None:
    from pipeforge.core.cosim.modular import modular_cosim

    audit = audit_source(SRC, "sample.m", CM)
    prod_nid = audit.dag.statements[0].root  # the multiply op
    needed = ["fixedp.sv", "elem_smul.sv", "smul.sv", "smul_raw.sv", "norm.sv", "valid.sv"]
    result = modular_cosim(
        audit,
        prod_nid,
        work_dir=tmp_path / "modular",
        extra_sources=[MATLIB_RTL / n for n in needed],
        include_dirs=[MATLIB_RTL],
        vector_count=64,
    )
    assert result.passed, result.log[-3000:]
    assert all(o.passed for o in result.outputs)
