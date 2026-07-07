"""Mixed-precision width planning from range analysis (MX-1).

The range propagation already *proves* how many integer bits every value
needs; codegen normally spends the full global WIDTH everywhere anyway.
This planner narrows operators whose proven range allows it — one fixedp
interface per distinct width, sign-extension/truncation at width boundaries
(both value-preserving under the range proof) — so narrow multipliers cost
fewer DSP tiles and narrow adders fewer LUTs.

Scope (deliberately conservative, v1):
* only **latency-invariant** operators are narrowed (add/sub/neg/abs/min/max/
  shift/mul/sqr/scale) — divider and sqrt latencies depend on WIDTH, and
  narrowing them would change the pipeline schedule the whole audit is built
  on. They stay at the global format.
* SCALE is shared; only integer bits (LEFT) shrink. Results are bit-identical
  to the global-width pipeline wherever the range proof holds — which is
  exactly where the planner narrows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeforge.core.audit.engine import Audit
from pipeforge.core.ranges.propagate import RangeReport

#: operators whose latency does not depend on WIDTH and whose fixed-point
#: result bits are the truncation of the wider computation (safe to narrow).
NARROWABLE_MODULES = frozenset(
    {
        "matadd",
        "matsub",
        "matadd3",
        "matadd3b1",
        "matadd3b2",
        "elem_neg",
        "elem_abs",
        "elem_smax",
        "elem_smin",
        "elem_rshift",
        "elem_smul",
        "elem_ssqr",
        "matscale",
    }
)


@dataclass
class FormatPlan:
    """Per-node WIDTH assignments (nodes absent from `widths` stay global)."""

    global_width: int
    scale: int
    widths: dict[str, int] = field(default_factory=dict)
    narrowed: int = 0  # instances narrower than global
    bits_saved: int = 0  # sum of width reductions over narrowed instances

    def width_of(self, nid: str) -> int:
        return self.widths.get(nid, self.global_width)

    def summary(self) -> str:
        if not self.narrowed:
            return "no operator could be narrowed under the given ranges"
        return (
            f"{self.narrowed} operator(s) narrowed, {self.bits_saved} operand bits "
            f"saved vs uniform {self.global_width}-bit"
        )


def plan_widths(audit: Audit, report: RangeReport) -> FormatPlan:
    """Assign each narrowable operator the smallest proven-safe WIDTH (MX-1).

    An instance's width covers its own result range *and* every operand's
    proven value range, so truncating a wider operand signal down to the
    instance width can never drop live bits.
    """
    w_global = audit.cm.width
    scale = audit.cm.scale
    plan = FormatPlan(global_width=w_global, scale=scale)

    def needed(nid: str) -> int:
        nr = report.nodes.get(nid)
        if nr is None or nr.integer_bits >= 64:
            return w_global
        return min(max(nr.integer_bits + scale, scale + 2), w_global)

    for nid in audit.dag.order:
        node = audit.dag.nodes[nid]
        if node.module not in NARROWABLE_MODULES:
            continue
        width = max(needed(nid), *(needed(a) for a in node.args)) if node.args else needed(nid)
        width += width % 2  # bucket to even widths: fewer distinct interfaces
        width = min(width, w_global)
        if width < w_global:
            plan.widths[nid] = width
            plan.narrowed += 1
            plan.bits_saved += w_global - width
    return plan
