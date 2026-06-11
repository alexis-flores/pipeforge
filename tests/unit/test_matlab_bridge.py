"""MATLAB bridge tests: pure parsing/generation always run; live tests are
tool-gated (mirror of the Verilator pattern, §8.2)."""

from __future__ import annotations

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


class TestSnapshotFunction:
    def test_parameterized_function_with_guards(self) -> None:
        text = mb.render_snapshot_function()
        assert "function pf_snapshot(pf_q_ascript, pf_q_asetup, pf_q_aout)" in text
        assert "run(pf_q_script);" in text
        assert "if ~isempty(pf_q_script)" in text  # script optional (.mat alone)
        assert "load(pf_q_setup);" in text  # .mat setup branch
        assert "if ~isempty(pf_q_setup)" in text
        assert "jsonencode" in text
        # everything internal (args included) is pf_q_-prefixed and filtered
        assert "strncmp(pf_q_name, 'pf_q_', 5)" in text

    def test_quote_escaping_helper(self) -> None:
        assert mb._mq(Path("/home/u/it's.m")) == "/home/u/it''s.m"


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
    # portable: whatever this machine's resolution order (settings, env, PATH,
    # standard installs, distrobox) finds is what the live tests run against
    cfg = mb.MatlabConfig.load()
    return cfg.source != "default" and mb.fast_available(cfg)


requires_matlab = pytest.mark.skipif(
    not _matlab_live(), reason="no MATLAB on this machine — skipped per §8.2"
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


@pytest.mark.tool("matlab")
@requires_matlab
def test_live_validate_against_matlab(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeforge.core.audit.engine import audit_source
    from pipeforge.core.costmodel.model import CostModel
    from pipeforge.core.fxp.fx import FxFormat
    from pipeforge.core.fxp.validate import compare_to_matlab

    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    snap = mb.take_snapshot(FIXTURES / "demo.m", setup=FIXTURES / "setup_demo.m")
    src = (FIXTURES / "demo.m").read_text(encoding="utf-8")
    audit = audit_source(src, "demo.m", CostModel(16, 12), snapshot=snap)
    report = compare_to_matlab(audit.dag, snap, FxFormat(16, 12))
    targets = {c.target: c for c in report.checks}
    assert set(targets) == {"y", "n"}
    # y = cfg.gain * x + offset: every operand is exactly representable at S=12
    assert targets["y"].stats.max_abs_error == 0.0
    # n = norm(x): quantized sqrt stays within a couple of LSBs of MATLAB
    assert 0.0 < targets["n"].stats.max_abs_error < 2.0**-11


class TestPortableDetection:
    """Auto-detection so a clone on another machine finds its own MATLAB."""

    @staticmethod
    def _shim(tmp_path: Path, name: str = "matlab", version: str = "9.99 (Rtest)") -> Path:
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        shim = bindir / name
        shim.write_text(f'#!/bin/sh\necho "{version}"\n', encoding="utf-8")
        shim.chmod(0o755)
        return bindir

    @staticmethod
    def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, path_dirs: str = "") -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.delenv(mb.ENV_OVERRIDE, raising=False)
        monkeypatch.setenv("PATH", path_dirs)  # no matlab, no distrobox
        monkeypatch.setattr(mb, "INSTALL_GLOBS", ())

    def test_env_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._isolate(monkeypatch, tmp_path)
        monkeypatch.setenv(mb.ENV_OVERRIDE, "ssh build-box matlab")
        candidates = mb.matlab_candidates()
        assert candidates[0] == ("env", ["ssh", "build-box", "matlab"])

    def test_path_matlab_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bindir = self._shim(tmp_path)
        self._isolate(monkeypatch, tmp_path, path_dirs=str(bindir))
        source, command = mb.autodetect_command()
        assert (source, command) == ("path", ["matlab"])

    def test_install_glob_newest_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate(monkeypatch, tmp_path)
        for rel in ("R2024b", "R2026a"):
            exe = tmp_path / "MATLAB" / rel / "bin" / "matlab"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o755)
        monkeypatch.setattr(
            mb, "INSTALL_GLOBS", (str(tmp_path / "MATLAB" / "R20*" / "bin" / "matlab"),)
        )
        source, command = mb.autodetect_command()
        assert source == "install"
        assert command == [str(tmp_path / "MATLAB" / "R2026a" / "bin" / "matlab")]

    def test_fresh_machine_with_normal_matlab_needs_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # the user's scenario: new computer, matlab on PATH, empty settings
        bindir = self._shim(tmp_path)
        self._isolate(monkeypatch, tmp_path, path_dirs=str(bindir))
        cfg = mb.MatlabConfig.load()
        assert cfg.command == ["matlab"]
        assert cfg.source == "path"

    def test_explicit_settings_beat_autodetection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindir = self._shim(tmp_path)
        self._isolate(monkeypatch, tmp_path, path_dirs=str(bindir))
        mb.MatlabConfig(command=["my", "wrapper"]).save()
        cfg = mb.MatlabConfig.load()
        assert cfg.command == ["my", "wrapper"]
        assert cfg.source == "settings"

    def test_nothing_found_falls_back_to_documented_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate(monkeypatch, tmp_path)
        source, command = mb.autodetect_command()
        assert source == "default"
        assert command == mb.DEFAULT_COMMAND

    def test_detect_and_save_probes_and_persists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # a real probe against a shim that answers like MATLAB -batch
        bindir = self._shim(tmp_path, version="10.0 (R2027a)")
        self._isolate(monkeypatch, tmp_path, path_dirs=f"{bindir}:/usr/bin:/bin")
        mb.MatlabConfig(command=[], setup=tmp_path / "s.mat").save()  # keep setup
        cfg, version = mb.detect_and_save(timeout=10)
        assert version == "10.0 (R2027a)"
        assert cfg.source == "path"
        assert cfg.setup == tmp_path / "s.mat"  # project setup preserved
        assert mb.MatlabConfig.load().command == ["matlab"]  # persisted

    def test_detect_and_save_skips_broken_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "broken" / "bin" / "matlab"
        broken.parent.mkdir(parents=True)
        broken.write_text("#!/bin/sh\nexit 7\n")
        broken.chmod(0o755)
        good_bin = self._shim(tmp_path, version="ok 1.0")
        self._isolate(monkeypatch, tmp_path, path_dirs=f"{good_bin}:/usr/bin:/bin")
        # broken install candidate ranks after the env override? no — env first:
        monkeypatch.setenv(mb.ENV_OVERRIDE, str(broken))
        cfg, version = mb.detect_and_save(timeout=10)
        assert version == "ok 1.0"  # fell through the broken env candidate
        assert cfg.source == "path"

    def test_detect_and_save_reports_everything_tried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._isolate(monkeypatch, tmp_path, path_dirs="/usr/bin:/bin")
        with pytest.raises(mb.MatlabUnavailable, match="No working MATLAB"):
            mb.detect_and_save(timeout=5)


