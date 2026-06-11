"""Global file/project context (UI-2).

One workspace per window: the loaded `.m` (and optional `.sv`), the
WIDTH/SCALE format, the optional live MATLAB snapshot, and the audit derived
from them. Every view reacts to its signals; selection is shared so views
stay synchronized (VZ-2).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.varinfo import WorkspaceSnapshot


class _SnapshotSignals(QObject):
    finished = pyqtSignal(object)  # WorkspaceSnapshot
    failed = pyqtSignal(str)
    logged = pyqtSignal(str)


class _SnapshotJob(QRunnable):
    """Runs the MATLAB bridge off the GUI thread (UI-3); MATLAB is slow."""

    def __init__(self, script: Path | None, setup: Path | None) -> None:
        super().__init__()
        self.script = script
        self.setup = setup
        self.signals = _SnapshotSignals()

    def run(self) -> None:
        from pipeforge.services.matlab_bridge import MatlabUnavailable, take_snapshot

        try:
            snapshot = take_snapshot(
                self.script,
                setup=self.setup,
                force=True,  # the GUI refresh is the explicit retake
                log=self.signals.logged.emit,
            )
            self.signals.finished.emit(snapshot)
        except MatlabUnavailable as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            self.signals.failed.emit(f"MATLAB refresh failed: {exc}")


class Workspace(QObject):
    auditChanged = pyqtSignal(object)  # Audit | None
    fileChanged = pyqtSignal(str)  # path ('' when cleared)
    formatChanged = pyqtSignal(int, int)  # width, scale
    selectionChanged = pyqtSignal(str)  # DAG node id ('' = cleared)
    snapshotChanged = pyqtSignal(object)  # WorkspaceSnapshot | None
    logMessage = pyqtSignal(str)  # console lines (MATLAB output etc.)
    problem = pyqtSignal(str)  # user-facing, non-fatal (NF-4 toast)

    def __init__(self) -> None:
        super().__init__()
        self.width = 16
        self.scale = 12
        self.m_path: Path | None = None
        self.sv_path: Path | None = None
        self.mat_path: Path | None = None  # opened .mat: session setup override
        self.source = ""
        self.audit: Audit | None = None
        self.selected_node = ""
        self.snapshot: WorkspaceSnapshot | None = None
        self._refreshing = False

    @property
    def cost_model(self) -> CostModel:
        return CostModel(self.width, self.scale)

    # -- loading -----------------------------------------------------------

    def open_file(self, path: Path) -> None:
        """Open a .m (audits it), a companion .sv, or a .mat parameter file.

        Opening a .mat never starts MATLAB (manual-refresh policy); it becomes
        this session's workspace setup — Ctrl+Shift+M loads it, alone or
        before the open script. Never raises (NF-4).
        """
        try:
            if path.suffix.lower() == ".sv":
                self.sv_path = path
                self.fileChanged.emit(str(path))
                return
            if path.suffix.lower() == ".mat":
                self.mat_path = path
                self.fileChanged.emit(str(path))
                self.logMessage.emit(
                    f"workspace: {path.name} set as MATLAB setup — refresh "
                    "(Ctrl+Shift+M) to load and browse it"
                )
                return
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.problem.emit(f"Cannot open {path.name}: {exc.strerror or exc}")
            return
        if self.m_path is not None and path != self.m_path:
            self.snapshot = None  # a different script: stale workspace data
            self.snapshotChanged.emit(None)
        self.m_path = path
        self.source = text
        sv = path.with_suffix(".sv")
        if sv.is_file():
            self.sv_path = sv
        self.fileChanged.emit(str(path))
        self._reaudit()

    def set_format(self, width: int, scale: int) -> None:
        """WIDTH/SCALE are workspace-level; all views react live (UI-2)."""
        try:
            CostModel(width, scale)
        except ValueError as exc:
            self.problem.emit(str(exc))
            return
        if (width, scale) == (self.width, self.scale):
            return
        self.width = width
        self.scale = scale
        self.formatChanged.emit(width, scale)
        self._reaudit()

    def rerun(self) -> None:
        """Re-run the current analysis (UI-4, Ctrl+R)."""
        self._reaudit()

    def _reaudit(self) -> None:
        if self.m_path is None:
            return
        try:
            self.audit = audit_source(
                self.source, self.m_path.name, self.cost_model, snapshot=self.snapshot
            )
        except Exception as exc:
            self.audit = None
            self.problem.emit(f"Audit failed: {exc}")
        self.auditChanged.emit(self.audit)

    # -- MATLAB bridge (manual refresh only; MATLAB start is slow) ----------

    def refresh_from_matlab(self) -> None:
        """Snapshot the live MATLAB workspace, then re-audit with it.

        Works with a .m script (setup loaded first), a .mat alone (load-only
        snapshot for browsing parameter types), or both.
        """
        from pipeforge.services.matlab_bridge import MatlabConfig

        setup = self.mat_path if self.mat_path is not None else MatlabConfig.load().setup
        if self.m_path is None and setup is None:
            self.problem.emit(
                "Open a MATLAB script or a .mat parameter file first, then refresh from MATLAB."
            )
            return
        if self._refreshing:
            self.problem.emit("A MATLAB refresh is already running.")
            return
        self._refreshing = True
        self.logMessage.emit("matlab: refreshing workspace snapshot…")
        job = _SnapshotJob(self.m_path, setup)
        job.signals.logged.connect(self.logMessage.emit)
        job.signals.finished.connect(self._on_snapshot)
        job.signals.failed.connect(self._on_snapshot_failed)
        QThreadPool.globalInstance().start(job)

    def _on_snapshot(self, snapshot: object) -> None:
        self._refreshing = False
        if isinstance(snapshot, WorkspaceSnapshot):
            self.snapshot = snapshot
            if snapshot.error:
                self.problem.emit(f"MATLAB ran with an error (partial snapshot): {snapshot.error}")
            self.snapshotChanged.emit(snapshot)
            self.logMessage.emit(
                f"matlab: snapshot of {len(snapshot.variables)} variables ({snapshot.timestamp})"
            )
            self._reaudit()

    def _on_snapshot_failed(self, message: str) -> None:
        self._refreshing = False
        self.problem.emit(message)

    # -- selection (VZ-2) ----------------------------------------------------

    def select_node(self, nid: str) -> None:
        if nid != self.selected_node:
            self.selected_node = nid
            self.selectionChanged.emit(nid)
