"""Optimization findings engine (AU-3): RECIP, CDIV, SERDIV, POW, CSE, FUSE, FEEDBACK."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.ast import Bin, Num, canon
from pipeforge.core.frontend.dag import DagBuilder, Node


@dataclass(frozen=True)
class Finding:
    tag: str
    line: int
    savings: int  # estimated cycles of pipeline depth removed (aggregate)
    message: str
    suggestion: str
    node: str = ""  # DAG node id this finding anchors to (VZ-2 cross-reference)


def _recip(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    # group by the divisor's DAG node, not its text: after loop unrolling the
    # same spelling ('x') names a different definition per iteration (LP-1)
    by_divisor: dict[tuple[str, str], list[Node]] = {}
    for node, _dividend, divisor in builder.div_nodes:
        if isinstance(divisor, Num):
            continue
        divisor_nid = node.args[1] if len(node.args) > 1 else node.args[0]
        by_divisor.setdefault((canon(divisor), divisor_nid), []).append(node)
    for (div_label, _nid), group in sorted(by_divisor.items(), key=lambda kv: kv[1][0].line):
        if len(group) < 2:
            continue
        k = len(group)
        line = min(n.line for n in group)
        savings = (k - 1) * (cm.div_lat - cm.mul_lat)
        findings.append(
            Finding(
                "RECIP",
                line,
                savings,
                f"{k} divisions share divisor '{div_label}'",
                f"compute r = 1/{div_label} once (elem_sinv) and multiply by r "
                f"(elem_smul): {k - 1} fewer dividers, "
                f"{savings} cycles of divider depth removed",
                node=group[0].nid,
            )
        )
    return findings


def _cdiv(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    for node, _dividend, divisor in builder.div_nodes:
        if not isinstance(divisor, Num):
            continue
        c = divisor.value
        if c != 0 and c == int(c) and int(c) > 0 and (int(c) & (int(c) - 1)) == 0:
            shift = int(math.log2(int(c)))
            findings.append(
                Finding(
                    "CDIV",
                    node.line,
                    cm.div_lat - 1,
                    f"division by power-of-two constant {canon(divisor)}",
                    f"replace with elem_rshift by {shift}: saves {cm.div_lat - 1} cycles "
                    f"and one divider",
                    node=node.nid,
                )
            )
        else:
            findings.append(
                Finding(
                    "CDIV",
                    node.line,
                    cm.div_lat - cm.mul_lat,
                    f"division by constant {canon(divisor)}",
                    f"multiply by the constant 1/{canon(divisor)} (elem_smul): "
                    f"saves {cm.div_lat - cm.mul_lat} cycles and one divider",
                    node=node.nid,
                )
            )
    return findings


def _serdiv(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    for node, dividend, _divisor in builder.div_nodes:
        if isinstance(dividend, Bin) and dividend.op in ("/", "./"):
            findings.append(
                Finding(
                    "SERDIV",
                    node.line,
                    cm.div_lat - cm.mul_lat,
                    "serial division chain",
                    f"multiply the divisors and divide once: saves "
                    f"{cm.div_lat - cm.mul_lat} cycles and one divider",
                    node=node.nid,
                )
            )
    return findings


def _pow(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    for line, base_label, exp, naive_muls in builder.pow_expansions:
        if exp == 2:
            findings.append(
                Finding(
                    "POW",
                    line,
                    0,
                    f"square of '{base_label}'",
                    "use elem_ssqr (same latency, one operand port)",
                )
            )
        else:
            bin_muls = (exp.bit_length() - 1) + (bin(exp).count("1") - 1)
            savings = (naive_muls - bin_muls) * cm.mul_lat
            findings.append(
                Finding(
                    "POW",
                    line,
                    savings,
                    f"'{base_label}' raised to the {exp} by a multiply chain "
                    f"({naive_muls} multipliers)",
                    f"use binary exponentiation via elem_ssqr ({bin_muls} multipliers): "
                    f"saves {savings} cycles",
                )
            )
    return findings


def _cse(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    dag = builder.dag
    # key on (text, operand identity): identical spellings whose operands are
    # different definitions (unrolled iterations, reassignment) are NOT common
    by_label: dict[tuple[str, tuple[str, ...]], list[Node]] = {}
    for nid in dag.order:
        n = dag.nodes[nid]
        if n.args and n.module not in ("", "input", "const"):
            by_label.setdefault((n.label, tuple(n.args)), []).append(n)
    for (label, _args), group in sorted(by_label.items(), key=lambda kv: kv[1][0].line):
        if len(group) < 2:
            continue
        k = len(group)
        findings.append(
            Finding(
                "CSE",
                group[0].line,
                (k - 1) * group[0].lat,
                f"'{label}' is computed {k} times (lines {', '.join(str(n.line) for n in group)})",
                f"compute once and `PIPE the result: removes {k - 1} {group[0].module} instance(s)",
                node=group[0].nid,
            )
        )
    return findings


def _fuse(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    findings: list[Finding] = []
    dag = builder.dag
    consumers = dag.consumers()
    for nid in dag.order:
        n = dag.nodes[nid]
        if n.module not in ("matadd", "matsub") or not n.args:
            continue
        inner = dag.nodes[n.args[0]]
        if inner.module not in ("matadd", "matsub") or consumers.get(inner.nid, 0) != 1:
            continue
        if inner.module == "matadd" and n.module == "matadd":
            fused = "matadd3"
        elif inner.module == "matadd" and n.module == "matsub":
            fused = "matadd3b1"
        elif inner.module == "matsub" and n.module == "matsub":
            fused = "matadd3b2"
        else:
            continue  # (a-b)+c: no direct 3-input module
        findings.append(
            Finding(
                "FUSE",
                n.line,
                cm.add_lat,
                f"chained adds '{n.label}'",
                f"fuse into one {fused}: saves {cm.add_lat} cycle of pipeline depth",
                node=n.nid,
            )
        )
    return findings


def _format(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    """FORMAT (MATLAB bridge): fi variables whose numerictype differs from the
    workspace WIDTH/SCALE. Only fires when a snapshot is attached."""
    if builder.snapshot is None:
        return []
    findings: list[Finding] = []
    inputs = {n.label: n for n in builder.dag.inputs()}
    for name, fi in sorted(builder.snapshot.fi_formats().items()):
        if name not in inputs:
            continue  # fi variable not used by this script
        if (fi.width, fi.scale) == (cm.width, cm.scale):
            continue
        node = inputs[name]
        findings.append(
            Finding(
                "FORMAT",
                node.line,
                0,
                f"'{name}' is fi {fi.width}/{fi.scale} in MATLAB but the workspace "
                f"is {cm.width}/{cm.scale}",
                f"insert elem_snorm at the '{name}' input, or adopt {fi.width}/"
                f"{fi.scale} as the workspace format so bits match end to end",
                node=node.nid,
            )
        )
    return findings


def _unroll(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    """UNROLL (LP-1): a constant-bound loop became pipeline structure —
    informational, so the report says where the extra instances came from."""
    return [
        Finding(
            "UNROLL",
            note.line,
            0,
            f"loop over '{note.var}' unrolled into {note.count} pipelined iteration(s)",
            "constant trip count: the recurrence is now a feedforward chain in "
            "space; throughput stays 1 sample/clock (no initiation-interval "
            "penalty). Run `optimize` to balance accumulation chains into trees.",
        )
        for note in getattr(builder, "unrolls", [])
    ]


def _feedback(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    return [
        Finding(
            "FEEDBACK",
            line,
            0,
            f"'{var}' feeds back into itself: loop initiation interval is {ii} cycles",
            f"a new iteration can start only every {ii} cycles; "
            "shorten the feedback path or restructure the recurrence",
        )
        for var, line, ii in builder.dag.feedbacks
    ]


def find_findings(builder: DagBuilder, cm: CostModel) -> list[Finding]:
    """Run every finding rule over a built DAG; result is line-sorted."""
    findings: list[Finding] = []
    for rule in (_recip, _cdiv, _serdiv, _pow, _cse, _fuse, _feedback, _unroll, _format):
        findings.extend(rule(builder, cm))
    findings.sort(key=lambda f: (f.line, f.tag))
    return findings
