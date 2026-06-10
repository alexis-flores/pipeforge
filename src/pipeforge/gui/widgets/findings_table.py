"""Sortable, tag-filterable findings table with click-through (UI-6)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.audit.findings import Finding


class FindingsTable(QWidget):
    findingActivated = pyqtSignal(object)  # Finding

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._findings: list[Finding] = []

        self._filter = QComboBox()
        self._filter.addItem("All tags")
        self._filter.currentTextChanged.connect(lambda _t: self._refill())

        header = QHBoxLayout()
        label = QLabel("Filter")
        label.setObjectName("muted")
        header.addWidget(label)
        header.addWidget(self._filter)
        header.addStretch(1)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Tag", "Line", "Saves", "Finding"])
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.cellActivated.connect(self._activate)
        self._table.cellClicked.connect(self._activate)
        hh = self._table.horizontalHeader()
        if hh is not None:
            hh.setStretchLastSection(True)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addLayout(header)
        box.addWidget(self._table)

    def set_findings(self, findings: list[Finding]) -> None:
        self._findings = list(findings)
        tags = sorted({f.tag for f in findings})
        current = self._filter.currentText()
        self._filter.blockSignals(True)
        self._filter.clear()
        self._filter.addItem("All tags")
        self._filter.addItems(tags)
        idx = self._filter.findText(current)
        if idx >= 0:
            self._filter.setCurrentIndex(idx)
        self._filter.blockSignals(False)
        self._refill()

    def _visible(self) -> list[Finding]:
        tag = self._filter.currentText()
        if tag in ("", "All tags"):
            return self._findings
        return [f for f in self._findings if f.tag == tag]

    def _refill(self) -> None:
        rows = self._visible()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for r, f in enumerate(rows):
            tag = QTableWidgetItem(f.tag)
            line = QTableWidgetItem()
            line.setData(Qt.ItemDataRole.DisplayRole, f.line)
            saves = QTableWidgetItem()
            saves.setData(Qt.ItemDataRole.DisplayRole, f.savings)
            msg = QTableWidgetItem(f.message)
            msg.setToolTip(f.suggestion)
            for item in (tag, line, saves, msg):
                item.setData(Qt.ItemDataRole.UserRole, r)
            self._table.setItem(r, 0, tag)
            self._table.setItem(r, 1, line)
            self._table.setItem(r, 2, saves)
            self._table.setItem(r, 3, msg)
        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()

    def _activate(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        visible = self._visible()
        if isinstance(idx, int) and 0 <= idx < len(visible):
            self.findingActivated.emit(visible[idx])
