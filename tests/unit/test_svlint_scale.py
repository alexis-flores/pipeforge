"""SL-5: format/SCALE continuity check."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.svlint.checks import CHECK_SCALE, lint_source

CM = CostModel(16, 12)

# a_0 is rescaled to SCALE 8 then fed to an adder alongside b_0 (still SCALE 12)
# without being brought back — the classic missing-rescale precision bug.
SV = """`include "macros.svh"
module dut (fixedp g, input valid_0,
  input [g.WIDTH-1:0] a_0, input [g.WIDTH-1:0] b_0,
  output valid_N, output [g.WIDTH-1:0] y_N);
logic [g.WIDTH-1:0] a_8;
snorm #(.F_SCALE(8)) i_snorm_a_8 ( .g (g), .a (a_0), .f (a_8) );
logic [g.WIDTH-1:0] y_1;
add i_add_y_1 ( .g (g), .a (a_8), .b (b_0), .f (y_1) );
assign valid_N = valid_0;
assign y_N = y_1;
endmodule
"""


@pytest.mark.req("SL-5")
def test_scale_continuity_flags_missing_rescale() -> None:
    result = lint_source(SV, "dut.sv", CM)
    scale_findings = result.by_check(CHECK_SCALE)
    assert scale_findings, "expected a SCALE-continuity finding"
    f = scale_findings[0]
    assert "i_add_y_1" in f.message  # names the consuming instance
    assert "a_8" in f.message and "SCALE 8" in f.message  # the odd operand + scale
    assert "delta 4" in f.message  # 12 - 8
    assert "elem_snorm" in f.fix  # the concrete rescale fix


@pytest.mark.req("SL-5")
def test_scale_check_suppressible() -> None:
    result = lint_source(SV, "dut.sv", CM, disabled=frozenset({CHECK_SCALE}))
    assert result.by_check(CHECK_SCALE) == []
