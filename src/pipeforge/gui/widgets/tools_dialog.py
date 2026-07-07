"""External tools dialog, opened from the status-bar availability dots (App. B).

Each optional tool with what it unlocks and — when missing — the exact
install command. Nothing here is required; missing tools only disable their
one feature.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.services.tools import detect_tools


class ToolsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("External tools")
        self.resize(720, 360)

        intro = QLabel(
            "Every tool below is optional — each unlocks exactly one feature, "
            "and everything else works without it."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tool", "Unlocks", "Status", "Install"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        vh = self.table.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        if hh is not None:
            hh.setStretchLastSection(True)

        self.refresh_btn = QPushButton("Re-detect")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        actions = QHBoxLayout()
        actions.addWidget(self.refresh_btn)
        actions.addStretch(1)
        actions.addWidget(buttons)

        box = QVBoxLayout(self)
        box.addWidget(intro)
        box.addWidget(self.table, 1)
        box.addLayout(actions)

        self.refresh()

    def refresh(self) -> None:
        tools = detect_tools()
        self.table.setRowCount(len(tools))
        for r, status in enumerate(tools.values()):
            cells = (
                status.name,
                status.feature,
                f"● {status.version}" if status.available else "○ not found",
                "" if status.available else status.install_hint,
            )
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
