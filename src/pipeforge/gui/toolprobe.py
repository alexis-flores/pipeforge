"""Background external-tool probing (NF-3): subprocess probes off the GUI thread.

Shared by the status-bar dots and the Settings view. The signal classes live
at module scope on purpose: classes defined inside a method can be collected
before a queued cross-thread emission is delivered, which corrupts delivery.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from pipeforge.services.tools import detect_tools


class ToolProbeSignals(QObject):
    done = pyqtSignal(object)  # dict[str, ToolStatus]


class ToolProbeJob(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = ToolProbeSignals()

    def run(self) -> None:
        self.signals.done.emit(detect_tools())


#: In-flight jobs: keeps the signals object alive until delivery.
_active: set[ToolProbeJob] = set()


def probe_tools_async(callback: Callable[[object], None]) -> None:
    """Run detect_tools() on a worker thread; deliver the dict to callback."""
    job = ToolProbeJob()
    _active.add(job)

    def _deliver(tools: object, job: ToolProbeJob = job) -> None:
        _active.discard(job)
        callback(tools)

    job.signals.done.connect(_deliver)
    QThreadPool.globalInstance().start(job)
