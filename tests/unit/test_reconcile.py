"""WS-3 / WS-4: `.mat` <-> SV `software` reconciliation."""

from __future__ import annotations

import pytest

from pipeforge.core.fxp.fx import FxFormat, from_float
from pipeforge.core.workspace.mat_loader import WorkspaceTree, WsField
from pipeforge.core.workspace.reconcile import (
    EXACT,
    MATCH,
    MISMATCH,
    MISSING_IN_MAT,
    MISSING_IN_SV,
    SHAPE_MISMATCH,
    TOLERANCE,
    reconcile,
)

FMT = FxFormat(16, 12)


def _tree(fields: dict[str, WsField], fmt: str = "v5") -> WorkspaceTree:
    return WorkspaceTree("t", fmt, fields)


def _f(path: str, *values: float, shape: tuple[int, int] | None = None) -> WsField:
    shp = shape if shape is not None else (1, len(values))
    return WsField(path, shp, tuple(values))


@pytest.mark.req("WS-3")
def test_exact_mode_quantized_bit_compare() -> None:
    # two doubles that quantize to the same code are an exact match; one off by
    # more than an LSB is a mismatch.
    mat = _tree({"gain": _f("gain", 0.5), "fc": _f("fc", 0.25)})
    sv = _tree({"gain": _f("gain", 0.5), "fc": _f("fc", 0.30)})
    report = reconcile(mat, sv, FMT, mode=EXACT)
    verdicts = {f.path: f.verdict for f in report.fields}
    assert verdicts["gain"] == MATCH
    assert verdicts["fc"] == MISMATCH

    # sub-LSB difference still quantizes to the same code -> match
    eps = 2.0**-FMT.scale / 4
    near = _tree({"gain": _f("gain", 0.5 + eps)})
    one = reconcile(near, _tree({"gain": _f("gain", 0.5)}), FMT, mode=EXACT)
    assert one.fields[0].verdict == MATCH
    assert from_float(0.5 + eps, FMT) == from_float(0.5, FMT)


@pytest.mark.req("WS-3")
def test_tolerance_mode_decimal_and_lsb() -> None:
    mat = _tree({"a": _f("a", 1.2345), "b": _f("b", 2.0)})
    sv = _tree({"a": _f("a", 1.2349), "b": _f("b", 2.0 + 2 * 2.0**-FMT.scale)})
    # 3 decimal places: 1.2345 vs 1.2349 both round to 1.234/1.235? -> mismatch at 3
    by_dec = reconcile(mat, sv, FMT, mode=TOLERANCE, decimals=3)
    assert by_dec.fields[0].verdict == MISMATCH  # 1.234 vs 1.235
    # within 3 LSB: b differs by 2 LSB -> match
    by_lsb = reconcile(mat, sv, FMT, mode=TOLERANCE, lsb_tol=3)
    assert {f.path: f.verdict for f in by_lsb.fields}["b"] == MATCH


@pytest.mark.req("WS-3")
def test_missing_extra_shape_mismatch_reported() -> None:
    mat = _tree(
        {
            "only_mat": _f("only_mat", 1.0),
            "shared": _f("shared", 1.0, 2.0, 3.0),  # 1x3
        }
    )
    sv = _tree(
        {
            "only_sv": _f("only_sv", 9.0),
            "shared": _f("shared", 1.0, 2.0, shape=(2, 1)),  # shape differs
        }
    )
    report = reconcile(mat, sv, FMT, mode=EXACT)
    verdicts = {f.path: f.verdict for f in report.fields}
    assert verdicts["only_mat"] == MISSING_IN_SV
    assert verdicts["only_sv"] == MISSING_IN_MAT
    assert verdicts["shared"] == SHAPE_MISMATCH


@pytest.mark.req("WS-4")
def test_hand_rounding_changes_quantized_code_flagged() -> None:
    # 0.00061045 quantizes to code 3, but round(.,6)=0.000610 quantizes to code 2
    x = 0.00061045
    assert from_float(round(x, 6), FMT) != from_float(x, FMT)  # the hazard exists
    mat = _tree({"cal": _f("cal", x), "gain": _f("gain", 0.5)})
    sv = _tree({"cal": _f("cal", round(x, 6)), "gain": _f("gain", 0.5)})
    report = reconcile(mat, sv, FMT, mode=EXACT, round_decimals=6)
    flagged = {f.path: f.rounding_hazard for f in report.fields}
    assert flagged["cal"] is True  # transcription/rounding hazard surfaced
    assert flagged["gain"] is False  # 0.5 is safe at any rounding
    assert report.hazards and report.hazards[0].path == "cal"
