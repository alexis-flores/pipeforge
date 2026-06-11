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


def _cmd_audit(args: argparse.Namespace) -> int:
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.audit.report import render_json, render_text
    from pipeforge.core.costmodel.model import CostModel

    path = Path(args.file)
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    cm = CostModel(args.width, args.scale)
    snapshot = _load_snapshot_arg(getattr(args, "snapshot", None))
    audit = audit_source(src, path.name, cm, snapshot=snapshot)
    print(render_json(audit) if args.json else render_text(audit), end="")
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
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
    try:
        result = run_cosim(
            audit,
            dut_sv=Path(args.sv),
            dut_module=args.top,
            work_dir=work_dir,
            extra_sources=[Path(p) for p in (args.source or [])],
            include_dirs=[Path(p) for p in (args.include or [])],
            vector_count=args.vectors,
        )
    except CosimUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if args.json:
        print(json_mod.dumps(result.to_payload(), indent=2))
    else:
        verdict = "PASS" if result.passed else "FAIL"
        print(f"cosim {m_path.name} vs {args.top}: {verdict}")
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
    try:
        sv = generate_sv(audit, module)
    except CodegenError as exc:
        print(f"cannot generate: {exc}", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(sv, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(sv, end="")
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
                f"max|e| {p.max_abs_error:.3g}, SQNR {p.sqnr_db:.1f} dB"
            )
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

    if args.matlab_action == "probe":
        try:
            version = probe(config)
        except MatlabUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 3
        print(f"MATLAB reachable via {' '.join(config.command)}")
        print(f"version: {version}")
        return 0

    # snapshot
    try:
        snapshot = take_snapshot(
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
        print(f"snapshot of {snapshot.script} — MATLAB {snapshot.matlab_version}")
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
    _add_fixedp_args(p_cosim)
    p_cosim.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_cosim.set_defaults(func=_cmd_cosim)

    p_gen = sub.add_parser(
        "codegen", help="emit an nkMatlib SystemVerilog skeleton from a MATLAB script"
    )
    p_gen.add_argument("file", help="MATLAB script (.m)")
    p_gen.add_argument("-m", "--module", help="generated module name (default: file stem)")
    p_gen.add_argument("-o", "--output", help="write to file instead of stdout")
    _add_fixedp_args(p_gen)
    p_gen.set_defaults(func=_cmd_codegen)

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
    p_snap = matlab_sub.add_parser(
        "snapshot", help="run setup + script in MATLAB and capture every variable"
    )
    p_snap.add_argument("file", help="MATLAB script (.m)")
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    func: object = getattr(args, "func", None)
    if callable(func):
        result = func(args)
        return int(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
