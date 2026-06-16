"""Co-simulation view (CS-1…CS-9, BI-4, DX-1): drive RTL vs the golden model.

Configures and runs a co-simulation off the GUI thread (Verilator/cocotb or the
verilator-native backend), shows PASS/FAIL per output with FX-4 stats, and on a
failure attaches the bisection localization + triage. Results are broadcast so
the Bisection view can render them. Sources are configured like the CLI (the
DUT's dependencies are design-specific).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.workspace import Workspace

_HINT = "Open a MATLAB file and point at its SystemVerilog DUT, then Run."


class _CosimSignals(QObject):
    finished = pyqtSignal(object)  # CosimResult
    failed = pyqtSignal(str)


class _CosimJob(QRunnable):
    def __init__(self, audit: object, kwargs: dict[str, object]) -> None:
        super().__init__()
        self._audit = audit
        self._kwargs = kwargs
        self.signals = _CosimSignals()

    def run(self) -> None:
        from pipeforge.core.cosim.runner import CosimUnavailable, run_cosim

        try:
            result = run_cosim(self._audit, **self._kwargs)  # type: ignore[arg-type]
            self.signals.finished.emit(result)
        except CosimUnavailable as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # never crash the GUI (NF-4)
            self.signals.failed.emit(f"co-simulation error: {exc}")


class CosimView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace

        title = QLabel("Co-simulation")
        title.setObjectName("viewTitle")
        self.summary = QLabel(_HINT)
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)

        self.top_edit = QLineEdit()
        self.top_edit.setPlaceholderText("DUT top module name")
        self.include_edit = QLineEdit()
        self.include_edit.setPlaceholderText("include dir (e.g. matlib-main/rtl)")
        self.sources_edit = QPlainTextEdit()
        self.sources_edit.setPlaceholderText("extra .sv sources, one path per line")
        self.sources_edit.setMaximumHeight(90)
        self.vectors_spin = QSpinBox()
        self.vectors_spin.setRange(1, 100000)
        self.vectors_spin.setValue(128)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["cocotb", "verilator"])
        self.cadence_combo = QComboBox()
        self.cadence_combo.addItems(["continuous", "gapped", "single", "restart"])
        self.bisect_check = QCheckBox("localize + triage on failure")
        self.bisect_check.setChecked(True)

        form = QFormLayout()
        form.addRow("Top module", self.top_edit)
        form.addRow("Include dir", self.include_edit)
        form.addRow("Extra sources", self.sources_edit)
        form.addRow("Vectors", self.vectors_spin)
        form.addRow("Backend", self.backend_combo)
        form.addRow("Cadence", self.cadence_combo)
        form.addRow("", self.bisect_check)

        self.run_btn = QPushButton("Run co-simulation")
        self.run_btn.clicked.connect(self._run)
        self.results = QLabel("")
        self.results.setObjectName("dataValue")
        self.results.setWordWrap(True)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addLayout(form)
        box.addWidget(self.run_btn)
        box.addWidget(self.results, 1)

        workspace.fileChanged.connect(self._on_file)

    def set_theme(self, _theme: Theme) -> None:
        pass

    def _on_file(self, _path: str) -> None:
        if self._ws.m_path and not self.top_edit.text():
            self.top_edit.setText(self._ws.m_path.stem)

    def run_kwargs(self) -> dict[str, object] | None:
        """Assemble run_cosim kwargs from the form (None if not ready)."""
        if self._ws.audit is None or self._ws.sv_path is None:
            self.summary.setText("open a .m and its .sv first")
            return None
        sources = [
            Path(line.strip())
            for line in self.sources_edit.toPlainText().splitlines()
            if line.strip()
        ]
        includes = [Path(self.include_edit.text())] if self.include_edit.text().strip() else []
        # NOTE: never auto-add probe ports to a hand-written DUT — they would not
        # exist on it and the build would fail. Bisection of hand-written RTL
        # uses the VCD-trace fallback (best-effort); probe-based localization is
        # for generated/probe-instrumented RTL.
        work = (self._ws.m_path.parent / "cosim_work") if self._ws.m_path else Path("cosim_work")
        return {
            "dut_sv": self._ws.sv_path,
            "dut_module": self.top_edit.text() or (self._ws.m_path.stem if self._ws.m_path else ""),
            "work_dir": work,
            "extra_sources": sources,
            "include_dirs": includes,
            "vector_count": self.vectors_spin.value(),
            "backend": self.backend_combo.currentText(),
            "cadence": self.cadence_combo.currentText(),
            "bisect_on_failure": self.bisect_check.isChecked(),
        }

    def _run(self) -> None:
        kwargs = self.run_kwargs()
        if kwargs is None:
            return
        self.run_btn.setEnabled(False)
        self.summary.setText("running co-simulation…")
        job = _CosimJob(self._ws.audit, kwargs)
        job.signals.finished.connect(self._on_finished)
        job.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(job)

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.summary.setText(message)

    def _on_finished(self, result: object) -> None:
        self.run_btn.setEnabled(True)
        self.show_result(result)
        self._ws.cosimFinished.emit(result)

    def show_result(self, result: object) -> None:
        """Render a CosimResult (also called directly in tests)."""
        from pipeforge.core.cosim.runner import CosimResult

        if not isinstance(result, CosimResult):
            return
        verdict = "PASS" if result.passed else "FAIL"
        lines = [f"{verdict}  [{result.harness_backend}]"]
        for o in result.outputs:
            if o.passed:
                lines.append(
                    f"  {o.name}: {o.compared} vectors bit-exact — SQNR {o.sqnr_db:.1f} dB"
                )
            else:
                lines.append(
                    f"  {o.name}: first failing vector #{o.first_failure} "
                    f"(expected 0x{o.expected:x}, got 0x{o.actual:x})"
                )
        if result.bisect_report is not None and result.bisect_report.diverged:
            from pipeforge.core.diagnostics.triage import triage

            summary = triage(result.bisect_report, None, self._ws.audit.dag)
            lines.append(f"  triage: {summary.message}")
            lines.append("  (see the Bisection view for the localized stage)")
        self.summary.setText(f"{Path(str(self._ws.sv_path)).name}: {verdict}")
        self.results.setText("\n".join(lines))
