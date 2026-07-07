"""Audit view (AU-4 GUI): timeline + findings + summary, selection-synced."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.audit.engine import Audit
from pipeforge.core.audit.findings import Finding
from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.widgets.findings_table import FindingsTable
from pipeforge.gui.widgets.timeline import TimelineWidget
from pipeforge.gui.workspace import Workspace


class AuditView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace

        title = QLabel("Audit")
        title.setObjectName("viewTitle")
        self._summary = QLabel("Open a MATLAB file to audit its pipeline latency.")
        self._summary.setObjectName("muted")
        self._summary.setWordWrap(True)

        self.timeline = TimelineWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline)
        scroll.setMinimumHeight(180)

        self.findings = FindingsTable()
        self.findings.findingActivated.connect(self._on_finding)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(scroll)
        split.addWidget(self.findings)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self._summary)
        box.addWidget(split, 1)

        # UI-9: apply the session density to this view's timeline
        self.timeline.set_density(getattr(workspace, "density", "comfortable"))

        workspace.auditChanged.connect(self._on_audit)
        workspace.selectionChanged.connect(self.timeline.set_selected)
        self.timeline.nodeClicked.connect(workspace.select_node)
        if hasattr(workspace, "densityChanged"):
            workspace.densityChanged.connect(self.timeline.set_density)

    def set_theme(self, theme: Theme) -> None:
        self.timeline.set_theme(theme)

    def _on_audit(self, audit: object) -> None:
        if not isinstance(audit, Audit):
            self.timeline.set_layout(None)
            self.findings.set_findings([], audited=False)
            self._summary.setText("Open a MATLAB file to audit its pipeline latency.")
            return
        self.timeline.set_layout(layout_for_audit(audit))
        self.findings.set_findings(audit.findings, audited=True)
        census = audit.census
        text = (
            f"{audit.filename} — {audit.total_latency} cycles critical path, "
            f"{sum(census.values())} operator instances, {audit.divider_count} dividers, "
            f"{len(audit.findings)} findings, {len(audit.skipped)} skipped statements."
        )
        from pipeforge.core.costmodel.resources import estimate_resources

        est = estimate_resources(census, audit.cm)
        text += f"  Resources: {est.summary()}."
        savings = sum(f.savings for f in audit.findings)
        if savings > 0:
            text += (
                f"  Next: the Rewrite column shows how to reclaim up to {savings} cycles; "
                "Codegen (Ctrl+4) writes the SystemVerilog skeleton."
            )
        elif audit.findings:
            text += "  Next: Codegen (Ctrl+4) writes the SystemVerilog skeleton."
        self._summary.setText(text)

    def _on_finding(self, finding: object) -> None:
        if isinstance(finding, Finding) and finding.node:
            # VZ-2a: a visible coupling cue to the timeline bar, plus selection
            # (which highlights the source line) — not merely independent recolor
            self.timeline.flash(finding.node)
            self._ws.select_node(finding.node)