class TestMatAloneSnapshots:
    """Script-optional snapshots: inspect a .mat parameter file by itself."""

    def test_snapshot_function_guards_empty_script(self) -> None:
        text = mb.render_snapshot_function()
        assert "if ~isempty(pf_q_script)" in text  # run is guarded (.mat alone)
        assert "load(pf_q_setup);" in text

    def test_take_snapshot_requires_something(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with pytest.raises(mb.MatlabUnavailable, match="nothing to snapshot"):
            mb.take_snapshot(None, setup=None, config=mb.MatlabConfig(command=["sh"]))

    def test_snapshot_target_mat_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_take(script, setup=None, **_kw):  # type: ignore[no-untyped-def]
            seen["script"] = script
            seen["setup"] = setup
            return WorkspaceSnapshot()

        monkeypatch.setattr(mb, "take_snapshot", fake_take)
        params = tmp_path / "params.mat"
        params.write_bytes(b"MATLAB 5.0")
        mb.snapshot_target(params)
        assert seen == {"script": None, "setup": params}

    def test_snapshot_target_m_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_take(script, setup=None, **_kw):  # type: ignore[no-untyped-def]
            seen["script"] = script
            seen["setup"] = setup
            return WorkspaceSnapshot()

        monkeypatch.setattr(mb, "take_snapshot", fake_take)
        script = tmp_path / "model.m"
        setup = tmp_path / "params.mat"
        mb.snapshot_target(script, setup=setup)
        assert seen == {"script": script, "setup": setup}

    def test_snapshot_target_rejects_mat_plus_setup(self, tmp_path: Path) -> None:
        with pytest.raises(mb.MatlabUnavailable, match="already a data file"):
            mb.snapshot_target(tmp_path / "params.mat", setup=tmp_path / "other.m")

    def test_cache_key_distinguishes_script_none(self, tmp_path: Path) -> None:
        setup = tmp_path / "p.mat"
        setup.write_bytes(b"x")
        script = tmp_path / "m.m"
        script.write_text("y = x;")
        assert mb._cache_key(None, setup, ["matlab"]) != mb._cache_key(script, setup, ["matlab"])


@pytest.mark.tool("matlab")
@requires_matlab
def test_live_mat_alone_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generate a real .mat in MATLAB, then snapshot it with no script."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    import subprocess

    from pipeforge.paths import config_dir

    work = config_dir() / "matlab_work"  # home-shared with the container
    work.mkdir(parents=True, exist_ok=True)
    mat = work / "pf_test_params.mat"
    mat.unlink(missing_ok=True)
    cfg = mb.MatlabConfig.load()
    gen = (
        f"gain = 0.5; taps = [0.25 -0.5 0.125]; cfg.mode = 2; save('{mat}', 'gain', 'taps', 'cfg');"
    )
    subprocess.run([*cfg.command, "-batch", gen], capture_output=True, timeout=180, check=True)
    assert mat.is_file()
    snap = mb.snapshot_target(mat, force=True)
    assert snap.error == ""
    gain = snap.get("gain")
    assert gain is not None and gain.class_name == "double" and gain.values == (0.5,)
    taps = snap.get("taps")
    assert taps is not None and taps.size == (1, 3)
    mode = snap.get("cfg.mode")
    assert mode is not None and mode.values == (2.0,)
    mat.unlink(missing_ok=True)
