"""Live MATLAB workspace metadata (the MATLAB bridge data model).

A :class:`WorkspaceSnapshot` is what the bridge produces and what every
analysis consumes: per-variable class, shape, fixed-point format (from fi
objects), value range, and (capped) values. Names are dotted for struct
fields, e.g. ``cfg.gain``. Pure data — Qt-free, MATLAB-free.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

#: Cap on flattened element values carried per variable (the query script
#: enforces the same cap server-side; min/max always cover the full array).
VALUE_CAP = 4096


@dataclass(frozen=True)
class FiFormat:
    """numerictype of a fi object: WordLength/FractionLength/Signedness."""

    width: int
    scale: int
    signed: bool = True


@dataclass(frozen=True)
class VarInfo:
    name: str  # dotted for struct fields: 'cfg.gain'
    class_name: str  # MATLAB class: 'double', 'embedded.fi', 'struct', ...
    size: tuple[int, ...]
    is_real: bool = True
    fi: FiFormat | None = None
    vmin: float | None = None
    vmax: float | None = None
    values: tuple[float, ...] = ()
    truncated: bool = False

    @property
    def is_scalar(self) -> bool:
        return all(d == 1 for d in self.size)

    @property
    def is_vector(self) -> bool:
        nontrivial = [d for d in self.size if d != 1]
        return len(nontrivial) == 1

    @property
    def is_matrix(self) -> bool:
        nontrivial = [d for d in self.size if d != 1]
        return len(nontrivial) >= 2

    @property
    def length(self) -> int:
        n = 1
        for d in self.size:
            n *= d
        return n

    @property
    def shape2d(self) -> tuple[int, int]:
        """(rows, cols) view of the size, collapsing trailing singletons."""
        dims = [*self.size, 1, 1]
        return (dims[0], dims[1])


@dataclass
class WorkspaceSnapshot:
    variables: dict[str, VarInfo] = field(default_factory=dict)
    matlab_version: str = ""
    script: str = ""
    setup: str = ""
    timestamp: str = ""
    error: str = ""  # non-empty when the MATLAB run had a problem

    def __contains__(self, name: str) -> bool:
        return name in self.variables

    def get(self, name: str) -> VarInfo | None:
        direct = self.variables.get(name)
        if direct is not None:
            return direct
        return self._lane(name)

    def _lane(self, name: str) -> VarInfo | None:
        """Resolve a constant-index lane like 'x(3)' / 'm(2, 3)' from its base
        variable's values (LN-1) — 1-based, MATLAB column-major."""
        import re

        m = re.fullmatch(r"(.+)\((\d+)(?:,\s*(\d+))?\)", name)
        if m is None:
            return None
        base = self.variables.get(m.group(1))
        if base is None or not base.values:
            return None
        rows, cols = base.shape2d
        if m.group(3) is None:
            idx = int(m.group(2)) - 1  # linear, column-major
        else:
            r, c = int(m.group(2)) - 1, int(m.group(3)) - 1
            if not (0 <= r < rows and 0 <= c < cols):
                return None
            idx = c * rows + r
        if not 0 <= idx < len(base.values):
            return None
        value = base.values[idx]
        return VarInfo(
            name=name,
            class_name=base.class_name,
            size=(1, 1),
            is_real=base.is_real,
            fi=base.fi,
            vmin=value,
            vmax=value,
            values=(value,),
        )

    def fi_formats(self) -> dict[str, FiFormat]:
        return {n: v.fi for n, v in self.variables.items() if v.fi is not None}

    # -- (de)serialization ---------------------------------------------------

    def to_json(self) -> str:
        doc: dict[str, Any] = {
            "matlab_version": self.matlab_version,
            "script": self.script,
            "setup": self.setup,
            "timestamp": self.timestamp,
            "error": self.error,
            "variables": [
                {
                    "name": v.name,
                    "class": v.class_name,
                    "size": list(v.size),
                    "is_real": v.is_real,
                    "fi": (
                        {"width": v.fi.width, "scale": v.fi.scale, "signed": v.fi.signed}
                        if v.fi
                        else None
                    ),
                    "min": v.vmin,
                    "max": v.vmax,
                    "values": list(v.values),
                    "truncated": v.truncated,
                }
                for v in self.variables.values()
            ],
        }
        return json.dumps(doc, indent=1)

    @classmethod
    def from_payload(cls, doc: dict[str, Any]) -> WorkspaceSnapshot:
        snap = cls(
            matlab_version=str(doc.get("matlab_version", "")),
            script=str(doc.get("script", "")),
            setup=str(doc.get("setup", "")),
            timestamp=str(doc.get("timestamp", "")),
            error=str(doc.get("error", "")),
        )
        raw_vars = doc.get("variables", [])
        if isinstance(raw_vars, dict):  # jsonencode of a scalar struct array
            raw_vars = [raw_vars]
        for raw in raw_vars:
            info = _varinfo_from_payload(raw)
            if info is not None:
                snap.variables[info.name] = info
        return snap

    @classmethod
    def from_json(cls, text: str) -> WorkspaceSnapshot:
        return cls.from_payload(json.loads(text))


def _as_float_list(value: Any) -> list[float]:
    """MATLAB jsonencode flattens: scalars arrive bare, arrays as (nested) lists."""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    out: list[float] = []
    if isinstance(value, list):
        for item in value:
            out.extend(_as_float_list(item))
    return out


def _varinfo_from_payload(raw: Any) -> VarInfo | None:
    if not isinstance(raw, dict) or "name" not in raw:
        return None
    fi_raw = raw.get("fi")
    fi = None
    if isinstance(fi_raw, dict) and "width" in fi_raw:
        fi = FiFormat(
            width=int(fi_raw["width"]),
            scale=int(fi_raw["scale"]),
            signed=bool(fi_raw.get("signed", True)),
        )
    size_raw = raw.get("size", [1, 1])
    if isinstance(size_raw, (int, float)):
        size_raw = [size_raw]
    values = tuple(v for v in _as_float_list(raw.get("values")) if not math.isnan(v))
    vmin = raw.get("min")
    vmax = raw.get("max")
    return VarInfo(
        name=str(raw["name"]),
        class_name=str(raw.get("class", "double")),
        size=tuple(int(d) for d in size_raw),
        is_real=bool(raw.get("is_real", True)),
        fi=fi,
        vmin=float(vmin) if isinstance(vmin, (int, float)) else None,
        vmax=float(vmax) if isinstance(vmax, (int, float)) else None,
        values=values[:VALUE_CAP],
        truncated=bool(raw.get("truncated", False)),
    )
