"""MATLAB↔RTL traceability export (DX-2).

Turns a completed correspondence map into a human-readable review artifact: each
MATLAB operation, its mapped SV instance group, and per-stage latency — suitable
for a design review (and an ITAR-style audit trail).
"""

from __future__ import annotations

import csv
import io

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.svlint.model import Instance, SvModule, operator_latency, pipe_latency

MARKDOWN = "markdown"
CSV = "csv"


def _op_label(dag: Dag, op_nid: str) -> str:
    node = dag.nodes.get(op_nid)
    if node is None:
        return op_nid
    return node.signal or node.label or op_nid


def _instance_latency(inst: Instance | None, cm: CostModel) -> int | None:
    if inst is None:
        return None
    lat = operator_latency(inst.module, cm)
    return lat if lat is not None else pipe_latency(inst.module, cm)


def _rows(cmap: CorrespondenceMap, dag: Dag, module: SvModule, cm: CostModel) -> list[list[str]]:
    by_name = {i.name: i for i in module.instances}
    rows: list[list[str]] = []
    for g in cmap.groups:
        per_stage = []
        total = 0
        for name in g.sv_instances:
            lat = _instance_latency(by_name.get(name), cm)
            per_stage.append(f"{name}={lat if lat is not None else '?'}")
            total += lat or 0
        rows.append(
            [
                _op_label(dag, g.matlab_op),
                ", ".join(g.sv_instances),
                "; ".join(per_stage),
                str(total),
            ]
        )
    return rows


_HEADER = ["MATLAB operation", "SV instance group", "per-stage latency", "total cycles"]


def export_traceability(
    cmap: CorrespondenceMap,
    dag: Dag,
    module: SvModule,
    cm: CostModel,
    fmt: str = MARKDOWN,
) -> str:
    """Render the MATLAB→RTL correspondence as Markdown or CSV (DX-2)."""
    if fmt not in (MARKDOWN, CSV):
        raise ValueError(f"unknown export format {fmt!r}")
    rows = _rows(cmap, dag, module, cm)
    if fmt == CSV:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_HEADER)
        writer.writerows(rows)
        return buf.getvalue()
    lines = [
        "# MATLAB ↔ RTL traceability",
        "",
        "| " + " | ".join(_HEADER) + " |",
        "|" + "|".join(["---"] * len(_HEADER)) + "|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    if not rows:
        lines.append("")
        lines.append("_No operation groups mapped yet._")
    return "\n".join(lines) + "\n"
