"""Design-space exploration view (DSE-1, DSE-2, UI-3).

Sweeps run off the GUI thread with progress and cancellation; the Pareto
front is plotted (error vs latency, divider count in the tooltip), point
selection reveals the configuration, and one click adopts the WIDTH/SCALE
into the workspace.
"""

from __future__ import annotations

from dataclasses import asdict
from threading import Event

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.dse.sweep import (
    SweepCancelled,
    SweepConfig,
    SweepPoint,
    pareto_front,
    run_sweep,
)
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.workspace import Workspace


class _SweepSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class _SweepJob(QRunnable):
    def __init__(self, src: str, filename: str, config: SweepConfig, cancel: Event) -> None:
        super().__init__()
        self.src = src
        self.filename = filename
        self.config = config
        self.cancel = cancel
        self.signals = _SweepSignals()

    def run(self) -> None:
        try:
            points = run_sweep(
                self.src,
                self.filename,
                self.config,
                progress=lambda d, t: self.signals.progress.emit(d, t),
                cancel=self.cancel,
            )
            self.signals.finished.emit(points)
        except SweepCancelled as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            self.signals.failed.emit(f"Sweep failed: {exc}")


class DseView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self._theme: Theme | None = None
        self._points: list[SweepPoint] = []
        self._front: list[SweepPoint] = []
        self._cancel = Event()

        title = QLabel("Exploration")
        title.setObjectName("viewTitle")
        self.status = QLabel("Open a MATLAB file, set the grids, then run the sweep.")
        self.status.setObjectName("muted")

        self.widths_edit = QLineEdit("12,16,20,24")
        self.scales_edit = QLineEdit("8,12,16")
        self.run_btn = QPushButton("Run sweep")
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_sweep)
        self.cancel_btn.setEnabled(False)
        self.adopt_btn = QPushButton("Adopt selected")
        self.adopt_btn.clicked.connect(self._adopt_selected)
        self.adopt_btn.setEnabled(False)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Widths"))
        controls.addWidget(self.widths_edit)
        controls.addWidget(QLabel("Scales"))
        controls.addWidget(self.scales_edit)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.cancel_btn)
        controls.addStretch(1)
        controls.addWidget(self.adopt_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.plot = self._make_plot()

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Pareto", "WIDTH/SCALE", "Latency", "Dividers", "max |error|", "RMS", "SQNR dB"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_selection)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.status)
        box.addLayout(controls)
        box.addWidget(self.progress)
        if self.plot is not None:
            box.addWidget(self.plot, 1)
        box.addWidget(self.table, 1)

    def _make_plot(self) -> QWidget | None:
        try:
            import pyqtgraph as pg
        except ImportError:
            return None
        widget = pg.PlotWidget()
        widget.setLabel("bottom", "critical-path latency (cycles)")
        widget.setLabel("left", "max |error|")
        widget.setLogMode(y=True)
        self._scatter_all = pg.ScatterPlotItem(size=8)
        self._scatter_front = pg.ScatterPlotItem(size=12, symbol="star")
        widget.addItem(self._scatter_all)
        widget.addItem(self._scatter_front)
        return widget

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        if self.plot is not None:
            self.plot.setBackground(theme.tokens.get("plotBg", theme["bg"]))
            self._restyle_points()

    # -- sweep -----------------------------------------------------------------

    def _parse_grid(self, text: str) -> tuple[int, ...]:
        return tuple(int(x) for x in text.replace(" ", "").split(",") if x)

    def _run(self) -> None:
        if self._ws.m_path is None:
            self._ws.problem.emit("Open a MATLAB file first, then run the sweep.")
            return
        try:
            config = SweepConfig(
                widths=self._parse_grid(self.widths_edit.text()),
                scales=self._parse_grid(self.scales_edit.text()),
                vectors=64,
            )
        except ValueError:
            self._ws.problem.emit("Grids must be comma-separated integers, e.g. 12,16,20.")
            return
        if not config.points():
            self._ws.problem.emit("The grid is empty: every SCALE must be below some WIDTH.")
            return
        self._cancel = Event()
        job = _SweepJob(self._ws.source, self._ws.m_path.name, config, self._cancel)
        job.signals.progress.connect(self._on_progress)
        job.signals.finished.connect(self._on_finished)
        job.signals.failed.connect(self._on_failed)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(config.points()))
        self.progress.setValue(0)
        self.status.setText(f"Sweeping {len(config.points())} configurations…")
        QThreadPool.globalInstance().start(job)

    def _cancel_sweep(self) -> None:
        self._cancel.set()
        self.status.setText("Cancelling after the current point…")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.status.setText(message)

    def _on_finished(self, points: list[SweepPoint]) -> None:
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.set_points(points)

    # -- presentation -------------------------------------------------------------

    def set_points(self, points: list[SweepPoint]) -> None:
        self._points = list(points)
        self._front = pareto_front(points)
        front_keys = {p.key for p in self._front}
        self.status.setText(
            f"{len(points)} configurations; {len(self._front)} on the Pareto front. "
            "Select a row and adopt it."
        )
        self.table.setRowCount(len(points))
        ordered = sorted(points, key=lambda p: (p.key not in front_keys, p.max_abs_error))
        self._ordered = ordered
        for r, p in enumerate(ordered):
            star = "★" if p.key in front_keys else ""
            cells = [
                star,
                f"{p.width}/{p.scale}",
                str(p.latency),
                str(p.dividers),
                f"{p.max_abs_error:.4g}",
                f"{p.rms_error:.4g}",
                f"{p.sqnr_db:.1f}",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(str(asdict(p)))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self._restyle_points()

    def _restyle_points(self) -> None:
        if self.plot is None or self._theme is None or not self._points:
            return
        t = self._theme

        def xy(pts: list[SweepPoint]) -> tuple[list[float], list[float]]:
            return (
                [float(p.latency) for p in pts],
                [max(p.max_abs_error, 1e-12) for p in pts],
            )

        x_all, y_all = xy(self._points)
        self._scatter_all.setData(x=x_all, y=y_all, brush=t["accentMuted"], pen=None)
        x_f, y_f = xy(self._front)
        self._scatter_front.setData(x=x_f, y=y_f, brush=t["accent"], pen=t["focusRing"])

    # -- adopt (DSE-2) ---------------------------------------------------------------

    def selected_point(self) -> SweepPoint | None:
        row = self.table.currentRow()
        if 0 <= row < len(getattr(self, "_ordered", [])):
            return self._ordered[row]
        return None

    def _on_selection(self) -> None:
        self.adopt_btn.setEnabled(self.selected_point() is not None)

    def _adopt_selected(self) -> None:
        point = self.selected_point()
        if point is not None:
            self.adopt(point)

    def adopt(self, point: SweepPoint) -> None:
        """One-click 'adopt this WIDTH/SCALE': updates the workspace (DSE-2)."""
        self._ws.set_format(point.width, point.scale)
        self.status.setText(f"Adopted {point.width}/{point.scale} — every view now reflects it.")
