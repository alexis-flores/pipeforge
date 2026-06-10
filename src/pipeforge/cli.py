"""pipeforge-cli — headless access to every PipeForge capability (§2.1).

Every P0 capability is exercisable from here without the GUI (§8.5d);
subcommands are added phase by phase.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pipeforge import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeforge-cli",
        description="MATLAB-to-nkMatlib FPGA pipeline workbench (headless)",
    )
    parser.add_argument("--version", action="version", version=f"pipeforge {__version__}")
    parser.add_subparsers(dest="command", metavar="command")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
