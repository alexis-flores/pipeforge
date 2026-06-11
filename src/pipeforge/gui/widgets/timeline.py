"""The pipeline timeline — PipeForge's signature element (§5.1, VZ-1).

A horizontal cycle ruler; every signal is a bar from its inputs-ready cycle
to its output-ready cycle. The critical path glows in the theme's red,
dividers in orange. Appears in the Audit, Visualizer, and Bisection views.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from pipeforge.core.viz.layout import Layout
from pipeforge.gui.theme.tokens import Theme

_CYCLE_PX = 12.0
_ROW_PX = 30.0
_BOX_H = 22.0
_MARGIN_X = 24.0
_RULER_H = 26.0


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
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

    # -- geometry ------------------------------------------------------------

    def _x(self, cycle: float) -> float:
        return _MARGIN_X + cycle * _CYCLE_PX

    def _box_rect(self, start: int, end: int, row: int) -> QRectF:
        x = self._x(start)
        w = max((end - start) * _CYCLE_PX, _CYCLE_PX)
        y = _RULER_H + row * _ROW_PX
        return QRectF(x, y, w, _BOX_H)

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
        nid = self.node_at(event.position().x(), event.position().y())
        if nid:
            self.nodeClicked.emit(nid)

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

        # edges (quiet)
        painter.setPen(QPen(QColor(t["border"]), 1.0))
        for a, b in layout.edges:
            ba, bb = layout.boxes[a], layout.boxes[b]
            ra = self._box_rect(ba.start, ba.end, ba.row)
            rb = self._box_rect(bb.start, bb.end, bb.row)
            painter.drawLine(
                int(ra.right()), int(ra.center().y()), int(rb.left()), int(rb.center().y())
            )

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
            text_color = QColor(t["textPrimary"])
            if box.nid in self._dimmed:
                text_color = QColor(t["textDisabled"])
            painter.setPen(text_color)
            label = box.label
            if self._slack:
                slack = self._slack.get(box.nid, 0)
                label = f"{label}  +{slack}" if slack else label
            painter.drawText(
                rect.adjusted(5, 0, -3, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
        painter.end()
