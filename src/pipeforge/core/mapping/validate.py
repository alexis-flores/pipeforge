"""Operation-group validation and coverage (MP-3, MP-4).

Operation grouping is **fully manual** (§10): the tool never proposes or alters a
group — it only does bookkeeping and validation. Given a user-drawn group (one
MATLAB op → one-or-more SV instances) it checks that

  * the group's summed cost-model latency matches the MATLAB op's latency, and
  * the instances can form a connected sub-pipeline (else it is structurally
    impossible and is warned about),

and reports coverage: ops with no group and SV instances assigned to none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag
from pipeforge.core.mapping.model import CorrespondenceMap, OperationGroup
from pipeforge.core.svlint.model import (
    DATA_PORTS,
    OUTPUT_PORTS,
    Instance,
    SvModule,
    operator_latency,
    pipe_latency,
)


@dataclass
class GroupValidation:
    matlab_op: str
    expected_latency: int
    actual_latency: int
    latency_ok: bool
    connected: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.latency_ok and self.connected and not self.warnings


@dataclass
class Coverage:
    ungrouped_ops: list[str]  # MATLAB ops with no group (MP-4)
    unassigned_instances: list[str]  # SV instances in no group (dead/unmapped)

    @property
    def complete(self) -> bool:
        return not self.ungrouped_ops and not self.unassigned_instances


def _instance_latency(inst: Instance, cm: CostModel) -> int | None:
    lat = operator_latency(inst.module, cm)
    if lat is not None:
        return lat
    return pipe_latency(inst.module, cm)


def _out_signal(inst: Instance) -> str | None:
    for port in OUTPUT_PORTS:
        if port in inst.conns:
            return inst.conns[port].strip()
    return None


def _in_signals(inst: Instance) -> set[str]:
    return {inst.conns[p].strip() for p in DATA_PORTS if p in inst.conns}


def _connected(insts: list[Instance]) -> bool:
    """True if the instances form one connected dataflow sub-graph."""
    if len(insts) <= 1:
        return True
    adj: dict[int, set[int]] = {i: set() for i in range(len(insts))}
    for i, a in enumerate(insts):
        a_out = _out_signal(a)
        for j, b in enumerate(insts):
            if i == j:
                continue
            if a_out is not None and a_out in _in_signals(b):
                adj[i].add(j)
                adj[j].add(i)
    seen: set[int] = set()
    stack = [0]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj[n] - seen)
    return len(seen) == len(insts)


def validate_group(
    group: OperationGroup, dag: Dag, module: SvModule, cm: CostModel
) -> GroupValidation:
    """Validate a manual operation group (MP-3); never alters it."""
    warnings: list[str] = []
    expected = dag.nodes[group.matlab_op].lat if group.matlab_op in dag.nodes else 0
    if group.matlab_op not in dag.nodes:
        warnings.append(f"MATLAB op '{group.matlab_op}' not found in the DAG")

    by_name = {i.name: i for i in module.instances}
    insts: list[Instance] = []
    for name in group.sv_instances:
        inst = by_name.get(name)
        if inst is None:
            warnings.append(f"SV instance '{name}' not found in the module")
        else:
            insts.append(inst)

    actual = 0
    for inst in insts:
        lat = _instance_latency(inst, cm)
        if lat is None:
            warnings.append(f"instance '{inst.name}' ({inst.module}) has no known latency")
        else:
            actual += lat

    latency_ok = actual == expected
    if not latency_ok:
        warnings.append(f"group latency {actual} != MATLAB op latency {expected}")
    connected = _connected(insts)
    if not connected:
        warnings.append("instances cannot form a connected sub-pipeline")

    return GroupValidation(
        matlab_op=group.matlab_op,
        expected_latency=expected,
        actual_latency=actual,
        latency_ok=latency_ok,
        connected=connected,
        warnings=warnings,
    )


def coverage(cmap: CorrespondenceMap, matlab_ops: list[str], sv_instances: list[str]) -> Coverage:
    """Surface ops with no group and SV instances assigned to none (MP-4)."""
    grouped_ops = {g.matlab_op for g in cmap.groups}
    assigned = {name for g in cmap.groups for name in g.sv_instances}
    return Coverage(
        ungrouped_ops=[op for op in matlab_ops if op not in grouped_ops],
        unassigned_instances=[name for name in sv_instances if name not in assigned],
    )
