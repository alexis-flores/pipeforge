"""VCD/FST trace capture — the fallback for hand-written RTL (CS-8).

The probe backend (CS-7) is the robust primary: it works on generated RTL by
adding explicit output ports. For hand-written RTL that cannot be re-emitted,
this fallback drives Verilator with trace dumping and reconstructs per-node
streams by mapping each DAG node id to its conventional signal name
(``<signal>_<stage>``) and sampling that signal whenever the output valid is
high. The active backend is reported, mirroring the SL-1 pyslang/regex pattern.
"""

from __future__ import annotations

from pipeforge.core.bisect.engine import Observations
from pipeforge.core.frontend.dag import Dag, Node

CAPTURE_PROBE = "probe"
CAPTURE_TRACE = "trace"


def _vcd_name_to_sym(vcd_text: str) -> dict[str, str]:
    """Map each VCD signal's leaf name to its symbol (robust token split).

    Handles every `$var <type> <width> <sym> <name> [range] $end` form Verilator
    emits (wire/reg/integer/real/parameter, with or without a bit range), unlike
    a single fixed-shape regex. Aliased signals share a symbol; first wins.
    """
    out: dict[str, str] = {}
    for raw in vcd_text.splitlines():
        s = raw.strip()
        if s.startswith("$var"):
            toks = s.split()
            if len(toks) >= 5:
                out.setdefault(toks[4].split("[")[0], toks[3])
    return out


def _vcd_value(token: str) -> int:
    body = token.lstrip("bB")
    return int(body, 2) if body and set(body) <= {"0", "1"} else 0


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


# --- VCD readers ------------------------------------------------------------


def parse_vcd_streams(
    vcd_text: str, signal_map: dict[str, str], valid_signal: str = "valid_N"
) -> Observations:
    """Reconstruct valid-gated per-node streams from a VCD dump (CS-8).

    `signal_map` maps node id -> signal name; the value of each mapped signal is
    sampled at every timestep where `valid_signal` is high, yielding the same
    Observations shape the probe backend produces.
    """
    name_to_sym = _vcd_name_to_sym(vcd_text)
    want = {nid: name_to_sym.get(sig) for nid, sig in signal_map.items()}
    valid_sym = name_to_sym.get(valid_signal)
    current: dict[str, int] = {}
    streams: Observations = {nid: [] for nid in signal_map}

    def value_of(token: str) -> int:
        return _vcd_value(token)

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


def observations_from_vcd(
    vcd_text: str,
    dag: Dag,
    total: int,
    valid_signal: str = "valid_N",
    clk_signal: str = "clk",
) -> Observations:
    """Reconstruct stage-aligned per-node streams from a VCD dump (CS-8).

    Sampling every internal signal at the output-valid cycle would misalign them:
    a node at stage ``s`` holds a *different* vector than the final output at that
    instant. So this snapshots each node's signal at every clock posedge, then
    reads node ``s`` for the k-th output ``(total - s)`` cycles earlier — the cycle
    that node held the k-th vector. The result is directly comparable to the
    golden intermediates (the same shape the probe backend produces, CS-7).

    Works when signal stage suffixes equal cost-model ready times (always true
    for generated RTL; true for convention-following hand-written RTL). Returns
    an empty dict — never raising — when nothing matches, so bisection simply
    does not run.
    """
    name_to_sym = _vcd_name_to_sym(vcd_text)
    valid_sym = name_to_sym.get(valid_signal)
    clk_sym = name_to_sym.get(clk_signal)
    if valid_sym is None or clk_sym is None:
        return {}
    targets: dict[str, tuple[str, int]] = {}  # nid -> (symbol, ready stage)
    for nid in dag.order:
        node = dag.nodes[nid]
        # delay (z^-1) is state: its signal is one sample behind its stage
        # suffix by construction, so the stage-aligned reconstruction would
        # report a false divergence — leave it unobserved (SD-1)
        if node.module in ("", "input", "const", "reshape", "delay"):
            continue
        sym = name_to_sym.get(node_signal_name(node))
        if sym is not None:
            targets[nid] = (sym, node.ready)
    if not targets:
        return {}

    current: dict[str, int] = {}
    snaps: dict[str, list[int]] = {nid: [] for nid in targets}
    valids: list[int] = []
    clk_prev = 0
    seen_ts = False

    def settle() -> None:  # post-edge settled values, captured once per posedge
        nonlocal clk_prev
        clk_now = current.get(clk_sym, 0)
        if clk_now == 1 and clk_prev == 0:
            for nid, (sym, _) in targets.items():
                snaps[nid].append(current.get(sym, 0))
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
        elif c in "rR":
            continue  # real-valued params are irrelevant to node streams
        elif c in "01xzXZ" and len(s) >= 2:
            current[s[1:]] = 1 if c == "1" else 0
    settle()

    valid_cycles = [i for i, v in enumerate(valids) if v == 1]
    out: Observations = {}
    for nid, (_sym, ready) in targets.items():
        stream: list[list[int]] = []
        for vc in valid_cycles:
            idx = vc - (total - ready)  # the cycle this stage held the k-th vector
            if 0 <= idx < len(snaps[nid]):
                stream.append([snaps[nid][idx]])
        if stream:
            out[nid] = stream
    return out
