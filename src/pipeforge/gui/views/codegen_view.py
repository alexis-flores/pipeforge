"""Codegen view (CG-1…CG-4): generate an nkMatlib SV module from the MATLAB.

Generates deterministically from the open `.m`, shows the SystemVerilog with a
clean-lint badge (generated code passes PipeForge's own linter), and writes it
to disk. Opaque constructs raise a clear, line-numbered error instead of
guessing.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.audit.engine import Audit
from pipeforge.core.codegen.emitter import CodegenError, generate_sv
from pipeforge.core.svlint.checks import lint_source
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.widgets.source_view import SourceView
from pipeforge.gui.workspace import Workspace

_HINT = "Open a MATLAB file to generate its nkMatlib SystemVerilog module."


class CodegenView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self._sv = ""

        title = QLabel("Codegen")
        title.setObjectName("viewTitle")
        self.summary = QLabel(_HINT)
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.source = SourceView()
        self.source.setReadOnly(True)

        self.save_btn = QPushButton("Save .sv…")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.save_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addWidget(self.source, 1)
        box.addLayout(actions)

        workspace.auditChanged.connect(self._on_audit)

    def set_theme(self, theme: Theme) -> None:
        self.source.set_theme(theme)

    def _module_name(self) -> str:
        return self._ws.m_path.stem if self._ws.m_path else "generated"

    def _on_audit(self, audit: object) -> None:
        if not isinstance(audit, Audit):
            self._sv = ""
            self.source.setPlainText("")
            self.summary.setText(_HINT)
            self.save_btn.setEnabled(False)
            return
        try:
            self._sv = generate_sv(audit, self._module_name())
        except CodegenError as exc:
            self._sv = ""
            self.source.setPlainText("")
            self.summary.setText(f"cannot generate: {exc}")
            self.save_btn.setEnabled(False)
            return
        self.source.setPlainText(self._sv)
        result = lint_source(self._sv, f"{self._module_name()}.sv", self._ws.cost_model)
        badge = (
            "lints clean ✓" if not result.findings else f"{len(result.findings)} lint finding(s)"
        )
        self.summary.setText(
            f"{self._module_name()}.sv — {audit.total_latency} cycles, "
            f"{sum(audit.census.values())} instances — {badge}"
        )
        self.save_btn.setEnabled(True)

    def _save(self) -> None:
        if not self._sv:
            return
        default = str((self._ws.m_path or Path("generated.m")).with_suffix(".sv"))
        fname, _ = QFileDialog.getSaveFileName(
            self, "Save generated SystemVerilog", default, "*.sv"
        )
        if fname:
            Path(fname).write_text(self._sv, encoding="utf-8")
            self.summary.setText(f"wrote {fname}")
