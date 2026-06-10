"""Co-simulation tests (CS-1, CS-2, CS-3) — generation and comparison logic."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.cosim.harness import golden_outputs, write_harness
from pipeforge.core.cosim.runner import CosimUnavailable, check_tools, compare_streams
from pipeforge.core.cosim.stimulus import generate_stimulus
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.fxp.fx import FxFormat, wrap

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)
FIXTURES = Path(__file__).parent.parent / "fixtures" / "cosim"


def sample_audit() -> Audit:
    src = (FIXTURES / "sample.m").read_text(encoding="utf-8")
    return audit_source(src, "sample.m", CM)


@pytest.mark.req("CS-1")
class TestStimulus:
    def test_corner_cases_present(self) -> None:
        vectors = generate_stimulus(["a", "b"], FMT, count=64)
        seen_a = {v["a"] for v in vectors}
        assert 0 in seen_a  # zeros
        assert 1 in seen_a  # +1 LSB
        assert wrap(-1, 16) in seen_a  # -1 LSB
        assert FMT.max_signed in seen_a  # +max
        assert FMT.min_raw in seen_a  # sign boundary / most negative

    def test_deterministic(self) -> None:
        a = generate_stimulus(["x", "y"], FMT, count=128, seed=7)
        b = generate_stimulus(["x", "y"], FMT, count=128, seed=7)
        assert a == b

    def test_all_inputs_in_every_vector(self) -> None:
        vectors = generate_stimulus(["a", "b", "c"], FMT, count=32)
        assert len(vectors) == 32
        for v in vectors:
            assert set(v) == {"a", "b", "c"}
            for raw in v.values():
                assert 0 <= raw <= FMT.mask


@pytest.mark.req("CS-1")
class TestHarness:
    def test_generated_collateral(self, tmp_path: Path) -> None:
        audit = sample_audit()
        vectors = generate_stimulus(["a", "b", "c"], FMT, count=16)
        spec = write_harness(audit, "cosim_sample", vectors, tmp_path)
        wrapper = (tmp_path / "tb_wrapper.sv").read_text(encoding="utf-8")
        assert "fixedp #(.WIDTH(16), .SCALE(12))" in wrapper
        assert "cosim_sample i_dut" in wrapper
        assert ".a_0 (a_0)" in wrapper
        assert ".y_N (y_N)" in wrapper
        tb = (tmp_path / "tb_cosim.py").read_text(encoding="utf-8")
        assert "valid_0" in tb
        assert "cocotb" in tb
        stim = json.loads((tmp_path / "stimulus.json").read_text(encoding="utf-8"))
        assert len(stim["vectors"]) == 16
        expected = json.loads((tmp_path / "expected.json").read_text(encoding="utf-8"))
        assert expected["latency"] == spec.latency == CM.mul_lat + CM.add_lat
        assert len(expected["outputs"]["y"]) == 16

    def test_expected_matches_golden_model(self) -> None:
        audit = sample_audit()
        vectors = generate_stimulus(["a", "b", "c"], FMT, count=8)
        outs = golden_outputs(audit, vectors, FMT)
        from pipeforge.core.fxp import ops

        for vec, got in zip(vectors, outs["y"], strict=True):
            manual = ops.add(ops.smul(vec["a"], vec["b"], FMT), vec["c"], FMT)
            assert got == manual


@pytest.mark.req("CS-3")
class TestCompare:
    def test_pass_with_error_stats(self) -> None:
        audit = sample_audit()
        vectors = generate_stimulus(["a", "b", "c"], FMT, count=16)
        expected = golden_outputs(audit, vectors, FMT)
        results = compare_streams(audit, vectors, expected, dict(expected), FMT)
        (res,) = results
        assert res.passed
        assert res.first_failure == -1
        assert res.compared == 16
        assert math.isfinite(res.rms_error)  # FX-4 stats present on pass

    def test_first_failing_vector_reported(self) -> None:
        audit = sample_audit()
        vectors = generate_stimulus(["a", "b", "c"], FMT, count=16)
        expected = golden_outputs(audit, vectors, FMT)
        corrupted = {name: list(stream) for name, stream in expected.items()}
        corrupted["y"][5] ^= 0x4
        results = compare_streams(audit, vectors, expected, corrupted, FMT)
        (res,) = results
        assert not res.passed
        assert res.first_failure == 5
        assert res.expected != res.actual

    def test_truncated_stream_fails(self) -> None:
        audit = sample_audit()
        vectors = generate_stimulus(["a", "b", "c"], FMT, count=8)
        expected = golden_outputs(audit, vectors, FMT)
        short = {"y": expected["y"][:3]}
        (res,) = compare_streams(audit, vectors, expected, short, FMT)
        assert not res.passed
        assert res.first_failure == 3


@pytest.mark.req("CS-2")
class TestToolDetection:
    def test_missing_verilator_message_is_actionable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil as shutil_mod

        monkeypatch.setattr(shutil_mod, "which", lambda _name: None)
        with pytest.raises(CosimUnavailable) as exc:
            check_tools()
        text = str(exc.value)
        assert "Verilator" in text
        assert "install" in text.lower()
        assert "keeps working" in text  # never a crash, never a hidden no-op
