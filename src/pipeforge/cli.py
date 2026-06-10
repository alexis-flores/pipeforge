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
