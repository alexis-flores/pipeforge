"""Golden model vs live MATLAB values (MATLAB bridge M4).

The snapshot carries what MATLAB actually computed for every variable —
including nested struct fields and the script's own outputs. This module
feeds those values through the bit-exact golden model and reports, per
assigned variable, how far the fixed-point pipeline deviates from MATLAB's
float answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeforge.core.frontend.dag import Dag
from pipeforge.core.frontend.varinfo import WorkspaceSnapshot
from pipeforge.core.fxp.evaluator import (
    ErrorStats,
    error_stats,
    evaluate_fixed,
)
from pipeforge.core.fxp.fx import FxFormat, to_float


class ValidateError(ValueError):
    """The snapshot cannot drive this DAG (missing variables or values)."""


def snapshot_inputs(dag: Dag, snapshot: WorkspaceSnapshot) -> dict[str, list[float]]:
    """Evaluator inputs from live workspace values, keyed by (dotted) label."""
    inputs: dict[str, list[float]] = {}
    missing: list[str] = []
    for node in dag.inputs():
        info = snapshot.get(node.label)
        if info is None or not info.values:
            missing.append(node.label)
            continue
        inputs[node.label] = list(info.values)
    if missing:
        raise ValidateError(
            "snapshot has no values for input(s): "
            + ", ".join(sorted(missing))
            + " — re-run the workspace setup so they exist in MATLAB"
        )
    return inputs


@dataclass(frozen=True)
class StatementCheck:
    target: str
    line: int
    node: str  # DAG node id (VZ-2 cross-reference)
    matlab: tuple[float, ...]  # what MATLAB computed
    golden: tuple[float, ...]  # what the fixed-point model computes
    stats: ErrorStats
    compared: int


@dataclass
class ValidationReport:
    fmt_width: int
    fmt_scale: int
    checks: list[StatementCheck]
    uncheckable: list[str]  # targets MATLAB has no values for

    @property
    def worst_sqnr_db(self) -> float:
        finite = [c.stats.sqnr_db for c in self.checks if c.stats.samples > 0]
        return min(finite) if finite else float("inf")

    @property
    def worst_abs_error(self) -> float:
        errs = [c.stats.max_abs_error for c in self.checks if c.stats.samples > 0]
        return max(errs) if errs else 0.0


def compare_to_matlab(dag: Dag, snapshot: WorkspaceSnapshot, fmt: FxFormat) -> ValidationReport:
    """Per-statement: golden fixed-point result vs MATLAB's live value.

    MATLAB is the float reference here — not our float64 evaluator — so this
    catches both quantization error and modeling gaps in one comparison.
    """
    inputs = snapshot_inputs(dag, snapshot)
    fixed = evaluate_fixed(dag, dict(inputs.items()), fmt)
    checks: list[StatementCheck] = []
    uncheckable: list[str] = []
    seen: set[str] = set()
    for stmt in dag.statements:
        if stmt.target in seen:  # compare only the final definition
            checks = [c for c in checks if c.target != stmt.target]
        seen.add(stmt.target)
        info = snapshot.get(stmt.target)
        if info is None or not info.values:
            uncheckable.append(stmt.target)
            continue
        golden = tuple(to_float(raw, fmt) for raw in fixed[stmt.root])
        matlab = info.values
        n = min(len(matlab), len(golden))
        if n == 0:
            uncheckable.append(stmt.target)
            continue
        stats = error_stats(list(matlab[:n]), list(golden[:n]))
        checks.append(
            StatementCheck(
                target=stmt.target,
                line=stmt.line,
                node=stmt.root,
                matlab=tuple(matlab[:n]),
                golden=tuple(golden[:n]),
                stats=stats,
                compared=n,
            )
        )
    return ValidationReport(
        fmt_width=fmt.width, fmt_scale=fmt.scale, checks=checks, uncheckable=uncheckable
    )
