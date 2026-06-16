"""Bisection view (BI-1…BI-4): show where RTL diverged from the golden model.

Consumes the most recent co-simulation result: matched stages glow green, the
first divergent stage red, everything downstream dims, and the classification
(wrong-math vs delay-skew) is spelled out.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from pipeforge.core.viz.layout import layout_for_audit
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.widgets.timeline import TimelineWidget
from pipeforge.gui.workspace import Workspace

_HINT = (
    "Run a co-simulation with localization enabled; when RTL and the model "
    "disagree, the first divergent pipeline stage is shown here."
)


class BisectionView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace

        title = QLabel("Bisection")
        title.setObjectName("viewTitle")
        self.summary = QLabel(_HINT)
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.timeline = TimelineWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addWidget(scroll, 1)

        workspace.cosimFinished.connect(self.show_result)
        workspace.selectionChanged.connect(self.timeline.set_selected)
        self.timeline.nodeClicked.connect(workspace.select_node)

    def set_theme(self, theme: Theme) -> None:
        self.timeline.set_theme(theme)

    def show_result(self, result: object) -> None:
        from pipeforge.core.cosim.runner import CosimResult

        audit = self._ws.audit
        if not isinstance(result, CosimResult) or audit is None:
            return
        self.timeline.set_layout(layout_for_audit(audit))
        report = result.bisect_report
        if report is None or not report.diverged:
            self.timeline.set_bisection({}, frozenset())
            self.summary.setText(
                "No divergence localized — co-simulation passed, or it was run "
                "without localization / captured intermediates."
            )
            return
        status = {v.nid: v.status for v in report.verdicts if v.status in ("ok", "bad")}
        dimmed = report.downstream_of_divergence(audit.dag)
        self.timeline.set_bisection(status, dimmed)
        self.summary.setText(report.message)
