"""Live theme application and persistence (TH-3, TH-4, NF-7)."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QObject, QStandardPaths, pyqtSignal
from PyQt6.QtWidgets import QApplication

from pipeforge.gui.theme.qss import build_qss
from pipeforge.gui.theme.tokens import (
    DEFAULT_THEME,
    Theme,
    ThemeError,
    builtin_theme_names,
    load_builtin_theme,
    load_theme_file,
)


def config_dir() -> Path:
    """Platform config directory; deleting it yields a clean first run (NF-7)."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    path = Path(base) if base else Path.home() / ".config" / "pipeforge"
    if path.name.lower() != "pipeforge":
        path = path / "pipeforge"
    return path


class ThemeManager(QObject):
    """Owns the active theme; applies QSS app-wide and persists the choice."""

    themeChanged = pyqtSignal(object)  # Theme

    def __init__(self, app: QApplication | None = None) -> None:
        super().__init__()
        self._app = app
        self._theme = load_builtin_theme(DEFAULT_THEME)
        self._name = DEFAULT_THEME
        self._errors: list[str] = []

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def current_name(self) -> str:
        return self._name

    @property
    def load_errors(self) -> list[str]:
        return list(self._errors)

    # -- discovery ---------------------------------------------------------

    def user_theme_dir(self) -> Path:
        return config_dir() / "themes"

    def available(self) -> dict[str, str]:
        """name -> display name, builtins plus valid user themes (TH-3)."""
        self._errors = []
        out: dict[str, str] = {}
        for name in builtin_theme_names():
            out[name] = load_builtin_theme(name).name
        user_dir = self.user_theme_dir()
        if user_dir.is_dir():
            for path in sorted(user_dir.glob("*.json")):
                try:
                    out[path.stem] = load_theme_file(path).name
                except ThemeError as exc:
                    self._errors.append(str(exc))
        return out

    def _load(self, name: str) -> Theme:
        user_path = self.user_theme_dir() / f"{name}.json"
        if user_path.is_file():
            return load_theme_file(user_path)
        return load_builtin_theme(name)

    # -- application -------------------------------------------------------

    def apply(self, name: str) -> Theme:
        """Switch theme live (TH-4); malformed themes fall back to default (TH-3)."""
        try:
            theme = self._load(name)
        except ThemeError as exc:
            self._errors.append(str(exc))
            theme = load_builtin_theme(DEFAULT_THEME)
            name = DEFAULT_THEME
        self._theme = theme
        self._name = name
        if self._app is not None:
            self._app.setStyleSheet(build_qss(theme))
        self.themeChanged.emit(theme)
        return theme

    # -- persistence (NF-7) --------------------------------------------------

    def _settings_path(self) -> Path:
        return config_dir() / "settings.json"

    def save(self) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        data["theme"] = self._name
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def restore(self) -> Theme:
        path = self._settings_path()
        name = DEFAULT_THEME
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data.get("theme"), str):
                    name = data["theme"]
            except (OSError, json.JSONDecodeError):
                pass
        return self.apply(name)
