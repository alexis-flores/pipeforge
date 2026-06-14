"""WS-6: extracted struct constants feed range analysis as point ranges."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.ranges.interval import Interval
from pipeforge.core.workspace.mat_loader import constant_ranges, load_mat

PARAMS = (
    Path(__file__).parent.parent.parent / "src" / "pipeforge" / "demos" / "matlab" / "params.mat"
)


@pytest.mark.req("WS-6")
def test_struct_constants_become_point_ranges() -> None:
    tree = load_mat(PARAMS)
    ranges = constant_ranges(tree)
    # a scalar constant is a point range (lo == hi)
    assert ranges["gain"] == Interval(0.5, 0.5)
    assert ranges["cfg.adc.vref"] == Interval(3.3, 3.3)
    # an array constant becomes its value hull
    taps = ranges["taps"]
    assert taps.lo == -0.5 and taps.hi == 0.25
    # char fields contribute no range
    assert "cfg.label" not in ranges
