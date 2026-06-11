"""Theme → Qt stylesheet generation (TH-1, TH-6). Qt-free string building."""

from __future__ import annotations

from pipeforge.gui.theme.tokens import Theme

#: TH-6 typography: system UI stack for chrome, monospace stack for code.
UI_FONTS = '-apple-system, "SF Pro Text", "Cantarell", "Inter", "Noto Sans", sans-serif'
MONO_FONTS = '"JetBrains Mono", "Menlo", "DejaVu Sans Mono", monospace'

#: Type scale (px), two weights used: 400 and 600.
FONT_SMALL = 11
FONT_BODY = 13
FONT_TITLE = 15
FONT_DISPLAY = 20


def build_qss(t: Theme) -> str:
    """Generate the application stylesheet from semantic tokens only."""
    return f"""
* {{
    font-family: {UI_FONTS};
    font-size: {FONT_BODY}px;
    color: {t["textPrimary"]};
}}
QMainWindow, QDialog {{ background: {t["bg"]}; }}
QWidget#view {{ background: {t["bg"]}; }}
QWidget#sidebar {{ background: {t["surface"]}; border-right: 1px solid {t["border"]}; }}
QToolButton {{
    background: transparent; border: none; border-radius: 6px;
    padding: 8px; color: {t["textSecondary"]};
}}
QToolButton:hover {{ background: {t["surfaceElevated"]}; color: {t["textPrimary"]}; }}
QToolButton:checked {{ background: {t["surfaceElevated"]}; color: {t["accent"]}; }}
QToolButton:focus {{ outline: none; border: 1px solid {t["focusRing"]}; }}
QPushButton {{
    background: {t["surfaceElevated"]}; border: 1px solid {t["border"]};
    border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {t["accent"]}; }}
QPushButton:focus {{ border: 1px solid {t["focusRing"]}; outline: none; }}
QPushButton:disabled {{ color: {t["textDisabled"]}; }}
QLineEdit, QSpinBox, QComboBox {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 6px; padding: 4px 8px;
    selection-background-color: {t["selection"]};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t["focusRing"]}; }}
QComboBox QAbstractItemView {{
    background: {t["surfaceElevated"]}; border: 1px solid {t["border"]};
    selection-background-color: {t["selection"]};
}}
QTableView, QTreeView, QListView {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 8px; gridline-color: {t["border"]};
    selection-background-color: {t["selection"]};
    selection-color: {t["textPrimary"]};
    alternate-background-color: {t["bg"]};
}}
QHeaderView::section {{
    background: {t["surface"]}; color: {t["textSecondary"]};
    border: none; border-bottom: 1px solid {t["border"]}; padding: 6px;
    font-size: {FONT_SMALL}px; font-weight: 600;
}}
QStatusBar {{
    background: {t["surface"]}; border-top: 1px solid {t["border"]};
    color: {t["textSecondary"]}; font-size: {FONT_SMALL}px;
}}
QPlainTextEdit, QTextEdit {{
    background: {t["consoleBg"]}; color: {t["consoleFg"]};
    font-family: {MONO_FONTS}; font-size: {FONT_BODY}px;
    border: 1px solid {t["border"]}; border-radius: 8px;
    selection-background-color: {t["selection"]};
}}
QLabel#viewTitle {{ font-size: {FONT_DISPLAY}px; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: {FONT_TITLE}px; font-weight: 600; }}
QLabel#muted {{ color: {t["textSecondary"]}; }}
QLabel#chip {{
    background: {t["surfaceElevated"]}; border: 1px solid {t["border"]};
    border-radius: 9px; padding: 2px 10px; font-size: {FONT_SMALL}px;
}}
QLabel#chipBusy {{
    background: {t["surfaceElevated"]}; border: 1px solid {t["accent"]};
    color: {t["accent"]};
    border-radius: 9px; padding: 2px 10px; font-size: {FONT_SMALL}px;
}}
QLabel#chipWarn {{
    background: {t["surfaceElevated"]}; border: 1px solid {t["warning"]};
    color: {t["warning"]};
    border-radius: 9px; padding: 2px 10px; font-size: {FONT_SMALL}px;
}}
QSplitter::handle {{ background: {t["border"]}; width: 1px; height: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{
    background: {t["surfaceElevated"]}; border-radius: 5px; min-height: 30px;
}}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {t["surfaceElevated"]}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{
    background: {t["surfaceElevated"]}; color: {t["textPrimary"]};
    border: 1px solid {t["border"]}; padding: 4px 8px;
}}
QDockWidget {{ titlebar-close-icon: none; }}
QMenu {{ background: {t["surfaceElevated"]}; border: 1px solid {t["border"]}; }}
QMenu::item:selected {{ background: {t["selection"]}; }}
QProgressBar {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 6px; text-align: center; color: {t["textSecondary"]};
}}
QProgressBar::chunk {{ background: {t["accentMuted"]}; border-radius: 5px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
""".strip()
