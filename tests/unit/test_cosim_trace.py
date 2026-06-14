"""CS-8: VCD/FST trace-capture fallback and backend reporting."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.bisect.engine import golden_intermediates
from pipeforge.core.cosim.trace import (
    CAPTURE_PROBE,
    CAPTURE_TRACE,
    active_capture_backend,
    parse_vcd_streams,
    trace_signal_map,
)
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.fxp.fx import FxFormat

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)


@pytest.mark.req("CS-8")
def test_fst_signal_map_by_convention() -> None:
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    prod, y = audit.dag.statements[0].root, audit.dag.statements[1].root
    mapping = trace_signal_map(audit.dag, [prod, y])
    # node id -> conventional <signal>_<stage> name (prod ready @4, y @5)
    assert mapping[prod] == "prod_4"
    assert mapping[y] == "y_5"

    # the reconstructed streams have the same shape the probe backend yields
    vcd = (
        "$var wire 1 ! valid_N $end\n"
        "$var wire 16 # prod_4 $end\n"
        "$enddefinitions $end\n"
        "#0\n0!\nb0 #\n"
        "#1\n1!\nb101 #\n"  # valid high, prod = 5
        "#2\n0!\nb110 #\n"  # valid low, ignored
        "#3\n1!\nb111 #\n"  # valid high, prod = 7
    )
    streams = parse_vcd_streams(vcd, {prod: "prod_4"})
    assert streams[prod] == [[5], [7]]


@pytest.mark.req("CS-8")
def test_active_capture_backend_reported() -> None:
    # probe is preferred when probe ports exist; trace is the fallback (SL-1 pattern)
    assert active_capture_backend(["n003"]) == CAPTURE_PROBE
    assert active_capture_backend(None) == CAPTURE_TRACE
    assert active_capture_backend([], trace_available=True) == CAPTURE_TRACE
    with pytest.raises(RuntimeError):
        active_capture_backend(None, trace_available=False)


@pytest.mark.req("CS-8")
def test_trace_streams_match_golden_shape() -> None:
    # a trace reconstruction feeds bisection exactly like probe Observations
    audit = audit_source("prod = a .* b;\ny = prod + c;", "s.m", CM)
    prod = audit.dag.statements[0].root
    golden = golden_intermediates(audit.dag, [{"a": 4096, "b": 4096, "c": 0}], FMT)
    assert isinstance(golden[prod], list) and isinstance(golden[prod][0], list)
