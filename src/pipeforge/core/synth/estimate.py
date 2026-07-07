"""Quick yosys synthesis sanity-check (SY-1): cells + logic depth, no vendor tools.

Runs generic `synth` + `stat` + `ltp` on the design and parses the reports.
This is a *sanity estimate* — "will this come close to fitting / making
timing" — not a substitute for the vendor flow. Missing yosys degrades to an
actionable message, like every other optional tool.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class SynthUnavailable(RuntimeError):
    """yosys is missing or could not elaborate the design."""


@dataclass
class SynthEstimate:
    module: str
    cells: dict[str, int] = field(default_factory=dict)
    total_cells: int = 0
    wires: int = 0
    longest_path: int = -1  # topological levels (ltp), -1 when unavailable
    log: str = ""

    def summary(self) -> str:
        interesting = {k: v for k, v in sorted(self.cells.items()) if not k.startswith("$_")}
        head = ", ".join(f"{k} x{v}" for k, v in list(interesting.items())[:6])
        depth = f", longest path {self.longest_path} levels" if self.longest_path >= 0 else ""
        return f"{self.total_cells} cells ({head}){depth}"


_CELL_RE = re.compile(r"^\s{5,}(\$?\w+)\s+(\d+)\s*$")
_WIRES_RE = re.compile(r"Number of wires:\s+(\d+)")
_CELLS_RE = re.compile(r"Number of cells:\s+(\d+)")
_LTP_RE = re.compile(r"Longest topological path.*\(length=(\d+)\)")


def parse_stat(log: str) -> SynthEstimate:
    """Parse `stat` and `ltp` output into a SynthEstimate (yosys-free, testable)."""
    est = SynthEstimate(module="")
    in_stat = False
    for line in log.splitlines():
        if "Printing statistics." in line:
            in_stat = True
            est.cells = {}
            continue
        m = _WIRES_RE.search(line)
        if m:
            est.wires = int(m.group(1))
            continue
        m = _CELLS_RE.search(line)
        if m:
            est.total_cells = int(m.group(1))
            continue
        if in_stat:
            m = _CELL_RE.match(line)
            if m:
                est.cells[m.group(1)] = int(m.group(2))
        m = _LTP_RE.search(line)
        if m:
            est.longest_path = int(m.group(1))
    est.log = log
    return est


def slang_available(timeout: int = 20) -> bool:
    """True when the yosys-slang plugin (real SystemVerilog frontend) loads."""
    if shutil.which("yosys") is None:
        return False
    try:
        proc = subprocess.run(
            ["yosys", "-Q", "-p", "help read_slang"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "No such command" not in (proc.stdout + proc.stderr)


def run_synth_estimate(
    sources: list[Path],
    top: str,
    include_dirs: list[Path] | None = None,
    timeout: int = 300,
) -> SynthEstimate:
    """Run yosys generic synth + stat + ltp over the design (SY-1).

    nkMatlib-style SystemVerilog (interface ports, ``g.WIDTH`` in ranges) is
    beyond yosys's built-in Verilog frontend; when the yosys-slang plugin is
    installed it is used instead — with the include dirs' library files read
    alongside the design so the hierarchy elaborates.
    """
    if shutil.which("yosys") is None:
        raise SynthUnavailable(
            "synthesis estimate needs yosys (install: pacman -S yosys / apt install yosys)."
        )
    dirs = [d.resolve() for d in (include_dirs or [])]
    use_slang = slang_available()
    if use_slang:
        lib_files = sorted({f for d in dirs for f in d.glob("*.sv")})
        incs = " ".join(f"-I{d}" for d in dirs)
        files = " ".join(str(s.resolve()) for s in [*sources, *lib_files])
        reads = f"read_slang {incs} --top {top} {files}"
    else:
        incs = " ".join(f"-I{d}" for d in dirs)
        reads = "\n".join(f"read_verilog -sv {incs} {s.resolve()}" for s in sources)
    script = f"{reads}\nhierarchy -top {top}\nsynth -top {top}\nstat\nltp -noff\n"
    try:
        proc = subprocess.run(
            ["yosys", "-Q", "-T", "-p", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SynthUnavailable(f"yosys failed to run: {exc}") from exc
    log = proc.stdout + proc.stderr
    if proc.returncode != 0:
        tail = "\n".join(log.strip().splitlines()[-8:])
        hint = (
            ""
            if use_slang
            else "\nHint: nkMatlib-style SystemVerilog (interface ports, g.WIDTH ranges) "
            "needs the yosys-slang plugin — https://github.com/povik/yosys-slang"
        )
        raise SynthUnavailable(
            f"yosys could not elaborate the design (exit {proc.returncode}). "
            f"Last output:\n{tail}{hint}"
        )
    est = parse_stat(log)
    est.module = top
    return est
