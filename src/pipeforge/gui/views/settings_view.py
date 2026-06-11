"""Settings view: theme, fixed-point format, external tools (TH-4, UI-2, App. B)."""

from __future__ import annotations

import shlex
from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace
from pipeforge.services.matlab_bridge import MatlabConfig
from pipeforge.services.tools import detect_tools


class SettingsView(QWidget):
    def __init__(
        self,
        workspace: Workspace,
        themes: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self._themes = themes

        title = QLabel("Settings")
        title.setObjectName("viewTitle")

        self.theme_combo = QComboBox()
        self._reload_theme_list()
        self.theme_combo.currentTextChanged.connect(self._on_theme)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(4, 64)
        self.width_spin.setValue(workspace.width)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(0, 63)
        self.scale_spin.setValue(workspace.scale)
        self.width_spin.valueChanged.connect(self._on_format)
        self.scale_spin.valueChanged.connect(self._on_format)

        form = QFormLayout()
        form.addRow("Theme", self.theme_combo)
        form.addRow("WIDTH (total bits)", self.width_spin)
        form.addRow("SCALE (fraction bits)", self.scale_spin)

        # MATLAB bridge: command template + per-project workspace setup
        matlab_cfg = MatlabConfig.load()
        self.matlab_command_edit = QLineEdit(shlex.join(matlab_cfg.command))
        self.matlab_command_edit.setPlaceholderText(
            f"auto-detected ({matlab_cfg.source}); edit to override"
        )
        self.matlab_command_edit.editingFinished.connect(self._save_matlab)
        self.matlab_detect_btn = QPushButton("Detect")
        self.matlab_detect_btn.setToolTip(
            "Try env/PATH/standard installs/distrobox until one answers, then save it"
        )
        self.matlab_detect_btn.clicked.connect(self._detect_matlab)
        command_row = QHBoxLayout()
        command_row.addWidget(self.matlab_command_edit, 1)
        command_row.addWidget(self.matlab_detect_btn)
        self.matlab_setup_edit = QLineEdit(str(matlab_cfg.setup) if matlab_cfg.setup else "")
        self.matlab_setup_edit.setPlaceholderText("setup .m to run or .mat to load (optional)")
        self.matlab_setup_edit.editingFinished.connect(self._save_matlab)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_setup)
        setup_row = QHBoxLayout()
        setup_row.addWidget(self.matlab_setup_edit, 1)
        setup_row.addWidget(browse)
        form.addRow("MATLAB command", command_row)
        form.addRow("MATLAB setup", setup_row)

        tools_title = QLabel("External tools")
        tools_title.setObjectName("sectionTitle")
        self.tools_label = QLabel()
        self.tools_label.setObjectName("muted")
        self.tools_label.setWordWrap(True)
        self.refresh_tools()

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(16)
        box.addWidget(title)
        box.addLayout(form)
        box.addWidget(tools_title)
        box.addWidget(self.tools_label)
        box.addStretch(1)

        workspace.formatChanged.connect(self._sync_format)

    def _reload_theme_list(self) -> None:
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        for name, display in self._themes.available().items():
            self.theme_combo.addItem(display, userData=name)
        idx = self.theme_combo.findData(self._themes.current_name)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)

    def _on_theme(self, _display: str) -> None:
        name = self.theme_combo.currentData()
        if isinstance(name, str) and name:
            self._themes.apply(name)
            self._themes.save()

    def _on_format(self, _v: int) -> None:
        self._ws.set_format(self.width_spin.value(), self.scale_spin.value())

    def _sync_format(self, width: int, scale: int) -> None:
        self.width_spin.blockSignals(True)
        self.scale_spin.blockSignals(True)
        self.width_spin.setValue(width)
        self.scale_spin.setValue(scale)
        self.width_spin.blockSignals(False)
        self.scale_spin.blockSignals(False)

    def _save_matlab(self) -> None:
        try:
            command = shlex.split(self.matlab_command_edit.text())
        except ValueError:
            self._ws.problem.emit("MATLAB command has unbalanced quotes; not saved.")
            return
        if not command:
            self._ws.problem.emit("MATLAB command cannot be empty; not saved.")
            return
        setup_text = self.matlab_setup_edit.text().strip()
        cfg = MatlabConfig(command=command, setup=Path(setup_text) if setup_text else None)
        cfg.save()

    def _detect_matlab(self) -> None:
        """Probe candidates off the GUI thread (UI-3); fill + save on success."""
        from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

        class _Signals(QObject):
            found = pyqtSignal(object, str)  # MatlabConfig, version
            failed = pyqtSignal(str)

        class _DetectJob(QRunnable):
            def __init__(self) -> None:
                super().__init__()
                self.signals = _Signals()

            def run(self) -> None:
                from pipeforge.services.matlab_bridge import (
                    MatlabUnavailable,
                    detect_and_save,
                )

                try:
                    cfg, version = detect_and_save()
                    self.signals.found.emit(cfg, version)
                except MatlabUnavailable as exc:
                    self.signals.failed.emit(str(exc))

        self.matlab_detect_btn.setEnabled(False)
        self.matlab_detect_btn.setText("Detecting…")
        job = _DetectJob()
        job.signals.found.connect(self._on_detected)
        job.signals.failed.connect(self._on_detect_failed)
        QThreadPool.globalInstance().start(job)

    def _on_detected(self, cfg: object, version: str) -> None:
        self.matlab_detect_btn.setEnabled(True)
        self.matlab_detect_btn.setText("Detect")
        if isinstance(cfg, MatlabConfig):
            self.matlab_command_edit.setText(shlex.join(cfg.command))
            self._ws.logMessage.emit(
                f"matlab: detected via {cfg.source} — {version} (saved to settings)"
            )

    def _on_detect_failed(self, message: str) -> None:
        self.matlab_detect_btn.setEnabled(True)
        self.matlab_detect_btn.setText("Detect")
        self._ws.problem.emit(message.splitlines()[0])
        self._ws.logMessage.emit(message)

    def _browse_setup(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self, "Workspace setup", "", "MATLAB setup (*.m *.mat)"
        )
        if fname:
            self.matlab_setup_edit.setText(fname)
            self._save_matlab()

    def refresh_tools(self) -> None:
        lines = []
        for status in detect_tools().values():
            if status.available:
                lines.append(f"● {status.name} — {status.feature} ({status.version})")
            else:
                lines.append(
                    f"○ {status.name} — {status.feature} unavailable. "
                    f"Install: {status.install_hint}"
                )
        self.tools_label.setText("\n".join(lines))
