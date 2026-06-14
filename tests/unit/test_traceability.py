"""DX-2: MATLAB->RTL traceability export."""

from __future__ import annotations

import csv
import io

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.diagnostics.traceability import CSV, MARKDOWN, export_traceability
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.svlint.model import Instance, SvModule

CM = CostModel(16, 12)

_SUMSQR = Instance("sumsqr", "i_sumsqr_ss_5", {"a": "v_0", "f": "ss_5"}, 1)
_USQRT = Instance("usqrt", "i_usqrt_n_19", {"a": "ss_5", "f": "n_19"}, 2)
MODULE = SvModule("dut", instances=[_SUMSQR, _USQRT])


def _norm_setup():
    assigns, _ = parse_program("n = norm(v);")
    dag = build_dag(assigns, CM)[0].dag
    nid = dag.statements[0].root
    cmap = CorrespondenceMap()
    cmap.add_group(nid, ["i_sumsqr_ss_5", "i_usqrt_n_19"])
    return dag, cmap


@pytest.mark.req("DX-2")
def test_export_matlab_to_rtl_with_per_stage_latency() -> None:
    dag, cmap = _norm_setup()

    md = export_traceability(cmap, dag, MODULE, CM, fmt=MARKDOWN)
    assert "MATLAB ↔ RTL traceability" in md
    assert "i_sumsqr_ss_5" in md and "i_usqrt_n_19" in md
    assert "i_sumsqr_ss_5=5" in md and "i_usqrt_n_19=14" in md  # per-stage latency
    assert "| n |" in md  # the MATLAB op label
    assert "19" in md  # total cycles (5 + 14 = rootsqr latency)

    out = export_traceability(cmap, dag, MODULE, CM, fmt=CSV)
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ["MATLAB operation", "SV instance group", "per-stage latency", "total cycles"]
    assert rows[1][0] == "n"
    assert rows[1][3] == "19"


@pytest.mark.req("DX-2")
def test_empty_map_exports_cleanly() -> None:
    dag, _ = _norm_setup()
    md = export_traceability(CorrespondenceMap(), dag, MODULE, CM)
    assert "No operation groups mapped yet" in md
