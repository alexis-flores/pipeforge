"""pipeforge-cli — headless access to every PipeForge capability (§2.1).

Every P0 capability is exercisable from here without the GUI (§8.5d);
subcommands are added phase by phase.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pipeforge import __version__

#: The star (✦ for the person who really likes stars). Shown on a bare
#: `pipeforge-cli` in a terminal — never in pipes, CI logs, or tests.
BANNER = r"""
                         ✵
                         ✵
                 ·       ✵       ·
                   ✵     ✵     ✵
                     ✵   ✵   ✵
                       ✵ ✵ ✵
      ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵ ✵
                       ✵ ✵ ✵
                     ✵   ✵   ✵
                   ✵     ✵     ✵
                 ·       ✵       ·
                         ✵
                         ✵

        P I P E F O R G E   —   MATLAB ✵ nkMatlib ✵ FPGA
"""


def _maybe_banner() -> None:
    """Print the star on interactive bare invocations (BN-1).

    PIPEFORGE_BANNER=0 silences it; =1 forces it (e.g. for screenshots).
    Non-TTY stdout (pipes, CI, tests) never sees it.
    """
    import os

    flag = os.environ.get("PIPEFORGE_BANNER", "")
    if flag == "0":
        return
    if flag == "1" or (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        print(BANNER)


def _cmd_audit(args: argparse.Namespace) -> int:
    import json as json_mod

    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.audit.report import render_text, to_payload
    from pipeforge.core.costmodel.model import CostModel

    path = Path(args.file)
    cm = CostModel(args.width, args.scale)
    snapshot = _load_snapshot_arg(getattr(args, "snapshot", None))
    last_latency: list[int] = []

    def run_once() -> int:
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        audit = audit_source(src, path.name, cm, snapshot=snapshot)
        if args.json:
            payload = to_payload(audit)
            if args.resources:
                from dataclasses import asdict

                from pipeforge.core.costmodel.resources import estimate_resources

                payload["resources"] = asdict(estimate_resources(audit.census, cm, args.family))
            print(json_mod.dumps(payload, indent=2))
        else:
            print(render_text(audit), end="")
            if args.resources:
                from pipeforge.core.costmodel.resources import estimate_resources

                est = estimate_resources(audit.census, cm, args.family)
                print(f"== resources ==  {est.summary()}")
        if last_latency and last_latency[-1] != audit.total_latency:
            delta = audit.total_latency - last_latency[-1]
            print(
                f"Δ critical path: {last_latency[-1]} → {audit.total_latency} "
                f"({'+' if delta > 0 else ''}{delta} cycles)"
            )
        last_latency.append(audit.total_latency)
        return 0

    if getattr(args, "watch", False):
        from pipeforge.core.watch import watch_loop

        print(f"watching {path} — Ctrl+C to stop", file=sys.stderr)
        watch_loop([path], lambda: run_once())
        return 0
    return run_once()


def _cmd_lint(args: argparse.Namespace) -> int:
    if getattr(args, "watch", False):
        from pipeforge.core.watch import watch_loop

        print(f"watching {args.file} — Ctrl+C to stop", file=sys.stderr)
        watch_loop([Path(args.file)], lambda: _lint_once(args))
        return 0
    return _lint_once(args)


def _lint_once(args: argparse.Namespace) -> int:
    import json as json_mod

    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.svlint.checks import lint_source

    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cm = CostModel(args.width, args.scale)
    result = lint_source(
        text,
        path.name,
        cm,
        disabled=frozenset(args.disable or []),
        prefer_pyslang=not args.no_pyslang,
    )
    if getattr(args, "verilator", False):
        from pipeforge.core.svlint.verilator import VerilatorUnavailable, verilator_lint

        try:
            extra = verilator_lint(
                path,
                include_dirs=[Path(d) for d in (args.include or [])],
                width=args.width,
                scale=args.scale,
            )
            result.findings.extend(extra)
        except VerilatorUnavailable as exc:
            print(f"note: {exc}", file=sys.stderr)
    if getattr(args, "sarif", None):
        from pipeforge import __version__ as tool_version
        from pipeforge.core.reports.sarif import sarif_document

        Path(args.sarif).write_text(
            sarif_document(result, str(path), tool_version), encoding="utf-8"
        )
        print(f"wrote {args.sarif}", file=sys.stderr)
    if args.json:
        payload = {
            "file": result.filename,
            "backend": result.backend,
            "module": result.module,
            "findings": [
                {
                    "check": f.check,
                    "line": f.line,
                    "message": f.message,
                    "fix": f.fix,
                    "signal": f.signal,
                }
                for f in result.findings
            ],
        }
        print(json_mod.dumps(payload, indent=2))
    else:
        print(f"lint {result.filename} — backend: {result.backend}, module: {result.module}")
        if not result.findings:
            print("  clean: no convention violations found")
        for f in result.findings:
            where = f"line {f.line}" if f.line else "module"
            print(f"  [{f.check}] {where}: {f.message}")
            print(f"      fix: {f.fix}")
    return 1 if result.findings else 0


def _cmd_cosim(args: argparse.Namespace) -> int:
    import json as json_mod

    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.cosim.runner import CosimUnavailable, run_cosim
    from pipeforge.core.costmodel.model import CostModel

    m_path = Path(args.file)
    try:
        src = m_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cm = CostModel(args.width, args.scale)
    audit = audit_source(src, m_path.name, cm)
    work_dir = Path(args.work_dir) if args.work_dir else m_path.parent / "cosim_work"
    probes: list[str] | None = None
    if args.probes == "auto":
        probes = [
            nid
            for nid in audit.dag.order
            if audit.dag.nodes[nid].module not in ("", "input", "const", "reshape")
        ]
    elif args.probes:
        probes = [p.strip() for p in args.probes.split(",") if p.strip()]
    vectors = None
    if getattr(args, "replay", None):
        from pipeforge.core.cosim.vectors import load_vectors

        try:
            vectors = load_vectors(Path(args.replay))
        except (OSError, ValueError, json_mod.JSONDecodeError) as exc:
            print(f"error: cannot replay {args.replay}: {exc}", file=sys.stderr)
            return 2
        print(f"replaying {len(vectors)} vector(s) from {args.replay}", file=sys.stderr)
    elif getattr(args, "range", None):
        from pipeforge.core.cosim.stimulus import generate_ranged_stimulus
        from pipeforge.core.fxp.fx import FxFormat

        declared = _parse_ranges(args.range)
        inputs = [n.label for n in audit.dag.inputs()]
        missing = [n for n in inputs if n not in declared]
        if missing:
            print(f"error: --range missing for input(s): {', '.join(missing)}", file=sys.stderr)
            return 2
        vectors = generate_ranged_stimulus(
            inputs, FxFormat(cm.width, cm.scale), declared, count=args.vectors
        )
    try:
        result = run_cosim(
            audit,
            dut_sv=Path(args.sv),
            dut_module=args.top,
            work_dir=work_dir,
            extra_sources=[Path(p) for p in (args.source or [])],
            include_dirs=[Path(p) for p in (args.include or [])],
            vector_count=args.vectors,
            cadence=args.cadence,
            backend=None if args.backend == "auto" else args.backend,
            probes=probes,
            bisect_on_failure=args.bisect,
            vectors=vectors,
        )
    except CosimUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if getattr(args, "junit_xml", None):
        from pipeforge.core.reports.junit import junit_xml

        Path(args.junit_xml).write_text(junit_xml(result, f"cosim.{args.top}"), encoding="utf-8")
        print(f"wrote {args.junit_xml}", file=sys.stderr)
    if args.json:
        payload = result.to_payload()
        payload["harness_backend"] = result.harness_backend
        if result.bisect_report is not None:
            r = result.bisect_report
            payload["bisect"] = {
                "diverged": r.diverged,
                "node": r.node,
                "instance": r.instance,
                "classification": r.classification,
                "inputs_matched": r.inputs_matched,
                "message": r.message,
            }
        print(json_mod.dumps(payload, indent=2))
    else:
        verdict = "PASS" if result.passed else "FAIL"
        tag = f"{result.harness_backend}/{args.cadence}"
        print(f"cosim {m_path.name} vs {args.top} [{tag}]: {verdict}")
        for o in result.outputs:
            if o.passed:
                print(
                    f"  {o.name}: {o.compared} vectors bit-exact — "
                    f"max|e|={o.max_abs_error:.3g} rms={o.rms_error:.3g} "
                    f"SQNR={o.sqnr_db:.1f} dB"
                )
            else:
                print(
                    f"  {o.name}: first failing vector #{o.first_failure} "
                    f"(expected 0x{o.expected:x}, got 0x{o.actual:x})"
                )
        if not result.passed and not result.outputs:
            print("  build or simulation failed; see the log in " + result.work_dir)
        if result.bisect_report is not None and result.bisect_report.diverged:
            from pipeforge.core.diagnostics.triage import triage

            summary = triage(result.bisect_report, None, audit.dag)
            print(f"  triage: {summary.message}")
        if result.failure_file:
            print(f"  replay: pipeforge-cli cosim … --replay {result.failure_file}")
        if result.gtkw_file:
            vcd = next(iter(sorted(Path(result.work_dir).rglob("*.vcd"))), None)
            if vcd is not None:
                print(f"  waveform: gtkwave {vcd} {result.gtkw_file}")
    return 0 if result.passed else 1


def _cmd_codegen(args: argparse.Namespace) -> int:
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.codegen.emitter import CodegenError, generate_sv
    from pipeforge.core.costmodel.model import CostModel

    path = Path(args.file)
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cm = CostModel(args.width, args.scale)
    audit = audit_source(src, path.name, cm)
    module = args.module or path.stem
    plan = None
    if getattr(args, "mixed", False):
        from pipeforge.core.codegen.mixed import plan_widths
        from pipeforge.core.ranges.interval import Interval
        from pipeforge.core.ranges.propagate import RangeError, propagate

        declared = _parse_ranges(args.range or [])
        if not declared:
            print(
                "error: --mixed needs input ranges (--range name=lo:hi per input) — "
                "the narrowing is only as safe as the ranges are true",
                file=sys.stderr,
            )
            return 2
        ranges = {k: Interval(lo, hi) for k, (lo, hi) in declared.items()}
        try:
            report = propagate(audit.dag, ranges, cm)
        except RangeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        plan = plan_widths(audit, report)
        print(f"mixed precision: {plan.summary()}", file=sys.stderr)
    try:
        sv = generate_sv(audit, module, plan=plan)
    except CodegenError as exc:
        print(f"cannot generate: {exc}", file=sys.stderr)
        return 1
    axis_sv = None
    if getattr(args, "axis", False):
        from pipeforge.core.codegen.axis import generate_axis_wrapper

        axis_sv = generate_axis_wrapper(audit, module)
    if args.output:
        Path(args.output).write_text(sv, encoding="utf-8")
        print(f"wrote {args.output}")
        if axis_sv is not None:
            axis_path = Path(args.output).with_name(f"{Path(args.output).stem}_axis.sv")
            axis_path.write_text(axis_sv, encoding="utf-8")
            print(f"wrote {axis_path}")
    else:
        print(sv, end="")
        if axis_sv is not None:
            print(axis_sv, end="")
    return 0


def _parse_ranges(specs: list[str]) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for spec in specs:
        try:
            name, bounds = spec.split("=", 1)
            lo_s, hi_s = bounds.split(":", 1)
            out[name.strip()] = (float(lo_s), float(hi_s))
        except ValueError as exc:
            raise SystemExit(f"bad --range '{spec}' (expected name=lo:hi)") from exc
    return out


def _cmd_ranges(args: argparse.Namespace) -> int:
    import json as json_mod

    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.ranges.interval import Interval
    from pipeforge.core.ranges.propagate import RangeError, propagate, recommend_format

    path = Path(args.file)
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cm = CostModel(args.width, args.scale)
    snapshot = _load_snapshot_arg(getattr(args, "snapshot", None))
    audit = audit_source(src, path.name, cm, snapshot=snapshot)
    declared = _parse_ranges(args.range or [])
    ranges = {k: Interval(lo, hi) for k, (lo, hi) in declared.items()}
    if snapshot is not None:
        from pipeforge.core.ranges.propagate import ranges_from_snapshot

        # empirical workspace ranges fill anything not explicitly declared
        for name, iv in ranges_from_snapshot(audit.dag, snapshot).items():
            ranges.setdefault(name, iv)
    try:
        report = propagate(audit.dag, ranges, cm, method=args.method)
    except RangeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        payload = {
            "method": report.method,
            "width": cm.width,
            "scale": cm.scale,
            "required_left": report.required_left,
            "nodes": [
                {
                    "id": n.nid,
                    "signal": n.signal,
                    "lo": n.interval.lo,
                    "hi": n.interval.hi,
                    "integer_bits": n.integer_bits,
                    "overflow_risk": n.overflow_risk,
                    "near_zero_divisor": n.near_zero_divisor,
                }
                for n in report.nodes.values()
            ],
        }
        print(json_mod.dumps(payload, indent=2))
    else:
        print(f"ranges {path.name} — method: {report.method}, WIDTH={cm.width} SCALE={cm.scale}")
        print(f"  required LEFT bits: {report.required_left}")
        for n in report.nodes.values():
            flags = []
            if n.overflow_risk:
                flags.append("OVERFLOW RISK")
            if n.near_zero_divisor:
                flags.append("NEAR-ZERO DIVISOR")
            suffix = ("   << " + ", ".join(flags)) if flags else ""
            print(
                f"  {n.signal:<14} [{n.interval.lo:.6g}, {n.interval.hi:.6g}] "
                f"int bits {n.integer_bits}{suffix}"
            )
    if args.recommend is not None:
        rec = recommend_format(audit.dag, ranges, cm, error_budget=args.recommend)
        verdict = "validated" if rec.meets_budget else "NOT met empirically"
        print(
            f"  recommend WIDTH={rec.width} SCALE={rec.scale} ({rec.rationale}); "
            f"budget {verdict}, worst SQNR {rec.validated_sqnr_db:.1f} dB"
        )
    return 0


def _cmd_dse(args: argparse.Namespace) -> int:
    import json as json_mod

    from pipeforge.core.dse.sweep import (
        SweepConfig,
        export_csv,
        pareto_front,
        run_sweep,
    )

    path = Path(args.file)
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    widths = tuple(int(w) for w in args.widths.split(","))
    scales = tuple(int(s) for s in args.scales.split(","))
    config = SweepConfig(widths=widths, scales=scales, vectors=args.vectors)

    def progress(done: int, total: int) -> None:
        if not args.json:
            print(f"\r  sweep {done}/{total}", end="", flush=True)

    points = run_sweep(src, path.name, config, progress=progress)
    if not args.json:
        print()
    front = pareto_front(points)
    if args.csv:
        export_csv(points, Path(args.csv))
    if args.json:
        from dataclasses import asdict

        print(
            json_mod.dumps(
                {"points": [asdict(p) for p in points], "pareto": [asdict(p) for p in front]},
                indent=2,
            )
        )
    else:
        print(f"dse {path.name}: {len(points)} points, Pareto front:")
        for p in front:
            print(
                f"  {p.width}/{p.scale}: latency {p.latency}, dividers {p.dividers}, "
                f"≈{p.dsp} DSP, max|e| {p.max_abs_error:.3g}, SQNR {p.sqnr_db:.1f} dB"
            )
    return 0


def _cmd_synth(args: argparse.Namespace) -> int:
    """SY-1: quick yosys synthesis sanity-check of an .sv (or a .m via codegen)."""
    import tempfile

    from pipeforge.core.synth.estimate import SynthUnavailable, run_synth_estimate

    path = Path(args.file)
    include_dirs = [Path(d) for d in (args.include or [])]
    sources = [Path(s) for s in (args.source or [])]
    top = args.top
    tmp_ctx: object | None = None
    if path.suffix.lower() == ".m":  # generate first, then synth the result
        from pipeforge.core.audit.engine import audit_source
        from pipeforge.core.codegen.emitter import CodegenError, generate_sv
        from pipeforge.core.costmodel.model import CostModel

        src = _read(str(path))
        if src is None:
            return 2
        audit = audit_source(src, path.name, CostModel(args.width, args.scale))
        top = top or path.stem
        try:
            sv = generate_sv(audit, top)
        except CodegenError as exc:
            print(f"cannot generate: {exc}", file=sys.stderr)
            return 1
        tmp_ctx = tempfile.TemporaryDirectory(prefix="pipeforge_synth_")
        gen = Path(tmp_ctx.name) / f"{top}.sv"  # type: ignore[attr-defined]
        gen.write_text(sv, encoding="utf-8")
        main_src = gen
    else:
        main_src = path
        top = top or path.stem
    try:
        est = run_synth_estimate([main_src, *sources], top, include_dirs=include_dirs)
    except SynthUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()  # type: ignore[attr-defined]
    print(f"synth estimate {top} (yosys generic synth — a sanity check, not a vendor result)")
    print(f"  {est.summary()}")
    print(f"  wires: {est.wires}")
    for cell, count in sorted(est.cells.items()):
        print(f"    {cell:<20} x {count}")
    return 0


def _cmd_export_tb(args: argparse.Namespace) -> int:
    """VX-2: export vectors + a standalone self-checking SV testbench."""
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.cosim.stimulus import generate_stimulus
    from pipeforge.core.cosim.vectors import export_testbench, load_vectors
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.fxp.fx import FxFormat

    src = _read(args.file)
    if src is None:
        return 2
    path = Path(args.file)
    cm = CostModel(args.width, args.scale)
    audit = audit_source(src, path.name, cm)
    if args.from_failure:
        try:
            vectors = load_vectors(Path(args.from_failure))
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        inputs = [n.label for n in audit.dag.inputs()]
        vectors = generate_stimulus(inputs, FxFormat(cm.width, cm.scale), count=args.vectors)
    out_dir = Path(args.output)
    module = args.module or path.stem
    written = export_testbench(audit, vectors, out_dir, module)
    print(f"export-tb {path.name}: {len(vectors)} vectors → {out_dir}")
    for p in written:
        print(f"  {p.name}")
    print(
        "  run standalone, e.g.: verilator --binary --timing -Imatlib-main/rtl "
        f"{module}.sv tb_check.sv --top-module tb_check && obj_dir/Vtb_check"
    )
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    """OP-1: apply the auditor's rewrites to the source and report honestly."""
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.optimize.rewrite import optimize_source

    src = _read(args.file)
    if src is None:
        return 2
    cm = CostModel(args.width, args.scale)
    result = optimize_source(src, cm, vectors=args.vectors)
    if not result.changed:
        print(f"optimize {Path(args.file).name}: {result.note or 'nothing to do'}")
        return 0
    print(f"optimize {Path(args.file).name}: {len(result.rewrites)} rewrite(s)")
    for rw in result.rewrites:
        print(f"  [{rw.tag:<6}] line {rw.line}: {rw.description}")
    delta = result.latency_after - result.latency_before
    print(
        f"  critical path: {result.latency_before} -> {result.latency_after} cycles "
        f"({delta:+d}); dividers: {result.dividers_before} -> {result.dividers_after}"
    )
    if delta > 0:
        print(
            "  note: latency rose — the divisions were parallel, so RECIP trades "
            "depth for divider area; keep whichever matters for this design"
        )
    print("  accuracy vs the original fixed-point pipeline (rounding moves — see docs):")
    for acc in result.accuracy:
        print(
            f"    {acc.name}: max |Δ| {acc.max_delta:.3g}, SQNR "
            f"{acc.sqnr_before_db:.1f} -> {acc.sqnr_after_db:.1f} dB"
        )
    if args.output:
        Path(args.output).write_text(result.source, encoding="utf-8")
        print(f"wrote {args.output}")
    elif args.in_place:
        Path(args.file).write_text(result.source, encoding="utf-8")
        print(f"rewrote {args.file} in place")
    else:
        print("--- optimized source (use -o FILE or --in-place to write) ---")
        print(result.source, end="")
    return 0


