"""Self-contained HTML design-review report (RH-1).

One attachable file per design: the pipeline timeline (inline SVG), audit
summary + findings with rewrites, resource estimate, optional range analysis
and co-simulation verdict. No external assets, no scripts — it renders in a
mail client, a PR, or a design-review projector.
"""

from __future__ import annotations

from html import escape

from pipeforge.core.audit.engine import Audit
from pipeforge.core.cosim.runner import CosimResult
from pipeforge.core.costmodel.resources import ResourceEstimate
from pipeforge.core.ranges.propagate import RangeReport
from pipeforge.core.svlint.checks import LintResult

#: neutral light palette for the embedded SVG (theme-independent artifact).
_SVG_COLORS = {
    "bg": "#ffffff",
    "box": "#f2f0e9",
    "box_border": "#b5ae9e",
    "text": "#3a3630",
    "critical": "#c14a3a",
    "divider": "#c07a2e",
    "edge": "#b5ae9e",
    "ruler": "#e7e3d8",
}

_CSS = """
body { font-family: -apple-system, "Segoe UI", sans-serif; margin: 2rem auto;
       max-width: 70rem; color: #2a2723; background: #faf9f6; line-height: 1.5; }
h1 { font-weight: 300; } h2 { font-weight: 600; margin-top: 2rem;
     border-bottom: 1px solid #d8d3c6; padding-bottom: .3rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th { text-align: left; color: #6a645a; font-size: .8rem; border-bottom: 1px solid #d8d3c6;
     padding: .4rem .6rem; }
td { padding: .4rem .6rem; border-bottom: 1px solid #eceade; vertical-align: top; }
.svgwrap { overflow-x: auto; border: 1px solid #d8d3c6; border-radius: 8px;
           background: #ffffff; padding: .5rem; }
.kpi { display: inline-block; margin-right: 2rem; }
.kpi b { font-size: 1.6rem; font-weight: 600; display: block; }
.kpi span { color: #6a645a; font-size: .8rem; }
.pass { color: #2c7a3d; font-weight: 600; } .fail { color: #c14a3a; font-weight: 600; }
.warn { color: #c07a2e; } .muted { color: #6a645a; font-size: .85rem; }
code { background: #f2f0e9; padding: 0 .3rem; border-radius: 4px; }
"""


def _timeline_svg(audit: Audit) -> str:
    from pipeforge.core.viz.layout import layout_for_audit
    from pipeforge.core.viz.svg import SvgPalette, render_svg

    layout = layout_for_audit(audit)
    return render_svg(layout, SvgPalette(**_SVG_COLORS), title=audit.filename)


def _kpis(audit: Audit, resources: ResourceEstimate | None) -> str:
    census = audit.census
    parts = [
        f'<div class="kpi"><b>{audit.total_latency}</b><span>cycles critical path</span></div>',
        f'<div class="kpi"><b>{sum(census.values())}</b><span>operator instances</span></div>',
        f'<div class="kpi"><b>{audit.divider_count}</b><span>dividers</span></div>',
        f'<div class="kpi"><b>{len(audit.findings)}</b><span>findings</span></div>',
    ]
    if resources is not None:
        parts.append(
            f'<div class="kpi"><b>{resources.dsp}</b>'
            f"<span>DSP tiles ({escape(resources.family)})</span></div>"
        )
        parts.append(
            f'<div class="kpi"><b>≈{resources.lut_approx}</b><span>LUTs (rough)</span></div>'
        )
    return "\n".join(parts)


