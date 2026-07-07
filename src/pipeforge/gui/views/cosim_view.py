"""Co-simulation view (CS-1…CS-9, BI-4, DX-1): drive RTL vs the golden model.

Configures and runs a co-simulation off the GUI thread (Verilator/cocotb or the
verilator-native backend), shows PASS/FAIL per output with FX-4 stats, and on a
failure attaches the bisection localization + triage. Results are broadcast so
the Bisection view can render them. Sources are configured like the CLI (the
DUT's dependencies are design-specific), with file pickers and a readiness
line so nothing has to be typed from memory.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
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

#: Plain-language help for the not-self-explanatory options.
BACKEND_HINTS = {
    "auto": "cocotb when installed, else the cocotb-free Verilator-native harness",
    "cocotb": "cocotb testbench under Verilator — needs pip install cocotb",
    "verilator": "native Verilator harness — no cocotb needed, only Verilator",
}
CADENCE_HINTS = {
    "continuous": "a new vector every clock (throughput = 1/clock, the nkMatlib contract)",
    "gapped": "idle cycles between vectors — catches valid-chain bugs masked by back-pressure",
    "single": "one vector at a time, wait for it to drain — simplest to eyeball in a trace",
    "restart": "reset between vectors — catches state that leaks across resets",
}


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
        # readiness at a glance: which of the two inputs are in place
        self.reqs = QLabel()
        self.reqs.setObjectName("muted")
        self.reqs.setWordWrap(True)

        self.dut_edit = QLineEdit()
        self.dut_edit.setPlaceholderText("path to the DUT .sv (auto-filled from the open file)")
        self.dut_edit.editingFinished.connect(self._dut_edited)
        dut_browse = QPushButton("Browse…")
        dut_browse.clicked.connect(self._browse_dut)
        dut_row = QHBoxLayout()
        dut_row.addWidget(self.dut_edit, 1)
        dut_row.addWidget(dut_browse)

        self.top_edit = QLineEdit()
        self.top_edit.setPlaceholderText("DUT top module name")
        self.include_edit = QLineEdit()
        self.include_edit.setPlaceholderText("directory of nkMatlib .sv sources")
        include_browse = QPushButton("Browse…")
        include_browse.clicked.connect(self._browse_include)
        include_row = QHBoxLayout()
        include_row.addWidget(self.include_edit, 1)
        include_row.addWidget(include_browse)

        self.sources_edit = QPlainTextEdit()
        self.sources_edit.setPlaceholderText("extra .sv sources, one path per line")
        self.sources_edit.setMaximumHeight(72)
        sources_add = QPushButton("Add…")
        sources_add.clicked.connect(self._add_sources)
        sources_row = QHBoxLayout()
        sources_row.addWidget(self.sources_edit, 1)
        sources_row.addWidget(sources_add, 0)

        self.vectors_spin = QSpinBox()
        self.vectors_spin.setRange(1, 100000)
        self.vectors_spin.setValue(128)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["auto", "cocotb", "verilator"])
        self.backend_hint = QLabel(BACKEND_HINTS["auto"])
        self.backend_hint.setObjectName("muted")
        self.backend_combo.currentTextChanged.connect(
            lambda t: self.backend_hint.setText(BACKEND_HINTS.get(t, ""))
        )
        self.cadence_combo = QComboBox()
        self.cadence_combo.addItems(["continuous", "gapped", "single", "restart"])
        self.cadence_hint = QLabel(CADENCE_HINTS["continuous"])
        self.cadence_hint.setObjectName("muted")
        self.cadence_hint.setWordWrap(True)
        self.cadence_combo.currentTextChanged.connect(
            lambda t: self.cadence_hint.setText(CADENCE_HINTS.get(t, ""))
        )
        self.bisect_check = QCheckBox("localize + triage on failure")
        self.bisect_check.setChecked(True)
        self.bisect_check.setToolTip(
            "On a mismatch, bisect to the first divergent pipeline stage "
            "and classify it (wrong math vs delay skew) — see the Bisection view"
        )

        form = QFormLayout()
        form.addRow("DUT .sv", dut_row)
        form.addRow("Top module", self.top_edit)
        form.addRow("Include dir", include_row)
        form.addRow("Extra sources", sources_row)
        form.addRow("Vectors", self.vectors_spin)
        form.addRow("Backend", self.backend_combo)
        form.addRow("", self.backend_hint)
        form.addRow("Cadence", self.cadence_combo)
        form.addRow("", self.cadence_hint)
        form.addRow("", self.bisect_check)

        self.run_btn = QPushButton("Run co-simulation")
        self.run_btn.clicked.connect(self._run)
        self.results = QLabel("")
        self.results.setObjectName("dataValue")
        self.results.setWordWrap(True)

        # elapsed feedback while the build+run is in flight (can take a while)
        self._elapsed = QTimer(self)
        self._elapsed.setInterval(1000)
        self._elapsed.timeout.connect(self._tick)
        self._started = 0.0

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addWidget(self.reqs)
        box.addLayout(form)
        box.addWidget(self.run_btn)
        box.addWidget(self.results, 1)

        workspace.fileChanged.connect(self._on_file)
        self._sync_reqs()

    def set_theme(self, _theme: Theme) -> None:
        pass

    # -- input plumbing ---------------------------------------------------------

    def _on_file(self, _path: str) -> None:
        self._apply_project()
        if self._ws.m_path and not self.top_edit.text():
            self.top_edit.setText(self._ws.m_path.stem)
        if self._ws.sv_path is not None:
            self.dut_edit.setText(str(self._ws.sv_path))
        if not self.include_edit.text():
            detected = self._detect_include()
            if detected is not None:
                self.include_edit.setText(str(detected))
        self._sync_reqs()

    def _apply_project(self) -> None:
        """Restore the sidecar's cosim config (PJ-1)."""
        from pipeforge.core.project import Project

        project = self._ws.project
        if not isinstance(project, Project) or self._ws.m_path is None:
            return
        cfg = project.cosim
        base = self._ws.m_path.parent
        if cfg.top:
            self.top_edit.setText(cfg.top)
        if cfg.backend in BACKEND_HINTS:
            self.backend_combo.setCurrentText(cfg.backend)
        if cfg.cadence:
            self.cadence_combo.setCurrentText(cfg.cadence)
        if cfg.vectors:
            self.vectors_spin.setValue(cfg.vectors)
        if cfg.include:
            self.include_edit.setText(str((base / cfg.include[0]).resolve()))
        if cfg.sources:
            self.sources_edit.setPlainText(
                "\n".join(str((base / s).resolve()) for s in cfg.sources)
            )

    def _store_project(self) -> None:
        """Persist the cosim config into the sidecar (PJ-1)."""
        import os

        from pipeforge.core.project import Project

        project = self._ws.project
        if not isinstance(project, Project) or self._ws.m_path is None:
            return
        base = self._ws.m_path.parent
        cfg = project.cosim
        cfg.top = self.top_edit.text()
        cfg.backend = self.backend_combo.currentText()
        cfg.cadence = self.cadence_combo.currentText()
        cfg.vectors = self.vectors_spin.value()
        include = self.include_edit.text().strip()
        cfg.include = [os.path.relpath(include, base)] if include else []
        cfg.sources = [
            os.path.relpath(line.strip(), base)
            for line in self.sources_edit.toPlainText().splitlines()
            if line.strip()
        ]
        self._ws.save_sidecar(create=True)

    def _detect_include(self) -> Path | None:
        """Walk up from the open .m looking for a bundled nkMatlib rtl dir."""
        from pipeforge.gui.detect import detect_matlib_rtl

        return detect_matlib_rtl(self._ws.m_path or self._ws.sv_path)

    def _browse_dut(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self, "Choose the DUT SystemVerilog file", "", "SystemVerilog (*.sv)"
        )
        if fname:
            self.dut_edit.setText(fname)
            self._dut_edited()

    def _dut_edited(self) -> None:
        text = self.dut_edit.text().strip()
        if text and Path(text).is_file():
            # route through the workspace so the Linter (and recents) see it too
            self._ws.open_file(Path(text))
            if not self.top_edit.text():
                self.top_edit.setText(Path(text).stem)
        self._sync_reqs()

    def _browse_include(self) -> None:
        dirname = QFileDialog.getExistingDirectory(self, "nkMatlib source directory")
        if dirname:
            self.include_edit.setText(dirname)

    def _add_sources(self) -> None:
        fnames, _ = QFileDialog.getOpenFileNames(
            self, "Extra SystemVerilog sources", "", "SystemVerilog (*.sv *.svh *.v)"
        )
        if not fnames:
            return
        existing = self.sources_edit.toPlainText().rstrip()
        joined = "\n".join(fnames)
        self.sources_edit.setPlainText(f"{existing}\n{joined}" if existing else joined)

    def _sync_reqs(self) -> None:
        m = self._ws.m_path
        sv = self._ws.sv_path
        m_part = f"✓ {m.name}" if m else "✗ no MATLAB source — open a .m first (Ctrl+O)"
        sv_part = f"✓ {sv.name}" if sv else "✗ no DUT — Browse to your .sv"
        self.reqs.setText(f"{m_part}    ·    {sv_part}")
        self.run_btn.setEnabled(m is not None and sv is not None)

    # -- running ---------------------------------------------------------------

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
        backend = self.backend_combo.currentText()
        return {
            "dut_sv": self._ws.sv_path,
            "dut_module": self.top_edit.text() or (self._ws.m_path.stem if self._ws.m_path else ""),
            "work_dir": work,
            "extra_sources": sources,
            "include_dirs": includes,
            "vector_count": self.vectors_spin.value(),
            "backend": None if backend == "auto" else backend,
            "cadence": self.cadence_combo.currentText(),
            "bisect_on_failure": self.bisect_check.isChecked(),
        }

    def _run(self) -> None:
        kwargs = self.run_kwargs()
        if kwargs is None:
            return
        self._store_project()  # a real run is worth remembering (PJ-1)
        import time

        self.run_btn.setEnabled(False)
        self._started = time.monotonic()
        self._elapsed.start()
        self.summary.setText("running co-simulation… 0s")
        job = _CosimJob(self._ws.audit, kwargs)
        job.signals.finished.connect(self._on_finished)
        job.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(job)

    def _tick(self) -> None:
        import time

        elapsed = int(time.monotonic() - self._started)
        self.summary.setText(
            f"running co-simulation… {elapsed}s (Verilator build + "
            f"{self.vectors_spin.value()} vectors)"
        )

    def _on_failed(self, message: str) -> None:
        self._elapsed.stop()
        self.run_btn.setEnabled(True)
        self.summary.setText(message)
        self._sync_reqs()

    def _on_finished(self, result: object) -> None:
        self._elapsed.stop()
        self.run_btn.setEnabled(True)
        self.show_result(result)
        self._ws.cosimFinished.emit(result)
        self._sync_reqs()

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
        if result.failure_file:
            lines.append(f"  replay file: {result.failure_file}")
        if result.gtkw_file:
            lines.append("  waveform ready — open it from the Bisection view (GTKWave)")
        self.summary.setText(f"{Path(str(self._ws.sv_path)).name}: {verdict}")
        self.results.setText("\n".join(lines))
