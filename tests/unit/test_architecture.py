"""Architecture tests (SRS §8.5) — structural constraints enforced in CI.

(a) no module under core/ imports PyQt6 (C1)
(b) no hex color literals outside gui/theme/ (TH-1)
(c) no hard-coded latency constants outside core/costmodel/ (C4)
(d) the CLI exposes every implemented P0 capability headlessly
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import pipeforge
from pipeforge.cli import build_parser

SRC = Path(pipeforge.__file__).parent


def _py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


@pytest.mark.req("C1")
def test_core_has_no_qt_imports() -> None:
    offenders = []
    pattern = re.compile(r"^\s*(import\s+PyQt6|from\s+PyQt6)", re.MULTILINE)
    for path in _py_files(SRC / "core"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path))
    assert not offenders, f"core/ modules import PyQt6: {offenders}"


@pytest.mark.req("TH-1")
def test_no_hex_colors_outside_theme_files() -> None:
    hex_re = re.compile(r"#[0-9a-fA-F]{6}\b")
    offenders = []
    for path in _py_files(SRC):
        rel = path.relative_to(SRC)
        text = path.read_text(encoding="utf-8")
        if hex_re.search(text):
            offenders.append(str(rel))
    assert not offenders, f"hex color literals outside theme JSON: {offenders}"


# Latency names that may only be assigned inside core/costmodel/ (and theme-free
# test fixtures). The seed/ directory is exempt: it is a frozen reference asset.
_LATENCY_ASSIGN = re.compile(
    r"^\s*(MUL_LAT|DIV_LAT|SQRT_LAT|MATMUL_LAT|SUMSQR_LAT|ROOTSQR_LAT|CROSSP_LAT)\s*[:=]",
    re.MULTILINE,
)


@pytest.mark.req("C4")
def test_no_hardcoded_latencies_outside_costmodel() -> None:
    offenders = []
    for path in _py_files(SRC):
        rel = path.relative_to(SRC)
        if rel.parts[:2] == ("core", "costmodel"):
            continue
        if _LATENCY_ASSIGN.search(path.read_text(encoding="utf-8")):
            offenders.append(str(rel))
    assert not offenders, f"latency constants assigned outside core/costmodel: {offenders}"


# Grows phase by phase; by Phase 8 it must list every P0 capability (§8.5d).
EXPECTED_CLI_COMMANDS: set[str] = set()


@pytest.mark.req("8.5d")
def test_cli_exposes_capabilities() -> None:
    parser = build_parser()
    subactions = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    available: set[str] = set()
    for action in subactions:
        available |= set(action.choices)  # type: ignore[attr-defined]
    missing = EXPECTED_CLI_COMMANDS - available
    assert not missing, f"CLI lacks capability subcommands: {sorted(missing)}"
