"""nkMatlib SystemVerilog emission from a DAG (CG-1, CG-4).

Conventions follow the nkMatlib README: ``fixedp`` port ``g``, ``_0`` inputs,
``_N`` outputs, instance names ``i_<module>_<signal>_<stage>`` with the stage
number equal to the output-ready cycle, and **every** matching delay (data
``pipe`` and reset ``valid``) computed from the cost model — including the
alignment of early outputs to the final stage. Emission order is the DAG's
stable node order, so output is deterministic (CG-4).
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeforge.core.audit.engine import Audit
from pipeforge.core.frontend.dag import Dag, Node, port_name

#: DAG module -> (instance port for each arg position, output port)
_PORTS_2IN = (("a", "b"), "f")
_PORTS_1IN = (("a",), "f")
_MODULE_PORTS: dict[str, tuple[tuple[str, ...], str]] = {
    "matadd": _PORTS_2IN,
    "matsub": _PORTS_2IN,
    "matadd3": (("a", "b", "c"), "f"),
    "matadd3b1": (("a", "b", "c"), "f"),
    "matadd3b2": (("a", "b", "c"), "f"),
    "elem_smul": _PORTS_2IN,
    "elem_sdiv": _PORTS_2IN,
    "elem_smax": _PORTS_2IN,
    "elem_smin": _PORTS_2IN,
    "elem_rshift": _PORTS_2IN,
    "matmul": _PORTS_2IN,
    "crossp": _PORTS_2IN,
    "elem_neg": _PORTS_1IN,
    "elem_abs": _PORTS_1IN,
    "elem_ssqr": _PORTS_1IN,
    "elem_sinv": _PORTS_1IN,
    "elem_usqrt": _PORTS_1IN,
    "sumsqr": _PORTS_1IN,
    "rootsqr": _PORTS_1IN,
    "vecnormrows": _PORTS_1IN,
    "vecnormcols": _PORTS_1IN,
    "transp": _PORTS_1IN,
}


class CodegenError(ValueError):
    """The DAG contains a construct the emitter cannot express in nkMatlib SV."""


@dataclass
class _Sig:
    base: str
    cycle: int

    @property
    def full(self) -> str:
        return f"{self.base}_{self.cycle}"


def probe_port(nid: str) -> str:
    """Conventional probe output-port base name for a DAG node (CS-7)."""
    return f"probe_{nid}"


class _Emitter:
    def __init__(self, audit: Audit, module_name: str, probes: list[str] | None = None) -> None:
        self.audit = audit
        self.dag: Dag = audit.dag
        self.module_name = module_name
        self.probes = probes or []
        self.sig: dict[str, _Sig] = {}  # node id -> output signal
        self.const_expr: dict[str, str] = {}  # node id -> literal expression
        self.used_names: set[str] = set()
        self.decls: list[str] = []
        self.body: list[str] = []
        self.tmp_counter = 0

    # -- naming --------------------------------------------------------------

    def _claim(self, base: str, cycle: int) -> _Sig:
        candidate = base
        while f"{candidate}_{cycle}" in self.used_names:
            candidate += "x"
        self.used_names.add(f"{candidate}_{cycle}")
        return _Sig(candidate, cycle)

    def _tmp_base(self, node: Node) -> str:
        self.tmp_counter += 1
        return f"t{self.tmp_counter}"

    # -- pieces ----------------------------------------------------------------

    def _declare(self, sig: _Sig) -> None:
        self.decls.append(f"logic [g.WIDTH-1:0] {sig.full};")

    def _pipe(self, src: _Sig, to_cycle: int) -> _Sig:
        """Matching delay from src to to_cycle; cached per (base, to_cycle)."""
        existing = f"{src.base}_{to_cycle}"
        if existing in self.used_names:
            return _Sig(src.base, to_cycle)
        delay = to_cycle - src.cycle
        if delay <= 0:
            return src
        dst = self._claim(src.base, to_cycle)
        # mirror what `PIPE expands to, with the cost-model delay (CG-1)
        self._declare(dst)
        self.body.append(
            f"pipe #(.WIDTH($bits({src.full})), .DELAY({delay})) i_pipe_{dst.full}\n"
            f"  (\n    .g (g), .i ({src.full}), .o ({dst.full})\n  );"
        )
        self.body.append("")
        return dst

    # -- emission ----------------------------------------------------------------

    def emit(self) -> str:
        dag = self.dag
        inputs = dag.inputs()
        outputs = [n for n in dag.outputs() if n.signal]
        if not outputs:
            raise CodegenError("the DAG has no outputs; nothing to generate")
        for node in inputs:
            safe = port_name(node.label)
            self.sig[node.nid] = _Sig(safe, 0)
            self.used_names.add(f"{safe}_0")

        for nid in dag.order:
            node = dag.nodes[nid]
            if node.module == "input":
                continue
            if node.module == "const":
                # lazy: only consumed constants must be expressible (`TOFXD)
                self.const_expr[nid] = node.label
                continue
            if node.module == "":
                self._emit_wiring(node)
                continue
            if node.module == "reshape":
                # pure column-major relabel: the output is the operand's own
                # wires — no instance, no latency (AR-3/AR-5)
                self.sig[node.nid] = self.sig[node.args[0]]
                continue
            self._emit_operator(node)

        total = self.audit.total_latency
        out_sigs: list[tuple[str, _Sig]] = []
        for node in outputs:
            sig = self.sig[node.nid]
            sig = self._pipe(sig, total)  # align every output to the final stage
            out_sigs.append((node.signal, sig))
        # probe ports: expose selected internal signals, aligned to the final
        # stage so they sample valid-gated exactly like primary outputs (CS-7)
        probe_sigs: list[tuple[str, _Sig]] = []
        for nid in self.probes:
            if nid not in self.sig:
                continue
            probe_sigs.append((probe_port(nid), self._pipe(self.sig[nid], total)))

        valid_sig = _Sig("valid", total)
        if total > 0:
            self.body.append(
                f"valid #(.WIDTH(1), .DELAY({total})) i_valid_{valid_sig.full}\n"
                f"  (\n    .g (g), .i (valid_0), .o ({valid_sig.full})\n  );"
            )
            self.body.append("")
            self.decls.append(f"logic {valid_sig.full};")
        assigns = [
            f"assign valid_N = {valid_sig.full if total > 0 else 'valid_0'};",
        ]
        for name, sig in out_sigs:
            assigns.append(f"assign {name}_N = {sig.full};")
        for name, sig in probe_sigs:
            assigns.append(f"assign {name}_N = {sig.full};")

        in_ports = "\n".join(f"  input [g.WIDTH-1:0] {port_name(n.label)}_0," for n in inputs)
        out_port_lines = [f"  output [g.WIDTH-1:0] {n.signal}_N" for n in outputs]
        out_port_lines += [f"  output [g.WIDTH-1:0] {name}_N" for name, _ in probe_sigs]
        out_ports = ",\n".join(out_port_lines)
        decls = "\n".join(self.decls)
        body = "\n".join(self.body)
        cm = self.audit.cm
        return f"""// Generated by PipeForge from {self.audit.filename}
