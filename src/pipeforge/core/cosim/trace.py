"""VCD/FST trace capture — the fallback for hand-written RTL (CS-8).

The probe backend (CS-7) is the robust primary: it works on generated RTL by
adding explicit output ports. For hand-written RTL that cannot be re-emitted,
this fallback drives Verilator with trace dumping and reconstructs per-node
streams by mapping each DAG node id to its conventional signal name
(``<signal>_<stage>``) and sampling that signal whenever the output valid is
high. The active backend is reported, mirroring the SL-1 pyslang/regex pattern.
"""

from __future__ import annotations

import re

from pipeforge.core.bisect.engine import Observations
from pipeforge.core.frontend.dag import Dag, Node

CAPTURE_PROBE = "probe"
CAPTURE_TRACE = "trace"


def node_signal_name(node: Node) -> str:
    """The DUT signal carrying a node's value: ``<signal>_<ready stage>``."""
    base = node.signal or node.nid
    return f"{base}_{node.ready}"


def trace_signal_map(dag: Dag, nids: list[str]) -> dict[str, str]:
    """Map DAG node ids to their conventional RTL signal names (CS-8)."""
    return {nid: node_signal_name(dag.nodes[nid]) for nid in nids}


def active_capture_backend(probes: list[str] | None, trace_available: bool = True) -> str:
    """Report which capture backend is in effect (probe preferred; CS-8)."""
    if probes:
        return CAPTURE_PROBE
    if trace_available:
        return CAPTURE_TRACE
    raise RuntimeError("no intermediate-capture backend available (need probes or a trace)")


# --- minimal VCD reader (enough to reconstruct valid-gated node streams) ------

_VAR_RE = re.compile(r"\$var\s+\w+\s+\d+\s+(\S+)\s+([^\s$]+)")


def parse_vcd_streams(
    vcd_text: str, signal_map: dict[str, str], valid_signal: str = "valid_N"
) -> Observations:
    """Reconstruct valid-gated per-node streams from a VCD dump (CS-8).

    `signal_map` maps node id -> signal name; the value of each mapped signal is
    sampled at every timestep where `valid_signal` is high, yielding the same
    Observations shape the probe backend produces.
    """
    # symbol (VCD identifier) -> signal name
    sym_to_name: dict[str, str] = {}
    for m in _VAR_RE.finditer(vcd_text):
        sym, name = m.group(1), m.group(2)
        sym_to_name[sym] = name.split("[")[0]
    name_to_sym = {name: sym for sym, name in sym_to_name.items()}

    want = {nid: name_to_sym.get(sig) for nid, sig in signal_map.items()}
    valid_sym = name_to_sym.get(valid_signal)
    current: dict[str, int] = {}
    streams: Observations = {nid: [] for nid in signal_map}

    def value_of(token: str) -> int:
        body = token[1:] if token[0] in "bB" else token
        return int(body, 2) if set(body) <= {"0", "1"} else 0

    def sample() -> None:  # record the just-completed timestep if valid is high
        if valid_sym is not None and current.get(valid_sym, 0) == 1:
            for nid, sym in want.items():
                if sym is not None:
                    streams[nid].append([current.get(sym, 0)])

    started = False
    for raw in vcd_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("$"):
            continue
        if line[0] == "#":  # new timestamp: the previous timestep is complete
            if started:
                sample()
            started = True
        elif line[0] in "bB":  # vector value: "b1010 <sym>"
            val, _, sym = line.partition(" ")
            current[sym.strip()] = value_of(val)
        elif line[0] in "01xzXZ" and len(line) >= 2:  # scalar: "1<sym>"
            current[line[1:]] = 1 if line[0] == "1" else 0
    if started:  # the final timestep has no trailing '#'
        sample()
    return streams
