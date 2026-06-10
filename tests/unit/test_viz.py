"""Layout and SVG export tests (VZ-1, VZ-3)."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.viz.layout import layered_layout, layout_for_audit
from pipeforge.core.viz.svg import SvgPalette, render_svg

CM = CostModel(16, 12)

PALETTE = SvgPalette(
    bg="bg-token",
    box="box-token",
    box_border="border-token",
    text="text-token",
    critical="critical-token",
    divider="divider-token",
    edge="edge-token",
    ruler="ruler-token",
)


def _audit(src: str):
    return audit_source(src, "t.m", CM)


@pytest.mark.req("VZ-1")
def test_timeline_axis_is_cycles() -> None:
    a = _audit("t = x .* y;\nu = t + z;\nv = u ./ w;")
    layout = layout_for_audit(a)
    roots = [s.root for s in a.dag.statements]
    bt, bu, bv = (layout.boxes[r] for r in roots)
    assert (bt.start, bt.end) == (0, 4)
    assert (bu.start, bu.end) == (4, 5)
    assert (bv.start, bv.end) == (5, 5 + CM.div_lat)
    assert layout.total_cycles == 5 + CM.div_lat


@pytest.mark.req("VZ-1")
def test_critical_path_and_dividers_marked() -> None:
    a = _audit("p = a ./ b;\nq = c + d;")
    layout = layout_for_audit(a)
    div_box = layout.boxes[a.dag.statements[0].root]
    assert div_box.is_divider
    assert div_box.on_critical_path
    add_box = layout.boxes[a.dag.statements[1].root]
    assert not add_box.is_divider
    assert not add_box.on_critical_path


def test_rows_never_overlap() -> None:
    a = _audit("\n".join(f"v{i} = a{i} .* b{i};" for i in range(12)))
    layout = layered_layout(a.dag)
    seen: dict[int, list[tuple[int, int]]] = {}
    for box in layout.boxes.values():
        for s, e in seen.get(box.row, []):
            assert box.end <= s or box.start >= e, "row overlap"
        seen.setdefault(box.row, []).append((box.start, max(box.end, box.start + 1)))


@pytest.mark.req("VZ-3")
def test_svg_export_uses_palette_tokens_only() -> None:
    a = _audit("ux = x ./ n;\nuy = y ./ n;")
    svg = render_svg(layout_for_audit(a), PALETTE, title="t.m")
    assert svg.startswith("<svg")
    assert "critical-token" in svg
    assert "divider-token" in svg
    assert "#" not in svg.replace("&#", "")  # no hex colors injected here


def test_empty_dag_layout() -> None:
    a = _audit("")
    layout = layout_for_audit(a)
    assert layout.total_cycles == 0
    assert not layout.boxes
    svg = render_svg(layout, PALETTE)
    assert svg.startswith("<svg")
