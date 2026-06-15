"""The pipeline timeline - PipeForge's signature element (5.1, VZ-1).

A horizontal cycle ruler; every signal is a bar from its inputs-ready cycle
to its output-ready cycle. The critical path glows in the theme's red,
dividers in orange. Appears in the Audit, Visualizer, and Bisection views.
"""

from __future__ import annotations

from itertools import pairwise

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from pipeforge.core.viz.layout import Layout
from pipeforge.gui.theme.tokens import Theme

_CYCLE_PX = 12.0
_ROW_PX = 32.0  # 8px-grid row pitch with breathing room (VZ-5)
_BOX_H = 24.0
_MARGIN_X = 24.0
_RULER_H = 32.0  # 8px grid
_ACCENT_W = 3.0  # per-op left-edge accent bar width (VZ-5)

#: per-operator-kind accent token (VZ-5) - semantic tokens only, no hex.
_OP_ACCENT: dict[str, str] = {
    "elem_smul": "accent",
    "elem_ssqr": "accent",
    "matscale": "accent",
    "matmul": "accent",
    "sumsqr": "accent",
    "crossp": "accent",
    "elem_sdiv": "divider",
    "elem_sinv": "divider",
    "matunscale": "divider",
    "elem_sdiv_by_row": "divider",
    "elem_usqrt": "warning",
    "rootsqr": "warning",
    "vecnormrows": "warning",
    "vecnormcols": "warning",
    "matadd": "success",
    "matsub": "success",
    "matadd3": "success",
    "elem_neg": "success",
    "elem_abs": "success",
    "elem_smax": "success",
    "elem_smin": "success",
}
_DEFAULT_ACCENT = "accentMuted"


