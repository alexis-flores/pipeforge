"""MP-6: human-readable, version-controllable sidecar map roundtrip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeforge.core.mapping.model import (
    CONFIRMED,
    PROPOSED,
    CorrespondenceMap,
    OperationGroup,
    VarMapping,
)
from pipeforge.core.mapping.persist import SIDECAR_NAME, load_map, save_map, sidecar_for


@pytest.mark.req("MP-6")
def test_sidecar_roundtrip_human_readable(tmp_path: Path) -> None:
    cmap = CorrespondenceMap(
        variables=[
            VarMapping("cfg.gain", "cfg_gain_0", "confident", CONFIRMED),
            VarMapping("taps", "taps_0", "weak", PROPOSED),
        ],
        groups=[OperationGroup("n007", ["i_smul_prod_4"], confirmed=True)],
        source_hashes={"design.m": "abc123"},
    )
    path = sidecar_for(tmp_path / "design.m")
    assert path.name == SIDECAR_NAME
    save_map(cmap, path)

    # human-readable: pretty-printed JSON with a trailing newline
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "  " in text  # indented
    payload = json.loads(text)
    assert payload["variables"][0]["status"] == CONFIRMED

    back = load_map(path)
    assert back.variables == cmap.variables
    assert back.groups == cmap.groups
    assert back.source_hashes == cmap.source_hashes
    assert back.version == cmap.version


@pytest.mark.req("MP-6")
def test_missing_sidecar_is_empty_map(tmp_path: Path) -> None:
    cmap = load_map(sidecar_for(tmp_path / "absent.m"))
    assert cmap.variables == [] and cmap.groups == []
