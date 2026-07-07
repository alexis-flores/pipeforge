"""File-watching loop for headless iteration (WT-1).

`pipeforge-cli audit --watch` re-runs on every save — matching how RTL
engineers actually iterate (editor + terminal, no GUI). Plain mtime polling:
portable, no dependencies, cheap at the 0.5 s cadence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path


def _mtimes(paths: list[Path]) -> dict[Path, float]:
    out: dict[Path, float] = {}
    for p in paths:
        try:
            out[p] = p.stat().st_mtime
        except OSError:
            out[p] = -1.0
    return out


def watch_loop(
    paths: list[Path],
    run: Callable[[], None],
    poll_seconds: float = 0.5,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run once, then re-run whenever any watched file's mtime changes (WT-1).

    `max_iterations` bounds the number of *re-runs* (None = forever, until
    KeyboardInterrupt). Returns the number of re-runs performed.
    """
    run()
    seen = _mtimes(paths)
    reruns = 0
    try:
        while max_iterations is None or reruns < max_iterations:
            sleep(poll_seconds)
            now = _mtimes(paths)
            if now != seen:
                seen = now
                run()
                reruns += 1
    except KeyboardInterrupt:
        pass
    return reruns