def _findings_table(audit: Audit) -> str:
    if not audit.findings:
        return '<p class="pass">✓ Clean pipeline — no findings.</p>'
    rows = "\n".join(
        f"<tr><td><code>{escape(f.tag)}</code></td><td>{f.line}</td><td>{f.savings}</td>"
        f"<td>{escape(f.message)}</td><td>{escape(f.suggestion)}</td></tr>"
        for f in audit.findings
    )
    return (
        "<table><thead><tr><th>Tag</th><th>Line</th><th>Saves (cycles)</th>"
        f"<th>Finding</th><th>Suggested rewrite</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def _ranges_section(report: RangeReport) -> str:
    rows = []
    for nr in report.nodes.values():
        flags = []
        if nr.overflow_risk:
            flags.append('<span class="warn">⚠ overflow</span>')
        if nr.near_zero_divisor:
            flags.append('<span class="warn">⚠ ÷ near 0</span>')
        bits = str(nr.integer_bits) if nr.integer_bits < 64 else "unbounded"
        rows.append(
            f"<tr><td><code>{escape(nr.signal)}</code></td>"
            f"<td>[{nr.interval.lo:.6g}, {nr.interval.hi:.6g}]</td>"
            f"<td>{bits}</td><td>{' '.join(flags)}</td></tr>"
        )
    overflow = len(report.overflow_nodes)
    hazards = len(report.hazard_nodes)
    verdict = (
        f'<p class="warn">⚠ {overflow} value(s) can overflow '
        f"{report.fmt_width}/{report.fmt_scale}; {hazards} divide-near-zero hazard(s). "
        f"Required LEFT ≥ {report.required_left}.</p>"
        if overflow or hazards
        else f'<p class="pass">✓ No overflow at {report.fmt_width}/{report.fmt_scale} '
        f"(required LEFT ≥ {report.required_left}).</p>"
    )
    return (
        f"<h2>Range analysis</h2>{verdict}"
        "<table><thead><tr><th>Signal</th><th>Range</th><th>Int bits</th><th>Flags</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _lint_section(lint: LintResult) -> str:
    if not lint.findings:
        return (
            f"<h2>RTL lint — <code>{escape(lint.filename)}</code></h2>"
            '<p class="pass">✓ Clean: no convention violations.</p>'
        )
    rows = "\n".join(
        f"<tr><td><code>{escape(f.check)}</code></td><td>{f.line}</td>"
        f"<td>{escape(f.message)}</td><td>{escape(f.fix)}</td></tr>"
        for f in lint.findings
    )
    return (
        f"<h2>RTL lint — <code>{escape(lint.filename)}</code></h2>"
        f'<p class="warn">{len(lint.findings)} finding(s), backend {escape(lint.backend)}.</p>'
        "<table><thead><tr><th>Check</th><th>Line</th><th>Message</th><th>Fix</th></tr>"
        f"</thead><tbody>{rows}</tbody></table>"
    )


def _cosim_section(cosim: CosimResult) -> str:
    verdict = '<span class="pass">PASS</span>' if cosim.passed else '<span class="fail">FAIL</span>'
    rows = []
    for o in cosim.outputs:
        if o.passed:
            rows.append(
                f"<tr><td><code>{escape(o.name)}</code></td><td>{verdict}</td>"
                f"<td>{o.compared} vectors bit-exact — SQNR {o.sqnr_db:.1f} dB</td></tr>"
            )
        else:
            rows.append(
                f"<tr><td><code>{escape(o.name)}</code></td>"
                f'<td><span class="fail">FAIL</span></td>'
                f"<td>first failing vector #{o.first_failure} "
                f"(expected 0x{o.expected:x}, got 0x{o.actual:x})</td></tr>"
            )
    bisect = ""
    if cosim.bisect_report is not None and cosim.bisect_report.diverged:
        bisect = f'<p class="warn">{escape(cosim.bisect_report.message)}</p>'
    return (
        f"<h2>Co-simulation — {verdict} <span class='muted'>"
        f"[{escape(cosim.harness_backend)}]</span></h2>"
        "<table><thead><tr><th>Output</th><th>Verdict</th><th>Detail</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>{bisect}"
    )


def build_report(
    audit: Audit,
    resources: ResourceEstimate | None = None,
    range_report: RangeReport | None = None,
    lint: LintResult | None = None,
    cosim: CosimResult | None = None,
) -> str:
    """Assemble the self-contained HTML report (RH-1)."""
    import datetime

    from pipeforge import __version__

    sections = [
        f"<h1>PipeForge design review — <code>{escape(audit.filename)}</code></h1>",
        f'<p class="muted">Format {audit.cm.width}/{audit.cm.scale} · '
        f"generated {datetime.date.today().isoformat()} · PipeForge {__version__}</p>",
        _kpis(audit, resources),
        "<h2>Pipeline timeline</h2>",
        f'<div class="svgwrap">{_timeline_svg(audit)}</div>',
        "<h2>Findings</h2>",
        _findings_table(audit),
    ]
    if range_report is not None:
        sections.append(_ranges_section(range_report))
    if lint is not None:
        sections.append(_lint_section(lint))
    if cosim is not None:
        sections.append(_cosim_section(cosim))
    body = "\n".join(sections)
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        f"<title>PipeForge report — {escape(audit.filename)}</title>"
        f"<style>{_CSS}</style></head><body>\n{body}\n</body></html>\n"
    )
