"""Audit driver (AU-2): parse → DAG → schedule → census → findings."""

from __future__ import annotations

from dataclasses import dataclass

from pipeforge.core.audit.findings import Finding, find_findings
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, DagBuilder, Node, build_dag
from pipeforge.core.frontend.parser import Skipped, parse_program


@dataclass
class Audit:
    """Complete audit result: structured objects per AU-4."""

    filename: str
    cm: CostModel
    dag: Dag
    findings: list[Finding]
    skipped: list[Skipped]

    @property
    def census(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for nid in self.dag.order:
            n = self.dag.nodes[nid]
            if n.module in ("", "input", "const"):
                continue
            out[n.module] = out.get(n.module, 0) + 1
        return dict(sorted(out.items()))

    @property
    def divider_count(self) -> int:
        return sum(v for k, v in self.census.items() if self.cm.is_divider(k))

    @property
    def total_latency(self) -> int:
        return max((s.ready for s in self.dag.statements), default=0)

    def critical_path(self) -> list[Node]:
        """The dominant dependency chain, leaf to final output (AU-2)."""
        if not self.dag.statements:
            return []
        root_id = max(self.dag.statements, key=lambda s: (s.ready, -s.line)).root
        chain: list[Node] = []
        nid: str | None = root_id
        while nid is not None:
            node = self.dag.nodes[nid]
            chain.append(node)
            if not node.args:
                nid = None
            else:
                nid = max(node.args, key=lambda a: self.dag.nodes[a].ready)
        chain.reverse()
        return chain


def audit_source(src: str, filename: str, cm: CostModel) -> Audit:
    """Audit MATLAB source text against the nkMatlib cost model."""
    assigns, skipped = parse_program(src)
    builder, problems = build_dag(assigns, cm)
    skipped = sorted([*skipped, *problems], key=lambda s: s.line)
    findings = find_findings(builder, cm)
    return Audit(filename, cm, builder.dag, findings, skipped)


def audit_builder(builder: DagBuilder, filename: str, skipped: list[Skipped]) -> Audit:
    """Wrap an existing DAG build into an Audit (shared by GUI/services)."""
    return Audit(filename, builder.cm, builder.dag, find_findings(builder, builder.cm), skipped)
