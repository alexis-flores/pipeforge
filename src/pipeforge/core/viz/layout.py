"""DAG layout (VZ-1, VZ-3).

The pipeline-stage timeline is the primary layout axis: a node's x position
is its inputs-ready cycle and its width is its latency. Rows are assigned
to avoid overlap. When graphviz `dot` is available it may refine y order;
the built-in layered layout below is the always-available fallback (C2).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from pipeforge.core.frontend.dag import Dag


@dataclass(frozen=True)
class NodeBox:
    nid: str
    start: int  # inputs-ready cycle
    end: int  # output-ready cycle
    row: int
    label: str
    module: str
    is_divider: bool = False
    on_critical_path: bool = False


@dataclass(frozen=True)
class Layout:
    boxes: dict[str, NodeBox]
    edges: list[tuple[str, str]]
    total_cycles: int
    rows: int


def _node_start(dag: Dag, nid: str) -> int:
    node = dag.nodes[nid]
    if not node.args:
        return 0
    return max(dag.nodes[a].ready for a in node.args)


def layered_layout(
    dag: Dag,
    critical: frozenset[str] = frozenset(),
    dividers: frozenset[str] = frozenset(),
    include_wiring: bool = False,
) -> Layout:
    """Longest-path layered layout: x = cycles, greedy row packing."""
    edges: list[tuple[str, str]] = []
    boxes: dict[str, NodeBox] = {}
    # rows: greedy interval packing — first row whose last end <= start
    row_ends: list[int] = []
    visible: set[str] = set()
    for nid in dag.order:
        node = dag.nodes[nid]
        if node.module in ("", "const") and not include_wiring:
            continue
        start = _node_start(dag, nid)
        end = node.ready
        width = max(end - start, 1)
        row = -1
        for i, last in enumerate(row_ends):
            if last <= start:
                row = i
                break
        if row < 0:
            row = len(row_ends)
            row_ends.append(0)
        row_ends[row] = start + width
        label = node.signal or node.label
        boxes[nid] = NodeBox(
            nid=nid,
            start=start,
            end=end,
            row=row,
            label=label,
            module=node.module,
            is_divider=nid in dividers,
            on_critical_path=nid in critical,
        )
        visible.add(nid)
    for nid in dag.order:
        for a in dag.nodes[nid].args:
            if nid in visible and a in visible:
                edges.append((a, nid))
    total = max((b.end for b in boxes.values()), default=0)
    return Layout(boxes, edges, total, len(row_ends))


def dot_available() -> bool:
    return shutil.which("dot") is not None


def dot_refined_rows(dag: Dag, layout: Layout, timeout: float = 5.0) -> Layout:
    """Use graphviz `dot -Tplain` to order rows when available (VZ-3).

    x positions stay cycle-accurate (the timeline owns x); only the row
    order is taken from dot's crossing reduction. Falls back silently to
    the input layout on any failure.
    """
    if not dot_available():
        return layout
    lines = ["digraph g { rankdir=LR;"]
    for nid in layout.boxes:
        lines.append(f'  "{nid}";')
    for a, b in layout.edges:
        lines.append(f'  "{a}" -> "{b}";')
    lines.append("}")
    try:
        proc = subprocess.run(
            ["dot", "-Tplain"],
            input="\n".join(lines),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return layout
    ys: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "node":
            ys[parts[1]] = float(parts[3])
    if not ys:
        return layout
    order = sorted(layout.boxes, key=lambda n: ys.get(n, 0.0))
    # re-pack rows in dot's vertical order
    row_ends: list[int] = []
    new_boxes: dict[str, NodeBox] = {}
    for nid in order:
        box = layout.boxes[nid]
        row = -1
        for i, last in enumerate(row_ends):
            if last <= box.start:
                row = i
                break
        if row < 0:
            row = len(row_ends)
            row_ends.append(0)
        row_ends[row] = box.start + max(box.end - box.start, 1)
        new_boxes[nid] = NodeBox(
            box.nid,
            box.start,
            box.end,
            row,
            box.label,
            box.module,
            box.is_divider,
            box.on_critical_path,
        )
    return Layout(new_boxes, layout.edges, layout.total_cycles, len(row_ends))


def layout_for_audit(audit: object, refine_with_dot: bool = False) -> Layout:
    """Layout an Audit's DAG with critical path and dividers marked (VZ-1).

    Typed loosely to avoid a hard dependency cycle; expects
    pipeforge.core.audit.engine.Audit.
    """
    from pipeforge.core.audit.engine import Audit

    assert isinstance(audit, Audit)
    critical = frozenset(n.nid for n in audit.critical_path())
    dividers = frozenset(
        nid for nid in audit.dag.order if audit.cm.is_divider(audit.dag.nodes[nid].module)
    )
    layout = layered_layout(audit.dag, critical=critical, dividers=dividers)
    if refine_with_dot:
        layout = dot_refined_rows(audit.dag, layout)
    return layout


def compute_slack(dag: Dag) -> dict[str, int]:
    """Per-node slack: cycles the node could slip without growing the
    critical path (VZ-1 'slack on demand')."""
    total = max((dag.nodes[s.root].ready for s in dag.statements), default=0)
    # latest required time, propagated backward from consumers
    latest: dict[str, int] = {}
    consumers: dict[str, list[str]] = {}
    for nid in dag.order:
        for a in dag.nodes[nid].args:
            consumers.setdefault(a, []).append(nid)
    for nid in reversed(dag.order):
        cons = consumers.get(nid, [])
        if not cons:
            latest[nid] = total
            continue
        latest[nid] = min(latest[c] - dag.nodes[c].lat for c in cons)
    return {nid: max(latest[nid] - dag.nodes[nid].ready, 0) for nid in dag.order}
