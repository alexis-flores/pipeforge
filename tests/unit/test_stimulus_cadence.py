"""CS-6: configurable valid cadence schedules."""

from __future__ import annotations

import pytest

from pipeforge.core.cosim.stimulus import valid_schedule


@pytest.mark.req("CS-6")
def test_gapped_valid_cadence() -> None:
    sched = valid_schedule(20, "gapped", seed=1)
    assert sum(sched) == 20  # every vector is still presented exactly once
    assert not all(sched)  # but with bubbles interspersed
    assert False in sched
    # deterministic for a given (count, cadence, seed)
    assert valid_schedule(20, "gapped", seed=1) == sched


@pytest.mark.req("CS-6")
def test_single_cycle_valids() -> None:
    sched = valid_schedule(5, "single")
    assert sum(sched) == 5
    # no two presents are adjacent: a bubble separates every valid
    assert not any(sched[i] and sched[i + 1] for i in range(len(sched) - 1))


@pytest.mark.req("CS-6")
def test_continuous_is_unbroken() -> None:
    assert valid_schedule(8, "continuous") == [True] * 8
