"""Waveform hand-off (WV-1): a GTKWave save file pointing at the divergence.

After a failing co-simulation with a VCD trace, an engineer's next step is a
waveform viewer — where they must rebuild by hand the context PipeForge
already has (which signals matter, which cycle failed). This module writes a
``.gtkw`` save file that pre-loads exactly the relevant signals — stimulus,
the divergent stage's operands and output, the primary outputs — with the
cursor parked on the failing cycle. ``gtkwave dump.vcd divergence.gtkw`` (or
Surfer, which reads the same format) opens ready to debug.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeforge.core.bisect.engine import BisectReport
from pipeforge.core.cosim.trace import node_signal_name
from pipeforge.core.frontend.dag import Dag


@dataclass(frozen=True)
class VcdSignal:
    full_path: str  # hierarchical, dot-separated
    width: int


def vcd_signal_index(vcd_text: str) -> dict[str, VcdSignal]:
    """Leaf name -> (full hierarchical path, width) from the VCD header.

    Later duplicates of a leaf name are ignored (first scope wins), matching
    the leaf-name convention trace reconstruction uses.
    """
    scopes: list[str] = []
    out: dict[str, VcdSignal] = {}
    for raw in vcd_text.splitlines():
        s = raw.strip()
        if s.startswith("$scope"):
            toks = s.split()
            if len(toks) >= 3:
                scopes.append(toks[2])
        elif s.startswith("$upscope"):
            if scopes:
                scopes.pop()
        elif s.startswith("$var"):
            toks = s.split()
            if len(toks) >= 5:
                leaf = toks[4].split("[")[0]
                try:
                    width = int(toks[2])
                except ValueError:
                    width = 1
                path = ".".join([*scopes, leaf])
                out.setdefault(leaf, VcdSignal(path, width))
        elif s.startswith("$enddefinitions"):
            break
    return out


def clk_posedge_times(vcd_text: str, clk_signal: str = "clk") -> list[int]:
    """Timestamps of every clk posedge in the dump."""
    sym = None
    for raw in vcd_text.splitlines():
        s = raw.strip()
        if s.startswith("$var"):
            toks = s.split()
            if len(toks) >= 5 and toks[4].split("[")[0] == clk_signal:
                sym = toks[3]
                break
    if sym is None:
        return []
    times: list[int] = []
    now = 0
    prev = 0
    for raw in vcd_text.splitlines():
        s = raw.strip()
        if not s or s.startswith("$"):
            continue
        if s[0] == "#":
            try:
                now = int(s[1:])
            except ValueError:
                continue
        elif s[0] in "01" and s[1:] == sym:
            val = 1 if s[0] == "1" else 0
            if val == 1 and prev == 0:
                times.append(now)
            prev = val
    return times


def _valid_cycle_indices(vcd_text: str, valid_signal: str = "valid_N") -> list[int]:
    """Posedge indices at which valid_N was high (same alignment as trace.py)."""
    from pipeforge.core.cosim.trace import _vcd_name_to_sym, _vcd_value

    syms = _vcd_name_to_sym(vcd_text)
    valid_sym = syms.get(valid_signal)
    clk_sym = syms.get("clk")
    if valid_sym is None or clk_sym is None:
        return []
    current: dict[str, int] = {}
    valids: list[int] = []
    clk_prev = 0
    seen_ts = False

    def settle() -> None:
        nonlocal clk_prev
        clk_now = current.get(clk_sym, 0)
        if clk_now == 1 and clk_prev == 0:
            valids.append(current.get(valid_sym, 0))
        clk_prev = clk_now

    for raw in vcd_text.splitlines():
        s = raw.strip()
        if not s or s.startswith("$"):
            continue
        c = s[0]
        if c == "#":
            if seen_ts:
                settle()
            seen_ts = True
        elif c in "bB":
            val, _, sym = s.partition(" ")
            current[sym.strip()] = _vcd_value(val)
        elif c in "01xzXZ" and len(s) >= 2:
            current[s[1:]] = 1 if c == "1" else 0
    settle()
    return [i for i, v in enumerate(valids) if v == 1]


def divergence_cursor_time(
    vcd_text: str, latency: int, ready: int, vector_index: int
) -> int | None:
    """Dump time of the cycle where the divergent stage held the failing vector."""
    posedges = clk_posedge_times(vcd_text)
    valid_cycles = _valid_cycle_indices(vcd_text)
    if vector_index < 0 or vector_index >= len(valid_cycles):
        return None
    idx = valid_cycles[vector_index] - (latency - ready)
    if 0 <= idx < len(posedges):
        return posedges[idx]
    return None


def _entry(index: dict[str, VcdSignal], leaf: str) -> str | None:
    sig = index.get(leaf)
    if sig is None:
        return None
    return f"{sig.full_path}[{sig.width - 1}:0]" if sig.width > 1 else sig.full_path


def render_gtkw(
    vcd_path: Path,
    dag: Dag,
    latency: int,
    report: BisectReport | None,
    vcd_text: str | None = None,
) -> str:
    """Render the GTKWave save file contents (WV-1)."""
    text = vcd_text if vcd_text is not None else vcd_path.read_text(encoding="utf-8")
    index = vcd_signal_index(text)
    lines = [
        "[*] generated by pipeforge — signals around the co-sim divergence",
        f'[dumpfile] "{vcd_path.resolve()}"',
        "[timestart] 0",
    ]
    cursor = None
    if report is not None and report.diverged and report.node in dag.nodes:
        node = dag.nodes[report.node]
        cursor = divergence_cursor_time(text, latency, node.ready, report.vector_index)
    if cursor is not None:
        lines.append(f"*-10.000000 {cursor} -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1")

    def group(title: str, leaves: list[str]) -> None:
        entries = [e for e in (_entry(index, leaf) for leaf in leaves) if e is not None]
        if not entries:
            return
        lines.append(f"-{title}")
        lines.extend(entries)

    group("stimulus", ["valid_0", *[f"{n.label}_0" for n in dag.inputs()]])
    if report is not None and report.diverged and report.node in dag.nodes:
        node = dag.nodes[report.node]
        operand_leaves = []
        for arg in node.args:
            arg_node = dag.nodes[arg]
            if arg_node.module not in ("const",):
                operand_leaves.append(node_signal_name(arg_node))
        group(
            f"divergence @ stage {node.ready}: {node.signal or node.label} "
            f"({report.classification})",
            [*operand_leaves, node_signal_name(node)],
        )
    group("outputs", ["valid_N", *[f"{n.signal}_N" for n in dag.outputs() if n.signal]])
    lines.append("[pattern_trace] 0")
    return "\n".join(lines) + "\n"


def write_gtkw(work_dir: Path, dag: Dag, latency: int, report: BisectReport | None) -> Path | None:
    """Write divergence.gtkw next to the newest VCD in work_dir; None if no VCD."""
    vcds = sorted(work_dir.rglob("*.vcd"))
    if not vcds:
        return None
    vcd = vcds[0]
    try:
        content = render_gtkw(vcd, dag, latency, report)
    except (OSError, ValueError):
        return None
    out = work_dir / "divergence.gtkw"
    out.write_text(content, encoding="utf-8")
    return out
