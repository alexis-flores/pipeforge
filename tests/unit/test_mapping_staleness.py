"""MP-5: map staleness — a renamed/removed entity trips re-confirmation."""

from __future__ import annotations

import pytest

from pipeforge.core.mapping.consume import resolve_confirmed
from pipeforge.core.mapping.model import CONFIRMED, DANGLING, CorrespondenceMap, VarMapping
from pipeforge.core.mapping.staleness import check_staleness, record_hashes


@pytest.mark.req("MP-5")
def test_source_change_flags_dangling_mappings() -> None:
    cmap = CorrespondenceMap(
        variables=[
            VarMapping("gain", "gain_0", "confident", CONFIRMED),
            VarMapping("taps", "taps_0", "confident", CONFIRMED),
        ]
    )
    sources = {"design.m": "gain = 0.5;\ntaps = 1;"}
    record_hashes(cmap, sources)

    # nothing changed -> no staleness, confirmed mappings still authoritative
    same = check_staleness(cmap, sources, {"gain", "taps"}, {"gain_0", "taps_0"})
    assert not same.is_stale
    assert resolve_confirmed(cmap, "gain") == "gain_0"

    # the .m changes and 'taps' is renamed away -> that mapping is now dangling
    changed = {"design.m": "gain = 0.5;\ncoeffs = 1;"}
    report = check_staleness(cmap, changed, {"gain", "coeffs"}, {"gain_0", "taps_0"})
    assert report.is_stale
    assert "design.m" in report.changed_sources
    assert [v.matlab for v in report.dangling] == ["taps"]

    # the dangling mapping is demoted and no longer used downstream (§10)...
    assert cmap.find("taps").status == DANGLING
    assert resolve_confirmed(cmap, "taps") is None
    # ...while the still-valid mapping keeps working
    assert resolve_confirmed(cmap, "gain") == "gain_0"


@pytest.mark.req("MP-5")
def test_reconfirmation_clears_dangling() -> None:
    cmap = CorrespondenceMap(variables=[VarMapping("x", "x_0", "confident", DANGLING)])
    assert resolve_confirmed(cmap, "x") is None
    cmap.link("x", "x_0")  # user re-confirms after reviewing the change
    assert resolve_confirmed(cmap, "x") == "x_0"
