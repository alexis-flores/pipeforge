"""Small GUI-side detection helpers (no Qt imports; unit-testable)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def detect_matlib_rtl(start: Path | None) -> Path | None:
    """Walk up from a design file looking for a bundled nkMatlib rtl dir."""
    if start is None:
        return None
    for parent in start.resolve().parents:
        candidate = parent / "matlib-main" / "rtl"
        if candidate.is_dir():
            return candidate
    return None


def open_in_gtkwave(work_dir: Path, gtkw_file: Path) -> str | None:
    """Launch GTKWave detached on the run's VCD + save file (WV-1).

    Returns an error message (None on success) — callers surface it as a
    toast; a missing viewer must never crash anything.
    """
    if shutil.which("gtkwave") is None:
        return (
            "GTKWave is not installed — install it (brew/apt/pacman install gtkwave) "
            f"or open the save file manually: {gtkw_file}"
        )
    vcds = sorted(work_dir.rglob("*.vcd"))
    if not vcds:
        return f"no VCD found under {work_dir}"
    try:
        subprocess.Popen(
            ["gtkwave", str(vcds[0]), str(gtkw_file)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return f"could not launch gtkwave: {exc}"
    return None
