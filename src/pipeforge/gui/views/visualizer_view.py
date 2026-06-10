"""Visualizer view (VZ-1, VZ-3): full DAG timeline + SVG/PNG export."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.audit.engine import Audit
from pipeforge.core.viz.layout import Layout, dot_available, layout_for_audit
from pipeforge.core.viz.svg import SvgPalette, render_svg
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.widgets.timeline import TimelineWidget
from pipeforge.gui.workspace import Workspace


class VisualizerView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self._theme: Theme | None = None
        self._layout_data: Layout | None = None

        title = QLabel("Visualizer")
        title.setObjectName("viewTitle")
        self._engine = QLabel()
        self._engine.setObjectName("muted")

        export_svg = QPushButton("Export SVG")
        export_svg.clicked.connect(self._export_svg)
        export_png = QPushButton("Export PNG")
        export_png.clicked.connect(self._export_png)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(export_svg)
        header.addWidget(export_png)

        self.timeline = TimelineWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addLayout(header)
        box.addWidget(self._engine)
        box.addWidget(scroll, 1)

        workspace.auditChanged.connect(self._on_audit)
        workspace.selectionChanged.connect(self.timeline.set_selected)
        self.timeline.nodeClicked.connect(workspace.select_node)
        self._on_audit(None)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.timeline.set_theme(theme)

    def _on_audit(self, audit: object) -> None:
        if not isinstance(audit, Audit):
            self._layout_data = None
            self.timeline.set_layout(None)
            self._engine.setText(
                "Layout engine: " + ("graphviz dot" if dot_available() else "built-in layered")
            )
            return
        self._layout_data = layout_for_audit(audit, refine_with_dot=True)
        self.timeline.set_layout(self._layout_data)
        self._engine.setText(
            "Layout engine: " + ("graphviz dot" if dot_available() else "built-in layered")
        )

    def _palette(self) -> SvgPalette | None:
        if self._theme is None:
            return None
        t = self._theme
        return SvgPalette(
            bg=t["bg"],
            box=t["surface"],
            box_border=t["border"],
            text=t["textPrimary"],
            critical=t["criticalPath"],
            divider=t["divider"],
            edge=t["border"],
            ruler=t["surfaceElevated"],
        )

    def export_svg_to(self, path: Path) -> bool:
        palette = self._palette()
        if self._layout_data is None or palette is None:
            return False
        name = self._ws.m_path.name if self._ws.m_path else "pipeline"
        path.write_text(render_svg(self._layout_data, palette, title=name), encoding="utf-8")
        return True

    def export_png_to(self, path: Path) -> bool:
        if self._layout_data is None:
            return False
        pixmap = self.timeline.grab()
        return pixmap.save(str(path), "PNG")

    def _export_svg(self) -> None:
        fname, _ = QFileDialog.getSaveFileName(self, "Export SVG", "pipeline.svg", "SVG (*.svg)")
        if fname:
            self.export_svg_to(Path(fname))

    def _export_png(self) -> None:
        fname, _ = QFileDialog.getSaveFileName(self, "Export PNG", "pipeline.png", "PNG (*.png)")
        if fname:
            self.export_png_to(Path(fname))
