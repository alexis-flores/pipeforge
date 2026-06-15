"""SL-6: divider-count sanity check against the optimized DAG."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.svlint.checks import CHECK_DIVIDERS, check_divider_count
from pipeforge.core.svlint.model import Instance, Port, SvModule

CM = CostModel(16, 12)


def _module(n_dividers: int) -> SvModule:
    insts = [
        Instance(
            "elem_sdiv", f"i_elem_sdiv_q{i}_28", {"a": f"a{i}_0", "b": "n_0", "f": f"q{i}_28"}, i
        )
        for i in range(n_dividers)
    ]
    return SvModule("dut", ports=[Port("valid_0", "input", 1)], instances=insts)


@pytest.mark.req("SL-6")
def test_excess_divider_count_flagged() -> None:
    # the DAG needs one divide; the RTL instantiates two -> audit advice not applied
    audit = audit_source("y = a / n;", "d.m", CM)
    assert audit.divider_count == 1
    findings = check_divider_count(_module(2), audit)
    assert findings and findings[0].check == CHECK_DIVIDERS
    assert "2 divider" in findings[0].message and "1" in findings[0].message


@pytest.mark.req("SL-6")
def test_divider_count_matches_optimized_dag() -> None:
    audit = audit_source("y = a / n;", "d.m", CM)
    assert check_divider_count(_module(1), audit) == []  # matches -> no finding
