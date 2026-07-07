"""WS-7: static .mat -> snapshot bridge — shape-aware analysis, no MATLAB."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.workspace.snapshot_bridge import STATIC_ORIGIN, snapshot_from_mat

CM = CostModel(16, 12)


@pytest.fixture
def design_mat(tmp_path: Path) -> Path:
    path = tmp_path / "design.mat"
    sio.savemat(
        str(path),
        {
            "A": np.arange(9).reshape(3, 3) * 0.1,
            "v": np.array([[0.5], [0.25], [0.125]]),
            "cfg": {"gain": 0.75, "label": "hello", "taps": np.array([0.5, 0.25, 0.25])},
        },
    )
    return path


@pytest.mark.req("WS-7")
def test_snapshot_from_mat_carries_shapes_types_ranges(design_mat: Path) -> None:
    snap = snapshot_from_mat(design_mat)
    assert snap.matlab_version == STATIC_ORIGIN
    a = snap.get("A")
    assert a is not None and a.size == (3, 3) and a.class_name == "double"
    assert a.vmin == 0.0 and a.vmax == pytest.approx(0.8)
    gain = snap.get("cfg.gain")  # nested struct fields arrive dotted
    assert gain is not None and gain.is_scalar and gain.values == (0.75,)
    taps = snap.get("cfg.taps")
    assert taps is not None and taps.is_vector
    assert snap.get("cfg.label") is None  # char fields carry no numeric value


@pytest.mark.req("WS-7")
def test_static_snapshot_makes_the_audit_shape_aware(design_mat: Path) -> None:
    src = "y = A * v;\nz = y / cfg.gain;\n"
    blind = audit_source(src, "d.m", CM)
    aware = audit_source(src, "d.m", CM, snapshot=snapshot_from_mat(design_mat))
    assert blind.census.get("elem_smul") == 1  # scalar guess without shapes
    assert aware.census.get("matmul") == 1  # 3x3 * 3x1: a real matrix product
    assert aware.census.get("matunscale") == 1  # matrix / scalar


@pytest.mark.req("WS-7")
def test_snapshot_json_roundtrip(design_mat: Path) -> None:
    from pipeforge.core.frontend.varinfo import WorkspaceSnapshot

    snap = snapshot_from_mat(design_mat)
    again = WorkspaceSnapshot.from_json(snap.to_json())
    assert set(again.variables) == set(snap.variables)
    assert again.get("A").size == (3, 3)  # type: ignore[union-attr]


@pytest.mark.req("WS-7")
def test_cli_mat2json_and_snapshot_args(
    design_mat: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from pipeforge.cli import main

    rc = main(["mat2json", str(design_mat)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cfg.gain" in out
    json_path = design_mat.with_suffix(".snapshot.json")
    assert json_path.is_file()

    m = tmp_path / "d.m"
    m.write_text("y = A * v;\n", encoding="utf-8")
    # both forms feed the audit: the JSON artifact and the .mat directly
    for snap_arg in (str(json_path), str(design_mat)):
        rc = main(["audit", str(m), "--snapshot", snap_arg])
        assert rc == 0
        assert "matmul" in capsys.readouterr().out


@pytest.mark.req("WS-7")
def test_optimize_uses_snapshot_shapes_and_data(tmp_path: Path) -> None:
    from pipeforge.core.optimize.rewrite import optimize_source

    mat = tmp_path / "data.mat"
    rng = np.random.default_rng(3)
    sio.savemat(
        str(mat),
        {"x": rng.uniform(-1, 1, 32), "y": rng.uniform(-1, 1, 32), "n": rng.uniform(0.5, 2, 32)},
    )
    src = "u = x ./ n;\nv = y ./ n;\n"
    result = optimize_source(src, CM, vectors=32, snapshot=snapshot_from_mat(mat))
    assert result.changed
    # divisors stay in the real data's [0.5, 2]: the comparison is meaningful
    assert all(a.max_delta < 0.01 for a in result.accuracy)
    assert all(a.sqnr_after_db > 40 for a in result.accuracy)
