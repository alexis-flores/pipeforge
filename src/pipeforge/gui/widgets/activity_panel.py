"""The Activity panel (UX-2): a persistent, clickable history of actions.

Newest first: a kind-colored dot, what happened, the numbers, the time, and
an Open button when the action produced or touched a file. This is the
answer to "what have I actually done so far?" — toasts fade, this stays.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pipeforge.gui.activity import ActivityEntry

_MAX_ENTRIES = 200

#: kind -> semantic token for the status dot (resolved in set_theme).
_KIND_TOKEN = {
    "success": "success",
    "info": "accent",
    "warning": "warning",
    "error": "error",
}


class _EntryWidget(QWidget):
    def __init__(self, entry: ActivityEntry, open_path: Callable[[Path], None]) -> None:
        super().__init__()
        self.entry = entry
        dot = QLabel("●")
        dot.setObjectName(f"dot_{entry.kind}")
        title = QLabel(entry.title)
        title.setObjectName("activityTitle")
        when = QLabel(entry.when)
        when.setObjectName("muted")
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(dot)
        top.addWidget(title, 1)
        if entry.path:
            btn = QPushButton("Open")
            btn.setObjectName("activityOpen")
            btn.setToolTip(entry.path)
            btn.clicked.connect(lambda: open_path(Path(entry.path)))
            top.addWidget(btn)
        top.addWidget(when)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(2)
        box.addLayout(top)
        if entry.detail:
            detail = QLabel(entry.detail)
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            detail.setContentsMargins(18, 0, 0, 0)
            box.addWidget(detail)


class ActivityPanel(QWidget):
    """Dockable list of ActivityEntry items, newest on top."""

    def __init__(self, open_path: Callable[[Path], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._open_path = open_path
        self.listing = QListWidget()
        self.listing.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.listing.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.empty = QLabel("Actions you take — optimize, codegen, co-sim, exports — land here.")
        self.empty.setObjectName("muted")
        self.empty.setContentsMargins(8, 8, 8, 8)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.empty)
        box.addWidget(self.listing, 1)
        self.listing.hide()

    def add(self, entry: ActivityEntry) -> None:
        self.empty.hide()
        self.listing.show()
        item = QListWidgetItem()
        widget = _EntryWidget(entry, self._open_path)
        item.setSizeHint(widget.sizeHint())
        self.listing.insertItem(0, item)
        self.listing.setItemWidget(item, widget)
        while self.listing.count() > _MAX_ENTRIES:
            self.listing.takeItem(self.listing.count() - 1)

    def entries(self) -> list[ActivityEntry]:
        out: list[ActivityEntry] = []
        for i in range(self.listing.count()):
            widget = self.listing.itemWidget(self.listing.item(i))
            if isinstance(widget, _EntryWidget):
                out.append(widget.entry)
        return out
