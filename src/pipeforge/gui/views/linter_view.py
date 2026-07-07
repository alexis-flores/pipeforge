"""Linter view (SL-1…SL-6): check a SystemVerilog file's nkMatlib conventions.

Loads the workspace `.sv`, runs the same cost-model-backed checks as the CLI
(delay-match, suffix, valid-chain, reset, naming, unknown-module, SCALE
continuity, and — when a `.m` is also open — the divider-count sanity check),
and shows each finding with its concrete fix.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.svlint.checks import lint_source
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.workspace import Workspace

_HINT = (
    "Open a SystemVerilog file (and optionally its MATLAB source) to check nkMatlib conventions."
)


class LinterView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace

        title = QLabel("Linter")
        title.setObjectName("viewTitle")
        self.summary = QLabel(_HINT)
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.affirmation = QLabel("✓ Clean: no convention violations.")
        self.affirmation.setObjectName("success")
        self.affirmation.hide()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Check", "Line", "Message", "Fix"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        if hh is not None:
            hh.setStretchLastSection(True)

        self.relint_btn = QPushButton("Re-lint")
        self.relint_btn.clicked.connect(self.relint)
        self.open_btn = QPushButton("Open .sv…")
        self.open_btn.setToolTip("Choose the SystemVerilog file to check")
        self.open_btn.clicked.connect(self._open_sv)
        from PyQt6.QtWidgets import QCheckBox

        self.verilator_check = QCheckBox("also run Verilator lint")
        self.verilator_check.setToolTip(
            "Merge `verilator --lint-only -Wall` findings (general SV problems: "
            "width mismatches, latches, UNOPTFLAT) into the table (SL-7)"
        )
        self.verilator_check.toggled.connect(lambda _c: self.relint())
        actions = QHBoxLayout()
        actions.addWidget(self.open_btn)
        actions.addWidget(self.verilator_check)
        actions.addStretch(1)
        actions.addWidget(self.relint_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addWidget(self.affirmation)
        box.addWidget(self.table, 1)
        box.addLayout(actions)

        workspace.fileChanged.connect(lambda _p: self.relint())
        workspace.formatChanged.connect(lambda _w, _s: self.relint())

    def set_theme(self, _theme: Theme) -> None:
        pass

    def _open_sv(self) -> None:
        from pathlib import Path

        fname, _ = QFileDialog.getOpenFileName(
            self, "Open SystemVerilog file", "", "SystemVerilog (*.sv)"
        )
        if fname:
            self._ws.open_file(Path(fname))  # emits fileChanged → relint

    def relint(self) -> None:
        sv_path = self._ws.sv_path
        if sv_path is None or not sv_path.is_file():
            self.summary.setText(_HINT)
            self.affirmation.hide()
            self.table.setRowCount(0)
            return
        try:
            text = sv_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.summary.setText(f"cannot read {sv_path.name}: {exc}")
            return
        # the divider-count check (SL-6) needs the optimized DAG from the .m
        result = lint_source(text, sv_path.name, self._ws.cost_model, audit=self._ws.audit)
        if self.verilator_check.isChecked():
            from pipeforge.core.svlint.verilator import VerilatorUnavailable, verilator_lint
            from pipeforge.gui.detect import detect_matlib_rtl

            include = detect_matlib_rtl(sv_path)
            try:
                result.findings.extend(
                    verilator_lint(
                        sv_path,
                        include_dirs=[include] if include else [],
                        width=self._ws.width,
                        scale=self._ws.scale,
                    )
                )
            except VerilatorUnavailable as exc:
                self._ws.problem.emit(str(exc))
        self.summary.setText(
            f"{sv_path.name} — backend: {result.backend}, module: {result.module or '?'} — "
            f"{len(result.findings)} finding(s)"
        )
        self.affirmation.setVisible(not result.findings)
        self.table.setRowCount(len(result.findings))
        for r, f in enumerate(result.findings):
            for c, text in enumerate((f.check, str(f.line or ""), f.message, f.fix)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
