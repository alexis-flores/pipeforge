"""PipeForge main window (UI-1…UI-6).

Left icon sidebar (eight capabilities + Settings), central workspace view
stack, bottom status bar (file, WIDTH/SCALE chip, tool dots), collapsible
right inspector, collapsible console. Keyboard-first: Ctrl+O / Ctrl+1…9 /
Ctrl+R.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pipeforge import __version__
from pipeforge.core.audit.engine import Audit
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.views.audit_view import AuditView
from pipeforge.gui.views.placeholder import PlaceholderView
from pipeforge.gui.views.settings_view import SettingsView
from pipeforge.gui.views.visualizer_view import VisualizerView
from pipeforge.gui.widgets.source_view import SourceView
from pipeforge.gui.widgets.toast import Toast
from pipeforge.gui.workspace import Workspace
from pipeforge.services.tools import detect_tools

#: Sidebar order = Ctrl+1…9 order (UI-4).
CAPABILITIES = [
    ("audit", "Audit", "⏱"),
    ("visualizer", "Visualizer", "⛓"),
    ("golden", "Golden model", "≡"),
    ("cosim", "Co-simulation", "▶"),
    ("bisect", "Bisection", "÷"),
    ("linter", "Linter", "✓"),
    ("codegen", "Codegen", "⚙"),
    ("dse", "Exploration", "✦"),
    ("settings", "Settings", "⚒"),
]


class MainWindow(QMainWindow):
    def __init__(
        self,
        workspace: Workspace | None = None,
        themes: ThemeManager | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"PipeForge {__version__}")
        self.resize(1280, 800)
        self.workspace = workspace if workspace is not None else Workspace()
        app = QApplication.instance()
        self.themes = (
            themes
            if themes is not None
            else ThemeManager(app if isinstance(app, QApplication) else None)
        )

        self._build_views()
        self._build_sidebar()
        self._build_statusbar()
        self._build_inspector()
        self._build_console()
        self._build_shortcuts()

        self.toast = Toast(self)
        self.workspace.problem.connect(self._on_problem)
        self.workspace.auditChanged.connect(self._on_audit)
        self.workspace.fileChanged.connect(self._on_file)
        self.workspace.formatChanged.connect(lambda _w, _s: self._update_chips())
        self.workspace.selectionChanged.connect(self._on_selection)
        self.themes.themeChanged.connect(self._on_theme)
        self._on_theme(self.themes.theme)

    # -- construction --------------------------------------------------------

    def _build_views(self) -> None:
        self.stack = QStackedWidget()
        self.views: dict[str, QWidget] = {}
        self.views["audit"] = AuditView(self.workspace)
        self.views["visualizer"] = VisualizerView(self.workspace)
        self.views["golden"] = PlaceholderView(
            "Golden model",
            "Open a MATLAB file, then run a fixed-vs-float comparison from the CLI:\n"
            "pipeforge-cli audit <file.m> — GUI evaluation arrives with co-simulation.",
        )
        self.views["cosim"] = PlaceholderView(
            "Co-simulation",
            "Open a MATLAB file and its SystemVerilog implementation to compare "
            "RTL against the golden model. Requires Verilator.",
        )
        self.views["bisect"] = PlaceholderView(
            "Bisection",
            "Run a co-simulation first; when RTL and model disagree, bisection "
            "localizes the first divergent pipeline stage.",
        )
        self.views["linter"] = PlaceholderView(
            "Linter",
            "Open a SystemVerilog file to check nkMatlib pipeline conventions "
            "(delay matching, stage suffixes, valid chain, reset discipline).",
        )
        self.views["codegen"] = PlaceholderView(
            "Codegen",
            "Open a MATLAB file to generate an nkMatlib SystemVerilog skeleton "
            "with all PIPE/valid bookkeeping computed automatically.",
        )
        from pipeforge.gui.views.dse_view import DseView

        self.views["dse"] = DseView(self.workspace)
        self.views["settings"] = SettingsView(self.workspace, self.themes)
        for name, _label, _icon in CAPABILITIES:
            self.stack.addWidget(self.views[name])
        self.setCentralWidget(self._wrap_central())

    def _wrap_central(self) -> QWidget:
        central = QWidget()
        box = QVBoxLayout(central)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.stack)
        return central

    def _build_sidebar(self) -> None:
        bar = QWidget()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(64)
        column = QVBoxLayout(bar)
        column.setContentsMargins(8, 16, 8, 16)
        column.setSpacing(8)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QToolButton] = {}
        for i, (name, label, icon) in enumerate(CAPABILITIES):
            btn = QToolButton()
            btn.setText(icon)
            btn.setToolTip(f"{label} (Ctrl+{i + 1})")
            btn.setCheckable(True)
            btn.setAccessibleName(label)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.clicked.connect(lambda _c, n=name: self.show_view(n))
            self._nav_group.addButton(btn)
            self.nav_buttons[name] = btn
            if name == "settings":
                column.addStretch(1)
            column.addWidget(btn)
        dock = QDockWidget()
        dock.setTitleBarWidget(QWidget())
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setWidget(bar)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.nav_buttons["audit"].setChecked(True)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        assert sb is not None
        self.file_label = QLabel("No file open — Ctrl+O to begin")
        self.format_chip = QLabel()
        self.format_chip.setObjectName("chip")
        self.tools_label = QLabel()
        self.tools_label.setObjectName("muted")
        sb.addWidget(self.file_label, 1)
        sb.addPermanentWidget(self.format_chip)
        sb.addPermanentWidget(self.tools_label)
        self._update_chips()
        self._update_tool_dots()

    def _build_inspector(self) -> None:
        self.inspector = QDockWidget("Inspector")
        self.inspector.setObjectName("inspector")
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        self.inspector_label = QLabel("Select a node to inspect it.")
        self.inspector_label.setObjectName("muted")
        self.inspector_label.setWordWrap(True)
        self.source_view = SourceView()
        box.addWidget(self.inspector_label)
        box.addWidget(self.source_view, 1)
        self.inspector.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector)

    def _build_console(self) -> None:
        self.console_dock = QDockWidget("Console")
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)
        self.console_dock.hide()

    def _build_shortcuts(self) -> None:
        open_action = QAction("Open", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_dialog)
        self.addAction(open_action)
        rerun = QAction("Re-run analysis", self)
        rerun.setShortcut(QKeySequence("Ctrl+R"))
        rerun.triggered.connect(self.workspace.rerun)
        self.addAction(rerun)
        for i, (name, _label, _icon) in enumerate(CAPABILITIES):
            act = QAction(f"View {name}", self)
            act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(lambda _c, n=name: self.show_view(n))
            self.addAction(act)
        toggle_console = QAction("Toggle console", self)
        toggle_console.setShortcut(QKeySequence("Ctrl+`"))
        toggle_console.triggered.connect(
            lambda: self.console_dock.setVisible(not self.console_dock.isVisible())
        )
        self.addAction(toggle_console)

    # -- behavior --------------------------------------------------------------

    def show_view(self, name: str) -> None:
        names = [c[0] for c in CAPABILITIES]
        if name in names:
            self.stack.setCurrentIndex(names.index(name))
            self.nav_buttons[name].setChecked(True)

    def current_view_name(self) -> str:
        return CAPABILITIES[self.stack.currentIndex()][0]

    def open_path(self, path: Path) -> None:
        self.workspace.open_file(path)

    def _open_dialog(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self, "Open MATLAB or SystemVerilog file", "", "MATLAB/SV (*.m *.sv)"
        )
        if fname:
            self.open_path(Path(fname))

    def log(self, text: str) -> None:
        self.console.appendPlainText(text)

    def _on_problem(self, message: str) -> None:
        self.toast.show_message(message)
        self.log(message)

    def _on_file(self, path: str) -> None:
        self.file_label.setText(path or "No file open — Ctrl+O to begin")
        self.source_view.setPlainText(self.workspace.source)

    def _on_audit(self, audit: object) -> None:
        if isinstance(audit, Audit):
            self.log(
                f"Audit: {audit.filename} — {audit.total_latency} cycles, "
                f"{len(audit.findings)} findings"
            )
        self._update_chips()

    def _update_chips(self) -> None:
        self.format_chip.setText(f"{self.workspace.width}/{self.workspace.scale}")

    def _update_tool_dots(self) -> None:
        tools = detect_tools()
        dots = []
        tips = []
        for status in tools.values():
            dots.append("●" if status.available else "○")
            state = status.version if status.available else f"missing — {status.install_hint}"
            tips.append(f"{status.name}: {status.feature} — {state}")
        self.tools_label.setText(" ".join(dots))
        self.tools_label.setToolTip("\n".join(tips))

    def _on_selection(self, nid: str) -> None:
        audit = self.workspace.audit
        if audit is None or not nid or nid not in audit.dag.nodes:
            self.inspector_label.setText("Select a node to inspect it.")
            self.source_view.highlight_span(0, 0)
            return
        node = audit.dag.nodes[nid]
        related = [f"{f.tag} (line {f.line})" for f in audit.findings if f.node == nid]
        parts = [
            f"<b>{node.signal or node.label}</b>",
            f"module: {node.module or 'wire'}",
            f"latency: {node.lat} — ready @ cycle {node.ready}",
            f"line {node.line}: {node.label}",
        ]
        if related:
            parts.append("findings: " + ", ".join(related))
        self.inspector_label.setText("<br>".join(parts))
        if node.span is not None:
            self.source_view.highlight_span(node.span.start, node.span.end)
        else:
            self.source_view.highlight_line(node.line)

    def _on_theme(self, theme: object) -> None:
        if isinstance(theme, Theme):
            for view in self.views.values():
                set_theme = getattr(view, "set_theme", None)
                if callable(set_theme):
                    set_theme(theme)
            self.source_view.set_theme(theme)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.show_message(self.toast.text())
