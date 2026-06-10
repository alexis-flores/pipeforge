"""SVG export of a DAG layout (VZ-3).

Colors arrive as parameters (semantic theme tokens); no color literals here.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from pipeforge.core.viz.layout import Layout

CYCLE_PX = 14
ROW_PX = 34
BOX_H = 24
MARGIN = 40


@dataclass(frozen=True)
class SvgPalette:
    """Semantic colors for export; values come from the active theme."""

    bg: str
    box: str
    box_border: str
    text: str
    critical: str
    divider: str
    edge: str
    ruler: str


def render_svg(layout: Layout, palette: SvgPalette, title: str = "") -> str:
    width = MARGIN * 2 + max(layout.total_cycles, 1) * CYCLE_PX
    height = MARGIN * 2 + max(layout.rows, 1) * ROW_PX
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="monospace" font-size="10">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="{palette.bg}"/>')
    if title:
        parts.append(f'<text x="{MARGIN}" y="16" fill="{palette.text}">{escape(title)}</text>')

    def x_of(cycle: int) -> int:
        return MARGIN + cycle * CYCLE_PX

    def y_of(row: int) -> int:
        return MARGIN + row * ROW_PX

    # cycle ruler
    step = max(1, (layout.total_cycles // 16) or 1)
    for c in range(0, layout.total_cycles + 1, step):
        x = x_of(c)
        parts.append(
            f'<line x1="{x}" y1="{MARGIN - 14}" x2="{x}" y2="{height - MARGIN + 8}" '
            f'stroke="{palette.ruler}" stroke-width="0.5"/>'
        )
        parts.append(f'<text x="{x + 2}" y="{MARGIN - 16}" fill="{palette.text}">{c}</text>')

    # edges
    for a, b in layout.edges:
        ba, bb = layout.boxes[a], layout.boxes[b]
        x1, y1 = x_of(ba.end), y_of(ba.row) + BOX_H // 2
        x2, y2 = x_of(bb.start), y_of(bb.row) + BOX_H // 2
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{palette.edge}" stroke-width="1"/>'
        )

    # node boxes
    for box in layout.boxes.values():
        x = x_of(box.start)
        w = max((box.end - box.start) * CYCLE_PX, CYCLE_PX)
        y = y_of(box.row)
        if box.on_critical_path:
            stroke = palette.critical
            sw = 2
        elif box.is_divider:
            stroke = palette.divider
            sw = 2
        else:
            stroke = palette.box_border
            sw = 1
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{BOX_H}" rx="4" '
            f'fill="{palette.box}" stroke="{stroke}" stroke-width="{sw}"/>'
        )
        parts.append(
            f'<text x="{x + 4}" y="{y + 16}" fill="{palette.text}">{escape(box.label)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