class TimelineWidget(QWidget):
    """Custom-painted cycle timeline over a DAG layout."""

    nodeClicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout: Layout | None = None
        self._theme: Theme | None = None
        self._selected = ""
        self._dimmed: frozenset[str] = frozenset()
        self._status: dict[str, str] = {}  # nid -> 'ok'|'bad' (bisection, BI-3)
        self._slack: dict[str, int] = {}  # nid -> spare cycles (VZ-1 overlay)
        self.cursor_cycle: int | None = None  # scrubbable cycle cursor (VZ-6)
        self._density = "comfortable"  # 'comfortable' | 'compact' (UI-9)
        self._golden: dict[str, int] = {}  # nid -> golden value at cursor (VZ-7)
        self._rtl: dict[str, int] = {}  # nid -> observed RTL value (VZ-7)
        self._flash_nid = ""  # transient coupling-cue node (VZ-2a)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # -- state ---------------------------------------------------------------

    def set_layout(self, layout: Layout | None) -> None:
        self._layout = layout
        if layout is not None:
            w = int(_MARGIN_X * 2 + max(layout.total_cycles, 1) * _CYCLE_PX)
            h = int(_RULER_H + max(layout.rows, 1) * _ROW_PX + 12)
            self.setMinimumSize(w, h)
        self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_selected(self, nid: str) -> None:
        if nid != self._selected:
            self._selected = nid
            self.update()

    def set_bisection(self, status: dict[str, str], dimmed: frozenset[str]) -> None:
        """BI-3: matched green, first divergent red, downstream dimmed."""
        self._status = dict(status)
        self._dimmed = dimmed
        self.update()

    def set_slack(self, slack: dict[str, int]) -> None:
        """Per-node slack overlay; empty dict hides it (VZ-1)."""
        self._slack = dict(slack)
        self.update()

    # -- per-op accent (VZ-5) -----------------------------------------------

    def accent_token(self, nid: str) -> str:
        """Semantic accent token for a node's operator kind (VZ-5)."""
        if self._layout is None or nid not in self._layout.boxes:
            return _DEFAULT_ACCENT
        box = self._layout.boxes[nid]
        if box.is_divider:
            return "divider"
        return _OP_ACCENT.get(box.module, _DEFAULT_ACCENT)

    @staticmethod
    def row_pitch() -> float:
        """Row pitch in px — honours the 8px grid (VZ-5)."""
        return _ROW_PX

    # -- edge routing + emphasis (VZ-4) -------------------------------------

    def route_edge(self, a: str, b: str) -> list[tuple[float, float]]:
        """Orthogonal (Manhattan) waypoints from a's output to b's input."""
        ba, bb = self._layout.boxes[a], self._layout.boxes[b]  # type: ignore[union-attr]
        ra = self._box_rect(ba.start, ba.end, ba.row)
        rb = self._box_rect(bb.start, bb.end, bb.row)
        x0, y0 = ra.right(), ra.center().y()
        x1, y1 = rb.left(), rb.center().y()
        mid = (x0 + x1) / 2.0
        return [(x0, y0), (mid, y0), (mid, y1), (x1, y1)]  # box-avoiding bends

    def edge_active(self, a: str, b: str) -> bool:
        """An edge is emphasized when it is the selected node's fan-in/out (VZ-4)."""
        return bool(self._selected) and self._selected in (a, b)

    def active_edges(self) -> list[tuple[str, str]]:
        if self._layout is None:
            return []
        return [(a, b) for a, b in self._layout.edges if self.edge_active(a, b)]

    # -- cycle cursor (VZ-6) ------------------------------------------------

    def cycle_at_x(self, px: float) -> int:
        return max(0, round((px - _MARGIN_X) / _CYCLE_PX))

    def set_cursor_cycle(self, cycle: int | None) -> None:
        self.cursor_cycle = cycle
        self.update()

    def scrub_to_x(self, px: float) -> None:
        """Move the cycle cursor to the column under px (VZ-6)."""
        if self._layout is None:
            return
        self.set_cursor_cycle(min(self.cycle_at_x(px), self._layout.total_cycles))

    def cursor_column_rect(self) -> QRectF | None:
        """The highlighted column spanning all rows at the cursor (VZ-6)."""
        if self.cursor_cycle is None:
            return None
        x = self._x(self.cursor_cycle)
        return QRectF(x - 1.0, _RULER_H, 2.0, self.height() - _RULER_H - 4)

    # -- value overlay at the cursor (VZ-7) ---------------------------------

    def set_overlay(self, golden: dict[str, int], rtl: dict[str, int] | None = None) -> None:
        """Per-node golden (and observed RTL) values to show while scrubbing."""
        self._golden = dict(golden)
        self._rtl = dict(rtl or {})
        self.update()

    def overlay_at_cursor(self) -> list[tuple[str, int, int | None, bool]]:
        """(nid, golden, rtl, mismatch) for nodes in flight at the cursor (VZ-7)."""
        if self._layout is None or self.cursor_cycle is None:
            return []
        out: list[tuple[str, int, int | None, bool]] = []
        for box in self._layout.boxes.values():
            if box.nid not in self._golden or not (box.start <= self.cursor_cycle <= box.end):
                continue
            g = self._golden[box.nid]
            r = self._rtl.get(box.nid)
            out.append((box.nid, g, r, r is not None and r != g))
        return out

    def value_token(self, mismatch: bool) -> str:
        return "error" if mismatch else "textPrimary"  # mismatches in error (VZ-7)

    # -- PIPE delay registers as explicit bars (VZ-8) -----------------------

    def delay_bars(self) -> list[tuple[str, int, int, int]]:
        """(consumer nid, from_cycle, to_cycle, row) for each operand wait (VZ-8).

        A delay register exists wherever an operand is ready before the consumer
        starts — the gap a `PIPE must cover. Distinct from operator bars.
        """
        if self._layout is None:
            return []
        bars: list[tuple[str, int, int, int]] = []
        for a, b in self._layout.edges:
            ba, bb = self._layout.boxes[a], self._layout.boxes[b]
            if bb.start > ba.end:  # operand waits: an explicit delay register
                bars.append((b, ba.end, bb.start, bb.row))
        return bars

    # -- density (UI-9) ------------------------------------------------------

    def flash(self, nid: str) -> None:
        """A transient coupling cue on a bar (VZ-2a) — clears itself shortly."""
        from PyQt6.QtCore import QTimer

        self._flash_nid = nid
        self.update()
        QTimer.singleShot(220, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash_nid = ""
        self.update()

    def set_density(self, density: str) -> None:
        self._density = "compact" if density == "compact" else "comfortable"
        self.update()

    @property
    def density(self) -> str:
        return self._density

    # -- critical-path emphasis (MO-1) --------------------------------------

    def critical_nodes(self) -> set[str]:
        """Nodes on the critical path, emphasized statically in paint (MO-1).

        NOTE: the earlier infinite QPropertyAnimation pulse was removed — a
        forever-running animation races with widget teardown (segfault) and the
        static red glow already draws the eye. Emphasis is now paint-only.
        """
        if self._layout is None:
            return set()
        return {b.nid for b in self._layout.boxes.values() if b.on_critical_path}

    def _row_px(self) -> float:
        return 24.0 if self._density == "compact" else _ROW_PX

    def _box_h(self) -> float:
        return 16.0 if self._density == "compact" else _BOX_H

    # -- geometry ------------------------------------------------------------

    def _x(self, cycle: float) -> float:
        return _MARGIN_X + cycle * _CYCLE_PX

    def _box_rect(self, start: int, end: int, row: int) -> QRectF:
        x = self._x(start)
        w = max((end - start) * _CYCLE_PX, _CYCLE_PX)
        y = _RULER_H + row * self._row_px()
        return QRectF(x, y, w, self._box_h())

    def node_at(self, px: float, py: float) -> str:
        if self._layout is None:
            return ""
        for box in self._layout.boxes.values():
            if self._box_rect(box.start, box.end, box.row).contains(px, py):
                return box.nid
        return ""

    # -- events ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        x, y = event.position().x(), event.position().y()
        nid = self.node_at(x, y)
        if nid:
            self.nodeClicked.emit(nid)
        elif y <= _RULER_H:  # click on the ruler positions the cycle cursor (VZ-6)
            self.scrub_to_x(x)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.position().y() <= _RULER_H:  # scrub the cursor across the ruler
            self.scrub_to_x(event.position().x())

    def paintEvent(self, event: object) -> None:
        if self._theme is None:
            return
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(t["bg"]))
        if self._layout is None or not self._layout.boxes:
            painter.setPen(QColor(t["textSecondary"]))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Open a MATLAB file to see its pipeline timeline",
            )
            painter.end()
            return
        layout = self._layout
        small = QFont(self.font())
        small.setPointSizeF(max(self.font().pointSizeF() - 2.0, 7.0))

        # cycle ruler
        painter.setFont(small)
        step = max(1, layout.total_cycles // 24 or 1)
        for c in range(0, layout.total_cycles + 1, step):
            x = self._x(c)
            painter.setPen(QPen(QColor(t["border"]), 0.5))
            painter.drawLine(int(x), int(_RULER_H - 6), int(x), self.height() - 8)
            painter.setPen(QColor(t["textSecondary"]))
            painter.drawText(int(x) + 2, int(_RULER_H - 10), str(c))

        # edges: orthogonal routing, low contrast by default; the selected node's
        # fan-in/out brighten while the rest fade (VZ-4)
        any_selected = bool(self._selected)
        for a, b in layout.edges:
            active = self.edge_active(a, b)
            color = QColor(t["accent"] if active else t["border"])
            color.setAlphaF(0.9 if active else (0.18 if any_selected else 0.4))
            painter.setPen(QPen(color, 1.6 if active else 1.0))
            pts = [QPointF(x, y) for x, y in self.route_edge(a, b)]
            for p, q in pairwise(pts):
                painter.drawLine(p, q)

        # bars
        painter.setFont(small)
        for box in layout.boxes.values():
            rect = self._box_rect(box.start, box.end, box.row)
            fill = QColor(t["surface"])
            border = QColor(t["border"])
            border_w = 1.0
            status = self._status.get(box.nid, "")
            if status == "ok":
                border = QColor(t["success"])
                border_w = 1.5
            elif status == "bad":
                border = QColor(t["error"])
                border_w = 2.5
                fill = QColor(t["surfaceElevated"])
            elif box.on_critical_path:
                border = QColor(t["criticalPath"])
                border_w = 2.0
            elif box.is_divider:
                border = QColor(t["divider"])
                border_w = 1.5
            if box.nid == self._selected:
                fill = QColor(t["selection"])
                border = QColor(t["focusRing"])
                border_w = 2.0
            if box.nid in self._dimmed:
                fill.setAlphaF(0.35)
                border.setAlphaF(0.35)
            if box.on_critical_path and status == "":
                glow = QColor(t["criticalPath"])
                glow.setAlphaF(0.25)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 7, 7)
            painter.setPen(QPen(border, border_w))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5, 5)
            # per-op left-edge accent bar (VZ-5): operator kind at a glance
            accent = QColor(t[self.accent_token(box.nid)])
            if box.nid in self._dimmed:
                accent.setAlphaF(0.35)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(rect.left(), rect.top(), _ACCENT_W, rect.height()), 2, 2)
            text_color = QColor(t["textPrimary"])
            if box.nid in self._dimmed:
                text_color = QColor(t["textDisabled"])
            painter.setPen(text_color)
            label = box.label
            if self._slack:
                slack = self._slack.get(box.nid, 0)
                label = f"{label}  +{slack}" if slack else label
            painter.drawText(
                rect.adjusted(_ACCENT_W + 4, 0, -3, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )

        # PIPE delay registers as explicit, distinct bars on the data path (VZ-8)
        delay_col = QColor(t["accentMuted"])
        delay_col.setAlphaF(0.5)
        painter.setPen(QPen(delay_col, 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for _nid, c0, c1, row in self.delay_bars():
            y = _RULER_H + row * self._row_px() + self._box_h() / 2.0
            painter.drawLine(QPointF(self._x(c0), y), QPointF(self._x(c1), y))
            painter.drawRect(QRectF(self._x(c0), y - 2, self._x(c1) - self._x(c0), 4))

        # value overlay at the cursor: golden and (when observed) RTL, mismatches
        # in the error token (VZ-7)
        overlay = self.overlay_at_cursor()
        if overlay:
            small2 = QFont(self.font())
            small2.setPointSizeF(max(self.font().pointSizeF() - 2.0, 7.0))
            painter.setFont(small2)
            for nid, g, r, mismatch in overlay:
                box = layout.boxes[nid]
                rect = self._box_rect(box.start, box.end, box.row)
                painter.setPen(QColor(t[self.value_token(mismatch)]))
                txt = f"g={g}" + (f" r={r}" if r is not None else "")
                painter.drawText(QPointF(rect.left(), rect.top() - 1), txt)

        # cycle cursor: faint column across all rows so occupancy is readable
        # vertically — "what is in flight at cycle N" (VZ-6)
        col = self.cursor_column_rect()
        if col is not None:
            highlight = QColor(t["accent"])
            highlight.setAlphaF(0.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            painter.drawRect(col)
        painter.end()
