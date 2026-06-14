"""MP-3: manual operation grouping (no auto-matching) + validation."""

from __future__ import annotations

import pytest

from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import build_dag
from pipeforge.core.frontend.parser import parse_program
from pipeforge.core.mapping import propose
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.mapping.validate import validate_group
from pipeforge.core.svlint.model import Instance, SvModule

CM = CostModel(16, 12)


def _norm_dag_and_nid():
    assigns, _ = parse_program("n = norm(v);")
    dag = build_dag(assigns, CM)[0].dag
    return dag, dag.statements[0].root  # the rootsqr op


# norm() = rootsqr = usqrt(sumsqr(v)); the two instances form a sub-pipeline
_SUMSQR = Instance("sumsqr", "i_sumsqr_ss_5", {"a": "v_0", "f": "ss_5"}, 1)
_USQRT = Instance("usqrt", "i_usqrt_n_19", {"a": "ss_5", "f": "n_19"}, 2)
_UNRELATED = Instance("smul", "i_smul_p_4", {"a": "x_0", "b": "y_0", "f": "p_4"}, 3)
MODULE = SvModule("dut", instances=[_SUMSQR, _USQRT, _UNRELATED])


@pytest.mark.req("MP-3")
def test_manual_one_to_many_group() -> None:
    _, nid = _norm_dag_and_nid()
    cmap = CorrespondenceMap()
    assert cmap.groups == []  # nothing until the user draws it
    group = cmap.add_group(nid, ["i_sumsqr_ss_5", "i_usqrt_n_19"])
    assert group.sv_instances == ["i_sumsqr_ss_5", "i_usqrt_n_19"]  # one-to-many
    assert cmap.group_for(nid) is group


@pytest.mark.req("MP-3")
def test_group_latency_validated_against_matlab_op() -> None:
    dag, nid = _norm_dag_and_nid()
    cmap = CorrespondenceMap()
    group = cmap.add_group(nid, ["i_sumsqr_ss_5", "i_usqrt_n_19"])
    result = validate_group(group, dag, MODULE, CM)
    # sumsqr(5) + usqrt(14) == rootsqr(19)
    assert result.expected_latency == CM.rootsqr_lat == 19
    assert result.actual_latency == 19
    assert result.latency_ok and result.connected and result.ok


@pytest.mark.req("MP-3")
def test_structurally_impossible_group_warned() -> None:
    dag, nid = _norm_dag_and_nid()
    cmap = CorrespondenceMap()
    # usqrt and an unrelated smul cannot form a connected sub-pipeline
    group = cmap.add_group(nid, ["i_usqrt_n_19", "i_smul_p_4"])
    result = validate_group(group, dag, MODULE, CM)
    assert not result.connected
    assert any("connected sub-pipeline" in w for w in result.warnings)
    assert not result.ok


@pytest.mark.req("MP-3")
def test_no_automatic_operation_matching() -> None:
    # the tool validates and bookkeeps groups but NEVER proposes them (§10)
    assert not hasattr(propose, "propose_operations")
    assert not hasattr(propose, "propose_groups")
    assert hasattr(propose, "propose_variables")  # variables only
