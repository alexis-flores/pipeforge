"""Command palette (UI-4, Ctrl+K): type-to-filter actions, Enter to run."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QDialog, QLineEdit, QListWidget, QVBoxLayout, QWidget


class CommandPalette(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setMinimumWidth(420)
        self._commands: list[tuple[str, Callable[[], None]]] = []
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command…")
        self.search.textChanged.connect(self._refilter)
        self.listing = QListWidget()
        self.listing.itemActivated.connect(lambda _i: self._run_selected())
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        box.addWidget(self.search)
        box.addWidget(self.listing)

    def set_commands(self, commands: list[tuple[str, Callable[[], None]]]) -> None:
        self._commands = list(commands)
        self._refilter(self.search.text())

    def _refilter(self, text: str) -> None:
        needle = text.lower().strip()
        self.listing.clear()
        for name, _fn in self._commands:
            if all(part in name.lower() for part in needle.split()):
                self.listing.addItem(name)
        if self.listing.count():
            self.listing.setCurrentRow(0)

    def visible_commands(self) -> list[str]:
        return [self.listing.item(i).text() for i in range(self.listing.count())]

    def _run_selected(self) -> None:
        item = self.listing.currentItem()
        if item is None:
            return
        name = item.text()
        self.accept()
        for cmd_name, fn in self._commands:
            if cmd_name == name:
                fn()
                return

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._run_selected()
            return
        if event is not None and event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def open_centered(self, host: QWidget) -> None:
        self.search.clear()
        self.move(
            host.mapToGlobal(host.rect().center()).x() - self.width() // 2,
            host.mapToGlobal(host.rect().topLeft()).y() + 120,
        )
        self.show()
        self.search.setFocus()
