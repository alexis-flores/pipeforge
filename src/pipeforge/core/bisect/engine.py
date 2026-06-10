"""Mismatch bisection (BI-1, BI-2).

Localizes the first divergent pipeline stage by comparing observed RTL
intermediate streams against golden-model intermediates (FX-3), and — the
dominant real-world failure mode — distinguishes "wrong math at stage X"
from "stage X inputs skewed by N cycles" (a delay-matching bug) by replaying
the stage with shifted operand streams.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeforge.core.frontend.dag import Dag, Node
from pipeforge.core.fxp.evaluator import FixedVec, apply_fixed, evaluate_fixed
from pipeforge.core.fxp.fx import FxFormat

#: observed RTL streams: node id -> one FixedVec per stimulus vector
Observations = dict[str, list[FixedVec]]

MAX_SKEW = 4


@dataclass(frozen=True)
class NodeVerdict:
    nid: str
    status: str  # 'ok' | 'bad' | 'unobserved'


@dataclass
class BisectReport:
    diverged: bool
    node: str = ""  # first divergent DAG node id (BI-1)
    instance: str = ""  # conventional nkMatlib instance name
    cycle: int = 0  # node ready time (cost model)
    vector_index: int = -1
    expected: FixedVec = field(default_factory=list)
    actual: FixedVec = field(default_factory=list)
    inputs_matched: bool = True
    classification: str = ""  # 'wrong-math' | 'delay-skew' (BI-2)
    skew_input: str = ""  # which operand stream is skewed
    skew_cycles: int = 0
    message: str = ""
    verdicts: list[NodeVerdict] = field(default_factory=list)

    def downstream_of_divergence(self, dag: Dag) -> frozenset[str]:
        """Nodes strictly after the divergent one (dimmed in the GUI, BI-3)."""
        if not self.diverged:
            return frozenset()
        reach: set[str] = set()
        frontier = {self.node}
        while frontier:
            nxt: set[str] = set()
            for nid in dag.order:
                node = dag.nodes[nid]
                if nid not in reach and any(a in frontier or a in reach for a in node.args):
                    nxt.add(nid)
            nxt -= reach | {self.node}
            if not nxt:
                break
            reach |= nxt
            frontier = nxt
        return frozenset(reach)


def instance_name(node: Node) -> str:
    base = node.module or "wire"
    sig = node.signal or node.nid
    return f"i_{base}_{sig}_{node.ready}"


def golden_intermediates(
    dag: Dag, stimulus: list[dict[str, int]], fmt: FxFormat
) -> dict[str, list[FixedVec]]:
    """Golden value streams for every node id (FX-3 over the stimulus set)."""
    streams: dict[str, list[FixedVec]] = {nid: [] for nid in dag.order}
    for vec in stimulus:
        values = evaluate_fixed(dag, dict(vec.items()), fmt)
        for nid in dag.order:
            streams[nid].append(values[nid])
    return streams


def _first_mismatch(expected: list[FixedVec], actual: list[FixedVec]) -> int:
    n = min(len(expected), len(actual))
    for i in range(n):
        if expected[i] != actual[i]:
            return i
    if len(actual) < len(expected):
        return len(actual)
    return -1


def _try_skew(
    node: Node,
    arg_streams: list[list[FixedVec]],
    actual: list[FixedVec],
    fmt: FxFormat,
) -> tuple[int, int] | None:
    """If actual == stage replayed with one operand delayed k cycles, return
    (arg_index, k)."""
    if not arg_streams:
        return None
    n = len(actual)
    for arg_idx in range(len(arg_streams)):
        for k in range(1, MAX_SKEW + 1):
            ok = True
            compared = 0
            for i in range(k, n):
                shifted_args = [
                    arg_streams[j][i - k] if j == arg_idx else arg_streams[j][i]
                    for j in range(len(arg_streams))
                ]
                try:
                    replay = apply_fixed(node, shifted_args, fmt)
                except Exception:
                    return None
                if replay != actual[i]:
                    ok = False
                    break
                compared += 1
            if ok and compared >= max(2, (n - k) // 2):
                return arg_idx, k
    return None


def bisect(
    dag: Dag,
    stimulus: list[dict[str, int]],
    observations: Observations,
    fmt: FxFormat,
) -> BisectReport:
    """Locate the first divergent stage in dataflow order (BI-1)."""
    golden = golden_intermediates(dag, stimulus, fmt)
    verdicts: list[NodeVerdict] = []
    first_bad: Node | None = None
    first_idx = -1
    for nid in dag.order:  # creation order is topological
        if nid not in observations:
            verdicts.append(NodeVerdict(nid, "unobserved"))
            continue
        idx = _first_mismatch(golden[nid], observations[nid])
        if idx == -1:
            verdicts.append(NodeVerdict(nid, "ok"))
        else:
            verdicts.append(NodeVerdict(nid, "bad"))
            if first_bad is None:
                first_bad = dag.nodes[nid]
                first_idx = idx
    if first_bad is None:
        return BisectReport(diverged=False, verdicts=verdicts, message="all stages match")

    nid = first_bad.nid
    inputs_matched = all(
        _first_mismatch(golden[a], observations[a]) == -1
        for a in first_bad.args
        if a in observations
    )
    arg_streams = [observations.get(a, golden[a]) for a in first_bad.args]
    actual = observations[nid]
    skew = _try_skew(first_bad, arg_streams, actual, fmt)
    if skew is not None:
        arg_idx, k = skew
        arg_node = dag.nodes[first_bad.args[arg_idx]]
        classification = "delay-skew"
        message = (
            f"stage '{first_bad.signal or first_bad.label}' computes correct math, but "
            f"input '{arg_node.signal or arg_node.label}' is skewed by {k} cycle(s) — "
            f"a delay-matching (`PIPE) bug, not an arithmetic one"
        )
        skew_input = arg_node.signal or arg_node.label
        skew_cycles = k
    else:
        classification = "wrong-math"
        message = (
            f"stage '{first_bad.signal or first_bad.label}' ({first_bad.module}) produces "
            f"wrong values while its inputs match the golden model"
            if inputs_matched
            else f"stage '{first_bad.signal or first_bad.label}' diverges and its inputs "
            f"could not be fully verified"
        )
        skew_input = ""
        skew_cycles = 0
    return BisectReport(
        diverged=True,
        node=nid,
        instance=instance_name(first_bad),
        cycle=first_bad.ready,
        vector_index=first_idx,
        expected=golden[nid][first_idx] if first_idx < len(golden[nid]) else [],
        actual=actual[first_idx] if first_idx < len(actual) else [],
        inputs_matched=inputs_matched,
        classification=classification,
        skew_input=skew_input,
        skew_cycles=skew_cycles,
        message=message,
        verdicts=verdicts,
    )
