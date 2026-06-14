"""TH-7: the rendered type scale realizes a clear visual hierarchy."""

from __future__ import annotations

import re

import pytest

from pipeforge.gui.theme.qss import FONT_BODY, FONT_DISPLAY, FONT_TITLE, MONO_FONTS, build_qss
from pipeforge.gui.theme.tokens import DEFAULT_THEME, load_builtin_theme


@pytest.mark.req("TH-7")
def test_type_scale_hierarchy_applied() -> None:
    qss = build_qss(load_builtin_theme(DEFAULT_THEME))

    def rule(selector: str) -> str:
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", qss)
        assert m, f"missing rule for {selector}"
        return m.group(1)

    title = rule("QLabel#viewTitle")
    section = rule("QLabel#sectionTitle")
    data = rule("QLabel#dataValue")

    # large/light title (replacing the italic treatment)
    assert f"font-size: {FONT_DISPLAY}px" in title
    assert "font-weight: 300" in title
    assert "italic" not in title
    # medium-weight section labels, distinct size from the title
    assert f"font-size: {FONT_TITLE}px" in section
    assert "font-weight: 600" in section
    # monospace reserved for numeric/code data
    assert MONO_FONTS in data
    assert FONT_DISPLAY > FONT_TITLE > FONT_BODY  # a real scale
