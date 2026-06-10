"""Read-only MATLAB source view with span highlighting (FE-4, VZ-2)."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from pipeforge.gui.theme.tokens import Theme


class SourceView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self._theme: Theme | None = None

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme

    def highlight_span(self, start: int, end: int) -> None:
        if self._theme is None or end <= start:
            self.setExtraSelections([])
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(self._theme["selection"]))
        fmt.setForeground(QColor(self._theme["textPrimary"]))
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = fmt
        self.setExtraSelections([selection])
        view_cursor = self.textCursor()
        view_cursor.setPosition(start)
        self.setTextCursor(view_cursor)
        self.ensureCursorVisible()

    def highlight_line(self, line: int) -> None:
        doc = self.document()
        if doc is None:
            return
        block = doc.findBlockByNumber(max(line - 1, 0))
        if block.isValid():
            self.highlight_span(block.position(), block.position() + block.length() - 1)
