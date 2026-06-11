"""External tool detection (Appendix B, C2).

Probes are subprocess-based, cheap, and never raise: a missing tool yields
an unavailable status with an actionable install hint.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolStatus:
    name: str
    available: bool
    version: str
    feature: str  # what the tool unlocks (status-bar tooltip)
    install_hint: str


_PROBES: list[tuple[str, list[str], str, str]] = [
    (
        "verilator",
        ["verilator", "--version"],
        "co-simulation (CS)",
        "sudo pacman -S verilator / apt install verilator",
    ),
    (
        "dot",
        ["dot", "-V"],
        "graphviz DAG layout (VZ)",
        "sudo pacman -S graphviz / apt install graphviz",
    ),
    (
        "yosys",
        ["yosys", "-V"],
        "formal verification (FV)",
        "sudo pacman -S yosys / apt install yosys",
    ),
    (
        "sby",
        ["sby", "--help"],
        "formal verification (FV)",
        "pip install symbiyosys or distro package",
    ),
]

_PY_PROBES: list[tuple[str, str, str]] = [
    ("cocotb", "co-simulation testbenches (CS)", "pip install cocotb"),
    ("pyslang", "full SystemVerilog parsing (SL)", "pip install pyslang"),
]


def _probe_exe(name: str, cmd: list[str], feature: str, hint: str) -> ToolStatus:
    if shutil.which(cmd[0]) is None:
        return ToolStatus(name, False, "", feature, hint)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = (proc.stdout or proc.stderr).strip().splitlines()
        version = out[0] if out else "unknown"
        return ToolStatus(name, True, version, feature, hint)
    except (OSError, subprocess.SubprocessError):
        return ToolStatus(name, False, "", feature, hint)


def _probe_module(name: str, feature: str, hint: str) -> ToolStatus:
    if importlib.util.find_spec(name) is not None:
        version = "installed"
        mod = sys.modules.get(name)
        if mod is not None:
            version = getattr(mod, "__version__", "installed")
        return ToolStatus(name, True, version, feature, hint)
    return ToolStatus(name, False, "", feature, hint)


def _probe_matlab() -> ToolStatus:
    # Fast check only — actually starting MATLAB takes seconds and happens
    # exclusively on explicit refresh (services.matlab_bridge).
    from pipeforge.services.matlab_bridge import MatlabConfig, fast_available

    cfg = MatlabConfig.load()
    available = fast_available(cfg)
    return ToolStatus(
        "matlab",
        available,
        cfg.command[0] if available else "",
        "live workspace snapshots (MATLAB bridge)",
        "configure the MATLAB command in Settings (default: matlab-sandbox distrobox)",
    )


def detect_tools() -> dict[str, ToolStatus]:
    """Probe every optional external tool (Appendix B)."""
    out: dict[str, ToolStatus] = {}
    for name, cmd, feature, hint in _PROBES:
        out[name] = _probe_exe(name, cmd, feature, hint)
    for name, feature, hint in _PY_PROBES:
        out[name] = _probe_module(name, feature, hint)
    out["matlab"] = _probe_matlab()
    return out


def tool_available(name: str) -> bool:
    tools = detect_tools()
    return name in tools and tools[name].available
