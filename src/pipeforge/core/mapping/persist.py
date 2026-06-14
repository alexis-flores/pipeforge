"""Read/write the human-readable, version-controllable sidecar map (MP-6).

The sidecar (``pipeforge.map.json``) lives next to the design and is the
authoritative correspondence every downstream capability loads. It is plain,
sorted JSON so it diffs cleanly in review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeforge.core.mapping.model import (
    CorrespondenceMap,
    OperationGroup,
    VarMapping,
)

SIDECAR_NAME = "pipeforge.map.json"


def sidecar_for(design: Path) -> Path:
    """The sidecar path next to a design file."""
    return design.parent / SIDECAR_NAME


def to_dict(m: CorrespondenceMap) -> dict[str, Any]:
    return {
        "version": m.version,
        "variables": [
            {
                "matlab": v.matlab,
                "sv": v.sv,
                "confidence": v.confidence,
                "status": v.status,
            }
            for v in m.variables
        ],
        "groups": [
            {
                "matlab_op": g.matlab_op,
                "sv_instances": list(g.sv_instances),
                "confirmed": g.confirmed,
            }
            for g in m.groups
        ],
        "source_hashes": dict(sorted(m.source_hashes.items())),
    }


def from_dict(d: dict[str, Any]) -> CorrespondenceMap:
    variables = [
        VarMapping(
            matlab=v.get("matlab", ""),
            sv=v.get("sv", ""),
            confidence=v.get("confidence", "unmatched"),
            status=v.get("status", "proposed"),
        )
        for v in d.get("variables", [])
    ]
    groups = [
        OperationGroup(
            matlab_op=g.get("matlab_op", ""),
            sv_instances=list(g.get("sv_instances", [])),
            confirmed=g.get("confirmed", False),
        )
        for g in d.get("groups", [])
    ]
    return CorrespondenceMap(
        variables=variables,
        groups=groups,
        source_hashes=dict(d.get("source_hashes", {})),
        version=int(d.get("version", 1)),
    )


def save_map(m: CorrespondenceMap, path: Path) -> None:
    """Write the map as pretty, trailing-newline JSON for clean diffs."""
    path.write_text(json.dumps(to_dict(m), indent=2) + "\n", encoding="utf-8")


def load_map(path: Path) -> CorrespondenceMap:
    """Load a sidecar map; a missing file yields an empty map."""
    if not path.is_file():
        return CorrespondenceMap()
    return from_dict(json.loads(path.read_text(encoding="utf-8")))
