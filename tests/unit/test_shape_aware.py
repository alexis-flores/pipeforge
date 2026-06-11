"""Shape-aware analysis tests (MATLAB bridge M3): matmul/matscale mapping,
fi FORMAT findings, and the snapshot=None bit-identity guarantee."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.audit.report import render_json, render_text
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.varinfo import FiFormat, VarInfo, WorkspaceSnapshot

CM = CostModel(16, 12)


def snap(*infos: VarInfo) -> WorkspaceSnapshot:
    s = WorkspaceSnapshot()
    for info in infos:
        s.variables[info.name] = info
    return s


def var(name: str, rows: int, cols: int, fi: FiFormat | None = None) -> VarInfo:
    return VarInfo(name=name, class_name="double", size=(rows, cols), fi=fi)


class TestShapeAwareMapping:
    def test_matrix_product_costed_as_matmul(self) -> None:
        s = snap(var("A", 2, 3), var("B", 3, 4))
        audit = audit_source("C = A * B;", "t.m", CM, snapshot=s)
        root = audit.dag.nodes[audit.dag.statements[0].root]
        assert root.module == "matmul"
        assert root.shape == (2, 4)
        assert audit.total_latency == CM.matmul_lat
        assert audit.census == {"matmul": 1}

    def test_scalar_times_matrix_is_matscale(self) -> None:
        s = snap(var("g0", 1, 1), var("A", 3, 3))
        audit = audit_source("B = g0 * A;", "t.m", CM, snapshot=s)
        root = audit.dag.nodes[audit.dag.statements[0].root]
        assert root.module == "matscale"
        assert root.shape == (3, 3)

    def test_matrix_over_scalar_is_matunscale(self) -> None:
        s = snap(var("A", 2, 2), var("d", 1, 1))
        audit = audit_source("B = A / d;", "t.m", CM, snapshot=s)
        root = audit.dag.nodes[audit.dag.statements[0].root]
        assert root.module == "matunscale"
        assert audit.divider_count == 1  # matunscale is a divider

    def test_dimension_mismatch_falls_back_to_elementwise(self) -> None:
        s = snap(var("A", 2, 3), var("B", 2, 3))  # inner dims do not align
        audit = audit_source("C = A * B;", "t.m", CM, snapshot=s)
        root = audit.dag.nodes[audit.dag.statements[0].root]
        assert root.module == "elem_smul"

    def test_dotted_star_never_matmul(self) -> None:
        s = snap(var("A", 3, 3), var("B", 3, 3))
        audit = audit_source("C = A .* B;", "t.m", CM, snapshot=s)
        assert audit.dag.nodes[audit.dag.statements[0].root].module == "elem_smul"

    def test_transpose_swaps_shape(self) -> None:
        s = snap(var("A", 2, 3), var("B", 2, 4))
        audit = audit_source("C = A' * B;", "t.m", CM, snapshot=s)
        root = audit.dag.nodes[audit.dag.statements[0].root]
        assert root.module == "matmul"  # (3x2) * (2x4)
        assert root.shape == (3, 4)

    def test_reductions_are_scalar(self) -> None:
        s = snap(var("v", 1, 8))
        audit = audit_source("n = norm(v);", "t.m", CM, snapshot=s)
        assert audit.dag.nodes[audit.dag.statements[0].root].shape == (1, 1)

    def test_field_shape_from_snapshot(self) -> None:
        s = snap(var("cfg.taps", 1, 16), var("x", 1, 16))
        audit = audit_source("y = cfg.taps .* x;", "t.m", CM, snapshot=s)
        root = audit.dag.nodes[audit.dag.statements[0].root]
        assert root.shape == (1, 16)


class TestFormatFinding:
    def test_fi_mismatch_flagged(self) -> None:
        s = snap(var("z", 1, 1, fi=FiFormat(18, 14)), var("x", 1, 1))
        audit = audit_source("y = z .* x;", "t.m", CM, snapshot=s)
        fmt = [f for f in audit.findings if f.tag == "FORMAT"]
        assert len(fmt) == 1
        assert "18/14" in fmt[0].message
        assert "16/12" in fmt[0].message
        assert "elem_snorm" in fmt[0].suggestion
        assert fmt[0].node  # anchored to the input node (VZ-2)

    def test_matching_fi_not_flagged(self) -> None:
        s = snap(var("z", 1, 1, fi=FiFormat(16, 12)), var("x", 1, 1))
        audit = audit_source("y = z .* x;", "t.m", CM, snapshot=s)
        assert not [f for f in audit.findings if f.tag == "FORMAT"]

    def test_unused_fi_variable_not_flagged(self) -> None:
        s = snap(var("unused", 1, 1, fi=FiFormat(18, 14)), var("x", 1, 1))
        audit = audit_source("y = x + x;", "t.m", CM, snapshot=s)
        assert not [f for f in audit.findings if f.tag == "FORMAT"]

    def test_no_snapshot_no_format_findings(self) -> None:
        audit = audit_source("y = z .* x;", "t.m", CM)
        assert not [f for f in audit.findings if f.tag == "FORMAT"]


class TestBitIdentityWithoutSnapshot:
    @pytest.mark.parametrize("fixture", ["example", "normalize3d", "rootsqr"])
    def test_reports_identical_with_and_without_none_snapshot(self, fixture: str) -> None:
        from pathlib import Path

        src = (Path(__file__).parent.parent / "fixtures" / f"{fixture}.m").read_text()
        plain = audit_source(src, f"{fixture}.m", CM)
        explicit = audit_source(src, f"{fixture}.m", CM, snapshot=None)
        assert render_text(plain) == render_text(explicit)
        assert render_json(plain) == render_json(explicit)

    def test_unknown_inputs_default_scalar(self) -> None:
        # snapshot present but variables missing from it: scalar fallback
        audit = audit_source("C = A * B;", "t.m", CM, snapshot=WorkspaceSnapshot())
        assert audit.dag.nodes[audit.dag.statements[0].root].module == "elem_smul"
