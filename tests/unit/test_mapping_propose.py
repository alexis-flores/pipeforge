"""MP-2: variable correspondence auto-proposal with confidence tiers."""

from __future__ import annotations

import pytest

from pipeforge.core.mapping.model import CONFIDENT, PROPOSED, UNMATCHED, WEAK
from pipeforge.core.mapping.propose import Entity, propose_variables


@pytest.mark.req("MP-2")
def test_variable_confidence_tiers() -> None:
    matlab = [
        Entity("gain", (1, 1), 16, 12),  # confident: all agree (vs gain_0)
        Entity("taps", (1, 4)),  # weak: shape differs from sv
        Entity("orphan", (1, 1)),  # unmatched: no SV counterpart
    ]
    sv = [
        Entity("gain_0", (1, 1), 16, 12),
        Entity("taps_0", (4, 1)),  # shape mismatch -> weak
        Entity("extra_0", (1, 1)),  # SV-only -> unmatched
    ]
    proposals = {(p.matlab, p.sv): p for p in propose_variables(matlab, sv)}

    confident = proposals[("gain", "gain_0")]
    assert confident.confidence == CONFIDENT
    assert confident.status == PROPOSED  # a draft, never auto-confirmed (MP-6)

    assert proposals[("taps", "taps_0")].confidence == WEAK
    assert proposals[("orphan", "")].confidence == UNMATCHED
    # an SV instance with no MATLAB counterpart is surfaced too (coverage)
    assert proposals[("", "extra_0")].confidence == UNMATCHED


@pytest.mark.req("MP-2")
def test_proposals_are_never_pre_confirmed() -> None:
    # the entire value of the layer is that no auto-guess is trusted (§10)
    proposals = propose_variables([Entity("x")], [Entity("x_0")])
    assert all(p.status == PROPOSED for p in proposals)
