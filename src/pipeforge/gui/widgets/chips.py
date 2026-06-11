"""Clickable status-bar chip with semantic states (idle/busy/fresh/stale)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel, QWidget


class ClickableChip(QLabel):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, state: str) -> None:
        """state: '' (neutral) | 'busy' | 'warn' — drives the QSS objectName."""
        name = {"busy": "chipBusy", "warn": "chipWarn"}.get(state, "chip")
        if self.objectName() != name:
            self.setObjectName(name)
            style = self.style()
            if style is not None:  # re-polish so the QSS selector re-applies
                style.unpolish(self)
                style.polish(self)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
