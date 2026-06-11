"""MATLAB bridge tests: pure parsing/generation always run; live tests are
tool-gated (mirror of the Verilator pattern, §8.2)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pipeforge.core.frontend.varinfo import FiFormat, WorkspaceSnapshot
from pipeforge.services import matlab_bridge as mb

FIXTURES = Path(__file__).parent.parent / "fixtures" / "matlab"

SAMPLE_PAYLOAD = {
    "matlab_version": "26.1.0 (R2026a)",
    "script": "/home/u/demo.m",
    "setup": "/home/u/setup_demo.m",
    "timestamp": "2026-06-10 20:00:00",
    "error": "",
    "variables": [
        {
            "name": "x",
            "class": "double",
            "size": [1, 3],
            "is_real": True,
            "fi": None,
            "min": -0.5,
            "max": 0.25,
            "values": [0.25, -0.5, 0.125],
            "truncated": False,
        },
        {
            "name": "cfg",
            "class": "struct",
            "size": [1, 1],
            "is_real": True,
            "fi": None,
            "min": None,
            "max": None,
            "values": [],
            "truncated": False,
        },
        {
            "name": "cfg.gain",
            "class": "double",
            "size": [1, 1],
            "is_real": True,
            "fi": None,
            "min": 0.5,
            "max": 0.5,
            "values": 0.5,  # MATLAB jsonencode emits bare scalars
            "truncated": False,
        },
        {
            "name": "z",
            "class": "embedded.fi",
            "size": [1, 1],
            "is_real": True,
            "fi": {"width": 18, "scale": 14, "signed": True},
            "min": 0.75,
            "max": 0.75,
            "values": 0.75,
            "truncated": False,
        },
        {
            "name": "A",
            "class": "double",
            "size": [2, 2],
            "is_real": True,
            "fi": None,
            "min": 0.125,
            "max": 0.5,
            "values": [0.125, 0.375, 0.25, 0.5],
            "truncated": False,
        },
    ],
}


class TestSnapshotModel:
    def test_round_trip(self) -> None:
        snap = WorkspaceSnapshot.from_payload(SAMPLE_PAYLOAD)
        again = WorkspaceSnapshot.from_json(snap.to_json())
        assert again.variables.keys() == snap.variables.keys()
        assert again.get("x") == snap.get("x")
        assert again.matlab_version == "26.1.0 (R2026a)"

    def test_nested_and_scalar_values(self) -> None:
        snap = WorkspaceSnapshot.from_payload(SAMPLE_PAYLOAD)
        gain = snap.get("cfg.gain")
        assert gain is not None
        assert gain.values == (0.5,)
        assert gain.is_scalar

    def test_fi_format(self) -> None:
        snap = WorkspaceSnapshot.from_payload(SAMPLE_PAYLOAD)
        z = snap.get("z")
        assert z is not None
        assert z.fi == FiFormat(width=18, scale=14, signed=True)
        assert snap.fi_formats() == {"z": FiFormat(18, 14, True)}

    def test_shape_predicates(self) -> None:
        snap = WorkspaceSnapshot.from_payload(SAMPLE_PAYLOAD)
        a = snap.get("A")
        x = snap.get("x")
        gain = snap.get("cfg.gain")
        assert a is not None and a.is_matrix and a.shape2d == (2, 2)
        assert x is not None and x.is_vector and x.length == 3
        assert gain is not None and gain.is_scalar

    def test_error_field_preserved(self) -> None:
        doc = dict(SAMPLE_PAYLOAD)
        doc["error"] = "Undefined variable 'q'."
        snap = WorkspaceSnapshot.from_payload(doc)
        assert "Undefined" in snap.error

    def test_malformed_variables_skipped(self) -> None:
        doc = dict(SAMPLE_PAYLOAD)
        doc["variables"] = [{"nope": 1}, SAMPLE_PAYLOAD["variables"][0]]
        snap = WorkspaceSnapshot.from_payload(doc)
        assert list(snap.variables) == ["x"]


class TestQueryScript:
    def test_renders_paths_and_guards(self, tmp_path: Path) -> None:
        text = mb.render_query_script(
            Path("/home/u/dsp.m"), Path("/home/u/data.mat"), tmp_path / "out.json"
        )
        assert "run(pf_q_script);" in text
        assert "load(pf_q_setup);" in text  # .mat branch exists
        assert "'/home/u/dsp.m'" in text
        assert "jsonencode" in text
        assert "pf_q_" in text  # locals are prefixed and filtered
        assert "strncmp(pf_q_name, 'pf_q_', 5)" in text

    def test_no_setup(self, tmp_path: Path) -> None:
        text = mb.render_query_script(Path("/home/u/dsp.m"), None, tmp_path / "o.json")
        assert "pf_q_setup = '';" in text

    def test_quote_escaping(self, tmp_path: Path) -> None:
        text = mb.render_query_script(Path("/home/u/it's.m"), None, tmp_path / "o.json")
        assert "it''s.m" in text


class TestCacheAndConfig:
    def test_cache_key_changes_with_mtime(self, tmp_path: Path) -> None:
        script = tmp_path / "a.m"
        script.write_text("y = x;")
        k1 = mb._cache_key(script, None, ["matlab"])
        script.write_text("y = x + 1;")
        import os

        os.utime(script, ns=(1, 2))
        k2 = mb._cache_key(script, None, ["matlab"])
        assert k1 != k2
        assert mb._cache_key(script, None, ["other"]) != k2

    def test_config_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = mb.MatlabConfig(command=["echo", "matlab"], setup=Path("/data/setup.mat"))
        cfg.save()
        loaded = mb.MatlabConfig.load()
        assert loaded.command == ["echo", "matlab"]
        assert loaded.setup == Path("/data/setup.mat")

    def test_fast_available(self) -> None:
        assert mb.fast_available(mb.MatlabConfig(command=["sh"]))
        assert not mb.fast_available(mb.MatlabConfig(command=["definitely-not-a-binary"]))
        assert not mb.fast_available(mb.MatlabConfig(command=[]))

    def test_unavailable_message_is_actionable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        script = tmp_path / "a.m"
        script.write_text("y = x;")
        cfg = mb.MatlabConfig(command=["definitely-not-a-binary"])
        with pytest.raises(mb.MatlabUnavailable, match="Settings"):
            mb.take_snapshot(script, config=cfg, force=True)

    def test_cached_snapshot_used_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        script = tmp_path / "a.m"
        script.write_text("y = x;")
        cfg = mb.MatlabConfig(command=["definitely-not-a-binary"])
        key = mb._cache_key(script.resolve(), None, cfg.command)
        mb.cache_dir().mkdir(parents=True, exist_ok=True)
        snap = WorkspaceSnapshot.from_payload(SAMPLE_PAYLOAD)
        (mb.cache_dir() / f"{key}.json").write_text(snap.to_json(), encoding="utf-8")
        # no MATLAB needed: the cache answers
        got = mb.take_snapshot(script, config=cfg, force=False)
        assert "x" in got


def _matlab_live() -> bool:
    cfg = mb.MatlabConfig()
    if shutil.which(cfg.command[0]) is None:
        return False
    try:
        out = subprocess.run(["distrobox", "list"], capture_output=True, text=True, timeout=20)
        return "matlab-sandbox" in out.stdout
    except (OSError, subprocess.SubprocessError):
        return False


requires_matlab = pytest.mark.skipif(
    not _matlab_live(), reason="MATLAB container absent — skipped per §8.2"
)


@pytest.mark.tool("matlab")
@requires_matlab
def test_live_snapshot_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    snap = mb.take_snapshot(FIXTURES / "demo.m", setup=FIXTURES / "setup_demo.m", force=True)
    assert snap.error == ""
    assert "R2026a" in snap.matlab_version or snap.matlab_version
    x = snap.get("x")
    assert x is not None and x.size == (1, 3) and x.values == (0.25, -0.5, 0.125)
    gain = snap.get("cfg.gain")
    assert gain is not None and gain.values == (0.5,)
    taps = snap.get("cfg.filter.taps")
    assert taps is not None and taps.values == (4.0,)
    big = snap.get("big")
    assert big is not None and big.truncated and len(big.values) == 4096
    assert big.vmin == -1.0 and big.vmax == 1.0
    a = snap.get("A")
    assert a is not None and a.is_matrix and a.shape2d == (2, 2)
    # outputs of the DSP script itself are captured too
    assert "y" in snap and "n" in snap
