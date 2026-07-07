"""WIDTH/SCALE editor popover, opened from the status-bar format chip (UI-2)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pipeforge.gui.workspace import Workspace


class FormatDialog(QDialog):
    """Edits the workspace fixed-point format live; every view reacts."""

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fixed-point format")
        self._ws = workspace

        self.width_spin = QSpinBox()
        self.width_spin.setRange(4, 64)
        self.width_spin.setValue(workspace.width)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(0, 63)
        self.scale_spin.setValue(workspace.scale)
        self.width_spin.valueChanged.connect(self._apply)
        self.scale_spin.valueChanged.connect(self._apply)

        self.left_label = QLabel()
        self.left_label.setObjectName("muted")
        self._sync_left()

        explain = QLabel(
            "WIDTH = total bits, SCALE = fraction bits, LEFT = WIDTH - SCALE "
            "(integer bits incl. sign). Changes apply immediately to every view; "
            "divider and sqrt latencies depend on it."
        )
        explain.setObjectName("muted")
        explain.setWordWrap(True)

        form = QFormLayout()
        form.addRow("WIDTH (total bits)", self.width_spin)
        form.addRow("SCALE (fraction bits)", self.scale_spin)
        form.addRow("", self.left_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        box = QVBoxLayout(self)
        box.addWidget(explain)
        box.addLayout(form)
        box.addWidget(buttons)

        workspace.formatChanged.connect(self._sync)

    def _apply(self, _v: int) -> None:
        self._ws.set_format(self.width_spin.value(), self.scale_spin.value())
        self._sync_left()

    def _sync(self, width: int, scale: int) -> None:
        self.width_spin.blockSignals(True)
        self.scale_spin.blockSignals(True)
        self.width_spin.setValue(width)
        self.scale_spin.setValue(scale)
        self.width_spin.blockSignals(False)
        self.scale_spin.blockSignals(False)
        self._sync_left()

    def _sync_left(self) -> None:
        left = self.width_spin.value() - self.scale_spin.value()
        self.left_label.setText(f"LEFT = {left} integer bit(s) incl. sign")
