"""DSE tests (DSE-1, DSE-2, DSE-3): sweep, cancellation, Pareto, cache, export."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from threading import Event

import pytest

from pipeforge.core.dse.sweep import (
    SweepCancelled,
    SweepConfig,
    SweepPoint,
    cache_key,
    export_csv,
    export_json,
    load_cached,
    pareto_front,
    run_sweep,
    store_cached,
)

SRC = "n2 = x .* x + y .* y;\nn = sqrt(n2);\nu = x ./ n;"


def _point(w: int, s: int, lat: int, div: int, err: float) -> SweepPoint:
    return SweepPoint(
        width=w,
        scale=s,
        latency=lat,
        instances=5,
        dividers=div,
        max_abs_error=err,
        rms_error=err / 2,
        sqnr_db=40.0,
    )


@pytest.mark.req("DSE-1")
def test_sweep_evaluates_grid_with_progress() -> None:
    config = SweepConfig(widths=(12, 16), scales=(8, 12), vectors=16)
    seen: list[tuple[int, int]] = []
    points = run_sweep(SRC, "t.m", config, progress=lambda d, t: seen.append((d, t)))
    # 12/12 invalid (scale >= width): 3 valid points
    assert {(p.width, p.scale) for p in points} == {(12, 8), (16, 8), (16, 12)}
    assert seen[-1] == (3, 3)
    for p in points:
        assert p.latency > 0
        assert p.dividers == 1
        assert math.isfinite(p.max_abs_error)
        # latency derives from WIDTH/SCALE at runtime (C4)
    lat_by_key = {(p.width, p.scale): p.latency for p in points}
    assert lat_by_key[(16, 12)] > lat_by_key[(12, 8)]


@pytest.mark.req("DSE-1")
def test_sweep_cancellation() -> None:
    config = SweepConfig(widths=(12, 14, 16, 18, 20, 22), scales=(8, 10), vectors=8)
    cancel = Event()
    cancel.set()  # cancel immediately: first completion triggers the check
    with pytest.raises(SweepCancelled):
        run_sweep(SRC, "t.m", config, cancel=cancel, max_workers=2)


@pytest.mark.req("DSE-2")
class TestPareto:
    def test_dominated_points_removed(self) -> None:
        good = _point(16, 12, 30, 1, 0.001)
        dominated = _point(18, 12, 40, 2, 0.002)  # worse everywhere
        other = _point(12, 8, 20, 1, 0.01)  # faster but less precise: stays
        front = pareto_front([good, dominated, other])
        keys = {p.key for p in front}
        assert (16, 12) in keys
        assert (12, 8) in keys
        assert (18, 12) not in keys

    def test_front_sorted_by_error(self) -> None:
        pts = [_point(16, 12, 30, 1, 0.01), _point(20, 16, 40, 1, 0.001)]
        front = pareto_front(pts)
        errors = [p.max_abs_error for p in front]
        assert errors == sorted(errors)

    def test_identical_metrics_both_kept(self) -> None:
        a = _point(16, 12, 30, 1, 0.001)
        b = _point(18, 14, 30, 1, 0.001)
        assert len(pareto_front([a, b])) == 2


@pytest.mark.req("DSE-3")
class TestCacheAndExport:
    def test_cache_round_trip(self, tmp_path: Path) -> None:
        config = SweepConfig(widths=(16,), scales=(12,), vectors=8)
        key = cache_key(SRC, config)
        assert load_cached(tmp_path, key) is None
        points = [_point(16, 12, 30, 1, 0.001)]
        store_cached(tmp_path, key, points)
        assert load_cached(tmp_path, key) == points
        # different source -> different key
        assert cache_key(SRC + "\nz = x;", config) != key

    def test_csv_and_json_export(self, tmp_path: Path) -> None:
        points = [_point(16, 12, 30, 1, 0.001), _point(12, 8, 20, 1, 0.01)]
        csv_path = tmp_path / "sweep.csv"
        export_csv(points, csv_path)
        rows = list(csv.DictReader(csv_path.open()))
        assert len(rows) == 2
        assert rows[0]["width"] == "16"
        json_path = tmp_path / "sweep.json"
        export_json(points, json_path)
        assert "max_abs_error" in json_path.read_text(encoding="utf-8")
