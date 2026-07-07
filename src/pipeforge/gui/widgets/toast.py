"""Toast notifications (UX-1): every action answers back.

A ToastManager stacks up to three kind-styled toasts (success / info /
warning / error) bottom-center over the window, each sliding up into place
(position animation only — opacity effects fight custom-painted widgets and
teardown, see MO-2/MO-3) and auto-dismissing. A toast may carry one action
("Bisection", "Show activity"); clicking anywhere on it runs the action or
dismisses.

The manager keeps the old single-toast API (`show_message`, `text`,
`isVisible`, `reflow`) so existing callers and tests keep working; problems
route here as error toasts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

_MAX_VISIBLE = 3
_WIDTH_MAX = 560
_MARGIN_BOTTOM = 24
_GAP = 8
_SLIDE_MS = 160

#: kind -> (glyph, QSS object name); colors live in the theme QSS (TH-1).
_KINDS: dict[str, tuple[str, str]] = {
    "success": ("✓", "toastSuccess"),
    "info": ("✵", "toastInfo"),
    "warning": ("⚠", "toastWarning"),
    "error": ("✕", "toastError"),
}


@dataclass
class ToastAction:
    label: str
    run: Callable[[], None]


class _Toast(QFrame):
    """One toast: glyph + message (+ action hint), kind-styled via QSS."""

    def __init__(
        self,
        parent: QWidget,
        kind: str,
        text: str,
        action: ToastAction | None,
        on_done: Callable[[_Toast], None],
    ) -> None:
        super().__init__(parent)
        glyph, obj = _KINDS.get(kind, _KINDS["info"])
        self.setObjectName(obj)
        self.kind = kind
        self.message = text
        self.action = action
        self._on_done = on_done
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        icon = QLabel(glyph)
        icon.setObjectName("toastIcon")
        body = QLabel(text)
        body.setWordWrap(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(body, 1)
        if action is not None:
            hint = QLabel(f"{action.label} ▸")
            hint.setObjectName("toastAction")
            row.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def start(self, msec: int) -> None:
        self._timer.start(msec)

    def dismiss(self) -> None:
        self._timer.stop()
        self._on_done(self)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            action = self.action
            self.dismiss()
            if action is not None:
                action.run()
        super().mousePressEvent(event)


class ToastManager(QWidget):
    """Owns and positions the toast stack over its parent window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._toasts: list[_Toast] = []
        self._animations: list[QPropertyAnimation] = []
        self.hide()

    # -- posting -----------------------------------------------------------------

    def push(
        self,
        kind: str,
        text: str,
        msec: int = 5000,
        action: ToastAction | None = None,
    ) -> None:
        while len(self._toasts) >= _MAX_VISIBLE:
            self._toasts[0].dismiss()
        toast = _Toast(self, kind, text, action, self._remove)
        self._toasts.append(toast)
        toast.show()
        toast.start(msec)
        self._restack(animate_new=toast)
        self.show()
        self.raise_()

    def success(self, text: str, msec: int = 5000, action: ToastAction | None = None) -> None:
        self.push("success", text, msec, action)

    def info(self, text: str, msec: int = 4000, action: ToastAction | None = None) -> None:
        self.push("info", text, msec, action)

    def warning(self, text: str, msec: int = 6000, action: ToastAction | None = None) -> None:
        self.push("warning", text, msec, action)

    def error(self, text: str, msec: int = 7000, action: ToastAction | None = None) -> None:
        self.push("error", text, msec, action)

    # -- legacy single-toast API (kept for callers/tests) --------------------------

    def show_message(
        self,
        text: str,
        msec: int = 5000,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        action = ToastAction("details", on_click) if on_click is not None else None
        self.push("error" if on_click is not None else "info", text, msec, action)

    def text(self) -> str:
        return self._toasts[-1].message if self._toasts else ""

    def reflow(self) -> None:
        self._restack()

    # -- stack management ------------------------------------------------------------

    def _remove(self, toast: _Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.hide()
        toast.deleteLater()
        if not self._toasts:
            self.hide()
        else:
            self._restack()

    def _restack(self, animate_new: _Toast | None = None) -> None:
        parent = self.parentWidget()
        if parent is None or not self._toasts:
            return
        width = min(parent.width() - 48, _WIDTH_MAX)
        heights: list[int] = []
        for toast in self._toasts:
            toast.setFixedWidth(max(width, 220))
            toast.adjustSize()
            heights.append(toast.height())
        total = sum(heights) + _GAP * (len(self._toasts) - 1)
        self.setGeometry(
            (parent.width() - max(width, 220)) // 2,
            parent.height() - _MARGIN_BOTTOM - total,
            max(width, 220),
            total,
        )
        self.raise_()  # docks shown later must not cover the stack
        y = 0
        for toast, h in zip(self._toasts, heights, strict=True):
            target = QPoint(0, y)
            if toast is animate_new:
                # slide up into place; position-only, no opacity effects (MO-2)
                toast.move(0, y + 14)
                anim = QPropertyAnimation(toast, b"pos", self)
                anim.setDuration(_SLIDE_MS)
                anim.setEndValue(target)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.finished.connect(lambda a=anim: self._animations.remove(a))
                self._animations.append(anim)
                anim.start()
            else:
                toast.move(target)
            y += h + _GAP

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        # tests (and users) may click the manager area: route to the toast there
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            while child is not None and not isinstance(child, _Toast):
                child = child.parentWidget() if child.parentWidget() is not self else None
            target = (
                child if isinstance(child, _Toast) else (self._toasts[-1] if self._toasts else None)
            )
            if target is not None:
                action = target.action
                target.dismiss()
                if action is not None:
                    action.run()
        super().mousePressEvent(event)


#: Back-compat alias — main_window historically imported `Toast`.
Toast = ToastManager
