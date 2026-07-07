"""Design-space exploration (DSE-1, DSE-2, DSE-3).

Sweeps WIDTH/SCALE grids in parallel worker processes with progress
reporting and cancellation; extracts the error-latency-divider Pareto
front; caches results on disk keyed by (source hash, config).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.cosim.stimulus import generate_stimulus
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.fxp.evaluator import error_stats, evaluate_fixed, evaluate_float
from pipeforge.core.fxp.fx import FxFormat, to_float


@dataclass(frozen=True)
class SweepPoint:
    """One evaluated (WIDTH, SCALE) configuration (DSE-1)."""

    width: int
    scale: int
    latency: int
    instances: int
    dividers: int
    max_abs_error: float
    rms_error: float
    sqnr_db: float
    dsp: int = 0  # hard multiplier tiles at the default device family (RE-1)

    @property
    def key(self) -> tuple[int, int]:
        return (self.width, self.scale)


@dataclass(frozen=True)
class SweepConfig:
    widths: tuple[int, ...]
    scales: tuple[int, ...]
    vectors: int = 64
    seed: int = 2024

    def points(self) -> list[tuple[int, int]]:
        return [(w, s) for w in self.widths for s in self.scales if 0 < s < w]


class SweepCancelled(RuntimeError):
    pass


def _evaluate_point(
    src: str, filename: str, width: int, scale: int, vectors: int, seed: int
) -> SweepPoint:
    """Worker: audit + fixed-vs-float error metrics for one format."""
    cm = CostModel(width, scale)
    audit = audit_source(src, filename, cm)
    fmt = FxFormat(width, scale)
    inputs = [n.label for n in audit.dag.inputs()]
    stim = generate_stimulus(inputs, FxFormat(width, scale), count=vectors, seed=seed)
    out_nodes = {n.signal: n.nid for n in audit.dag.outputs() if n.signal}
    refs: dict[str, list[float]] = {k: [] for k in out_nodes}
    meas: dict[str, list[float]] = {k: [] for k in out_nodes}
    for vec in stim:
        inputs_map: dict[str, list[int] | float | list[float]] = {k: [v] for k, v in vec.items()}
        fixed = evaluate_fixed(audit.dag, inputs_map, fmt)
        ref = evaluate_float(audit.dag, inputs_map, fmt)
        for name, nid in out_nodes.items():
            refs[name].append(ref[nid][0])
            meas[name].append(to_float(fixed[nid][0], fmt))
    max_abs = 0.0
    rms = 0.0
    sqnr = math.inf
    for name in out_nodes:
        s = error_stats(refs[name], meas[name])
        if math.isfinite(s.max_abs_error):
            max_abs = max(max_abs, s.max_abs_error)
            rms = max(rms, s.rms_error)
        if math.isfinite(s.sqnr_db):
            sqnr = min(sqnr, s.sqnr_db)
    from pipeforge.core.costmodel.resources import estimate_resources

    return SweepPoint(
        width=width,
        scale=scale,
        latency=audit.total_latency,
        instances=sum(audit.census.values()),
        dividers=audit.divider_count,
        max_abs_error=max_abs,
        rms_error=rms,
        sqnr_db=sqnr,
        dsp=estimate_resources(audit.census, cm).dsp,
    )


def run_sweep(
    src: str,
    filename: str,
    config: SweepConfig,
    progress: Callable[[int, int], None] | None = None,
    cancel: Event | None = None,
    max_workers: int | None = None,
) -> list[SweepPoint]:
    """Parallel sweep with progress and cancellation (DSE-1)."""
    todo = config.points()
    results: list[SweepPoint] = []
    total = len(todo)
    done = 0
    # spawn, not fork: the GUI host process is multi-threaded (Qt), where
    # fork() is deprecated on 3.12+ and can deadlock the children
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
        futures = {
            pool.submit(_evaluate_point, src, filename, w, s, config.vectors, config.seed): (w, s)
            for (w, s) in todo
        }
        for fut in as_completed(futures):
            if cancel is not None and cancel.is_set():
                for other in futures:
                    other.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                raise SweepCancelled(f"sweep cancelled after {done}/{total} points")
            results.append(fut.result())
            done += 1
            if progress is not None:
                progress(done, total)
    results.sort(key=lambda p: p.key)
    return results


# ---------------------------------------------------------------------------
# Pareto front (DSE-2): minimize (max_abs_error, latency, dividers)
# ---------------------------------------------------------------------------


def _dominates(a: SweepPoint, b: SweepPoint) -> bool:
    le = a.max_abs_error <= b.max_abs_error and a.latency <= b.latency and a.dividers <= b.dividers
    lt = a.max_abs_error < b.max_abs_error or a.latency < b.latency or a.dividers < b.dividers
    return le and lt


def pareto_front(points: list[SweepPoint]) -> list[SweepPoint]:
    """Non-dominated subset, sorted by error (DSE-2)."""
    front = [p for p in points if not any(_dominates(q, p) for q in points if q.key != p.key)]
    front.sort(key=lambda p: (p.max_abs_error, p.latency, p.dividers))
    return front


# ---------------------------------------------------------------------------
# Cache + export (DSE-3)
# ---------------------------------------------------------------------------


def cache_key(src: str, config: SweepConfig) -> str:
    h = hashlib.sha256()
    h.update(src.encode("utf-8"))
    h.update(repr((config.widths, config.scales, config.vectors, config.seed)).encode())
    return h.hexdigest()[:24]


def load_cached(cache_dir: Path, key: str) -> list[SweepPoint] | None:
    path = cache_dir / f"sweep_{key}.json"
    if not path.is_file():
        return None
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [SweepPoint(**row) for row in rows]
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def store_cached(cache_dir: Path, key: str, points: list[SweepPoint]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"sweep_{key}.json"
    path.write_text(json.dumps([asdict(p) for p in points], indent=1), encoding="utf-8")


def export_csv(points: list[SweepPoint], path: Path) -> None:
    fields = [
        "width",
        "scale",
        "latency",
        "instances",
        "dividers",
        "max_abs_error",
        "rms_error",
        "sqnr_db",
        "dsp",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for p in points:
            writer.writerow(asdict(p))


def export_json(points: list[SweepPoint], path: Path) -> None:
    path.write_text(json.dumps([asdict(p) for p in points], indent=1), encoding="utf-8")
