"""Demos window (Ctrl+Shift+D): browse and open the packaged examples."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pipeforge.demos import DemoEntry, load_index


class DemosDialog(QDialog):
    """List on the left, description + suggested command on the right."""

    def __init__(
        self,
        open_path: Callable[[Path], None],
        parent: QWidget | None = None,
        navigate: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("PipeForge demos")
        self.resize(840, 480)
        self._open_path = open_path
        self._navigate = navigate
        self._entries: list[DemoEntry] = load_index()

        self.listing = QListWidget()
        for entry in self._entries:
            self.listing.addItem(f"{entry.demo_id} — {entry.title}")
        self.listing.currentRowChanged.connect(self._show)
        self.listing.itemActivated.connect(lambda _i: self._open_selected())

        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setObjectName("muted")
        self.command = QPlainTextEdit()
        self.command.setReadOnly(True)
        self.command.setMaximumHeight(96)

        self.open_btn = QPushButton("Open in PipeForge")
        self.open_btn.clicked.connect(self._open_selected)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(12, 0, 0, 0)
        right_box.setSpacing(8)
        right_box.addWidget(self.detail)
        cmd_label = QLabel("Try it headless:")
        cmd_label.setObjectName("sectionTitle")
        right_box.addWidget(cmd_label)
        right_box.addWidget(self.command)
        right_box.addStretch(1)

        split = QSplitter()
        split.addWidget(self.listing)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(close_btn)

        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(8)
        box.addWidget(split, 1)
        box.addLayout(buttons)

        if self._entries:
            self.listing.setCurrentRow(0)

    def selected(self) -> DemoEntry | None:
        row = self.listing.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _show(self, _row: int) -> None:
        entry = self.selected()
        if entry is None:
            return
        self.detail.setText(f"{entry.description}\n\nIn the GUI: {entry.gui}")
        self.command.setPlainText(entry.command)

    def _open_selected(self) -> None:
        entry = self.selected()
        if entry is None:
            return
        self.accept()
        for path in entry.paths():
            self._open_path(path)
        if self._navigate is not None and entry.view:
            self._navigate(entry.view)  # land on the view the demo showcases