def _cmd_ci(args: argparse.Namespace) -> int:
    """PJ-2: run the whole configured gate from one project sidecar."""
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.project import load_project

    toml_path = Path(args.project)
    try:
        project = load_project(toml_path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    base = toml_path.parent
    m_path = project.resolve(base, project.m)
    if m_path is None or not m_path.is_file():
        print(f"error: [design] m = {project.m!r} not found next to {toml_path}", file=sys.stderr)
        return 2
    cm = CostModel(project.width, project.scale)
    src = m_path.read_text(encoding="utf-8")
    audit = audit_source(src, m_path.name, cm)
    failed = False
    print(f"ci {toml_path.name} @ {cm.width}/{cm.scale}")
    print(
        f"  audit: {audit.total_latency} cycles, {sum(audit.census.values())} instances, "
        f"{len(audit.findings)} finding(s), {len(audit.skipped)} skipped"
    )
    if project.ranges:
        from pipeforge.core.ranges.interval import Interval
        from pipeforge.core.ranges.propagate import RangeError, propagate

        try:
            report = propagate(
                audit.dag,
                {k: Interval(lo, hi) for k, (lo, hi) in project.ranges.items()},
                cm,
            )
            overflow, hazards = len(report.overflow_nodes), len(report.hazard_nodes)
            verdict = "ok" if not (overflow or hazards) else "FAIL"
            print(f"  ranges: {verdict} — {overflow} overflow, {hazards} ÷-near-0")
            failed |= bool(overflow or hazards)
        except RangeError as exc:
            print(f"  ranges: FAIL — {exc}")
            failed = True
    sv_path = project.resolve(base, project.sv)
    if sv_path is not None and sv_path.is_file():
        from pipeforge.core.svlint.checks import lint_source

        lint = lint_source(
            sv_path.read_text(encoding="utf-8", errors="replace"), sv_path.name, cm, audit=audit
        )
        if args.sarif:
            from pipeforge.core.reports.sarif import sarif_document

            Path(args.sarif).write_text(
                sarif_document(lint, str(sv_path), __version__), encoding="utf-8"
            )
        print(f"  lint: {'clean' if not lint.findings else f'{len(lint.findings)} finding(s)'}")
        failed |= bool(lint.findings)
        cfg = project.cosim
        if cfg.top:
            from pipeforge.core.cosim.runner import CosimUnavailable, run_cosim

            try:
                result = run_cosim(
                    audit,
                    dut_sv=sv_path,
                    dut_module=cfg.top,
                    work_dir=base / "cosim_work",
                    include_dirs=[base / d for d in cfg.include],
                    extra_sources=[base / s for s in cfg.sources],
                    vector_count=cfg.vectors,
                    cadence=cfg.cadence,
                    backend=None if cfg.backend == "auto" else cfg.backend,
                    bisect_on_failure=True,
                )
            except CosimUnavailable as exc:
                print(f"  cosim: tools unavailable — {exc}", file=sys.stderr)
                return 3
            if args.junit_xml:
                from pipeforge.core.reports.junit import junit_xml

                Path(args.junit_xml).write_text(
                    junit_xml(result, f"cosim.{cfg.top}"), encoding="utf-8"
                )
            print(f"  cosim: {'PASS' if result.passed else 'FAIL'} [{result.harness_backend}]")
            if not result.passed and result.failure_file:
                print(f"         replay: {result.failure_file}")
            failed |= not result.passed
    print(f"  gate: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def _cmd_report(args: argparse.Namespace) -> int:
    """RH-1: one self-contained HTML design-review report."""
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.costmodel.resources import estimate_resources
    from pipeforge.core.reports.html import build_report

    src = _read(args.file)
    if src is None:
        return 2
    path = Path(args.file)
    cm = CostModel(args.width, args.scale)
    audit = audit_source(src, path.name, cm)
    resources = estimate_resources(audit.census, cm, args.family)
    range_report = None
    if args.range:
        from pipeforge.core.ranges.interval import Interval
        from pipeforge.core.ranges.propagate import RangeError, propagate

        declared = _parse_ranges(args.range)
        try:
            range_report = propagate(
                audit.dag, {k: Interval(lo, hi) for k, (lo, hi) in declared.items()}, cm
            )
        except RangeError as exc:
            print(f"note: skipping range section — {exc}", file=sys.stderr)
    lint = None
    if args.sv:
        from pipeforge.core.svlint.checks import lint_source

        sv_text = _read(args.sv)
        if sv_text is not None:
            lint = lint_source(sv_text, Path(args.sv).name, cm, audit=audit)
    html = build_report(audit, resources=resources, range_report=range_report, lint=lint)
    out = Path(args.output)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def _cmd_matlab(args: argparse.Namespace) -> int:
    from pipeforge.services.matlab_bridge import (
        MatlabConfig,
        MatlabUnavailable,
        probe,
        take_snapshot,
    )

    config = MatlabConfig.load()
    if args.matlab_action == "validate":
        from pipeforge.core.audit.engine import audit_source
        from pipeforge.core.costmodel.model import CostModel
        from pipeforge.core.fxp.fx import FxFormat
        from pipeforge.core.fxp.validate import ValidateError, compare_to_matlab

        m_path = Path(args.file)
        if m_path.suffix.lower() == ".mat":
            print(
                "validate needs a .m script (its statements are what get checked); "
                "to browse a .mat alone use: pipeforge-cli matlab snapshot "
                f"{m_path.name}",
                file=sys.stderr,
            )
            return 2
        try:
            src = m_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            snapshot = take_snapshot(
                m_path,
                setup=Path(args.setup) if args.setup else None,
                config=config,
                force=args.force,
                log=lambda line: print(line, file=sys.stderr),
            )
        except MatlabUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3
        cm = CostModel(args.width, args.scale)
        audit = audit_source(src, m_path.name, cm, snapshot=snapshot)
        from pipeforge.core.fxp.evaluator import EvalError

        try:
            report = compare_to_matlab(audit.dag, snapshot, FxFormat(args.width, args.scale))
        except (ValidateError, EvalError) as exc:
            print(f"cannot validate: {exc}", file=sys.stderr)
            return 1
        print(
            f"validate {m_path.name} @ {args.width}/{args.scale} — golden model vs "
            f"MATLAB {snapshot.matlab_version}"
        )
        for c in report.checks:
            exact = c.stats.max_abs_error == 0.0
            verdict = "bit-clean" if exact else f"max|e| {c.stats.max_abs_error:.3g}"
            sqnr = f", SQNR {c.stats.sqnr_db:.1f} dB" if not exact else ""
            print(f"  line {c.line:>3}  {c.target:<14} {c.compared} value(s): {verdict}{sqnr}")
        for name in report.uncheckable:
            print(f"  {name}: no MATLAB value to compare against")
        print(f"worst: max|e| {report.worst_abs_error:.3g}, SQNR {report.worst_sqnr_db:.1f} dB")
        return 0

    if args.matlab_action == "detect":
        from pipeforge.services.matlab_bridge import detect_and_save

        try:
            detected, version = detect_and_save(log=lambda s: print(s, file=sys.stderr))
        except MatlabUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3
        print(f"MATLAB found via {detected.source}: {' '.join(detected.command)}")
        print(f"version: {version}")
        print("saved to settings — every machine keeps its own.")
        return 0

    if args.matlab_action == "probe":
        try:
            version = probe(config)
        except MatlabUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3
        print(f"MATLAB reachable via {' '.join(config.command)} (source: {config.source})")
        print(f"version: {version}")
        return 0

    # snapshot — a .m script (with optional setup) or a .mat file by itself
    from pipeforge.services.matlab_bridge import snapshot_target

    try:
        snapshot = snapshot_target(
            Path(args.file),
            setup=Path(args.setup) if args.setup else None,
            config=config,
            force=args.force,
            log=lambda line: print(line, file=sys.stderr),
        )
    except MatlabUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if args.output:
        Path(args.output).write_text(snapshot.to_json(), encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        if snapshot.error:
            print(f"script error (partial snapshot): {snapshot.error}")
        origin = snapshot.script or snapshot.setup or "workspace"
        print(f"snapshot of {origin} — MATLAB {snapshot.matlab_version}")
        for name, v in sorted(snapshot.variables.items()):
            fi = f" fi {v.fi.width}/{v.fi.scale}" if v.fi else ""
            rng = (
                f" range [{v.vmin:.6g}, {v.vmax:.6g}]"
                if v.vmin is not None and v.vmax is not None
                else ""
            )
            size = "x".join(str(d) for d in v.size)
            print(f"  {name:<20} {v.class_name:<14} {size:<8}{fi}{rng}")
    return 0


def _load_snapshot_arg(path_str: str | None):  # -> WorkspaceSnapshot | None
    if not path_str:
        return None
    from pipeforge.core.frontend.varinfo import WorkspaceSnapshot

    return WorkspaceSnapshot.from_json(Path(path_str).read_text(encoding="utf-8"))


def _cmd_demos(_args: argparse.Namespace) -> int:
    from pipeforge.demos import demo_dir, load_index

    print(f"packaged demos in {demo_dir()}\n")
    for entry in load_index():
        print(f"{entry.demo_id} — {entry.title}")
        print(f"  {entry.description}")
        print(f"  try:  {entry.command}")
        print(f"  gui:  {entry.gui}")
        print()
    return 0


def _read(path_str: str) -> str | None:
    try:
        return Path(path_str).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _fmt_vals(vals: tuple[float, ...] | None) -> str:
    if vals is None:
        return "-"
    head = ", ".join(f"{v:.6g}" for v in vals[:3])
    return f"[{head}{', …' if len(vals) > 3 else ''}]"


def _cmd_reconcile(args: argparse.Namespace) -> int:
    """WS-3/WS-4: reconcile a .mat against its SV `software` mirror."""
    import json as json_mod

    from pipeforge.core.fxp.fx import FxFormat
    from pipeforge.core.mapping.persist import load_map
    from pipeforge.core.workspace.mat_loader import load_mat
    from pipeforge.core.workspace.reconcile import EXACT, TOLERANCE, reconcile
    from pipeforge.core.workspace.sv_struct import SvStructError, load_sv_software

    try:
        mat = load_mat(args.mat)
        sv = load_sv_software(args.sv)
    except (OSError, ValueError, SvStructError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cmap = load_map(Path(args.map)) if args.map else None
    mode = TOLERANCE if args.mode == "tolerance" else EXACT
    report = reconcile(
        mat,
        sv,
        FxFormat(args.width, args.scale),
        mode=mode,
        decimals=args.decimals,
        lsb_tol=args.lsb,
        cmap=cmap,
    )
    if args.json:
        print(
            json_mod.dumps(
                {
                    "mode": report.mode,
                    "fields": [
                        {
                            "path": f.path,
                            "verdict": f.verdict,
                            "delta": f.delta,
                            "rounding_hazard": f.rounding_hazard,
                            "mat": list(f.mat_value) if f.mat_value else None,
                            "sv": list(f.sv_value) if f.sv_value else None,
                        }
                        for f in report.fields
                    ],
                },
                indent=2,
            )
        )
    else:
        print(
            f"reconcile {Path(args.mat).name} <-> {Path(args.sv).name} "
            f"({report.mode} @ {args.width}/{args.scale})"
        )
        print(f"  {'PATH':<22} {'MAT':<16} {'SV':<16} {'VERDICT':<14} Δ")
        for f in report.fields:
            hazard = "  ⚠ rounding-hazard" if f.rounding_hazard else ""
            print(
                f"  {f.path:<22} {_fmt_vals(f.mat_value):<16} {_fmt_vals(f.sv_value):<16} "
                f"{f.verdict:<14} {f.delta:.3g}{hazard}"
            )
        verdicts: dict[str, int] = {}
        for f in report.fields:
            verdicts[f.verdict] = verdicts.get(f.verdict, 0) + 1
        summary = ", ".join(f"{n} {v}" for v, n in sorted(verdicts.items()))
        haz = len(report.hazards)
        print(f"  summary: {summary}" + (f", {haz} rounding-hazard(s)" if haz else ""))
    return 1 if (report.mismatches or report.hazards) else 0


def _entities_for_map(m_file: str | None, sv_file: str | None, mat_file: str | None, cm):
    """Build (matlab_entities, sv_entities) from the loaded design sources (MP-2)."""
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.mapping.sources import matlab_entities, sv_entities
    from pipeforge.core.svlint.parse import parse_sv
    from pipeforge.core.workspace.mat_loader import load_mat
    from pipeforge.core.workspace.sv_struct import SvStructError, parse_sv_software

    dag = audit_source(_read(m_file), Path(m_file).name, cm).dag if m_file else None
    module = None
    software = None
    if sv_file:
        sv_text = _read(sv_file) or ""
        module = parse_sv(sv_text)[0]
        try:
            software = parse_sv_software(sv_text)
        except SvStructError:
            software = None
    mat_tree = load_mat(mat_file) if mat_file else None
    return matlab_entities(dag, mat_tree), sv_entities(module, software)


def _cmd_map(args: argparse.Namespace) -> int:
    """MP-2/MP-3/MP-6: propose, show, confirm, and group correspondences."""
    import json as json_mod

    from pipeforge.core.mapping.persist import load_map, save_map
    from pipeforge.core.mapping.propose import propose_variables

    if args.map_action == "propose":
        from pipeforge.core.costmodel.model import CostModel
        from pipeforge.core.mapping.model import CorrespondenceMap

        cm = CostModel(args.width, args.scale)
        matlab, sv = _entities_for_map(args.m, args.sv, args.mat, cm)

        cmap = CorrespondenceMap(variables=propose_variables(matlab, sv))
        out = Path(args.output)
        save_map(cmap, out)
        print(f"map propose: {len(matlab)} MATLAB, {len(sv)} SV entities — wrote {out}")
        print(f"  {'MATLAB':<18} {'SV':<18} CONFIDENCE")
        for v in cmap.variables:
            print(f"  {v.matlab or '-':<18} {v.sv or '-':<18} {v.confidence}")
        return 0

    sidecar = Path(args.sidecar)
    cmap = load_map(sidecar)
    if args.map_action == "show":
        if args.json:
            from pipeforge.core.mapping.persist import to_dict

            print(json_mod.dumps(to_dict(cmap), indent=2))
            return 0
        confirmed = cmap.confirmed()
        print(
            f"map {sidecar.name} — {len(confirmed)} confirmed, "
            f"{len(cmap.variables) - len(confirmed)} unconfirmed, {len(cmap.groups)} group(s)"
        )
        for v in cmap.variables:
            print(f"  [{v.status:<9}] {v.matlab or '-'} -> {v.sv or '-'}  ({v.confidence})")
        for g in cmap.groups:
            mark = "confirmed" if g.confirmed else "draft"
            print(f"  group {g.matlab_op} -> {g.sv_instances}  ({mark})")
        return 0
    if args.map_action == "confirm":
        cmap.link(args.matlab, args.sv_entity)
        save_map(cmap, sidecar)
        print(f"confirmed {args.matlab} -> {args.sv_entity} in {sidecar.name}")
        return 0
    if args.map_action == "group":
        cmap.add_group(args.matlab_op, list(args.instances))
        save_map(cmap, sidecar)
        print(f"grouped {args.matlab_op} -> {list(args.instances)} in {sidecar.name}")
        return 0
    return 2


def _cmd_traceability(args: argparse.Namespace) -> int:
    """DX-2: export the MATLAB↔RTL correspondence as Markdown/CSV."""
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.diagnostics.traceability import export_traceability
    from pipeforge.core.frontend.dag import build_dag
    from pipeforge.core.frontend.parser import parse_program
    from pipeforge.core.mapping.persist import load_map
    from pipeforge.core.svlint.parse import parse_sv

    cm = CostModel(args.width, args.scale)
    m_src = _read(args.m)
    sv_src = _read(args.sv)
    if m_src is None or sv_src is None:
        return 2
    assigns, _ = parse_program(m_src)
    dag = build_dag(assigns, cm)[0].dag
    module = parse_sv(sv_src)[0]
    cmap = load_map(Path(args.sidecar))
    doc = export_traceability(cmap, dag, module, cm, fmt=args.format)
    if args.output:
        Path(args.output).write_text(doc, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(doc, end="")
    return 0


def _cmd_oracle(args: argparse.Namespace) -> int:
    """WS-5: drive the golden model with a .mat's I/O vectors and grade it."""
    import json as json_mod

    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.cosim.oracle import REFERENCE_FIXED, REFERENCE_FLOAT, run_vector_oracle
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.fxp.fx import FxFormat
    from pipeforge.core.workspace.mat_loader import load_mat

    m_src = _read(args.file)
    if m_src is None:
        return 2
    cm = CostModel(args.width, args.scale)
    audit = audit_source(m_src, Path(args.file).name, cm)
    try:
        tree = load_mat(args.mat)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # convention: .mat fields named like a DAG input feed it; fields named like
    # an output signal are the reference outputs.
    in_labels = {n.label for n in audit.dag.inputs()}
    out_signals = {n.signal for n in audit.dag.outputs() if n.signal}
    inputs = {p: list(f.values) for p, f in tree.fields.items() if p in in_labels and f.values}
    references = {
        p: list(f.values) for p, f in tree.fields.items() if p in out_signals and f.values
    }
    if not inputs:
        print(
            f"error: no .mat fields match the script's inputs ({sorted(in_labels)})",
            file=sys.stderr,
        )
        return 2
    kind = REFERENCE_FIXED if args.reference == "fixed" else REFERENCE_FLOAT
    result = run_vector_oracle(audit, inputs, references, FxFormat(args.width, args.scale), kind)
    if args.json:
        print(
            json_mod.dumps(
                {
                    "reference_kind": result.reference_kind,
                    "mode": result.mode,
                    "passed": result.passed,
                    "outputs": {
                        k: {
                            "max_abs_error": s.max_abs_error,
                            "rms_error": s.rms_error,
                            "sqnr_db": s.sqnr_db,
                        }
                        for k, s in result.outputs.items()
                    },
                    "bit_exact": result.bit_exact,
                },
                indent=2,
            )
        )
    else:
        print(
            f"oracle {Path(args.file).name} vs {Path(args.mat).name} — "
            f"reference: {result.reference_kind} ({result.mode})"
        )
        for sig, stats in result.outputs.items():
            be = f", bit-exact: {result.bit_exact.get(sig)}" if kind == REFERENCE_FIXED else ""
            print(
                f"  {sig}: max|e| {stats.max_abs_error:.3g}, RMS {stats.rms_error:.3g}, "
                f"SQNR {stats.sqnr_db:.1f} dB{be}"
            )
        if result.passed is None:
            print("  (float reference — within-precision only; no bit-exact verdict)")
    return 1 if result.passed is False else 0


def _add_fixedp_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-w", "--width", type=int, default=16, help="fixedp WIDTH (default 16)")
    p.add_argument("-s", "--scale", type=int, default=12, help="fixedp SCALE (default 12)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeforge-cli",
        description="MATLAB-to-nkMatlib FPGA pipeline workbench (headless)",
    )
    parser.add_argument("--version", action="version", version=f"pipeforge {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p_audit = sub.add_parser(
        "audit", help="latency audit of a MATLAB script against the nkMatlib cost model"
    )
    p_audit.add_argument("file", help="MATLAB script (.m)")
    _add_fixedp_args(p_audit)
    p_audit.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_audit.add_argument(
        "--snapshot",
        metavar="JSON",
        help="MATLAB workspace snapshot (from 'matlab snapshot -o'): enables "
        "shape-aware costing and fi FORMAT findings",
    )
    p_audit.add_argument(
        "--resources",
        action="store_true",
        help="append a device resource estimate (DSP tiles + rough LUT/FF) (RE-1)",
    )
    p_audit.add_argument(
        "--family",
        default="xilinx7",
        choices=("xilinx7", "ultrascale", "intel", "lattice"),
        help="device family for --resources (default xilinx7)",
    )
    p_audit.add_argument(
        "--watch", action="store_true", help="re-run on every save; prints the latency delta"
    )
    p_audit.set_defaults(func=_cmd_audit)

    p_lint = sub.add_parser(
        "lint", help="check a SystemVerilog file against nkMatlib pipeline conventions"
    )
    p_lint.add_argument("file", help="SystemVerilog file (.sv)")
    _add_fixedp_args(p_lint)
    p_lint.add_argument(
        "--disable",
        action="append",
        metavar="CHECK",
        help="suppress a check (delay-match, suffix, valid-chain, reset, naming, unknown-module)",
    )
    p_lint.add_argument(
        "--no-pyslang", action="store_true", help="force the structural fallback backend"
    )
    p_lint.add_argument(
        "--verilator",
        action="store_true",
        help="also run `verilator --lint-only -Wall` and merge its findings (SL-7)",
    )
    p_lint.add_argument(
        "--include",
        action="append",
        metavar="DIR",
        help="include directory for the Verilator backend (repeatable)",
    )
    p_lint.add_argument(
        "--sarif",
        metavar="FILE",
        help="also write findings as SARIF 2.1.0 (GitHub code-scanning annotations) (CI-2)",
    )
    p_lint.add_argument("--watch", action="store_true", help="re-lint on every save")
    p_lint.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_lint.set_defaults(func=_cmd_lint)

    p_cosim = sub.add_parser(
        "cosim", help="co-simulate RTL against the bit-exact golden model (needs Verilator)"
    )
    p_cosim.add_argument("file", help="MATLAB script (.m)")
    p_cosim.add_argument("--sv", required=True, help="SystemVerilog DUT file")
    p_cosim.add_argument("--top", required=True, help="DUT module name")
    p_cosim.add_argument(
        "--source", action="append", metavar="SV", help="additional SV source (repeatable)"
    )
    p_cosim.add_argument(
        "--include", action="append", metavar="DIR", help="include directory (repeatable)"
    )
    p_cosim.add_argument("--vectors", type=int, default=256, help="stimulus vector count")
    p_cosim.add_argument("--work-dir", help="working directory for generated collateral")
    p_cosim.add_argument(
        "--backend",
        choices=("auto", "cocotb", "verilator"),
        default="auto",
        help="harness backend: auto (default: cocotb when importable, else the "
        "cocotb-free verilator-native path), or force one (TL-1/TL-2)",
    )
    p_cosim.add_argument(
        "--cadence",
        choices=("continuous", "gapped", "single", "restart"),
        default="continuous",
        help="valid-driving cadence (CS-6)",
    )
    p_cosim.add_argument(
        "--probes",
        metavar="auto|IDS",
        help="capture internal signals: 'auto' (all ops) or comma-separated node ids (CS-7)",
    )
    p_cosim.add_argument(
        "--bisect",
        action="store_true",
        help="on failure, localize the first divergent stage + print triage (BI-4/DX-1)",
    )
    p_cosim.add_argument(
        "--replay",
        metavar="FAILURE_JSON",
        help="re-run the exact stimulus persisted by a previous failing run (VX-1)",
    )
    p_cosim.add_argument(
        "--range",
        action="append",
        metavar="NAME=LO:HI",
        help="constrain stimulus to declared input ranges (required to verify "
        "--mixed modules) (MX-1)",
    )
    p_cosim.add_argument(
        "--junit-xml",
        metavar="FILE",
        help="write the result as JUnit XML for CI dashboards (CI-1)",
    )
    _add_fixedp_args(p_cosim)
    p_cosim.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_cosim.set_defaults(func=_cmd_cosim)

    p_gen = sub.add_parser(
        "codegen", help="emit an nkMatlib SystemVerilog skeleton from a MATLAB script"
    )
    p_gen.add_argument("file", help="MATLAB script (.m)")
    p_gen.add_argument("-m", "--module", help="generated module name (default: file stem)")
    p_gen.add_argument("-o", "--output", help="write to file instead of stdout")
    p_gen.add_argument(
        "--axis",
        action="store_true",
        help="also emit an AXI-Stream (tvalid/tready) wrapper with credit-based "
        "backpressure (AX-1)",
    )
    p_gen.add_argument(
        "--mixed",
        action="store_true",
        help="narrow range-proven operators to per-instance widths (needs --range "
        "per input) (MX-1)",
    )
    p_gen.add_argument(
        "--range",
        action="append",
        metavar="NAME=LO:HI",
        help="declared input range for --mixed (repeatable)",
    )
    _add_fixedp_args(p_gen)
    p_gen.set_defaults(func=_cmd_codegen)

    p_synth = sub.add_parser(
        "synth", help="quick yosys synthesis sanity-check: cells + logic depth (SY-1)"
    )
    p_synth.add_argument("file", help="SystemVerilog file (.sv) or MATLAB script (.m)")
    p_synth.add_argument("--top", help="top module (default: file stem)")
    p_synth.add_argument(
        "--include", action="append", metavar="DIR", help="include directory (repeatable)"
    )
    p_synth.add_argument(
        "--source", action="append", metavar="SV", help="additional SV source (repeatable)"
    )
    _add_fixedp_args(p_synth)
    p_synth.set_defaults(func=_cmd_synth)

    p_extb = sub.add_parser(
        "export-tb",
        help="export vectors + a standalone self-checking SV testbench (no PipeForge "
        "needed to run it) (VX-2)",
    )
    p_extb.add_argument("file", help="MATLAB script (.m)")
    p_extb.add_argument("-o", "--output", required=True, help="output directory")
    p_extb.add_argument("-m", "--module", help="DUT module name (default: file stem)")
    p_extb.add_argument("--vectors", type=int, default=256, help="stimulus vector count")
    p_extb.add_argument(
        "--from-failure",
        metavar="FAILURE_JSON",
        help="use the exact vectors persisted by a failing cosim run (VX-1)",
    )
    _add_fixedp_args(p_extb)
    p_extb.set_defaults(func=_cmd_export_tb)

    p_opt = sub.add_parser(
        "optimize",
        help="apply the auditor's rewrites (RECIP/CDIV/SERDIV/POW/CSE) to the source (OP-1)",
    )
    p_opt.add_argument("file", help="MATLAB script (.m)")
    p_opt.add_argument("-o", "--output", help="write the optimized source here")
    p_opt.add_argument(
        "--in-place", action="store_true", help="overwrite the input file with the result"
    )
    p_opt.add_argument(
        "--vectors", type=int, default=64, help="vectors for the accuracy comparison"
    )
    _add_fixedp_args(p_opt)
    p_opt.set_defaults(func=_cmd_optimize)

    p_ci = sub.add_parser(
        "ci", help="run the whole configured gate from a .pipeforge.toml sidecar (PJ-2)"
    )
    p_ci.add_argument("project", help="design sidecar (model.pipeforge.toml)")
    p_ci.add_argument("--junit-xml", metavar="FILE", help="write cosim results as JUnit XML")
    p_ci.add_argument("--sarif", metavar="FILE", help="write lint findings as SARIF")
    p_ci.set_defaults(func=_cmd_ci)

    p_report = sub.add_parser("report", help="one self-contained HTML design-review report (RH-1)")
    p_report.add_argument("file", help="MATLAB script (.m)")
    p_report.add_argument("-o", "--output", required=True, help="output .html path")
    p_report.add_argument(
        "--range",
        action="append",
        metavar="NAME=LO:HI",
        help="input range: adds the range-analysis section (repeatable)",
    )
    p_report.add_argument("--sv", help="SystemVerilog file: adds the lint section")
    p_report.add_argument(
        "--family",
        default="xilinx7",
        choices=("xilinx7", "ultrascale", "intel", "lattice"),
        help="device family for the resource estimate",
    )
    _add_fixedp_args(p_report)
    p_report.set_defaults(func=_cmd_report)

    p_ranges = sub.add_parser(
        "ranges", help="propagate value ranges; flag overflow and near-zero divisors"
    )
    p_ranges.add_argument("file", help="MATLAB script (.m)")
    p_ranges.add_argument(
        "--range",
        action="append",
        metavar="NAME=LO:HI",
        help="declared input range (repeatable)",
    )
    p_ranges.add_argument(
        "--method", choices=("interval", "affine"), default="interval", help="analysis method"
    )
    p_ranges.add_argument(
        "--recommend",
        type=float,
        metavar="BUDGET",
        help="also recommend WIDTH/SCALE for this absolute error budget",
    )
    p_ranges.add_argument(
        "--snapshot",
        metavar="JSON",
        help="MATLAB workspace snapshot: derive input ranges from live min/max",
    )
    _add_fixedp_args(p_ranges)
    p_ranges.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_ranges.set_defaults(func=_cmd_ranges)

    p_dse = sub.add_parser("dse", help="sweep WIDTH/SCALE grids; report the Pareto front")
    p_dse.add_argument("file", help="MATLAB script (.m)")
    p_dse.add_argument("--widths", default="12,16,20,24", help="comma-separated WIDTH grid")
    p_dse.add_argument("--scales", default="8,12,16", help="comma-separated SCALE grid")
    p_dse.add_argument("--vectors", type=int, default=64, help="stimulus vectors per point")
    p_dse.add_argument("--csv", help="export all points as CSV")
    p_dse.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_dse.set_defaults(func=_cmd_dse)

    p_matlab = sub.add_parser(
        "matlab", help="bridge to a live MATLAB session (snapshot workspace variables)"
    )
    matlab_sub = p_matlab.add_subparsers(dest="matlab_action", metavar="action", required=True)
    matlab_sub.add_parser("probe", help="check MATLAB reachability and version (slow)")
    matlab_sub.add_parser(
        "detect",
        help="find a working MATLAB (env/PATH/installs/distrobox) and save it to settings",
    )
    p_snap = matlab_sub.add_parser(
        "snapshot",
        help="capture every variable: run setup + a .m script, or load a .mat alone",
    )
    p_snap.add_argument("file", help="MATLAB script (.m) or parameter file (.mat)")
    p_snap.add_argument("--setup", help="workspace setup: a .m to run or a .mat to load")
    p_snap.add_argument("-o", "--output", help="write snapshot JSON here")
    p_snap.add_argument(
        "--force", action="store_true", help="retake even if a cached snapshot exists"
    )
    p_val = matlab_sub.add_parser(
        "validate",
        help="compare the fixed-point golden model against MATLAB's live values, "
        "statement by statement",
    )
    p_val.add_argument("file", help="MATLAB script (.m)")
    p_val.add_argument("--setup", help="workspace setup: a .m to run or a .mat to load")
    p_val.add_argument("--force", action="store_true", help="retake the snapshot")
    _add_fixedp_args(p_val)
    p_matlab.set_defaults(func=_cmd_matlab)

    p_recon = sub.add_parser(
        "reconcile", help="reconcile a .mat workspace against its SV `software` mirror (WS-3/4)"
    )
    p_recon.add_argument("mat", help="MATLAB workspace file (.mat)")
    p_recon.add_argument("sv", help="SystemVerilog file containing the `software` struct")
    p_recon.add_argument(
        "--mode",
        choices=("exact", "tolerance"),
        default="exact",
        help="exact (quantized bit-compare) or tolerance",
    )
    p_recon.add_argument("--decimals", type=int, help="tolerance: equal to N decimal places")
    p_recon.add_argument("--lsb", type=int, help="tolerance: within N LSBs")
    p_recon.add_argument("--map", metavar="SIDECAR", help="confirmed map to align renamed fields")
    _add_fixedp_args(p_recon)
    p_recon.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_recon.set_defaults(func=_cmd_reconcile)

    p_map = sub.add_parser("map", help="MATLAB↔SV correspondence map (propose/show/confirm/group)")
    map_sub = p_map.add_subparsers(dest="map_action", metavar="action", required=True)
    mp = map_sub.add_parser("propose", help="auto-propose variable correspondences (MP-2)")
    mp.add_argument("--m", help="MATLAB script (.m)")
    mp.add_argument("--sv", help="SystemVerilog file (.sv)")
    mp.add_argument("--mat", help="optional .mat workspace")
    mp.add_argument("-o", "--output", default="pipeforge.map.json", help="sidecar to write")
    _add_fixedp_args(mp)
    ms = map_sub.add_parser("show", help="print a sidecar map")
    ms.add_argument("sidecar", help="pipeforge.map.json")
    ms.add_argument("--json", action="store_true")
    mc = map_sub.add_parser("confirm", help="confirm a variable mapping (MP-2/MP-6)")
    mc.add_argument("sidecar")
    mc.add_argument("matlab")
    mc.add_argument("sv_entity", metavar="sv")
    mg = map_sub.add_parser("group", help="group a MATLAB op to SV instances (MP-3)")
    mg.add_argument("sidecar")
    mg.add_argument("matlab_op")
    mg.add_argument("instances", nargs="+", help="SV instance name(s)")
    p_map.set_defaults(func=_cmd_map)

    p_trace = sub.add_parser(
        "traceability", help="export the MATLAB↔RTL correspondence as Markdown/CSV (DX-2)"
    )
    p_trace.add_argument("sidecar", help="pipeforge.map.json")
    p_trace.add_argument("--m", required=True, help="MATLAB script (.m)")
    p_trace.add_argument("--sv", required=True, help="SystemVerilog file (.sv)")
    p_trace.add_argument("--format", choices=("markdown", "csv"), default="markdown")
    p_trace.add_argument("-o", "--output", help="write to file instead of stdout")
    _add_fixedp_args(p_trace)
    p_trace.set_defaults(func=_cmd_traceability)

    p_oracle = sub.add_parser(
        "oracle", help="drive the golden model with a .mat's I/O vectors as ground truth (WS-5)"
    )
    p_oracle.add_argument("file", help="MATLAB script (.m)")
    p_oracle.add_argument("--mat", required=True, help=".mat with input/output vectors")
    p_oracle.add_argument(
        "--reference",
        choices=("float", "fixed"),
        default="float",
        help="float -> within-precision (SQNR); fixed -> bit-exact allowed (§10)",
    )
    _add_fixedp_args(p_oracle)
    p_oracle.add_argument("--json", action="store_true")
    p_oracle.set_defaults(func=_cmd_oracle)

    p_demos = sub.add_parser(
        "demos", help="list the packaged demos with paths and suggested commands"
    )
    p_demos.set_defaults(func=_cmd_demos)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        _maybe_banner()
        parser.print_help()
        return 0
    func: object = getattr(args, "func", None)
    if callable(func):
        result = func(args)
        return int(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
