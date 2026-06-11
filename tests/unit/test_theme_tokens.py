"""Theme token engine tests (TH-1, TH-2, TH-3, TH-5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeforge.gui.theme.tokens import (
    DEFAULT_THEME,
    REQUIRED_TOKENS,
    Theme,
    ThemeError,
    builtin_theme_names,
    load_builtin_theme,
    load_theme_file,
)


@pytest.mark.req("TH-2")
def test_default_theme_is_gruvbox_dark_soft() -> None:
    theme = load_builtin_theme(DEFAULT_THEME)
    assert theme.name == "Gruvbox Dark Soft"
    # Normative values from SRS Appendix A.
    assert theme["bg"] == "#32302f"
    assert theme["surface"] == "#3c3836"
    assert theme["surfaceElevated"] == "#504945"
    assert theme["border"] == "#665c54"
    assert theme["textPrimary"] == "#ebdbb2"
    assert theme["textSecondary"] == "#bdae93"
    assert theme["textDisabled"] == "#928374"
    assert theme["accent"] == "#8ec07c"
    assert theme["accentMuted"] == "#689d6a"
    assert theme["success"] == "#b8bb26"
    assert theme["warning"] == "#fabd2f"
    assert theme["error"] == "#fb4934"
    assert theme["criticalPath"] == "#fb4934"
    assert theme["divider"] == "#fe8019"
    assert theme["selection"] == "#504945"
    assert theme["focusRing"] == "#83a598"
    assert theme["consoleBg"] == "#282828"
    assert theme["consoleFg"] == "#d5c4a1"
    # Chart series order: aqua, blue, yellow, purple, orange, green (bright).
    assert theme.chart_series == [
        "#8ec07c",
        "#83a598",
        "#fabd2f",
        "#d3869b",
        "#fe8019",
        "#b8bb26",
    ]


@pytest.mark.req("TH-3")
@pytest.mark.req("TH-5")
def test_bundled_alternates_present_and_valid() -> None:
    names = builtin_theme_names()
    for required in ("gruvbox-dark-soft", "gruvbox-dark-hard", "gruvbox-light", "high-contrast"):
        assert required in names
    for name in names:
        theme = load_builtin_theme(name)
        assert isinstance(theme, Theme)
        for token in REQUIRED_TOKENS:
            assert token in theme.tokens


@pytest.mark.req("TH-3")
def test_malformed_theme_fails_validation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"tokens": {"bg": "notahex"}}))
    with pytest.raises(ThemeError, match="bg"):
        load_theme_file(bad)

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"tokens": {"bg": "#000000"}}))
    with pytest.raises(ThemeError, match="missing required tokens"):
        load_theme_file(missing)

    notjson = tmp_path / "notjson.json"
    notjson.write_text("{nope")
    with pytest.raises(ThemeError, match="cannot read"):
        load_theme_file(notjson)
