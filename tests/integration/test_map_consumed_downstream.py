"""MP-6: downstream capabilities read only CONFIRMED mappings from the sidecar.

The defect this guards against (§10): an unconfirmed auto-proposal being used as
if confirmed, producing a confident wrong comparison. WS reconciliation, the
WS-5 oracle, and bisection's node→instance binding all resolve correspondence
through :mod:`pipeforge.core.mapping.consume`; this test pins that those reads
never surface a proposed (unconfirmed) guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.mapping.consume import confirmed_sv, resolve_confirmed
from pipeforge.core.mapping.model import (
    PROPOSED,
    WEAK,
    CorrespondenceMap,
    VarMapping,
)
from pipeforge.core.mapping.persist import load_map, save_map, sidecar_for


@pytest.mark.req("MP-6")
def test_reconcile_oracle_bisect_read_confirmed_map(tmp_path: Path) -> None:
    cmap = CorrespondenceMap(
        variables=[
            # user-confirmed: authoritative for every downstream consumer
            VarMapping("norm_out", "i_rootsqr_norm_19", "confident", "confirmed"),
            # an auto-proposed guess the user has NOT confirmed
            VarMapping("prod", "i_smul_prod_4", WEAK, PROPOSED),
        ]
    )
    path = sidecar_for(tmp_path / "design.m")
    save_map(cmap, path)
    loaded = load_map(path)  # consumers load the sidecar, not the in-memory draft

    # the confirmed mapping resolves; the proposed guess resolves to None — the
    # consumer must treat that as "unknown", never as the guessed instance.
    assert resolve_confirmed(loaded, "norm_out") == "i_rootsqr_norm_19"
    assert resolve_confirmed(loaded, "prod") is None

    # the authoritative dict every consumer iterates excludes the guess entirely
    pairs = confirmed_sv(loaded)
    assert pairs == {"norm_out": "i_rootsqr_norm_19"}
    assert "prod" not in pairs


@pytest.mark.req("MP-6")
def test_confirming_promotes_a_proposal_to_authoritative(tmp_path: Path) -> None:
    cmap = CorrespondenceMap(variables=[VarMapping("prod", "i_smul_prod_4", WEAK, PROPOSED)])
    assert resolve_confirmed(cmap, "prod") is None  # not yet trusted
    cmap.link("prod", "i_smul_prod_4")  # user confirms
    assert resolve_confirmed(cmap, "prod") == "i_smul_prod_4"
    # marking unmapped removes it from the authoritative set again
    cmap.mark_unmapped("prod")
    assert resolve_confirmed(cmap, "prod") is None
