"""Theme token engine (TH-1, TH-5).

Themes are JSON files of named semantic tokens. Every color in the
application flows from a loaded :class:`Theme`; no hex literal may appear
outside theme JSON files (enforced by an architecture test).

This module is deliberately Qt-free so it can be unit-tested headlessly;
QSS generation from a Theme lives in :mod:`pipeforge.gui.theme.qss`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

#: Semantic tokens every theme must define (TH-5).
REQUIRED_TOKENS: tuple[str, ...] = (
    "bg",
    "surface",
    "surfaceElevated",
    "border",
    "textPrimary",
    "textSecondary",
    "textDisabled",
    "accent",
    "accentMuted",
    "success",
    "warning",
    "error",
    "criticalPath",
    "divider",
    "selection",
    "focusRing",
    "consoleBg",
    "consoleFg",
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeError(ValueError):
    """Raised when a theme file is malformed (TH-3)."""


@dataclass(frozen=True)
class Theme:
    """A validated set of semantic color tokens plus chart series."""

    name: str
    tokens: dict[str, str]
    chart_series: list[str] = field(default_factory=list)
    dark: bool = True

    def __getitem__(self, token: str) -> str:
        return self.tokens[token]


def _validate(name: str, data: object) -> Theme:
    if not isinstance(data, dict):
        raise ThemeError(f"theme '{name}': top level must be a JSON object")
    raw_tokens = data.get("tokens")
    if not isinstance(raw_tokens, dict):
        raise ThemeError(f"theme '{name}': missing 'tokens' object")
    tokens: dict[str, str] = {}
    for key, value in raw_tokens.items():
        if not isinstance(value, str) or not _HEX_RE.match(value):
            raise ThemeError(
                f"theme '{name}': token '{key}' must be a '#rrggbb' hex string, got {value!r}"
            )
        tokens[str(key)] = value.lower()
    missing = [t for t in REQUIRED_TOKENS if t not in tokens]
    if missing:
        raise ThemeError(f"theme '{name}': missing required tokens: {', '.join(missing)}")
    series_raw = data.get("chartSeries", [])
    if not isinstance(series_raw, list) or not all(
        isinstance(c, str) and _HEX_RE.match(c) for c in series_raw
    ):
        raise ThemeError(f"theme '{name}': 'chartSeries' must be a list of '#rrggbb' strings")
    chart_series = [c.lower() for c in series_raw]
    display = data.get("name", name)
    if not isinstance(display, str):
        raise ThemeError(f"theme '{name}': 'name' must be a string")
    dark = bool(data.get("dark", True))
    return Theme(name=display, tokens=tokens, chart_series=chart_series, dark=dark)


def load_theme_file(path: Path) -> Theme:
    """Load and validate a theme JSON file; raises ThemeError on any problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeError(f"theme '{path.name}': cannot read ({exc})") from exc
    return _validate(path.stem, data)


def builtin_theme_names() -> list[str]:
    """Names (stems) of the themes bundled with PipeForge."""
    pkg = resources.files(__package__) / "themes"
    return sorted(p.name[: -len(".json")] for p in pkg.iterdir() if p.name.endswith(".json"))


def load_builtin_theme(name: str) -> Theme:
    """Load a bundled theme by stem name, e.g. 'gruvbox-dark-soft' (TH-2/TH-3)."""
    pkg = resources.files(__package__) / "themes" / f"{name}.json"
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeError(f"builtin theme '{name}': cannot read ({exc})") from exc
    return _validate(name, data)


DEFAULT_THEME = "gruvbox-dark-soft"
