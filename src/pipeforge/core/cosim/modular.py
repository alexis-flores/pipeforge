"""Per-operation modular co-simulation (CS-9).

Once operation groups exist (MP-3), any single mapped operation becomes
independently unit-testable ("verify just the sqrt stage of my norm"). This
isolates the MATLAB op's cone into a standalone sub-DAG, generates a module for
just that cone, and co-simulates it against the golden model of the sub-DAG
(FX-3) — without simulating the whole pipeline.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from pipeforge.core.audit.engine import Audit
from pipeforge.core.codegen.emitter import generate_sv
from pipeforge.core.frontend.dag import Dag, StmtInfo

if TYPE_CHECKING:
    from pipeforge.core.cosim.runner import CosimResult


def _cone(dag: Dag, root: str) -> set[str]:
    """The node and all its transitive operands (its input cone)."""
    seen: set[str] = set()
    stack = [root]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(dag.nodes[nid].args)
    return seen


def sub_audit(audit: Audit, op_nid: str, output_name: str = "out") -> Audit:
    """An Audit over just the cone of `op_nid`, with that node as the output."""
    if op_nid not in audit.dag.nodes:
        raise KeyError(f"node {op_nid!r} not in DAG")
    cone = _cone(audit.dag, op_nid)
    sub = Dag()
    for nid in audit.dag.order:  # preserve topological (creation) order
        if nid in cone:
            sub.add(replace(audit.dag.nodes[nid]))
    root = sub.nodes[op_nid]
    if not root.signal:
        root.signal = output_name
    sub.statements.append(StmtInfo(root.line, root.signal, root.ready, root.lat, op_nid))
    return Audit(audit.filename, audit.cm, sub, [], [])


def modular_cosim(
    audit: Audit,
    op_nid: str,
    work_dir: Path,
    extra_sources: list[Path] | None = None,
    include_dirs: list[Path] | None = None,
    vector_count: int = 64,
) -> CosimResult:
    """Co-simulate just one operation's sub-DAG against its golden model (CS-9)."""
    from pipeforge.core.cosim.runner import run_cosim

    sub = sub_audit(audit, op_nid)
    work_dir.mkdir(parents=True, exist_ok=True)
    dut = work_dir / "sub_dut.sv"
    dut.write_text(generate_sv(sub, "sub_dut"), encoding="utf-8")
    return run_cosim(
        sub,
        dut_sv=dut,
        dut_module="sub_dut",
        work_dir=work_dir / "run",
        extra_sources=extra_sources,
        include_dirs=include_dirs,
        vector_count=vector_count,
    )