// fixedp WIDTH={cm.width} SCALE={cm.scale} — critical path {total} cycles
// Do not edit: regenerate with `pipeforge-cli codegen`.

`include "macros.svh"

module {self.module_name}
  (
  fixedp g,

  input valid_0,
{in_ports}

  output valid_N,
{out_ports}
  );

{decls}

{body}{chr(10).join(assigns)}

endmodule
"""

    def _const_expr(self, label: str) -> str:
        try:
            value = float(label)
        except ValueError as exc:
            raise CodegenError(f"unsupported constant '{label}'") from exc
        return f"`TOFXD({value})"

    def _arg_expr(self, nid: str, at_cycle: int) -> str:
        if nid in self.const_expr:
            # constants are steady values; no matching delay needed
            return self._const_expr(self.const_expr[nid])
        sig = self.sig[nid]
        return self._pipe(sig, at_cycle).full

    def _emit_wiring(self, node: Node) -> None:
        if node.op == "wire" and len(node.args) == 1:
            arg = node.args[0]
            if arg in self.const_expr:
                base = node.signal or self._tmp_base(node)
                sig = self._claim(base, node.ready)
                self._declare(sig)
                self.body.append(f"assign {sig.full} = {self._const_expr(self.const_expr[arg])};")
                self.body.append("")
                self.sig[node.nid] = sig
                return
            self.sig[node.nid] = self.sig[arg]
            return
        raise CodegenError(
            f"line {node.line}: '{node.op}' ({node.label}) has no nkMatlib mapping; "
            "rewrite the MATLAB without indexing/concatenation or extend the generator"
        )

    def _emit_operator(self, node: Node) -> None:
        ports = _MODULE_PORTS.get(node.module)
        if ports is None:
            raise CodegenError(f"line {node.line}: no emission rule for module '{node.module}'")
        arg_ports, out_port = ports
        data_args = list(node.args)
        if len(data_args) > len(arg_ports):
            raise CodegenError(f"line {node.line}: {node.module} with {len(data_args)} operands")
        start = node.ready - node.lat
        base = node.signal or self._tmp_base(node)
        out = self._claim(base, node.ready)
        self._declare(out)
        conns = ["    .g (g)"]
        for port, arg in zip(arg_ports, data_args, strict=False):
            conns.append(f"    .{port} ({self._arg_expr(arg, start)})")
        conns.append(f"    .{out_port} ({out.full})")
        self.body.append(
            f"// stage {node.ready}: {node.label}\n"
            f"{node.module} i_{node.module}_{out.full}\n  (\n" + ",\n".join(conns) + "\n  );"
        )
        self.body.append("")
        self.sig[node.nid] = out


def generate_sv(audit: Audit, module_name: str, probes: list[str] | None = None) -> str:
    """Emit a complete nkMatlib module from an audited DAG (CG-1, CG-4).

    `probes` exposes the named DAG nodes' internal signals as extra valid-gated
    output ports for intermediate capture (CS-7).
    """
    return _Emitter(audit, module_name, probes=probes).emit()
