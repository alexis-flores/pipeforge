"""MATLAB-as-reference validation tests (MATLAB bridge M4)."""

from __future__ import annotations

import pytest

from pipeforge.core.cosim.stimulus import corner_values, generate_stimulus_with_samples
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.frontend.varinfo import VarInfo, WorkspaceSnapshot
from pipeforge.core.fxp.fx import FxFormat, from_float
from pipeforge.core.fxp.validate import (
    ValidateError,
    compare_to_matlab,
    snapshot_inputs,
)
from pipeforge.core.ranges.interval import Interval
from pipeforge.core.ranges.propagate import propagate, ranges_from_snapshot

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)


def dag_of(src: str, snapshot: WorkspaceSnapshot | None = None) -> Dag:
    assigns, skipped = parse_program(src)
    assert not skipped
    builder, problems = build_dag(assigns, CM, snapshot=snapshot)
    assert not problems
    return builder.dag


def var(name: str, values: list[float]) -> VarInfo:
    n = len(values)
    return VarInfo(
        name=name,
        class_name="double",
        size=(1, n),
        values=tuple(values),
        vmin=min(values),
        vmax=max(values),
    )


def snap(*infos: VarInfo) -> WorkspaceSnapshot:
    s = WorkspaceSnapshot()
    for info in infos:
        s.variables[info.name] = info
    return s


class TestSnapshotInputs:
    def test_inputs_extracted_with_dotted_names(self) -> None:
        s = snap(var("cfg.gain", [0.5]), var("x", [0.25, -0.5, 0.125]))
        dag = dag_of("y = cfg.gain * x;", snapshot=s)
        inputs = snapshot_inputs(dag, s)
        assert inputs == {"cfg.gain": [0.5], "x": [0.25, -0.5, 0.125]}

    def test_missing_value_is_clear_error(self) -> None:
        s = snap(var("x", [1.0]))
        dag = dag_of("y = x + q;")
        with pytest.raises(ValidateError, match="q"):
            snapshot_inputs(dag, s)


class TestCompareToMatlab:
    def test_quantization_error_measured(self) -> None:
        # MATLAB float: 0.5 * 0.3 = 0.15 (not exactly representable at S=12)
        s = snap(var("g0", [0.5]), var("x", [0.3]), var("y", [0.15]))
        dag = dag_of("y = g0 .* x;", snapshot=s)
        report = compare_to_matlab(dag, s, FMT)
        (check,) = report.checks
        assert check.target == "y"
        assert check.compared == 1
        assert 0.0 < check.stats.max_abs_error < 2.0**-11  # within ~2 LSB
        assert report.worst_abs_error == check.stats.max_abs_error

    def test_bit_clean_when_values_exact(self) -> None:
        # all values exactly representable: golden matches MATLAB exactly
        s = snap(var("a", [0.25, 0.5]), var("b", [0.75, -1.5]), var("y", [1.0, -1.0]))
        dag = dag_of("y = a + b;", snapshot=s)
        report = compare_to_matlab(dag, s, FMT)
        (check,) = report.checks
        assert check.stats.max_abs_error == 0.0
        assert check.golden == (1.0, -1.0)

    def test_intermediates_checked_too(self) -> None:
        s = snap(
            var("a", [0.5]),
            var("b", [0.25]),
            var("t", [0.75]),
            var("y", [0.5625]),  # 0.75^2
        )
        dag = dag_of("t = a + b;\ny = t .* t;", snapshot=s)
        report = compare_to_matlab(dag, s, FMT)
        assert [c.target for c in report.checks] == ["t", "y"]
        assert all(c.stats.max_abs_error == 0.0 for c in report.checks)

    def test_uncheckable_targets_listed(self) -> None:
        s = snap(var("a", [0.5]), var("b", [0.25]))  # no value for 'y'
        dag = dag_of("y = a + b;", snapshot=s)
        report = compare_to_matlab(dag, s, FMT)
        assert report.uncheckable == ["y"]
        assert not report.checks


class TestSnapshotRangesAndStimulus:
    def test_ranges_from_snapshot(self) -> None:
        s = snap(var("x", [-0.5, 0.25]), var("d", [2.0, 4.0]))
        dag = dag_of("y = x ./ d;", snapshot=s)
        ranges = ranges_from_snapshot(dag, s)
        assert ranges["x"] == Interval(-0.5, 0.25)
        assert ranges["d"] == Interval(2.0, 4.0)
        report = propagate(dag, ranges, CM)
        root = dag.statements[0].root
        assert not report.nodes[root].near_zero_divisor  # d is safely away from 0

    def test_stimulus_includes_real_samples_after_corners(self) -> None:
        samples = {"x": [0.1, 0.2, 0.3], "d": [1.0, 2.0, 3.0]}
        vectors = generate_stimulus_with_samples(["x", "d"], FMT, samples, count=64)
        assert len(vectors) == 64
        n_corners = len(corner_values(FMT)) + 1
        lane0 = vectors[n_corners]
        assert lane0["x"] == from_float(0.1, FMT)
        assert lane0["d"] == from_float(1.0, FMT)
        # corners still present at the front (zeros vector first)
        assert vectors[0] == {"x": 0, "d": 0}

    def test_short_streams_cycle(self) -> None:
        samples = {"x": [0.5], "d": [1.0, 2.0]}
        vectors = generate_stimulus_with_samples(["x", "d"], FMT, samples, count=32)
        n_corners = len(corner_values(FMT)) + 1
        assert vectors[n_corners]["x"] == vectors[n_corners + 1]["x"]  # x repeats
