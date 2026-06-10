"""Audit report renderers (AU-4): plain text and JSON.

The formats are pinned byte-for-byte (modulo the version header) by golden
files captured from the seed auditor (AU-5); do not change them casually.
"""

from __future__ import annotations

import json
from typing import Any

from pipeforge.core.audit.engine import Audit

#: Version string for report headers. Goldens ignore the header line/key.
REPORT_VERSION = "1.0"
TOOL_NAME = "matlib_audit"


def _short(label: str, width: int = 38) -> str:
    return label if len(label) <= width else label[: width - 1] + "…"


def render_text(audit: Audit) -> str:
    cm = audit.cm
    lines: list[str] = []
    lines.append(f"{TOOL_NAME} {REPORT_VERSION} — nkMatlib latency audit")
    lines.append(f"file: {audit.filename}")
    lines.append(f"fixedp: WIDTH={cm.width} SCALE={cm.scale} LEFT={cm.left}")
    lines.append("latencies: " + " ".join(f"{k}={v}" for k, v in cm.summary().items()))
    lines.append("")
    lines.append("== statements ==")
    if audit.dag.statements:
        for s in audit.dag.statements:
            lines.append(f"  line {s.line:>3}  {s.target:<12} ready @ {s.ready:>4}  (+{s.lat})")
    else:
        lines.append("  (none)")
    lines.append("")
    chain = audit.critical_path()
    lines.append(f"== critical path ==  total {audit.total_latency} cycles")
    for node in chain:
        mod = node.module if node.module else "wire"
        plus = f"+{node.lat}" if node.lat else ""
        lines.append(
            f"  @ {node.ready:>4}  line {node.line:>3}  {_short(node.label):<38} {mod:<12} {plus}"
        )
    lines.append("")
    census = audit.census
    total = sum(census.values())
    lines.append(f"== operator census ==  ({total} instances, {audit.divider_count} dividers)")
    if census:
        for mod, count in census.items():
            marker = "   << divider" if cm.is_divider(mod) else ""
            lines.append(f"  {mod:<14} x {count}{marker}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("== findings ==")
    if audit.findings:
        for f in audit.findings:
            lines.append(f"  [{f.tag:<8}] line {f.line}: {f.message}")
            lines.append(f"             -> {f.suggestion}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("== skipped ==")
    if audit.skipped:
        for sk in audit.skipped:
            lines.append(f"  line {sk.line}: {sk.reason}")
    else:
        lines.append("  (none)")
    lines.append("")
    return "\n".join(lines)


def to_payload(audit: Audit) -> dict[str, Any]:
    """JSON-ready structured audit (AU-4)."""
    cm = audit.cm
    chain = audit.critical_path()
    return {
        "tool": TOOL_NAME,
        "version": REPORT_VERSION,
        "file": audit.filename,
        "width": cm.width,
        "scale": cm.scale,
        "left": cm.left,
        "latencies": cm.summary(),
        "statements": [
            {"line": s.line, "target": s.target, "ready": s.ready, "lat": s.lat, "root": s.root}
            for s in audit.dag.statements
        ],
        "critical_path": {
            "total": audit.total_latency,
            "chain": [
                {
                    "id": n.nid,
                    "cycle": n.ready,
                    "line": n.line,
                    "label": n.label,
                    "module": n.module,
                    "lat": n.lat,
                }
                for n in chain
            ],
        },
        "census": audit.census,
        "instances": sum(audit.census.values()),
        "dividers": audit.divider_count,
        "findings": [
            {
                "tag": f.tag,
                "line": f.line,
                "savings": f.savings,
                "message": f.message,
                "suggestion": f.suggestion,
            }
            for f in audit.findings
        ],
        "skipped": [{"line": s.line, "reason": s.reason} for s in audit.skipped],
        "nodes": [
            {
                "id": n.nid,
                "module": n.module,
                "op": n.op,
                "lat": n.lat,
                "ready": n.ready,
                "args": n.args,
                "line": n.line,
                "signal": n.signal,
                "label": n.label,
            }
            for n in (audit.dag.nodes[nid] for nid in audit.dag.order)
        ],
    }


def render_json(audit: Audit) -> str:
    return json.dumps(to_payload(audit), indent=2)
