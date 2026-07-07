"""Keyboard shortcut cheat sheet (Help menu)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: (shortcut, action) rows shown in the cheat sheet. The view-switching rows
#: are appended at construction from the live CAPABILITIES order.
BASE_SHORTCUTS: list[tuple[str, str]] = [
    ("Ctrl+O", "Open a MATLAB / SystemVerilog / .mat file"),
    ("Ctrl+K", "Command palette — every action, searchable"),
    ("Ctrl+R", "Re-run the analysis"),
    ("Ctrl+`", "Toggle the console"),
    ("Ctrl+Shift+M", "Refresh the MATLAB workspace snapshot"),
    ("Ctrl+Shift+D", "Open the demos browser"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, view_rows: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.resize(520, 420)

        rows = BASE_SHORTCUTS + view_rows
        self.table = QTableWidget(len(rows), 2)
        self.table.setHorizontalHeaderLabels(["Shortcut", "Action"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        vh = self.table.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        hh = self.table.horizontalHeader()
        if hh is not None:
            hh.setStretchLastSection(True)
        for r, (key, action) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(key))
            self.table.setItem(r, 1, QTableWidgetItem(action))
        self.table.resizeColumnsToContents()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        box = QVBoxLayout(self)
        box.addWidget(self.table, 1)
        box.addWidget(buttons)
