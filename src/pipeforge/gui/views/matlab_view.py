"""Workspace view: browse every variable of the live MATLAB snapshot.

Lists name (dotted struct fields included), class, size, fi format, range,
and a values preview for the whole captured workspace — works for a `.m`
script run, a `.mat` parameter file loaded alone, or both. Clicking a row
whose name matches a DAG node selects it everywhere (VZ-2).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.frontend.varinfo import VarInfo, WorkspaceSnapshot
from pipeforge.gui.workspace import Workspace

_EMPTY_HINT = (
    "No MATLAB snapshot yet. Open a .m script or a .mat parameter file, then "
    "refresh from MATLAB (Ctrl+Shift+M) to capture and browse every variable's "
    "type, size, fixed-point format, and values."
)


def _preview(info: VarInfo) -> str:
    if not info.values:
        return ""
    head = ", ".join(f"{v:.6g}" for v in info.values[:4])
    more = ", …" if len(info.values) > 4 or info.truncated else ""
    return f"[{head}{more}]"


class MatlabView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self._snapshot: WorkspaceSnapshot | None = None

        title = QLabel("Workspace")
        title.setObjectName("viewTitle")
        self.meta = QLabel(_EMPTY_HINT)
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name…")
        self.filter_edit.textChanged.connect(lambda _t: self._refill())
        self.refresh_btn = QPushButton("Refresh from MATLAB")
        self.refresh_btn.clicked.connect(workspace.refresh_from_matlab)
        workspace.refreshStarted.connect(self._on_refresh_started)
        workspace.refreshFinished.connect(self._on_refresh_finished)

        header = QHBoxLayout()
        header.addWidget(self.filter_edit, 1)
        header.addWidget(self.refresh_btn)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Class", "Size", "fi format", "Min", "Max", "Values"]
        )
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(self._on_row)
        hh = self.table.horizontalHeader()
        if hh is not None:
            hh.setStretchLastSection(True)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.meta)
        box.addLayout(header)
        box.addWidget(self.table, 1)

        workspace.snapshotChanged.connect(self._on_snapshot)

    def _on_refresh_started(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Refreshing…")

    def _on_refresh_finished(self, _message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh from MATLAB")

    # -- population ----------------------------------------------------------

    def _on_snapshot(self, snapshot: object) -> None:
        self._snapshot = snapshot if isinstance(snapshot, WorkspaceSnapshot) else None
        if self._snapshot is None:
            self.meta.setText(_EMPTY_HINT)
        else:
            s = self._snapshot
            origin = s.script or s.setup or "workspace"
            pieces = [
                f"{len(s.variables)} variables from {origin}",
                f"MATLAB {s.matlab_version}",
                s.timestamp,
            ]
            if s.error:
                pieces.append(f"partial — MATLAB error: {s.error}")
            self.meta.setText(" — ".join(p for p in pieces if p))
        self._refill()

    def _visible(self) -> list[VarInfo]:
        if self._snapshot is None:
            return []
        needle = self.filter_edit.text().lower().strip()
        out = [
            v
            for name, v in sorted(self._snapshot.variables.items())
            if not needle or needle in name.lower()
        ]
        return out

    def _refill(self) -> None:
        rows = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            fi = f"{v.fi.width}/{v.fi.scale}" if v.fi else ""
            cells = [
                v.name,
                v.class_name,
                "x".join(str(d) for d in v.size),
                fi,
                f"{v.vmin:.6g}" if v.vmin is not None else "",
                f"{v.vmax:.6g}" if v.vmax is not None else "",
                _preview(v),
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, v.name)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    # -- selection sync (VZ-2) -------------------------------------------------

    def _on_row(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        audit = self._ws.audit
        if item is None or audit is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        for nid in audit.dag.order:
            node = audit.dag.nodes[nid]
            if node.label == name or node.signal == name:
                self._ws.select_node(nid)
                return
