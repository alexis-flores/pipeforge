"""Empty-state placeholder for capabilities arriving in later phases (UI-5)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderView(QWidget):
    def __init__(self, title: str, how_to_begin: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        heading = QLabel(title)
        heading.setObjectName("viewTitle")
        hint = QLabel(how_to_begin)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.addWidget(heading)
        box.addStretch(1)
        box.addWidget(hint)
        box.addStretch(2)
