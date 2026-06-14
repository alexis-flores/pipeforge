"""Cost model tests (AU-1, C4): all latencies derived from WIDTH/SCALE."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel


@pytest.mark.req("AU-1")
@pytest.mark.parametrize(
    ("width", "scale"),
    [(16, 12), (18, 14), (20, 12), (32, 16), (12, 8)],
)
def test_latencies_match_nkmatlib_model(width: int, scale: int) -> None:
    cm = CostModel(width, scale)
    left = width - scale
    assert cm.left == left
    assert cm.mul_lat == 4
    assert cm.div_lat == width + scale
    assert cm.sqrt_lat == width - left // 2
    assert cm.matmul_lat == cm.mul_lat + 1
    assert cm.sumsqr_lat == cm.mul_lat + 1
    assert cm.rootsqr_lat == cm.sqrt_lat + cm.sumsqr_lat
    assert cm.crossp_lat == cm.mul_lat + 1


@pytest.mark.req("AU-1")
def test_module_latency_table() -> None:
    cm = CostModel(16, 12)
    assert cm.latency_of("matadd") == 1
    assert cm.latency_of("elem_smul") == 4
    assert cm.latency_of("elem_sdiv") == 28
    assert cm.latency_of("elem_sinv") == 28
    assert cm.latency_of("elem_usqrt") == 14
    assert cm.latency_of("rootsqr") == 19
    assert cm.latency_of("elem_snorm") == 0
    assert cm.latency_of("transp") == 0
    with pytest.raises(KeyError):
        cm.latency_of("nonexistent_module")


def test_divider_classification() -> None:
    cm = CostModel(16, 12)
    assert cm.is_divider("elem_sdiv")
    assert cm.is_divider("elem_sinv")
    assert cm.is_divider("matunscale")
    assert not cm.is_divider("elem_smul")


def test_invalid_parameters_rejected() -> None:
    with pytest.raises(ValueError):
        CostModel(0, 0)
    with pytest.raises(ValueError):
        CostModel(16, 16)
    with pytest.raises(ValueError):
        CostModel(16, -1)


@pytest.mark.req("AR-5")
def test_reshape_zero_latency_zero_instances() -> None:
    from pipeforge.core.audit.engine import audit_source

    cm = CostModel(16, 12)
    assert cm.latency_of("reshape") == 0  # a relabeling, not hardware
    assert not cm.is_divider("reshape")

    # reshape neither adds latency nor appears in the operator census
    audit = audit_source("v = reshape(x, 4, 1);\ny = v + v;", "reshape.m", cm)
    assert "reshape" not in audit.census
    assert audit.census == {"matadd": 1}
    # the reshape stage contributes 0 cycles to the critical path
    assert audit.total_latency == cm.add_lat
