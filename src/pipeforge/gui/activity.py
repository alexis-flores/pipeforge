"""Activity entries (UX-2): the app remembers what it did for you.

Pure data — the Workspace emits these, the Activity panel renders them, and
toasts reference them. One entry per meaningful action: a file opened, an
optimize written, RTL generated, a co-simulation verdict, a sidecar saved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActivityEntry:
    kind: str  # 'success' | 'info' | 'warning' | 'error'
    title: str  # one line: what happened
    detail: str = ""  # the numbers: cycles, dividers, vectors, rewrites
    path: str = ""  # produced/affected file (clickable in the panel)
    when: str = field(default_factory=lambda: time.strftime("%H:%M:%S"))
