"""Reconcile the `.mat` workspace against its SV `software` mirror (WS-3/WS-4).

The SV mirror is hand-maintained, so it drifts silently against the `.mat`. This
compares the two dotted-path trees field-by-field under a selectable mode:

  * **exact** — quantize both sides to the active WIDTH/SCALE (nkMatlib
    semantics) and compare the fixed-point codes bit-for-bit;
  * **tolerance** — agree within a decimal-place count or an LSB count.

Missing, extra, and shape-mismatched fields are always reported. In exact mode it
additionally flags **hand-rounding hazards** (WS-4): values where rounding the
double to N decimals changes the quantized code, i.e. ``quantize(round_n(x)) !=
quantize(x)`` — a silent transcription hazard invisible to a plain value diff.

Where a confirmed correspondence map (MP-6) is supplied, it aligns differently
named fields; only confirmed mappings are honoured.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeforge.core.fxp.fx import FxFormat, from_float
from pipeforge.core.mapping.consume import resolve_confirmed
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.workspace.mat_loader import WorkspaceTree, WsField

# verdicts
MATCH = "match"
MISMATCH = "mismatch"
MISSING_IN_SV = "missing_in_sv"
MISSING_IN_MAT = "missing_in_mat"
SHAPE_MISMATCH = "shape_mismatch"

EXACT = "exact"
TOLERANCE = "tolerance"


@dataclass(frozen=True)
class FieldVerdict:
    path: str
    mat_value: tuple[float, ...] | None
    sv_value: tuple[float, ...] | None
    mode: str
    verdict: str
    delta: float = 0.0
    rounding_hazard: bool = False  # WS-4: round_n changes the quantized code
    detail: str = ""


@dataclass
class ReconcileReport:
    mode: str
    fields: list[FieldVerdict]

    @property
    def mismatches(self) -> list[FieldVerdict]:
        return [f for f in self.fields if f.verdict != MATCH]

    @property
    def hazards(self) -> list[FieldVerdict]:
        return [f for f in self.fields if f.rounding_hazard]

    @property
    def clean(self) -> bool:
        return not self.mismatches and not self.hazards


def _max_delta(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return max((abs(x - y) for x, y in zip(a, b, strict=False)), default=0.0)


def _exact_equal(a: tuple[float, ...], b: tuple[float, ...], fmt: FxFormat) -> bool:
    if len(a) != len(b):
        return False
    return all(from_float(x, fmt) == from_float(y, fmt) for x, y in zip(a, b, strict=True))


def _tolerance_equal(
    a: tuple[float, ...],
    b: tuple[float, ...],
    fmt: FxFormat,
    decimals: int | None,
    lsb_tol: int | None,
) -> bool:
    if len(a) != len(b):
        return False
    if decimals is not None:
        return all(round(x, decimals) == round(y, decimals) for x, y in zip(a, b, strict=True))
    tol = (lsb_tol if lsb_tol is not None else 0) * (2.0**-fmt.scale)
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def _rounding_hazard(values: tuple[float, ...], fmt: FxFormat, decimals: int) -> bool:
    """True if rounding any element to `decimals` changes its quantized code (WS-4)."""
    return any(from_float(round(v, decimals), fmt) != from_float(v, fmt) for v in values)


def reconcile(
    mat: WorkspaceTree,
    sv: WorkspaceTree,
    fmt: FxFormat,
    *,
    mode: str = EXACT,
    decimals: int | None = None,
    lsb_tol: int | None = None,
    round_decimals: int = 6,
    cmap: CorrespondenceMap | None = None,
) -> ReconcileReport:
    """Field-by-field reconciliation of the `.mat` and SV `software` trees."""
    if mode not in (EXACT, TOLERANCE):
        raise ValueError(f"unknown reconcile mode {mode!r}")
    fields: list[FieldVerdict] = []
    consumed_sv: set[str] = set()

    for path in mat.paths():
        mat_field = mat.get(path)
        assert mat_field is not None
        sv_path = (resolve_confirmed(cmap, path) if cmap is not None else None) or path
        sv_field = sv.get(sv_path)
        if sv_field is None:
            fields.append(FieldVerdict(path, mat_field.values, None, mode, MISSING_IN_SV))
            continue
        consumed_sv.add(sv_path)
        fields.append(
            _compare(path, mat_field, sv_field, fmt, mode, decimals, lsb_tol, round_decimals)
        )

    for path in sv.paths():
        if path not in consumed_sv:
            sv_field = sv.get(path)
            assert sv_field is not None
            fields.append(FieldVerdict(path, None, sv_field.values, mode, MISSING_IN_MAT))

    return ReconcileReport(mode=mode, fields=fields)


def _compare(
    path: str,
    mat_field: WsField,
    sv_field: WsField,
    fmt: FxFormat,
    mode: str,
    decimals: int | None,
    lsb_tol: int | None,
    round_decimals: int,
) -> FieldVerdict:
    hazard = mode == EXACT and _rounding_hazard(mat_field.values, fmt, round_decimals)
    if mat_field.shape != sv_field.shape:
        return FieldVerdict(
            path,
            mat_field.values,
            sv_field.values,
            mode,
            SHAPE_MISMATCH,
            rounding_hazard=hazard,
            detail=f"{mat_field.shape} vs {sv_field.shape}",
        )
    if mode == EXACT:
        ok = _exact_equal(mat_field.values, sv_field.values, fmt)
    else:
        ok = _tolerance_equal(mat_field.values, sv_field.values, fmt, decimals, lsb_tol)
    return FieldVerdict(
        path,
        mat_field.values,
        sv_field.values,
        mode,
        MATCH if ok else MISMATCH,
        delta=_max_delta(mat_field.values, sv_field.values),
        rounding_hazard=hazard,
    )
