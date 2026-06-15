"""CLI basics."""

from __future__ import annotations

import pytest

from pipeforge import __version__
from pipeforge.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "pipeforge-cli" in capsys.readouterr().out


# --- v1.1 surfacing commands -------------------------------------------------

from pathlib import Path  # noqa: E402

import scipy.io as _sio  # noqa: E402

_ROOT = Path(__file__).parent.parent.parent
PARAMS = _ROOT / "src" / "pipeforge" / "demos" / "matlab" / "params.mat"
SOFTWARE = _ROOT / "tests" / "fixtures" / "workspace" / "software.sv"
SAMPLE_M = _ROOT / "tests" / "fixtures" / "cosim" / "sample.m"
SAMPLE_SV = _ROOT / "tests" / "fixtures" / "cosim" / "sample.sv"


@pytest.mark.req("WS-3")
def test_cli_reconcile(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["reconcile", str(PARAMS), str(SOFTWARE)])
    out = capsys.readouterr().out
    assert "reconcile" in out and "match" in out
    assert "missing_in_sv" in out  # .mat has fields the SV mirror lacks
    assert code == 1  # mismatches/missing -> non-zero


@pytest.mark.req("MP-2")
def test_cli_map_propose_confirm_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = tmp_path / "pf.map.json"
    assert (
        main(["map", "propose", "--m", str(SAMPLE_M), "--sv", str(SAMPLE_SV), "-o", str(sidecar)])
        == 0
    )
    assert sidecar.is_file()
    assert "confident" in capsys.readouterr().out
    assert main(["map", "confirm", str(sidecar), "a", "a_0"]) == 0
    assert main(["map", "show", str(sidecar)]) == 0
    out = capsys.readouterr().out
    assert "1 confirmed" in out and "a -> a_0" in out


@pytest.mark.req("DX-2")
def test_cli_traceability(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = tmp_path / "pf.map.json"
    main(["map", "propose", "--m", str(SAMPLE_M), "--sv", str(SAMPLE_SV), "-o", str(sidecar)])
    capsys.readouterr()
    code = main(
        [
            "traceability",
            str(sidecar),
            "--m",
            str(SAMPLE_M),
            "--sv",
            str(SAMPLE_SV),
            "--format",
            "csv",
        ]
    )
    assert code == 0
    assert "MATLAB operation" in capsys.readouterr().out


@pytest.mark.req("WS-5")
def test_cli_oracle_float_within_precision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    m = tmp_path / "sq.m"
    m.write_text("y = x .* x;", encoding="utf-8")
    mat = tmp_path / "io.mat"
    xs = [0.25, 0.5, -0.75, 1.0]
    _sio.savemat(str(mat), {"x": xs, "y": [v * v for v in xs]})
    code = main(["oracle", str(m), "--mat", str(mat), "--reference", "float"])
    out = capsys.readouterr().out
    assert "within-precision" in out and "reference: float" in out
    assert code == 0  # float reference: no bit-exact verdict, never a hard fail
