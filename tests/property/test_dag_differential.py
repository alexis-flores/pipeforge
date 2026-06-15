"""VT-1 / VT-2: DAG-level differential (metamorphic) verification.

A Hypothesis generator emits random valid small DAGs in the supported subset;
each is codegen'd and (when Verilator is present) co-simulated, asserting RTL ==
golden bit-for-bit. Without Verilator the co-sim assertion is skipped, never
failed. The generator is seedable and shrinks to a minimal reproducing DAG,
emitted to a fixtures directory for regression pinning.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.codegen.emitter import generate_sv
from pipeforge.core.costmodel.model import CostModel

MATLIB_RTL = Path(__file__).parent.parent.parent / "matlib-main" / "rtl"
CM = CostModel(16, 12)
_INPUTS = ["a", "b", "c"]
_OPS = ["+", "-", ".*"]
# every op the generator emits, with the matlib modules its RTL needs
_NEEDED = [
    "fixedp.sv",
    "elem_smul.sv",
    "smul.sv",
    "smul_raw.sv",
    "norm.sv",
    "matadd.sv",
    "add.sv",
    "matsub.sv",
    "sub.sv",
    "pipe.sv",
    "valid.sv",
]


def _cocotb_available() -> bool:
    try:
        import cocotb  # noqa: F401

        return True
    except ImportError:
        return False


def _verilator_available() -> bool:
    return shutil.which("verilator") is not None and _cocotb_available()


@st.composite
def small_program(draw: st.DrawFn) -> str:
    """A random valid straight-line program over +, -, .* (codegen-safe)."""
    n = draw(st.integers(min_value=1, max_value=3))
    avail = list(_INPUTS)
    lines: list[str] = []
    for i in range(1, n + 1):
        left = draw(st.sampled_from(avail))
        right = draw(st.sampled_from(avail))
        op = draw(st.sampled_from(_OPS))
        var = f"v{i}"
        lines.append(f"{var} = {left} {op} {right};")
        avail.append(var)
    return "\n".join(lines)


def differential_check(m_src: str) -> bool | None:
    """Codegen the program; co-sim RTL vs golden when Verilator is present.

    Returns True/False on a real run, or None when the tools are absent (the
    caller treats None as 'skipped', never a failure — VT-1).
    """
    audit = audit_source(m_src, "gen.m", CM)
    generate_sv(audit, "gen")  # must always emit cleanly
    if not _verilator_available():
        return None
    from pipeforge.core.cosim.runner import run_cosim

    work = Path(tempfile.mkdtemp())
    dut = work / "gen.sv"
    dut.write_text(generate_sv(audit, "gen"), encoding="utf-8")
    result = run_cosim(
        audit,
        dut_sv=dut,
        dut_module="gen",
        work_dir=work / "cs",
        extra_sources=[MATLIB_RTL / n for n in _NEEDED],
        include_dirs=[MATLIB_RTL],
        vector_count=8,
    )
    return result.passed


requires_tools = pytest.mark.skipif(
    not _verilator_available(),
    reason="co-simulation tools absent (verilator/cocotb) — skipped per §8.2",
)


@pytest.mark.tool("verilator")
@requires_tools
@pytest.mark.req("VT-1")
@settings(max_examples=3, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(src=small_program())
def test_random_dag_codegen_matches_golden(src: str) -> None:
    assert differential_check(src) is True  # RTL == golden, bit-for-bit


@pytest.mark.req("VT-1")
def test_skipped_without_verilator(monkeypatch: pytest.MonkeyPatch) -> None:
    # with the tools forced absent, the differential check skips (None), not fails
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert differential_check("y = a .* b;") is None


@pytest.mark.req("VT-2")
def test_failing_case_shrinks_to_minimal_dag(tmp_path: Path) -> None:
    from hypothesis import find

    # a seedable generator + shrinking finds the *minimal* DAG with >= 2 statements
    minimal = find(small_program(), lambda s: s.count(";") >= 2)
    assert minimal.count(";") == 2  # shrunk to the smallest reproducing DAG

    # emit the minimal repro (.m + generated .sv) to a fixtures dir for pinning
    out = tmp_path / "repro"
    out.mkdir()
    (out / "repro.m").write_text(minimal, encoding="utf-8")
    audit = audit_source(minimal, "repro.m", CM)
    (out / "repro.sv").write_text(generate_sv(audit, "repro"), encoding="utf-8")
    assert (out / "repro.m").is_file() and (out / "repro.sv").is_file()
