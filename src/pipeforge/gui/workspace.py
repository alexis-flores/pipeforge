"""Global file/project context (UI-2).

One workspace per window: the loaded `.m` (and optional `.sv`), the
WIDTH/SCALE format, the optional live MATLAB snapshot, and the audit derived
from them. Every view reacts to its signals; selection is shared so views
stay synchronized (VZ-2).
"""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.varinfo import WorkspaceSnapshot


class _SnapshotSignals(QObject):
    finished = pyqtSignal(object)  # WorkspaceSnapshot
    failed = pyqtSignal(str)
    logged = pyqtSignal(str)


class _SnapshotJob(QRunnable):
    """Runs the MATLAB bridge off the GUI thread (UI-3).

    Routes through the warm session when one is alive (sub-second), else
    batch mode (cold start).
    """

    def __init__(self, script: Path | None, setup: Path | None) -> None:
        super().__init__()
        self.script = script
        self.setup = setup
        self.signals = _SnapshotSignals()

    def run(self) -> None:
        from pipeforge.services.matlab_bridge import MatlabUnavailable, snapshot_auto

        try:
            snapshot = snapshot_auto(
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


class _SessionStartJob(QRunnable):
    """Cold-starts the warm MATLAB session in the background."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = _SnapshotSignals()  # reuse: logged/failed

    def run(self) -> None:
        from pipeforge.services.matlab_bridge import MatlabUnavailable
        from pipeforge.services.matlab_session import MatlabSession

        session = MatlabSession()
        try:
            session.start(log=self.signals.logged.emit)
            self.signals.finished.emit(session)
        except MatlabUnavailable as exc:
            self.signals.failed.emit(str(exc))


class Workspace(QObject):
    auditChanged = pyqtSignal(object)  # Audit | None
    fileChanged = pyqtSignal(str)  # path ('' when cleared)
    formatChanged = pyqtSignal(int, int)  # width, scale
    selectionChanged = pyqtSignal(str)  # DAG node id ('' = cleared)
    snapshotChanged = pyqtSignal(object)  # WorkspaceSnapshot | None
    refreshStarted = pyqtSignal()  # MATLAB refresh in flight (busy chip)
    refreshFinished = pyqtSignal(str)  # human message: "11 variables in 0.4 s"
    snapshotStale = pyqtSignal(bool)  # watched files changed since the snapshot
    logMessage = pyqtSignal(str)  # console lines (MATLAB output etc.)
    problem = pyqtSignal(str)  # user-facing, non-fatal (NF-4 toast)
    densityChanged = pyqtSignal(str)  # 'comfortable' | 'compact' (UI-9)
    cosimFinished = pyqtSignal(object)  # CosimResult — feeds the Bisection view
    rangeFlagsChanged = pyqtSignal(object, object)  # overflow nids, hazard nids (RP GUI)

    #: sidecar autosave master switch — tests running on shared fixtures turn
    #: it off so no .pipeforge.toml appears next to repository files (PJ-1)
    sidecar_enabled = True

    def __init__(self) -> None:
        super().__init__()
        self.width = 16
        self.scale = 12
        self.m_path: Path | None = None
        self.sv_path: Path | None = None
        self.mat_path: Path | None = None  # opened .mat: session setup override
        self.software_tree: object | None = None  # WorkspaceTree from the .mat (WS-6)
        self.density = "comfortable"  # timeline density, per session (UI-9)
        self.project: object | None = None  # core.project.Project sidecar (PJ-1)
        self.project_ranges: dict[str, tuple[float, float]] = {}
        self.inspector_collapsed = False  # right inspector collapsed (UI-11)
        self.source = ""
        self.audit: Audit | None = None
        self.selected_node = ""
        self.snapshot: WorkspaceSnapshot | None = None
        self.stale = False
        self._refreshing = False
        self._refresh_started_at = 0.0
        self._session: object | None = None  # MatlabSession when warm

        # staleness + auto-sync: watch the open .m/.mat and the configured setup
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_watched_change)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._after_file_change)

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
                try:  # also load the struct tree for inspector resolution (WS-6)
                    from pipeforge.core.workspace.mat_loader import load_mat

                    self.software_tree = load_mat(path)
                except Exception as exc:  # never fatal (NF-4)
                    self.software_tree = None
                    self.logMessage.emit(f"workspace: could not parse {path.name}: {exc}")
                self._rearm_watcher()
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
        self._load_sidecar(path)
        self._rearm_watcher()
        self.fileChanged.emit(str(path))
        self._reaudit()

    # -- project sidecar (PJ-1): restore/persist per-design working state -------

    def _load_sidecar(self, m_path: Path) -> None:
        from pipeforge.core.project import Project, load_for_design

        project = load_for_design(m_path)
        if project is None:
            self.project = Project(m=m_path.name)
            self.project_ranges = {}
            return
        self.project = project
        self.project_ranges = dict(project.ranges)
        try:
            from pipeforge.core.costmodel.model import CostModel

            CostModel(project.width, project.scale)
            self.width, self.scale = project.width, project.scale
            self.formatChanged.emit(self.width, self.scale)
        except ValueError:
            pass
        sv = project.resolve(m_path.parent, project.sv)
        if sv is not None and sv.is_file():
            self.sv_path = sv
        self.logMessage.emit(f"project: restored {m_path.stem}.pipeforge.toml")

    def save_sidecar(self, create: bool = False) -> None:
        """Persist the working state next to the .m (PJ-1). Never raises.

        `create=True` writes a new sidecar (explicit user actions: propagating
        ranges, running cosim); otherwise only an existing sidecar is updated,
        so merely opening files never litters directories.
        """
        if not self.sidecar_enabled or self.m_path is None or self.project is None:
            return
        import os

        from pipeforge.core.project import Project, save_project, sidecar_for

        target = sidecar_for(self.m_path)
        if not create and not target.is_file():
            return
        project: Project = self.project  # type: ignore[assignment]
        project.m = self.m_path.name
        if self.sv_path is not None:
            project.sv = os.path.relpath(self.sv_path, self.m_path.parent)
        project.width, project.scale = self.width, self.scale
        project.ranges = dict(self.project_ranges)
        try:
            save_project(project, target)
        except OSError as exc:
            self.logMessage.emit(f"project: could not save sidecar — {exc}")

    def set_project_ranges(self, ranges: dict[str, tuple[float, float]]) -> None:
        """Ranges the user declared in the Ranges view: persist them (PJ-1)."""
        self.project_ranges = dict(ranges)
        self.save_sidecar(create=True)

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
        self.save_sidecar()  # updates an existing sidecar only (PJ-1)
        self._reaudit()

    def rerun(self) -> None:
        """Re-run the current analysis (UI-4, Ctrl+R)."""
        self._reaudit()

    def set_density(self, density: str) -> None:
        """Comfortable/compact timeline density, remembered for the session (UI-9)."""
        density = "compact" if density == "compact" else "comfortable"
        if density != self.density:
            self.density = density
            self.densityChanged.emit(density)

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
        self._refresh_started_at = time.monotonic()
        self.refreshStarted.emit()
        self.logMessage.emit("matlab: refreshing workspace snapshot…")
        job = _SnapshotJob(self.m_path, setup)
        job.signals.logged.connect(self.logMessage.emit)
        job.signals.finished.connect(self._on_snapshot)
        job.signals.failed.connect(self._on_snapshot_failed)
        QThreadPool.globalInstance().start(job)

    @property
    def refreshing(self) -> bool:
        return self._refreshing

    def _on_snapshot(self, snapshot: object) -> None:
        self._refreshing = False
        if isinstance(snapshot, WorkspaceSnapshot):
            elapsed = time.monotonic() - self._refresh_started_at
            self.snapshot = snapshot
            self._set_stale(False)
            if snapshot.error:
                self.problem.emit(f"MATLAB ran with an error (partial snapshot): {snapshot.error}")
            self.snapshotChanged.emit(snapshot)
            message = f"{len(snapshot.variables)} variables in {elapsed:.1f} s"
            self.logMessage.emit(f"matlab: snapshot of {message} ({snapshot.timestamp})")
            self.refreshFinished.emit(message)
            self._reaudit()

    def _on_snapshot_failed(self, message: str) -> None:
        self._refreshing = False
        self.refreshFinished.emit("")  # clears the busy chip; toast carries the error
        self.problem.emit(message)

    # -- staleness + auto-sync -------------------------------------------------

    def _watch_targets(self) -> list[Path]:
        from pipeforge.services.matlab_bridge import MatlabConfig

        targets = [self.m_path, self.mat_path, MatlabConfig.load().setup]
        return [t for t in targets if t is not None and t.is_file()]

    def _rearm_watcher(self) -> None:
        old = self._watcher.files()
        if old:
            self._watcher.removePaths(old)
        targets = [str(t) for t in self._watch_targets()]
        if targets:
            self._watcher.addPaths(targets)

    def _on_watched_change(self, _path: str) -> None:
        self._debounce.start()  # editors replace files; debounce the burst

    def _after_file_change(self) -> None:
        import contextlib

        self._rearm_watcher()  # re-add paths dropped by file replacement
        if self.m_path is not None:  # the source may have changed: re-audit
            with contextlib.suppress(OSError):
                self.source = self.m_path.read_text(encoding="utf-8", errors="replace")
        from pipeforge.services.matlab_bridge import MatlabConfig
        from pipeforge.services.matlab_session import server_alive

        if self.snapshot is None:
            self._reaudit()
            return
        if MatlabConfig.load().auto_refresh and server_alive() and not self._refreshing:
            self.logMessage.emit("matlab: files changed — auto-refreshing (warm session)")
            self.refresh_from_matlab()
        else:
            self._set_stale(True)
            self._reaudit()

    def _set_stale(self, stale: bool) -> None:
        if stale != self.stale:
            self.stale = stale
            self.snapshotStale.emit(stale)

    # -- warm session lifecycle ---------------------------------------------------

    def start_warm_session(self) -> None:
        """Cold-start the background MATLAB session (non-blocking)."""
        from pipeforge.services.matlab_session import server_alive

        if server_alive():
            return
        job = _SessionStartJob()
        job.signals.logged.connect(self.logMessage.emit)
        job.signals.finished.connect(self._on_session_started)
        job.signals.failed.connect(self.problem.emit)
        QThreadPool.globalInstance().start(job)

    def _on_session_started(self, session: object) -> None:
        self._session = session

    def stop_warm_session(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            stop = getattr(session, "stop", None)
            if callable(stop):
                stop()

    # -- selection (VZ-2) ----------------------------------------------------

    def select_node(self, nid: str) -> None:
        if nid != self.selected_node:
            self.selected_node = nid
            self.selectionChanged.emit(nid)
