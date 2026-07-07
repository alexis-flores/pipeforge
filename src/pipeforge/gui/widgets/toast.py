"""Non-modal toast for problems (NF-4): state what happened, never block.

A toast may carry a details action (e.g. open the console); clicking the
toast triggers it. Plain toasts just dismiss on click.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel, QWidget


class Toast(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.hide()
        self._on_click: Callable[[], None] | None = None
        self._raw = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(
        self,
        text: str,
        msec: int = 5000,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self._raw = text
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(f"{text} — click for details" if on_click else text)
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(msec)

    def reflow(self) -> None:
        """Re-fit to the parent after a resize, without restarting the timer."""
        if self.isVisible():
            self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            width = min(parent.width() - 40, 560)
            self.setFixedWidth(max(width, 200))
            self.adjustSize()
            self.move(
                (parent.width() - self.width()) // 2,
                parent.height() - self.height() - 24,
            )

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            callback = self._on_click
            self.hide()
            if callback is not None:
                callback()
        super().mousePressEvent(event)
