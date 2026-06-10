"""Settings view: theme, fixed-point format, external tools (TH-4, UI-2, App. B)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.workspace import Workspace
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
