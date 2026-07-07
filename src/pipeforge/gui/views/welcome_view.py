"""Welcome view: what a new user sees before any file is open.

Three ways in, in order of likelihood: reopen a recent file, open a file,
or explore a packaged demo. Replaced by the capability views the moment a
file is opened; reachable again only when the workspace is empty.
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

from pipeforge.demos import DemoEntry, load_index
from pipeforge.gui.recent import load_recent

_TAGLINE = (
    "Audit, verify, visualize, and generate fixed-point nkMatlib pipelines "
    "from straight-line MATLAB DSP code."
)
_FLOW = (
    "The typical flow: open a .m file → Audit shows cycle cost and savings → "
    "Ranges checks overflow → Codegen writes the SystemVerilog → Linter and "
    "Co-simulation prove your RTL matches."
)


class WelcomeView(QWidget):
    def __init__(
        self,
        open_dialog: Callable[[], None],
        open_path: Callable[[Path], None],
        open_demo: Callable[[DemoEntry], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._open_path = open_path
        self._open_demo = open_demo
        self._demos: list[DemoEntry] = []
        self._recent: list[Path] = []

        title = QLabel("PipeForge")
        title.setObjectName("viewTitle")
        tagline = QLabel(_TAGLINE)
        tagline.setObjectName("muted")
        tagline.setWordWrap(True)
        flow = QLabel(_FLOW)
        flow.setObjectName("muted")
        flow.setWordWrap(True)

        open_btn = QPushButton("Open a MATLAB, SystemVerilog, or .mat file…")
        open_btn.clicked.connect(lambda: open_dialog())
        open_row = QHBoxLayout()
        open_row.addWidget(open_btn)
        open_row.addStretch(1)

        recent_title = QLabel("Recent files")
        recent_title.setObjectName("sectionTitle")
        self.recent_list = QListWidget()
        self.recent_list.setToolTip("Click to reopen")
        self.recent_list.itemClicked.connect(self._open_recent)
        self.recent_list.itemActivated.connect(self._open_recent)
        self.no_recent = QLabel("Nothing opened yet — try a demo below.")
        self.no_recent.setObjectName("muted")

        demos_title = QLabel("Demos — one small example per capability")
        demos_title.setObjectName("sectionTitle")
        self.demo_list = QListWidget()
        self.demo_list.setWordWrap(True)
        self.demo_list.setToolTip("Click to open the demo files and jump to the right view")
        self.demo_list.itemClicked.connect(self._open_demo_item)
        self.demo_list.itemActivated.connect(self._open_demo_item)

        columns = QHBoxLayout()
        recent_col = QVBoxLayout()
        recent_col.setSpacing(8)
        recent_col.addWidget(recent_title)
        recent_col.addWidget(self.no_recent)
        recent_col.addWidget(self.recent_list, 3)
        recent_col.addStretch(1)
        demos_col = QVBoxLayout()
        demos_col.setSpacing(8)
        demos_col.addWidget(demos_title)
        demos_col.addWidget(self.demo_list, 1)
        columns.addLayout(recent_col, 2)
        columns.addSpacing(24)
        columns.addLayout(demos_col, 3)

        box = QVBoxLayout(self)
        box.setContentsMargins(48, 32, 48, 32)
        box.setSpacing(12)
        box.addWidget(title)
        box.addWidget(tagline)
        box.addWidget(flow)
        box.addSpacing(8)
        box.addLayout(open_row)
        box.addSpacing(8)
        box.addLayout(columns, 1)

        self.refresh()

    def refresh(self) -> None:
        """Reload recent files and demos (cheap; called whenever shown)."""
        self._recent = load_recent()
        self.recent_list.clear()
        for path in self._recent:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            self.recent_list.addItem(item)
        self.recent_list.setVisible(bool(self._recent))
        self.no_recent.setVisible(not self._recent)
        if not self._demos:
            try:
                self._demos = load_index()
            except Exception:  # packaged index missing: never crash (NF-4)
                self._demos = []
            for entry in self._demos:
                item = QListWidgetItem(entry.title)
                item.setToolTip(f"{entry.description}\n\nIn the GUI: {entry.gui}")
                self.demo_list.addItem(item)

    def _open_recent(self, item: QListWidgetItem) -> None:
        row = self.recent_list.row(item)
        if 0 <= row < len(self._recent):
            self._open_path(self._recent[row])

    def _open_demo_item(self, item: QListWidgetItem) -> None:
        row = self.demo_list.row(item)
        if 0 <= row < len(self._demos):
            self._open_demo(self._demos[row])

    def keyPressEvent(self, event) -> None:
        if event is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.recent_list.currentItem()
            if current is not None:
                self._open_recent(current)
                return
        super().keyPressEvent(event)
