"""TL-1/TL-2: harness backend selection and reporting."""

from __future__ import annotations

import pytest

from pipeforge.core.cosim.runner import CosimResult, select_harness_backend


@pytest.mark.req("TL-1")
def test_explicit_backend_wins() -> None:
    assert select_harness_backend("cocotb") == "cocotb"
    assert select_harness_backend("verilator") == "verilator"
    # the result reports which backend ran (default cocotb)
    assert CosimResult(passed=False).harness_backend == "cocotb"


@pytest.mark.req("TL-2")
def test_auto_prefers_whatever_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    real = importlib.util.find_spec
    # auto resolves by availability, never to a missing tool's error message
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: real("json"))
    assert select_harness_backend(None) == "cocotb"
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert select_harness_backend(None) == "verilator"
    assert select_harness_backend("nonsense") in ("cocotb", "verilator")  # unknown -> auto
