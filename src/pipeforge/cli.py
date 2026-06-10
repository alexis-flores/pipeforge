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
    audit = audit_source(src, path.name, cm)
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
