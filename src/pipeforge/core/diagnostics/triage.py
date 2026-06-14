"""Unified failure triage (DX-1).

On a co-sim failure, scattered per-panel evidence — struct equivalence (WS-3),
bisection localization + classification (BI-1/BI-2), and whether the divergent
stage's inputs matched — is synthesized into ONE coherent diagnosis reported
against the mapped MATLAB operation (MP-3), e.g.:

    "equivalence clean; localized to the sqrt stage of `norm`; inputs matched;
     classification wrong-math"
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeforge.core.bisect.engine import BisectReport
from pipeforge.core.frontend.dag import Dag
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.workspace.reconcile import ReconcileReport


@dataclass
class TriageSummary:
    equivalence_clean: bool | None  # None when no reconcile was run
    localized_op: str
    classification: str
    inputs_matched: bool
    message: str


def _op_label(dag: Dag, nid: str, cmap: CorrespondenceMap | None) -> str:
    node = dag.nodes.get(nid)
    label = (node.signal or node.label) if node is not None else nid
    if cmap is not None:
        group = cmap.group_for(nid)
        if group is not None:
            return f"{label} (group of {len(group.sv_instances)} SV instance(s))"
    return label


def triage(
    bisect_report: BisectReport | None,
    reconcile_report: ReconcileReport | None,
    dag: Dag,
    cmap: CorrespondenceMap | None = None,
) -> TriageSummary:
    """Synthesize equivalence + bisection + input-match into one diagnosis (DX-1)."""
    parts: list[str] = []

    equivalence_clean: bool | None = None
    if reconcile_report is not None:
        equivalence_clean = reconcile_report.clean
        if equivalence_clean:
            parts.append("equivalence clean")
        else:
            parts.append(f"equivalence: {len(reconcile_report.mismatches)} field mismatch(es)")

    localized_op = ""
    classification = ""
    inputs_matched = True
    if bisect_report is not None and bisect_report.diverged:
        localized_op = _op_label(dag, bisect_report.node, cmap)
        classification = bisect_report.classification
        inputs_matched = bisect_report.inputs_matched
        parts.append(f"localized to {localized_op}")
        parts.append("inputs matched" if inputs_matched else "inputs differ")
        parts.append(f"classification {classification}")
    elif bisect_report is not None:
        parts.append("no pipeline divergence localized")

    return TriageSummary(
        equivalence_clean=equivalence_clean,
        localized_op=localized_op,
        classification=classification,
        inputs_matched=inputs_matched,
        message="; ".join(parts),
    )
