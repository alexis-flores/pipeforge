"""TL-1: harness backend selection and reporting."""

from __future__ import annotations

import pytest

from pipeforge.core.cosim.runner import CosimResult, select_harness_backend


@pytest.mark.req("TL-1")
def test_active_harness_backend_reported() -> None:
    # cocotb is the default until native parity is demonstrated
    assert select_harness_backend(None) == "cocotb"
    assert select_harness_backend("cocotb") == "cocotb"
    assert select_harness_backend("verilator") == "verilator"
    assert select_harness_backend("nonsense") == "cocotb"  # unknown -> safe default
    # the result reports which backend ran (default cocotb)
    assert CosimResult(passed=False).harness_backend == "cocotb"
