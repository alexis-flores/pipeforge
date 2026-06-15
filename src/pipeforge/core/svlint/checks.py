"""nkMatlib convention checks (SL-2, SL-3) over the structural model.

The same cost model as the auditor (AU-1) prices every operator and pipe,
so a lint stage number is directly comparable to an audit ready time.
Each check is individually suppressible by ID.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.svlint.model import (
    DATA_PORTS,
    OUTPUT_PORTS,
    PIPE_MODULES,
    RESET_PIPES,
    UNRESET_PIPES,
    Instance,
    SvModule,
    is_valid_signal,
    operator_latency,
    pipe_latency,
    split_suffix,
)
from pipeforge.core.svlint.parse import parse_sv

#: Check IDs (SL-3: each individually suppressible).
CHECK_DELAY = "delay-match"
CHECK_SUFFIX = "suffix"
CHECK_VALID_CHAIN = "valid-chain"
CHECK_RESET = "reset"
CHECK_NAMING = "naming"
CHECK_UNKNOWN = "unknown-module"
CHECK_SCALE = "scale-continuity"  # SL-5
CHECK_DIVIDERS = "divider-count"  # SL-6
ALL_CHECKS = (
    CHECK_DELAY,
    CHECK_SUFFIX,
    CHECK_VALID_CHAIN,
    CHECK_RESET,
    CHECK_NAMING,
    CHECK_UNKNOWN,
    CHECK_SCALE,
    CHECK_DIVIDERS,
)

#: nkMatlib modules that rescale SCALE (the legitimate place a SCALE may change).
RESCALE_MODULES = frozenset({"snorm", "unorm", "norm", "elem_snorm"})
#: RTL module names that contain a divider (for the SL-6 census).
DIVIDER_RTL = frozenset(
    {"elem_sdiv", "elem_sinv", "matunscale", "elem_sdiv_by_row", "sdiv", "sinv", "udiv", "uinv"}
)


@dataclass(frozen=True)
class LintFinding:
    check: str
    line: int
    message: str
    fix: str
    signal: str = ""  # DAG cross-reference key when derivable (SL-4)


@dataclass
class LintResult:
    filename: str
    backend: str
    module: str
    findings: list[LintFinding] = field(default_factory=list)
    cycles: dict[str, int] = field(default_factory=dict)

    def by_check(self, check: str) -> list[LintFinding]:
        return [f for f in self.findings if f.check == check]


_IDENT_RE = re.compile(r"^\w+$")
_NUM_RE = re.compile(r"^\d|^'|^\{|^`")


def _is_signal_ref(expr: str) -> bool:
    return bool(_IDENT_RE.match(expr)) and not _NUM_RE.match(expr)


def _suggest_pipe(diff: int, cm: CostModel) -> str:
    options = {
        1: "pipe",
        cm.mul_lat: "mul_pipe",
        cm.div_lat: "div_pipe",
        cm.sqrt_lat: "sqrt_pipe",
        cm.matmul_lat: "matmul_pipe",
        cm.sumsqr_lat: "sumsqr_pipe",
        cm.rootsqr_lat: "rootsqr_pipe",
    }
    if diff in options:
        return f"`PIPE({options[diff]}, …)"
    return f"a {diff}-cycle matching delay (pipe #(.DELAY({diff})))"


def _propagate(module: SvModule, cm: CostModel) -> tuple[dict[str, int], list[LintFinding]]:
    """Signal -> arrival cycle, plus delay-match findings (SL-2)."""
    cycles: dict[str, int] = {}
    for port in module.ports:
        if port.direction == "input":
            base = split_suffix(port.name)
            if base is None or base[1] == "0":
                cycles[port.name] = 0
    findings: list[LintFinding] = []
    flagged: set[int] = set()

    for _ in range(12):  # fixpoint over forward references
        changed = False
        for pipe in module.pipes:
            src = f"{pipe.signal}_{pipe.from_stage}"
            dst = f"{pipe.signal}_{pipe.to_stage}"
            lat = pipe_latency(pipe.pipe_module, cm)
            if lat is None or src not in cycles:
                continue
            value = cycles[src] + lat
            if cycles.get(dst) != value:
                cycles[dst] = value
                changed = True
        for inst in module.instances:
            if inst.module in PIPE_MODULES:
                # explicit pipe instance: i -> o with the module's delay
                lat = pipe_latency(inst.module, cm)
                delay_param = inst.params.get("DELAY", "")
                if delay_param.isdigit():
                    lat = int(delay_param)
                src = inst.conns.get("i", "")
                dst = inst.conns.get("o", "")
                if lat is not None and _is_signal_ref(src) and src in cycles and dst:
                    value = cycles[src] + lat
                    if cycles.get(dst) != value:
                        cycles[dst] = value
                        changed = True
                continue
            lat = operator_latency(inst.module, cm)
            if lat is None:
                continue
            arrivals: dict[str, int] = {}
            ready = True
            for port_name in DATA_PORTS:
                expr = inst.conns.get(port_name, "")
                if not expr or not _is_signal_ref(expr):
                    continue
                if expr in cycles:
                    arrivals[expr] = cycles[expr]
                else:
                    ready = False
            if not ready or not arrivals:
                continue
            if len(set(arrivals.values())) > 1 and id(inst) not in flagged:
                flagged.add(id(inst))
                ordered = sorted(arrivals.items(), key=lambda kv: kv[1])
                early, late = ordered[0], ordered[-1]
                diff = late[1] - early[1]
                findings.append(
                    LintFinding(
                        CHECK_DELAY,
                        inst.line,
                        f"instance '{inst.name}' ({inst.module}): input '{early[0]}' "
                        f"arrives at stage {early[1]} but '{late[0]}' arrives at stage "
                        f"{late[1]}",
                        f"delay '{early[0]}' by {diff} cycles with {_suggest_pipe(diff, cm)} "
                        f"so both operands meet at stage {late[1]}",
                        signal=_signal_of_instance(inst),
                    )
                )
            out_cycle = max(arrivals.values()) + lat
            for port_name in OUTPUT_PORTS:
                out = inst.conns.get(port_name, "")
                if out and _is_signal_ref(out) and cycles.get(out) != out_cycle:
                    cycles[out] = out_cycle
                    changed = True
        for assign in module.assigns:
            if _is_signal_ref(assign.rhs) and assign.rhs in cycles:
                if cycles.get(assign.lhs) != cycles[assign.rhs]:
                    cycles[assign.lhs] = cycles[assign.rhs]
                    changed = True
        if not changed:
            break
    return cycles, findings


def _signal_of_instance(inst: Instance) -> str:
    """i_<module>_<signal>_<stage> -> <signal> (SL-4 cross-reference key)."""
    m = re.match(rf"^i_{re.escape(inst.module)}_(\w+?)_(\d+)$", inst.name)
    return m.group(1) if m else ""


def _check_suffixes(cycles: dict[str, int]) -> list[LintFinding]:
    """SL-3a: _nn suffix consistency with computed stages.

    Valid signals are excluded here; their alignment is the valid-chain
    check's job (SL-3b), so one root cause yields one finding.
    """
    stages: dict[str, dict[str, int]] = {}
    for sig, cyc in cycles.items():
        base = split_suffix(sig)
        if base is None or base[1] == "N" or is_valid_signal(sig):
            continue
        stages.setdefault(base[1], {})[sig] = cyc
    findings: list[LintFinding] = []
    for stage, sigs in sorted(stages.items()):
        values = sorted(set(sigs.values()))
        if len(values) > 1:
            detail = ", ".join(f"{s} @ {c}" for s, c in sorted(sigs.items(), key=lambda kv: kv[1]))
            findings.append(
                LintFinding(
                    CHECK_SUFFIX,
                    0,
                    f"signals with stage suffix _{stage} arrive at different cycles: {detail}",
                    "every signal of one stage must be delayed to the same cycle; "
                    "fix the matching `PIPE delays",
                )
            )
    return findings


def _check_valid_chain(cycles: dict[str, int]) -> list[LintFinding]:
    """SL-3b: valid-chain delay == data-path delay at every stage."""
    findings: list[LintFinding] = []
    by_stage: dict[str, tuple[dict[str, int], dict[str, int]]] = {}
    for sig, cyc in cycles.items():
        base = split_suffix(sig)
        if base is None or base[1] == "N":
            continue  # _N outputs are aliases of the final real stage
        valids, datas = by_stage.setdefault(base[1], ({}, {}))
        (valids if is_valid_signal(sig) else datas)[sig] = cyc
    for stage, (valids, datas) in sorted(by_stage.items()):
        if not valids or not datas:
            continue
        for vsig, vcyc in valids.items():
            data_cycle = max(datas.values())
            if vcyc != data_cycle:
                findings.append(
                    LintFinding(
                        CHECK_VALID_CHAIN,
                        0,
                        f"'{vsig}' arrives at cycle {vcyc} but stage {stage} data arrives "
                        f"at cycle {data_cycle}",
                        "the valid chain must use the *_valid module matching the "
                        "data path's operator latency",
                    )
                )
    return findings


def _check_reset_discipline(module: SvModule) -> list[LintFinding]:
    """SL-3c: valid FFs reset; data pipes unreset (SRL inference)."""
    findings: list[LintFinding] = []
    for pipe in module.pipes:
        valid = is_valid_signal(pipe.signal)
        if valid and pipe.pipe_module in UNRESET_PIPES:
            findings.append(
                LintFinding(
                    CHECK_RESET,
                    pipe.line,
                    f"valid signal '{pipe.signal}' is delayed through unreset '{pipe.pipe_module}'",
                    f"use '{pipe.pipe_module.removesuffix('_pipe')}_valid' (or 'valid') so "
                    "the valid chain is correct immediately after reset",
                )
            )
        elif not valid and pipe.pipe_module in RESET_PIPES:
            findings.append(
                LintFinding(
                    CHECK_RESET,
                    pipe.line,
                    f"data signal '{pipe.signal}' is delayed through reset '{pipe.pipe_module}'",
                    "use the unreset *_pipe variant so synthesis can infer SRLs",
                    signal=pipe.signal,
                )
            )
    return findings


_INSTANCE_NAME_RE = re.compile(r"^i_(\w+?)_\w+?_\d+$")


def _check_naming(module: SvModule) -> list[LintFinding]:
    """SL-3d: instance naming i_<module>_<signal>_<stage>."""
    findings: list[LintFinding] = []
    for inst in module.instances:
        if inst.module in PIPE_MODULES:
            continue  # `PIPE generates its own conventional names
        m = _INSTANCE_NAME_RE.match(inst.name)
        if not m or not inst.name.startswith(f"i_{inst.module}_"):
            findings.append(
                LintFinding(
                    CHECK_NAMING,
                    inst.line,
                    f"instance '{inst.name}' of '{inst.module}' does not follow "
                    "i_<module>_<signal>_<stage>",
                    f"rename to i_{inst.module}_<signal>_<stage>",
                )
            )
    return findings


def _check_unknown_modules(module: SvModule, cm: CostModel) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for inst in module.instances:
        if inst.module in PIPE_MODULES:
            continue
        if operator_latency(inst.module, cm) is None:
            findings.append(
                LintFinding(
                    CHECK_UNKNOWN,
                    inst.line,
                    f"'{inst.module}' is not a known nkMatlib module; its latency "
                    "cannot be checked",
                    "if this is a custom block, add it to the cost model configuration",
                )
            )
    return findings


def _propagate_scales(module: SvModule, cm: CostModel) -> dict[str, int]:
    """Signal -> SCALE, assuming standard ops preserve it and *snorm rescale (SL-5)."""
    scales: dict[str, int] = {}
    for port in module.ports:
        if port.direction == "input":
            base = split_suffix(port.name)
            if base is not None and base[1] == "0":
                scales[port.name] = cm.scale
    for _ in range(12):
        changed = False
        for pipe in module.pipes:
            src, dst = f"{pipe.signal}_{pipe.from_stage}", f"{pipe.signal}_{pipe.to_stage}"
            if src in scales and scales.get(dst) != scales[src]:
                scales[dst] = scales[src]
                changed = True
        for inst in module.instances:
            if inst.module in PIPE_MODULES:
                src, dst = inst.conns.get("i", ""), inst.conns.get("o", "")
                if src in scales and dst and scales.get(dst) != scales[src]:
                    scales[dst] = scales[src]
                    changed = True
                continue
            in_scales = [scales[e] for p in DATA_PORTS if (e := inst.conns.get(p, "")) in scales]
            if inst.module in RESCALE_MODULES:
                fs = inst.params.get("F_SCALE", "")
                out_scale = int(fs) if fs.isdigit() else (in_scales[0] if in_scales else cm.scale)
            else:
                out_scale = in_scales[0] if in_scales else cm.scale
            for p in OUTPUT_PORTS:
                out = inst.conns.get(p, "")
                if out and _is_signal_ref(out) and scales.get(out) != out_scale:
                    scales[out] = out_scale
                    changed = True
        if not changed:
            break
    return scales


def _check_scale_continuity(
    module: SvModule, cm: CostModel, expected: dict[str, int] | None = None
) -> list[LintFinding]:
    """SL-5: SCALE entering each operator must be consistent; flag missing rescale.

    `expected` (from an MP-6 per-point format map) overrides the inferred SCALE
    for named signals when supplied.
    """
    scales = _propagate_scales(module, cm)
    if expected:
        scales.update(expected)
    findings: list[LintFinding] = []
    for inst in module.instances:
        if inst.module in PIPE_MODULES or inst.module in RESCALE_MODULES:
            continue
        pairs = [
            (inst.conns[p], scales[inst.conns[p]])
            for p in DATA_PORTS
            if inst.conns.get(p, "") in scales
        ]
        if len({s for _, s in pairs}) > 1:
            ordered = sorted(pairs, key=lambda kv: kv[1])
            lo, hi = ordered[0], ordered[-1]
            findings.append(
                LintFinding(
                    CHECK_SCALE,
                    inst.line,
                    f"instance '{inst.name}' ({inst.module}): operand '{lo[0]}' enters at "
                    f"SCALE {lo[1]} but '{hi[0]}' at SCALE {hi[1]} (delta {hi[1] - lo[1]})",
                    f"insert elem_snorm to rescale '{lo[0]}' to SCALE {hi[1]} before '{inst.name}'",
                    signal=_signal_of_instance(inst),
                )
            )
    return findings


def check_divider_count(module: SvModule, audit: object) -> list[LintFinding]:
    """SL-6: flag RTL that instantiates more dividers than the optimized DAG implies."""
    from pipeforge.core.audit.engine import Audit

    assert isinstance(audit, Audit)
    rtl = sum(1 for inst in module.instances if inst.module in DIVIDER_RTL)
    implied = audit.divider_count
    if rtl > implied:
        return [
            LintFinding(
                CHECK_DIVIDERS,
                0,
                f"RTL instantiates {rtl} divider(s) but the optimized DAG implies "
                f"{implied} — audit advice (RECIP/CDIV sharing) was not applied",
                "share reciprocals / fold constant divides per the audit findings to "
                f"reach {implied} divider(s)",
            )
        ]
    return []


def lint_source(
    text: str,
    filename: str,
    cm: CostModel,
    disabled: frozenset[str] = frozenset(),
    prefer_pyslang: bool = True,
    audit: object | None = None,
) -> LintResult:
    """Lint one SystemVerilog file against nkMatlib conventions (SL-1..3)."""
    module, backend = parse_sv(text, prefer_pyslang=prefer_pyslang)
    result = LintResult(filename=filename, backend=backend, module=module.name)
    cycles, delay_findings = _propagate(module, cm)
    result.cycles = cycles
    checks: list[tuple[str, list[LintFinding]]] = [
        (CHECK_DELAY, delay_findings),
        (CHECK_SUFFIX, _check_suffixes(cycles)),
        (CHECK_VALID_CHAIN, _check_valid_chain(cycles)),
        (CHECK_RESET, _check_reset_discipline(module)),
        (CHECK_NAMING, _check_naming(module)),
        (CHECK_UNKNOWN, _check_unknown_modules(module, cm)),
        (CHECK_SCALE, _check_scale_continuity(module, cm)),
    ]
    if audit is not None:
        checks.append((CHECK_DIVIDERS, check_divider_count(module, audit)))
    for check_id, findings in checks:
        if check_id not in disabled:
            result.findings.extend(findings)
    result.findings.sort(key=lambda f: (f.line, f.check))
    return result


def crossref_dag(result: LintResult, dag: object) -> dict[int, str]:
    """SL-4: finding index -> DAG node id, matched by signal name."""
    from pipeforge.core.frontend.dag import Dag

    assert isinstance(dag, Dag)
    by_signal = {dag.nodes[s.root].signal: s.root for s in dag.statements}
    out: dict[int, str] = {}
    for i, finding in enumerate(result.findings):
        base = split_suffix(finding.signal)
        name = base[0] if base else finding.signal
        if name and name in by_signal:
            out[i] = by_signal[name]
    return out
