"""Workspace data cards (WS-8): see the data, not just its metadata.

One card per snapshot variable, custom-painted in the timeline's visual
language (semantic theme tokens only): a sparkline with a min/max band for
signals and vectors, a heatmap for matrices, a large numeral for scalars,
and a class chip so the type is readable at a glance. Clicking a card
selects the variable (VZ-2 selection sync).
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from pipeforge.core.frontend.varinfo import VarInfo, WorkspaceSnapshot
from pipeforge.gui.theme.tokens import Theme

_CARD_W = 232.0
_CARD_H = 138.0
_GAP = 12.0
_PAD = 12.0
_VIZ_H = 64.0
_MAX_SPARK_POINTS = 140
_MAX_HEAT_CELLS = 22  # per axis

#: MATLAB class -> accent token for the type chip (semantic tokens only).
_CLASS_TOKEN: dict[str, str] = {
    "double": "accent",
    "single": "accentMuted",
    "logical": "success",
    "embedded.fi": "divider",
    "char": "textDisabled",
}


def _class_token(class_name: str) -> str:
    if class_name.startswith(("int", "uint")):
        return "warning"
    return _CLASS_TOKEN.get(class_name, "accentMuted")


def _scaled(base: QFont, delta: float) -> QFont:
    """A font `delta` steps larger/smaller — robust to pixel-sized app fonts
    (QSS sets px, making pointSizeF() return -1)."""
    f = QFont(base)
    if base.pixelSize() > 0:
        f.setPixelSize(max(int(base.pixelSize() + delta), 8))
    else:
        f.setPointSizeF(max(base.pointSizeF() + delta, 7.0))
    return f


def _lerp(a: QColor, b: QColor, t: float) -> QColor:
    t = min(max(t, 0.0), 1.0)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def _stride(values: tuple[float, ...], cap: int) -> list[float]:
    if len(values) <= cap:
        return list(values)
    step = len(values) / cap
    return [values[int(i * step)] for i in range(cap)]


class DataCardsWidget(QWidget):
    """A responsive grid of variable cards over a WorkspaceSnapshot."""

    variableClicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme: Theme | None = None
        self._vars: list[VarInfo] = []
        self._rects: list[tuple[QRectF, str]] = []
        self._selected = ""
        self._hover = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMouseTracking(True)

    # -- state -----------------------------------------------------------------

    def set_snapshot(self, snapshot: WorkspaceSnapshot | None, needle: str = "") -> None:
        self._vars = []
        if snapshot is not None:
            needle = needle.lower().strip()
            self._vars = [
                v
                for name, v in sorted(snapshot.variables.items())
                if not needle or needle in name.lower()
            ]
        self._relayout()
        self.update()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_selected(self, name: str) -> None:
        if name != self._selected:
            self._selected = name
            self.update()

    # -- geometry ----------------------------------------------------------------

    def _columns(self) -> int:
        return max(1, int((self.width() - _GAP) // (_CARD_W + _GAP)))

    def _relayout(self) -> None:
        cols = self._columns()
        rows = (len(self._vars) + cols - 1) // cols if self._vars else 1
        self.setMinimumHeight(int(rows * (_CARD_H + _GAP) + _GAP))

    def resizeEvent(self, event) -> None:
        self._relayout()
        super().resizeEvent(event)

    def card_at(self, x: float, y: float) -> str:
        for rect, name in self._rects:
            if rect.contains(x, y):
                return name
        return ""

    # -- events -------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        name = self.card_at(event.position().x(), event.position().y())
        if name:
            self.set_selected(name)
            self.variableClicked.emit(name)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        hover = self.card_at(event.position().x(), event.position().y())
        if hover != self._hover:
            self._hover = hover
            self.update()

    # -- painting -------------------------------------------------------------------

    def paintEvent(self, event: object) -> None:
        if self._theme is None:
            return
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(t["bg"]))
        self._rects = []
        if not self._vars:
            painter.setPen(QColor(t["textSecondary"]))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Open a .mat (or refresh from MATLAB) to see the data here",
            )
            painter.end()
            return
        cols = self._columns()
        for i, info in enumerate(self._vars):
            row, col = divmod(i, cols)
            rect = QRectF(
                _GAP + col * (_CARD_W + _GAP),
                _GAP + row * (_CARD_H + _GAP),
                _CARD_W,
                _CARD_H,
            )
            self._rects.append((rect, info.name))
            self._paint_card(painter, rect, info, t)
        painter.end()

    def _paint_card(self, p: QPainter, rect: QRectF, info: VarInfo, t: Theme) -> None:
        selected = info.name == self._selected
        hovered = info.name == self._hover
        fill = QColor(t["surfaceElevated"] if hovered else t["surface"])
        border = QColor(t["focusRing"] if selected else t["border"])
        p.setPen(QPen(border, 2.0 if selected else 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(rect, 8, 8)

        base = self.font()
        name_font = QFont(base)
        name_font.setWeight(QFont.Weight.DemiBold)
        small = _scaled(base, -2.0)

        # header: name + class chip
        p.setFont(name_font)
        p.setPen(QColor(t["textPrimary"]))
        name_rect = QRectF(rect.left() + _PAD, rect.top() + 8, rect.width() - 2 * _PAD - 58, 18)
        name = p.fontMetrics().elidedText(
            info.name, Qt.TextElideMode.ElideMiddle, int(name_rect.width())
        )
        p.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        chip_color = QColor(t[_class_token(info.class_name)])
        p.setFont(small)
        chip_text = info.class_name.removeprefix("embedded.")
        chip_w = p.fontMetrics().horizontalAdvance(chip_text) + 12
        chip = QRectF(rect.right() - _PAD - chip_w, rect.top() + 8, chip_w, 16)
        chip_fill = QColor(chip_color)
        chip_fill.setAlphaF(0.18)
        p.setPen(QPen(chip_color, 1.0))
        p.setBrush(chip_fill)
        p.drawRoundedRect(chip, 8, 8)
        p.setPen(chip_color)
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, chip_text)

        # subheader: shape · fi · range
        times = "\u00d7"  # a real multiplication sign reads better on a card
        pieces = [times.join(str(d) for d in info.size)]
        if info.fi is not None:
            pieces.append(f"fi {info.fi.width}/{info.fi.scale}")
        if info.vmin is not None and info.vmax is not None and not info.is_scalar:
            pieces.append(f"[{info.vmin:.3g}, {info.vmax:.3g}]")
        if info.truncated:
            pieces.append("…")
        p.setPen(QColor(t["textSecondary"]))
        p.drawText(
            QRectF(rect.left() + _PAD, rect.top() + 28, rect.width() - 2 * _PAD, 14),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            " · ".join(pieces),
        )

        viz = QRectF(rect.left() + _PAD, rect.top() + 50, rect.width() - 2 * _PAD, _VIZ_H)
        if not info.values:
            p.setPen(QColor(t["textDisabled"]))
            p.drawText(viz, Qt.AlignmentFlag.AlignCenter, "—")
            return
        if info.is_scalar:
            self._paint_scalar(p, viz, info, t)
        elif info.is_matrix:
            self._paint_heatmap(p, viz, info, t)
        else:
            self._paint_sparkline(p, viz, info, t)

    def _paint_scalar(self, p: QPainter, viz: QRectF, info: VarInfo, t: Theme) -> None:
        big = _scaled(self.font(), +9.0)
        big.setWeight(QFont.Weight.Light)
        p.setFont(big)
        p.setPen(QColor(t["accent"]))
        p.drawText(viz, Qt.AlignmentFlag.AlignCenter, f"{info.values[0]:.6g}")

    def _paint_sparkline(self, p: QPainter, viz: QRectF, info: VarInfo, t: Theme) -> None:
        values = _stride(info.values, _MAX_SPARK_POINTS)
        lo = min(values)
        hi = max(values)
        span = (hi - lo) or 1.0
        inner = viz.adjusted(0, 6, 0, -12)

        def pt(i: int, v: float) -> QPointF:
            x = inner.left() + inner.width() * (i / max(len(values) - 1, 1))
            y = inner.bottom() - inner.height() * ((v - lo) / span)
            return QPointF(x, y)

        # zero line when zero is in range: the eye's anchor for signed signals
        if lo <= 0.0 <= hi:
            zero_y = inner.bottom() - inner.height() * ((0.0 - lo) / span)
            p.setPen(QPen(QColor(t["border"]), 0.8, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(inner.left(), zero_y), QPointF(inner.right(), zero_y))
        accent = QColor(t["accent"])
        path = QPainterPath(pt(0, values[0]))
        for i, v in enumerate(values[1:], start=1):
            path.lineTo(pt(i, v))
        # soft area fill under the curve, then the line itself
        area = QPainterPath(path)
        area.lineTo(inner.right(), inner.bottom())
        area.lineTo(inner.left(), inner.bottom())
        area.closeSubpath()
        area_color = QColor(accent)
        area_color.setAlphaF(0.14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(area_color)
        p.drawPath(area)
        p.setPen(QPen(accent, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setFont(_scaled(self.font(), -3.0))
        p.setPen(QColor(t["textSecondary"]))
        p.drawText(
            QRectF(viz.left(), viz.bottom() - 11, viz.width(), 11),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{lo:.3g}",
        )
        p.drawText(
            QRectF(viz.left(), viz.bottom() - 11, viz.width(), 11),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{hi:.3g}",
        )

    def _paint_heatmap(self, p: QPainter, viz: QRectF, info: VarInfo, t: Theme) -> None:
        rows, cols = info.shape2d
        rows_s = min(rows, _MAX_HEAT_CELLS)
        cols_s = min(cols, _MAX_HEAT_CELLS)
        lo = info.vmin if info.vmin is not None else min(info.values)
        hi = info.vmax if info.vmax is not None else max(info.values)
        span = (hi - lo) or 1.0
        cold = QColor(t["surface"])
        warm = QColor(t["accent"])
        hot = QColor(t["criticalPath"])
        cell = min(viz.width() / cols_s, (viz.height() - 2) / rows_s)
        grid_w, grid_h = cell * cols_s, cell * rows_s
        left = viz.left() + (viz.width() - grid_w) / 2
        top = viz.top() + (viz.height() - grid_h) / 2
        p.setPen(Qt.PenStyle.NoPen)
        for r in range(rows_s):
            src_r = int(r * rows / rows_s)
            for c in range(cols_s):
                src_c = int(c * cols / cols_s)
                idx = src_c * rows + src_r  # column-major (MATLAB layout)
                if idx >= len(info.values):
                    continue
                x = (info.values[idx] - lo) / span
                # two-stop ramp: surface -> accent -> criticalPath for the peaks
                color = _lerp(cold, warm, x * 2) if x < 0.5 else _lerp(warm, hot, x * 2 - 1)
                p.setBrush(color)
                p.drawRect(
                    QRectF(left + c * cell + 0.5, top + r * cell + 0.5, cell - 1.0, cell - 1.0)
                )
