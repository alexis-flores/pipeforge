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
        self.axis_btn = QPushButton("Save AXI-S wrapper…")
        self.axis_btn.setToolTip(
            "tvalid/tready wrapper with credit-based backpressure — drops into "
            "Vivado block designs (the nkMatlib core itself cannot stall)"
        )
        self.axis_btn.clicked.connect(self._save_axis)
        self.axis_btn.setEnabled(False)
        self.synth_btn = QPushButton("Synth estimate (yosys)")
        self.synth_btn.setToolTip(
            "Quick generic-yosys synthesis: cell counts + logic depth — a "
            "sanity check, not a vendor result"
        )
        self.synth_btn.clicked.connect(self._synth)
        self.synth_btn.setEnabled(False)
        self.synth_label = QLabel("")
        self.synth_label.setObjectName("muted")
        self.synth_label.setWordWrap(True)
        actions = QHBoxLayout()
        actions.addWidget(self.synth_btn)
        actions.addStretch(1)
        actions.addWidget(self.axis_btn)
        actions.addWidget(self.save_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addWidget(self.source, 1)
        box.addWidget(self.synth_label)
        box.addLayout(actions)

        workspace.auditChanged.connect(self._on_audit)

    def set_theme(self, theme: Theme) -> None:
        self.source.set_theme(theme)

    def _module_name(self) -> str:
        return self._ws.m_path.stem if self._ws.m_path else "generated"

    def _on_audit(self, audit: object) -> None:
        self.synth_label.setText("")
        if not isinstance(audit, Audit):
            self._sv = ""
            self.source.setPlainText("")
            self.summary.setText(_HINT)
            self.save_btn.setEnabled(False)
            self.axis_btn.setEnabled(False)
            self.synth_btn.setEnabled(False)
            return
        try:
            self._sv = generate_sv(audit, self._module_name())
        except CodegenError as exc:
            self._sv = ""
            self.source.setPlainText("")
            self.summary.setText(f"cannot generate: {exc}")
            self.save_btn.setEnabled(False)
            self.axis_btn.setEnabled(False)
            self.synth_btn.setEnabled(False)
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
        self.axis_btn.setEnabled(True)
        self.synth_btn.setEnabled(True)

    def _save_axis(self) -> None:
        """Emit the AXI-Stream wrapper next to the generated module (AX-1)."""
        audit = self._ws.audit
        if audit is None:
            return
        from pipeforge.core.codegen.axis import generate_axis_wrapper

        try:
            wrapper = generate_axis_wrapper(audit, self._module_name())
        except ValueError as exc:
            self.summary.setText(f"cannot wrap: {exc}")
            return
        default = str(
            (self._ws.m_path or Path("generated.m")).with_name(f"{self._module_name()}_axis.sv")
        )
        fname, _ = QFileDialog.getSaveFileName(self, "Save AXI-S wrapper", default, "*.sv")
        if fname:
            Path(fname).write_text(wrapper, encoding="utf-8")
            self.summary.setText(f"wrote {fname} (instantiate it next to {self._module_name()})")
            self._ws.log_activity(
                "success",
                f"AXI-Stream wrapper → {Path(fname).name}",
                "tvalid/tready with credit backpressure — drops into block designs",
                fname,
            )
            self._ws.toast("success", f"Wrote {Path(fname).name}")

    def _synth(self) -> None:
        """Run the yosys estimate off the GUI thread (SY-1)."""
        if not self._sv:
            return
        from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

        from pipeforge.gui.detect import detect_matlib_rtl

        sv_text = self._sv
        top = self._module_name()
        include = detect_matlib_rtl(self._ws.m_path)

        class _Signals(QObject):
            done = pyqtSignal(str)

        class _SynthJob(QRunnable):
            def __init__(self) -> None:
                super().__init__()
                self.signals = _Signals()

            def run(self) -> None:
                import tempfile
                from pathlib import Path as _P

                from pipeforge.core.synth.estimate import SynthUnavailable, run_synth_estimate

                try:
                    with tempfile.TemporaryDirectory(prefix="pipeforge_synth_") as tmp:
                        src = _P(tmp) / f"{top}.sv"
                        src.write_text(sv_text, encoding="utf-8")
                        est = run_synth_estimate(
                            [src], top, include_dirs=[include] if include else []
                        )
                    self.signals.done.emit(f"synth estimate: {est.summary()}")
                except SynthUnavailable as exc:
                    self.signals.done.emit(str(exc).splitlines()[0] + " (see console)")

        self.synth_btn.setEnabled(False)
        self.synth_label.setText("running yosys…")
        self._synth_job = _SynthJob()  # keep a ref: queued signal delivery (NF-4)
        self._synth_job.signals.done.connect(self._on_synth)
        QThreadPool.globalInstance().start(self._synth_job)

    def _on_synth(self, message: str) -> None:
        self.synth_btn.setEnabled(True)
        self.synth_label.setText(message)
        kind = "success" if message.startswith("synth estimate") else "warning"
        self._ws.log_activity(kind, f"Synth estimate — {self._module_name()}", message)

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
            audit = self._ws.audit
            detail = (
                f"{audit.total_latency} cycles, {sum(audit.census.values())} instances"
                if audit is not None
                else ""
            )
            self._ws.log_activity("success", f"Generated → {Path(fname).name}", detail, fname)
            self._ws.toast("success", f"Wrote {Path(fname).name} — lint it or co-simulate next")
