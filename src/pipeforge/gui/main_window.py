"""PipeForge main window (UI-1…UI-6).

Menu bar (File/View/Run/Help), left sidebar of labeled capabilities in
workflow order, central view stack fronted by a welcome screen, bottom
status bar (file, clickable WIDTH/SCALE chip, clickable tool dots),
collapsible right inspector, collapsible console. Keyboard-first
(Ctrl+O / Ctrl+1…9 / Ctrl+K / Ctrl+R) with every shortcut discoverable
in the menus.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pipeforge import __version__
from pipeforge.core.audit.engine import Audit
from pipeforge.gui.recent import add_recent, clear_recent, load_recent
from pipeforge.gui.theme.manager import ThemeManager
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.views.audit_view import AuditView
from pipeforge.gui.views.settings_view import SettingsView
from pipeforge.gui.views.visualizer_view import VisualizerView
from pipeforge.gui.widgets.source_view import SourceView
from pipeforge.gui.widgets.toast import Toast
from pipeforge.gui.workspace import Workspace

#: Sidebar order = the pipeline workflow (UI-4): understand the MATLAB first,
#: then generate/check RTL, then verify, then explore alternatives.
CAPABILITIES = [
    ("audit", "Audit", "⏱"),
    ("visualizer", "Visualizer", "⛓"),
    ("ranges", "Ranges", "±"),
    ("codegen", "Codegen", "⚙"),
    ("linter", "Linter", "✓"),
    ("cosim", "Co-sim", "▶"),
    ("bisect", "Bisection", "÷"),
    ("dse", "Explore", "✦"),
    ("golden", "Workspace", "≡"),
    ("mapping", "Mapping", "⇄"),
    ("settings", "Settings", "⚒"),
]

#: One line per capability: what it does, shown in tooltips and the View menu.
DESCRIPTIONS = {
    "audit": "cycle cost, operator census, and savings findings for the open .m",
    "visualizer": "the pipeline as a timeline; export SVG/PNG",
    "ranges": "will WIDTH/SCALE overflow? propagate input ranges to find out",
    "codegen": "generate the nkMatlib SystemVerilog skeleton",
    "linter": "check hand-written RTL for nkMatlib convention bugs",
    "cosim": "prove RTL == golden model bit-for-bit (Verilator)",
    "bisect": "when co-sim fails: the first divergent pipeline stage",
    "dse": "sweep WIDTH/SCALE; error-vs-latency-vs-area Pareto front",
    "golden": "browse the live MATLAB workspace / .mat variables",
    "mapping": "MATLAB variables ↔ RTL signals correspondence",
    "settings": "theme, format, MATLAB bridge, external tools",
}

#: Discoverable view shortcuts, workflow order (UI-4).
VIEW_SHORTCUTS = {
    "audit": "Ctrl+1",
    "visualizer": "Ctrl+2",
    "ranges": "Ctrl+3",
    "codegen": "Ctrl+4",
    "linter": "Ctrl+5",
    "cosim": "Ctrl+6",
    "bisect": "Ctrl+7",
    "dse": "Ctrl+8",
    "golden": "Ctrl+9",
    "mapping": "Ctrl+0",
    "settings": "Ctrl+,",
}


def _fmt_values(values: tuple[float, ...]) -> str:
    head = ", ".join(f"{v:.6g}" for v in values[:4])
    return f"[{head}{', …' if len(values) > 4 else ''}]"


class MainWindow(QMainWindow):
    def __init__(
        self,
        workspace: Workspace | None = None,
        themes: ThemeManager | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"PipeForge {__version__}")
        self.resize(1280, 800)
        self.setAcceptDrops(True)
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
        self._build_menus()

        self.toast = Toast(self)
        self.workspace.problem.connect(self._on_problem)
        self.workspace.logMessage.connect(self.log)
        self.workspace.refreshStarted.connect(self._on_refresh_started)
        self.workspace.refreshFinished.connect(self._on_refresh_finished)
        self.workspace.snapshotStale.connect(self._on_snapshot_stale)
        self.workspace.snapshotChanged.connect(lambda _s: self._on_selection(""))
        self.workspace.snapshotChanged.connect(lambda _s: self._sync_matlab_chip())
        self.workspace.auditChanged.connect(self._on_audit)
        self.workspace.auditChanged.connect(lambda _a: self._refresh_mapping())
        self.workspace.fileChanged.connect(self._on_file)
        self.workspace.formatChanged.connect(lambda _w, _s: self._update_chips())
        self.workspace.selectionChanged.connect(self._on_selection)
        self.themes.themeChanged.connect(self._on_theme)
        self._on_theme(self.themes.theme)

    # -- construction --------------------------------------------------------

    def _build_views(self) -> None:
        self.stack = QStackedWidget()
        self.views: dict[str, QWidget] = {}
        from pipeforge.gui.views.welcome_view import WelcomeView

        self.welcome = WelcomeView(self._open_dialog, self.open_path, self._open_demo)
        self.views["audit"] = AuditView(self.workspace)
        self.views["visualizer"] = VisualizerView(self.workspace)
        from pipeforge.gui.views.ranges_view import RangesView

        self.views["ranges"] = RangesView(self.workspace)
        from pipeforge.gui.views.matlab_view import MatlabView

        self.views["golden"] = MatlabView(self.workspace)
        from pipeforge.gui.views.bisection_view import BisectionView
        from pipeforge.gui.views.cosim_view import CosimView

        self.views["cosim"] = CosimView(self.workspace)
        self.views["bisect"] = BisectionView(self.workspace, navigate=self.show_view)
        from pipeforge.gui.views.codegen_view import CodegenView
        from pipeforge.gui.views.linter_view import LinterView

        self.views["linter"] = LinterView(self.workspace)
        self.views["codegen"] = CodegenView(self.workspace)
        from pipeforge.gui.views.dse_view import DseView
        from pipeforge.gui.views.mapping_view import MappingView

        self.views["dse"] = DseView(self.workspace)
        self.views["mapping"] = MappingView(self.workspace)
        self.views["settings"] = SettingsView(self.workspace, self.themes)
        self._stack_names = ["welcome"] + [c[0] for c in CAPABILITIES]
        self.stack.addWidget(self.welcome)
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
        bar.setFixedWidth(92)
        column = QVBoxLayout(bar)
        column.setContentsMargins(6, 12, 6, 12)
        column.setSpacing(4)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QToolButton] = {}
        for name, label, icon in CAPABILITIES:
            btn = QToolButton()
            btn.setText(f"{icon}\n{label}")
            shortcut = VIEW_SHORTCUTS.get(name, "")
            tip = DESCRIPTIONS.get(name, "")
            btn.setToolTip(f"{label} — {tip} ({shortcut})" if tip else f"{label} ({shortcut})")
            btn.setCheckable(True)
            btn.setAccessibleName(label)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        self.show_welcome()  # first thing a new user sees: ways in, not a blank view

    def _build_statusbar(self) -> None:
        from PyQt6.QtCore import QTimer

        from pipeforge.gui.widgets.chips import ClickableChip

        sb = self.statusBar()
        assert sb is not None
        self.file_label = QLabel("No file open — Ctrl+O to begin, Ctrl+Shift+D for demos")
        self.format_chip = ClickableChip()
        self.format_chip.setToolTip("Fixed-point format WIDTH/SCALE — click to edit")
        self.format_chip.clicked.connect(self.open_format_dialog)
        self.matlab_chip = ClickableChip()
        self.matlab_chip.hide()
        self.matlab_chip.setToolTip("MATLAB snapshot state — click to refresh")
        self.matlab_chip.clicked.connect(self.workspace.refresh_from_matlab)
        self._matlab_elapsed = QTimer(self)
        self._matlab_elapsed.setInterval(1000)
        self._matlab_elapsed.timeout.connect(self._tick_matlab_chip)
        self._matlab_started = 0.0
        self.tools_chip = ClickableChip()
        self.tools_chip.setObjectName("muted")
        self.tools_chip.clicked.connect(self.open_tools_dialog)
        sb.addWidget(self.file_label, 1)
        sb.addPermanentWidget(self.matlab_chip)
        sb.addPermanentWidget(self.format_chip)
        sb.addPermanentWidget(self.tools_chip)
        self._update_chips()
        self.tools_chip.setText("…")
        self.tools_chip.setToolTip("Detecting external tools…")
        self._update_tool_dots()  # async: subprocess probes never block startup (NF-3)

    # -- MATLAB chip states (busy / fresh / stale) -----------------------------

    def _on_refresh_started(self) -> None:
        import time

        self._matlab_started = time.monotonic()
        self.matlab_chip.set_state("busy")
        self.matlab_chip.setText("MATLAB ⟳ 0s")
        self.matlab_chip.show()
        self._matlab_elapsed.start()

    def _tick_matlab_chip(self) -> None:
        import time

        elapsed = int(time.monotonic() - self._matlab_started)
        self.matlab_chip.setText(f"MATLAB ⟳ {elapsed}s")

    def _on_refresh_finished(self, message: str) -> None:
        self._matlab_elapsed.stop()
        if message:
            self.toast.show_message(f"MATLAB snapshot updated — {message}")
        self._sync_matlab_chip()

    def _on_snapshot_stale(self, _stale: bool) -> None:
        self._sync_matlab_chip()

    def _sync_matlab_chip(self) -> None:
        snapshot = self.workspace.snapshot
        if self.workspace.refreshing:
            return  # busy state owns the chip
        if snapshot is None:
            self.matlab_chip.hide()
            return
        self.matlab_chip.show()
        if self.workspace.stale:
            self.matlab_chip.set_state("warn")
            self.matlab_chip.setText("MATLAB ⚠ stale")
            self.matlab_chip.setToolTip(
                "Watched files changed since this snapshot — click to refresh"
            )
        else:
            self.matlab_chip.set_state("")
            when = snapshot.timestamp.split(" ")[-1][:5] if snapshot.timestamp else ""
            from pipeforge.core.workspace.snapshot_bridge import STATIC_ORIGIN

            if snapshot.matlab_version == STATIC_ORIGIN:
                self.matlab_chip.setText(f".mat ✓ {len(snapshot.variables)} vars")
                self.matlab_chip.setToolTip(
                    "Static .mat snapshot (no MATLAB) — click to swap in a live "
                    "MATLAB snapshot (adds fi formats)"
                )
            else:
                self.matlab_chip.setText(f"MATLAB ✓ {when} · {len(snapshot.variables)} vars")
                self.matlab_chip.setToolTip("Snapshot is current — click to refresh anyway")

    def _build_inspector(self) -> None:
        self.inspector = QDockWidget("Inspector")
        self.inspector.setObjectName("inspector")
        # docked only: never floats or detaches into a dead window (collapse is
        # via toggle_inspector / setVisible)
        self.inspector.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
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
        self.inspector.setVisible(not self.workspace.inspector_collapsed)  # persisted (UI-11)

    def toggle_inspector(self) -> None:
        """Collapse/expand the right inspector, reclaiming timeline space (UI-11)."""
        collapsed = not self.workspace.inspector_collapsed
        self.workspace.inspector_collapsed = collapsed
        self.inspector.setVisible(not collapsed)

    def _build_console(self) -> None:
        self.console_dock = QDockWidget("Console")
        self.console_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)
        self.console_dock.hide()

    # -- menus (every shortcut discoverable, UI-4) -------------------------------

    def _action(self, text: str, shortcut: str | QKeySequence.StandardKey, slot: object) -> QAction:
        act = QAction(text, self)
        if isinstance(shortcut, str):
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
        else:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)  # type: ignore[arg-type]
        self.addAction(act)  # window-level too: shortcuts work with menus closed
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        assert bar is not None

        file_menu = bar.addMenu("&File")
        assert file_menu is not None
        self.open_action = self._action("&Open…", QKeySequence.StandardKey.Open, self._open_dialog)
        file_menu.addAction(self.open_action)
        self.recent_menu = file_menu.addMenu("Open &Recent")
        assert self.recent_menu is not None
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)  # filled lazily (NF-3)
        self.demos_action = self._action("Open &Demos…", "Ctrl+Shift+D", self.open_demos)
        file_menu.addAction(self.demos_action)
        file_menu.addSeparator()
        self.report_action = self._action("Export HTML &Report…", "", self.export_report)
        file_menu.addAction(self.report_action)
        file_menu.addSeparator()
        quit_action = self._action("&Quit", QKeySequence.StandardKey.Quit, self.close)
        file_menu.addAction(quit_action)

        view_menu = bar.addMenu("&View")
        assert view_menu is not None
        self.view_actions: dict[str, QAction] = {}
        for name, label, _icon in CAPABILITIES:
            act = self._action(
                f"{label} — {DESCRIPTIONS.get(name, '')}",
                VIEW_SHORTCUTS.get(name, ""),
                lambda _c=False, n=name: self.show_view(n),
            )
            self.view_actions[name] = act
            view_menu.addAction(act)
        view_menu.addSeparator()
        self.inspector_action = self._action(
            "Toggle &Inspector", "Ctrl+Shift+I", self.toggle_inspector
        )
        view_menu.addAction(self.inspector_action)
        self.console_action = self._action("Toggle &Console", "Ctrl+`", self.toggle_console)
        view_menu.addAction(self.console_action)
        view_menu.addSeparator()
        self.palette_action = self._action("Command &Palette…", "Ctrl+K", self.open_palette)
        view_menu.addAction(self.palette_action)
        self.theme_menu = view_menu.addMenu("&Theme")
        assert self.theme_menu is not None
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)  # filled lazily (NF-3)

        run_menu = bar.addMenu("&Run")
        assert run_menu is not None
        self.rerun_action = self._action("&Re-run analysis", "Ctrl+R", self.workspace.rerun)
        run_menu.addAction(self.rerun_action)
        self.matlab_action = self._action(
            "Refresh from &MATLAB", "Ctrl+Shift+M", self.workspace.refresh_from_matlab
        )
        run_menu.addAction(self.matlab_action)

        help_menu = bar.addMenu("&Help")
        assert help_menu is not None
        self.shortcuts_action = self._action("&Keyboard Shortcuts…", "", self.open_shortcuts_dialog)
        help_menu.addAction(self.shortcuts_action)
        self.tools_action = self._action("&External Tools…", "", self.open_tools_dialog)
        help_menu.addAction(self.tools_action)
        about_action = self._action("&About PipeForge", "", self._about)
        help_menu.addAction(about_action)

    def _fill_recent_menu(self) -> None:
        menu = self.recent_menu
        menu.clear()
        recent = load_recent()
        if not recent:
            empty = menu.addAction("No recent files")
            assert empty is not None
            empty.setEnabled(False)
            return
        for path in recent:
            act = menu.addAction(path.name)
            assert act is not None
            act.setToolTip(str(path))
            act.triggered.connect(lambda _c=False, p=path: self.open_path(p))
        menu.addSeparator()
        clear = menu.addAction("Clear Menu")
        assert clear is not None
        clear.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        clear_recent()
        self.welcome.refresh()

    def _fill_theme_menu(self) -> None:
        menu = self.theme_menu
        menu.clear()
        for theme_name, display in self.themes.available().items():
            act = menu.addAction(display)
            assert act is not None
            act.setCheckable(True)
            act.setChecked(theme_name == self.themes.current_name)
            act.triggered.connect(
                lambda _c=False, n=theme_name: (self.themes.apply(n), self.themes.save())
            )

    def toggle_console(self) -> None:
        self.console_dock.setVisible(not self.console_dock.isVisible())

    def show_console(self) -> None:
        self.console_dock.setVisible(True)

    def _about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            "About PipeForge",
            f"<b>PipeForge {__version__}</b><br>"
            "MATLAB-to-nkMatlib FPGA pipeline workbench.<br><br>"
            "Audit, verify, visualize, and generate fixed-point pipelines "
            "targeting the nkMatlib SystemVerilog library.<br><br>"
            "<tt>pipeforge-cli -h</tt> exposes every capability headless.",
        )

    def open_shortcuts_dialog(self) -> None:
        from pipeforge.gui.widgets.shortcuts_dialog import ShortcutsDialog

        view_rows = [
            (VIEW_SHORTCUTS.get(name, ""), f"Go to {label}") for name, label, _ in CAPABILITIES
        ]
        dialog = ShortcutsDialog(view_rows, self)
        dialog.exec()

    def open_format_dialog(self) -> None:
        from pipeforge.gui.widgets.format_dialog import FormatDialog

        dialog = FormatDialog(self.workspace, self)
        dialog.exec()

    def open_tools_dialog(self) -> None:
        from pipeforge.gui.widgets.tools_dialog import ToolsDialog

        dialog = ToolsDialog(self)
        dialog.exec()
        self._update_tool_dots()  # the user may have installed something

    def export_report(self) -> None:
        """RH-1: one self-contained HTML design-review file for the open design."""
        audit = self.workspace.audit
        if audit is None:
            self.toast.show_message("Open a MATLAB file first — the report describes its audit.")
            return
        from pipeforge.core.costmodel.resources import estimate_resources
        from pipeforge.core.reports.html import build_report
        from pipeforge.core.svlint.checks import lint_source

        lint = None
        if self.workspace.sv_path is not None and self.workspace.sv_path.is_file():
            try:
                sv_text = self.workspace.sv_path.read_text(encoding="utf-8", errors="replace")
                lint = lint_source(
                    sv_text, self.workspace.sv_path.name, self.workspace.cost_model, audit=audit
                )
            except OSError:
                lint = None
        html = build_report(
            audit,
            resources=estimate_resources(audit.census, self.workspace.cost_model),
            lint=lint,
        )
        default = str((self.workspace.m_path or Path("design.m")).with_suffix(".report.html"))
        fname, _ = QFileDialog.getSaveFileName(self, "Export HTML report", default, "*.html")
        if fname:
            Path(fname).write_text(html, encoding="utf-8")
            self.toast.show_message(f"Report written: {fname}")

    def open_demos(self) -> None:
        from pipeforge.gui.widgets.demos_dialog import DemosDialog

        dialog = DemosDialog(self.open_path, self, navigate=self.show_view)
        dialog.exec()

    def _open_demo(self, entry: object) -> None:
        """Open a demo from the welcome screen and land on its view."""
        from pipeforge.demos import DemoEntry

        if not isinstance(entry, DemoEntry):
            return
        for path in entry.paths():
            self.open_path(path)
        if entry.view:
            self.show_view(entry.view)

    def palette_commands(self) -> list[tuple[str, object]]:
        commands: list[tuple[str, object]] = [
            ("Open file…", self._open_dialog),
            ("Open demos…", self.open_demos),
            ("Re-run audit", self.workspace.rerun),
            ("Refresh from MATLAB", self.workspace.refresh_from_matlab),
            ("Toggle console", self.toggle_console),
            ("Toggle inspector", self.toggle_inspector),
            ("Export HTML report…", self.export_report),
            ("Edit fixed-point format…", self.open_format_dialog),
            ("External tools…", self.open_tools_dialog),
            ("Keyboard shortcuts…", self.open_shortcuts_dialog),
        ]
        for name, label, _icon in CAPABILITIES:
            commands.append((f"Go to {label}", lambda n=name: self.show_view(n)))
        for theme_name, display in self.themes.available().items():
            commands.append(
                (
                    f"Theme: {display}",
                    lambda n=theme_name: (self.themes.apply(n), self.themes.save()),
                )
            )
        return commands

    def open_palette(self) -> None:
        from pipeforge.gui.widgets.palette import CommandPalette

        palette = CommandPalette(self)
        palette.set_commands(self.palette_commands())  # type: ignore[arg-type]
        palette.open_centered(self)
        self._palette = palette

    # -- behavior --------------------------------------------------------------

    def show_welcome(self) -> None:
        """The empty-workspace landing view: recent files, demos, open."""
        self.welcome.refresh()
        self.stack.setCurrentIndex(0)
        # no capability is active: release the exclusive nav selection
        self._nav_group.setExclusive(False)
        for btn in self.nav_buttons.values():
            btn.setChecked(False)
            btn.setProperty("active", False)
            style = btn.style()
            if style is not None:
                style.unpolish(btn)
                style.polish(btn)
        self._nav_group.setExclusive(True)

    def show_view(self, name: str) -> None:
        if name == "welcome":
            self.show_welcome()
            return
        if name in self._stack_names:
            # NOTE: the MO-2 opacity-effect cross-fade was removed — QGraphicsOpacityEffect
            # renders custom-painted views (timeline) and scroll areas black. View
            # switching is an instant, reliable set.
            self.stack.setCurrentIndex(self._stack_names.index(name))
            self.nav_buttons[name].setChecked(True)
            # UI-8: an unmistakable accent edge bar on the active item
            for n, btn in self.nav_buttons.items():
                btn.setProperty("active", n == name)
                style = btn.style()
                if style is not None:
                    style.unpolish(btn)
                    style.polish(btn)

    def current_view_name(self) -> str:
        return self._stack_names[self.stack.currentIndex()]

    def open_path(self, path: Path) -> None:
        self.workspace.open_file(path)

    def _open_dialog(self) -> None:
        fname, _ = QFileDialog.getOpenFileName(
            self, "Open MATLAB, SystemVerilog, or .mat file", "", "MATLAB/SV (*.m *.sv *.mat)"
        )
        if fname:
            self.open_path(Path(fname))

    # -- drag and drop: any supported file onto the window opens it ------------

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if event is None:
            return
        mime = event.mimeData()
        if mime is not None and any(
            url.isLocalFile() and url.toLocalFile().lower().endswith((".m", ".sv", ".mat"))
            for url in mime.urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent | None) -> None:
        if event is None:
            return
        mime = event.mimeData()
        if mime is None:
            return
        for url in mime.urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in (".m", ".sv", ".mat") and path.is_file():
                    self.open_path(path)
        event.acceptProposedAction()

    def log(self, text: str) -> None:
        self.console.appendPlainText(text)

    def _on_problem(self, message: str) -> None:
        self.log(message)
        self.toast.show_message(message, on_click=self.show_console)

    def _on_file(self, path: str) -> None:
        if not path:
            self.file_label.setText("No file open — Ctrl+O to begin, Ctrl+Shift+D for demos")
            self.source_view.setPlainText("")
            self.show_welcome()
            return
        self.file_label.setText(path)
        self.source_view.setPlainText(self.workspace.source)
        add_recent(Path(path))
        self.welcome.refresh()
        if self.current_view_name() == "welcome":
            # a file just arrived: land on the natural first view for its kind
            suffix = Path(path).suffix.lower()
            self.show_view({"": "audit", ".sv": "linter", ".mat": "golden"}.get(suffix, "audit"))

    def _on_audit(self, audit: object) -> None:
        if isinstance(audit, Audit):
            self.log(
                f"Audit: {audit.filename} — {audit.total_latency} cycles, "
                f"{len(audit.findings)} findings"
            )
        self._update_chips()

    def _refresh_mapping(self) -> None:
        """Populate the correspondence view from the current workspace (best-effort)."""
        view = self.views.get("mapping")
        if view is None or not hasattr(view, "load"):
            return
        sv_source = None
        if self.workspace.sv_path is not None:
            try:
                sv_source = self.workspace.sv_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                sv_source = None
        try:
            view.load(
                m_source=self.workspace.source or None,
                sv_source=sv_source,
                mat_path=self.workspace.mat_path,
                width=self.workspace.width,
                scale=self.workspace.scale,
            )
        except Exception as exc:  # never let the mapping view break the window (NF-4)
            self.log(f"mapping: could not refresh — {exc}")

    def _update_chips(self) -> None:
        # MO-3: an Adopt is made perceptible by the chip's value change; the
        # opacity-effect animation was removed (it races with teardown).
        self.format_chip.setText(f"{self.workspace.width}/{self.workspace.scale}")

    def _update_tool_dots(self) -> None:
        """Probe external tools on a worker thread; paint the dots when done."""
        from pipeforge.gui.toolprobe import probe_tools_async

        probe_tools_async(self._on_tools_detected)

    def _on_tools_detected(self, tools: object) -> None:
        if not isinstance(tools, dict):
            return
        dots = []
        tips = []
        for status in tools.values():
            dots.append("●" if status.available else "○")
            state = status.version if status.available else f"missing — {status.install_hint}"
            tips.append(f"{status.name}: {status.feature} — {state}")
        self.tools_chip.setText(" ".join(dots))
        self.tools_chip.setToolTip("\n".join(tips) + "\n\nClick for details and install commands.")

    def _source_context(self, line: int) -> str:
        """The originating source line in local context (not the whole file)."""
        lines = self.workspace.source.splitlines()
        if 1 <= line <= len(lines):
            return f"line {line}: {lines[line - 1].strip()}"
        return f"line {line}"

    def _on_selection(self, nid: str) -> None:
        audit = self.workspace.audit
        if audit is None or not nid or nid not in audit.dag.nodes:
            self.inspector_label.setText("Select a node to inspect it.")
            self.source_view.highlight_span(0, 0)
            return
        node = audit.dag.nodes[nid]
        # UI-7: structured node facts (kind, latency, ready, slack, findings,
        # the originating source line in local context) — never a full-file dump
        from pipeforge.core.viz.layout import compute_slack

        slack = compute_slack(audit.dag).get(nid, 0)
        related = [f"{f.tag} (line {f.line})" for f in audit.findings if f.node == nid]
        parts = [
            f"<b>{node.signal or node.label}</b>",
            f"kind: {node.module or 'wire'}",
            f"latency: {node.lat} — ready @ cycle {node.ready} — slack +{slack}",
        ]
        parts.append(self._source_context(node.line))
        if related:
            parts.append("findings: " + ", ".join(related))
        # WS-6: an operand resolving to a software.* field shows its facts here
        tree = self.workspace.software_tree
        field = tree.get(node.label) if tree is not None else None  # type: ignore[union-attr]
        if field is not None:
            shape = f"{field.shape[0]}x{field.shape[1]}"
            preview = field.text if field.text is not None else _fmt_values(field.values)
            parts.append(f"<i>software.{node.label}: {field.class_name} {shape} = {preview}</i>")
        snapshot = self.workspace.snapshot
        if snapshot is not None:
            info = snapshot.get(node.signal) or snapshot.get(node.label)
            if info is not None:
                size = "x".join(str(d) for d in info.size)
                live = [f"MATLAB: {info.class_name} {size}"]
                if info.fi is not None:
                    live.append(f"fi {info.fi.width}/{info.fi.scale}")
                if info.values:
                    preview = ", ".join(f"{v:.6g}" for v in info.values[:4])
                    more = "…" if len(info.values) > 4 or info.truncated else ""
                    live.append(f"= [{preview}{more}]")
                parts.append("<i>" + " — ".join(live) + "</i>")
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
        self.toast.reflow()
