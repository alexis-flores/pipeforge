"""Parse the SystemVerilog ``software`` struct mirror into a workspace tree (WS-2).

Each design carries a **hand-written** SV mirror of its `.mat` workspace struct,
conventionally named ``software``. Because it is maintained by hand it drifts
against the `.mat`; WS-3 reconciles the two, so both must reduce to the same
dotted-path/shape representation (the :class:`WsField` tree from WS-1).

Assumed convention (the nkMatlib-style mirror): the values live in a
SystemVerilog **assignment pattern** bound to ``software``::

    software_t software = '{
        gain: 0.5,
        taps: '{0.25, -0.5, 0.125, 0.0625},
        filt: '{ order: 4.0, ripple: 0.1 },
        cfg:  '{ fs: 48000.0, adc: '{ bits: 12.0, vref: 3.3 } }
    };

Keyed patterns (``key: value``) become struct fields (dotted paths); positional
patterns (``'{a, b, c}``) become vectors; nested positional patterns become
matrices, flattened column-major to match the AR-3/AR-4 layout contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from pipeforge.core.svlint.parse import strip_comments
from pipeforge.core.workspace.mat_loader import WorkspaceTree, WsField

# parsed value: a number, a struct (dict), or an array (list of values)
_Value = float | dict[str, "_Value"] | list["_Value"]

_SOFTWARE_RE = re.compile(r"\bsoftware\b\s*=\s*'\{")
_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")


class SvStructError(ValueError):
    """The ``software`` assignment pattern could not be parsed."""


def _match_brace(text: str, open_idx: int) -> int:
    """Index just past the ``}`` matching the ``{`` at ``open_idx``."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise SvStructError("unterminated '{ ... } assignment pattern")


def _split_top_level(body: str) -> list[str]:
    """Split a pattern body at top-level commas (ignoring nested patterns)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(body[start:i])
            start = i + 1
    tail = body[start:]
    if tail.strip():
        parts.append(tail)
    return parts


def _parse_value(text: str, start: int) -> tuple[_Value, int]:
    """Parse a scalar or a ``'{...}`` pattern beginning at/after ``start``."""
    i = start
    while i < len(text) and text[i] in " \t\n":
        i += 1
    if text.startswith("'{", i) or text[i] == "{":
        open_idx = text.index("{", i)
        end = _match_brace(text, open_idx)
        return _parse_pattern(text[open_idx + 1 : end - 1]), end
    m = _NUMBER_RE.match(text, i)
    if m is None:
        raise SvStructError(f"expected a number or pattern at: {text[i : i + 20]!r}")
    return float(m.group(0)), m.end()


def _parse_pattern(body: str) -> _Value:
    """Parse a pattern body into a struct (dict) or an array (list)."""
    entries = _split_top_level(body)
    keyed: dict[str, _Value] = {}
    array: list[_Value] = []
    for entry in entries:
        if not entry.strip():
            continue
        key_m = re.match(r"\s*([A-Za-z_]\w*)\s*:", entry)
        if key_m:
            value, _ = _parse_value(entry, key_m.end())
            keyed[key_m.group(1)] = value
        else:
            value, _ = _parse_value(entry, 0)
            array.append(value)
    if keyed and array:
        raise SvStructError("mixed keyed and positional entries in one pattern")
    return keyed if keyed else array


def _as_float(v: _Value) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    raise SvStructError("expected a scalar value in the assignment pattern")


def _flatten(path: str, value: _Value, out: dict[str, WsField]) -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            _flatten(f"{path}.{key}" if path else key, sub, out)
        return
    if isinstance(value, list):
        if value and all(isinstance(v, list) for v in value):  # matrix (rows of cols)
            rows = [v for v in value if isinstance(v, list)]
            nrows, ncols = len(rows), len(rows[0])
            colmajor = tuple(_as_float(rows[r][c]) for c in range(ncols) for r in range(nrows))
            out[path] = WsField(path, (nrows, ncols), colmajor)
        else:  # row vector of scalars
            out[path] = WsField(path, (1, len(value)), tuple(_as_float(v) for v in value))
        return
    out[path] = WsField(path, (1, 1), (_as_float(value),))


def parse_sv_software(text: str, source: str = "<sv>") -> WorkspaceTree:
    """Parse SV source containing a ``software`` assignment pattern (WS-2)."""
    clean = strip_comments(text)
    m = _SOFTWARE_RE.search(clean)
    if m is None:
        raise SvStructError("no `software` assignment pattern found")
    open_idx = clean.index("{", m.start())
    end = _match_brace(clean, open_idx)
    root = _parse_pattern(clean[open_idx + 1 : end - 1])
    fields: dict[str, WsField] = {}
    _flatten("", root, fields)
    return WorkspaceTree(source, "sv", fields)


def load_sv_software(path: str | Path) -> WorkspaceTree:
    """Load and parse an SV file containing the ``software`` mirror (WS-2)."""
    p = Path(path)
    return parse_sv_software(p.read_text(encoding="utf-8"), source=str(p))
