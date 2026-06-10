"""Bisection tests (BI-1, BI-2): corrupted-stage localization, skew classification."""

from __future__ import annotations

import pytest

from pipeforge.core.bisect.engine import Observations, bisect, golden_intermediates
from pipeforge.core.cosim.stimulus import generate_stimulus
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag, build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.fxp.evaluator import apply_fixed
from pipeforge.core.fxp.fx import FxFormat

CM = CostModel(16, 12)
FMT = FxFormat(16, 12)

SRC = "prod = a .* b;\nu = prod + c;\ny = u ./ d;"


def make_dag() -> Dag:
    assigns, _ = parse_program(SRC)
    builder, _ = build_dag(assigns, CM)
    return builder.dag


def observed_all(dag: Dag, stimulus: list[dict[str, int]]) -> Observations:
    return {nid: list(vals) for nid, vals in golden_intermediates(dag, stimulus, FMT).items()}


@pytest.mark.req("BI-1")
def test_clean_run_reports_no_divergence() -> None:
    dag = make_dag()
    stim = generate_stimulus(["a", "b", "c", "d"], FMT, count=24)
    report = bisect(dag, stim, observed_all(dag, stim), FMT)
    assert not report.diverged
    assert all(v.status == "ok" for v in report.verdicts)


@pytest.mark.req("BI-1")
def test_corrupted_stage_localized() -> None:
    dag = make_dag()
    stim = generate_stimulus(["a", "b", "c", "d"], FMT, count=24)
    obs = observed_all(dag, stim)
    # corrupt the adder stage ('u') and everything downstream of it
    u_root = dag.statements[1].root
    y_root = dag.statements[2].root
    for i in range(4, len(stim)):
        obs[u_root][i] = [v ^ 0x10 for v in obs[u_root][i]]
        obs[y_root][i] = [v ^ 0x3 for v in obs[y_root][i]]
    report = bisect(dag, stim, obs, FMT)
    assert report.diverged
    assert report.node == u_root  # the FIRST divergent stage, not downstream
    assert report.vector_index == 4
    assert report.inputs_matched
    assert report.classification == "wrong-math"
    assert "matadd" in report.instance
    assert report.expected != report.actual


@pytest.mark.req("BI-2")
def test_delay_skew_classified_not_wrong_math() -> None:
    dag = make_dag()
    stim = generate_stimulus(["a", "b", "c", "d"], FMT, count=32)
    obs = observed_all(dag, stim)
    u_root = dag.statements[1].root
    node = dag.nodes[u_root]
    prod_stream = obs[node.args[0]]
    c_stream = obs[node.args[1]]
    # rebuild 'u' with operand c arriving one cycle late (missing `PIPE bug)
    for i in range(len(stim)):
        obs[u_root][i] = apply_fixed(
            node, [prod_stream[i], c_stream[i - 1] if i else c_stream[0]], FMT
        )
    # downstream y also corrupts as a consequence
    y_node = dag.nodes[dag.statements[2].root]
    d_stream = obs[y_node.args[1]]
    for i in range(len(stim)):
        obs[y_node.nid][i] = apply_fixed(y_node, [obs[u_root][i], d_stream[i]], FMT)
    report = bisect(dag, stim, obs, FMT)
    assert report.diverged
    assert report.node == u_root
    assert report.classification == "delay-skew"
    assert report.skew_cycles == 1
    assert report.skew_input == "c"
    assert "`PIPE" in report.message


@pytest.mark.req("BI-1")
def test_unobserved_intermediates_tolerated() -> None:
    dag = make_dag()
    stim = generate_stimulus(["a", "b", "c", "d"], FMT, count=16)
    full = observed_all(dag, stim)
    y_root = dag.statements[2].root
    obs: Observations = {y_root: [[v[0] ^ 1] for v in full[y_root]]}
    report = bisect(dag, stim, obs, FMT)
    assert report.diverged
    assert report.node == y_root
    statuses = {v.nid: v.status for v in report.verdicts}
    assert statuses[dag.statements[0].root] == "unobserved"


def test_downstream_dimming_set() -> None:
    dag = make_dag()
    stim = generate_stimulus(["a", "b", "c", "d"], FMT, count=16)
    obs = observed_all(dag, stim)
    prod_root = dag.statements[0].root
    for i in range(len(stim)):
        obs[prod_root][i] = [v ^ 0x2 for v in obs[prod_root][i]]
    report = bisect(dag, stim, obs, FMT)
    assert report.diverged
    downstream = report.downstream_of_divergence(dag)
    assert dag.statements[1].root in downstream
    assert dag.statements[2].root in downstream
    assert prod_root not in downstream
