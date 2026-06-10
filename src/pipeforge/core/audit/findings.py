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
    by_divisor: dict[str, list[Node]] = {}
    for node, _dividend, divisor in builder.div_nodes:
        if isinstance(divisor, Num):
            continue
        by_divisor.setdefault(canon(divisor), []).append(node)
    for div_label, group in sorted(by_divisor.items(), key=lambda kv: kv[1][0].line):
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
    by_label: dict[str, list[Node]] = {}
    for nid in dag.order:
        n = dag.nodes[nid]
        if n.args and n.module not in ("", "input", "const"):
            by_label.setdefault(n.label, []).append(n)
    for label, group in sorted(by_label.items(), key=lambda kv: kv[1][0].line):
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
    for rule in (_recip, _cdiv, _serdiv, _pow, _cse, _fuse, _feedback):
        findings.extend(rule(builder, cm))
    findings.sort(key=lambda f: (f.line, f.tag))
    return findings
