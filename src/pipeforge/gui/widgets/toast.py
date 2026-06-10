"""Non-modal toast for problems (NF-4): state what happened, never block."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QWidget


class Toast(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, msec: int = 5000) -> None:
        self.setText(text)
        parent = self.parentWidget()
        if parent is not None:
            width = min(parent.width() - 40, 560)
            self.setFixedWidth(max(width, 200))
            self.adjustSize()
            self.move(
                (parent.width() - self.width()) // 2,
                parent.height() - self.height() - 24,
            )
        self.show()
        self.raise_()
        self._timer.start(msec)
