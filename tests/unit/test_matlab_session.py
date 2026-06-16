"""Warm MATLAB session: protocol units (fake server) + tool-gated live test."""

from __future__ import annotations

import json
import secrets
import shutil
import threading
import time
from pathlib import Path

import pytest

from pipeforge.core.frontend.varinfo import WorkspaceSnapshot
from pipeforge.services import matlab_bridge as mb
from pipeforge.services import matlab_session as ms


class FakeServer(threading.Thread):
    """Acts like pf_server.m: heartbeats and answers request files."""

    def __init__(self, sdir: Path, payload: dict | None = None) -> None:
        super().__init__(daemon=True)
        self.sdir = sdir
        self.payload = payload or {"variables": [], "matlab_version": "fake"}
        self.stop_flag = threading.Event()
        self.served = 0

    def run(self) -> None:
        self.sdir.mkdir(parents=True, exist_ok=True)
        while not self.stop_flag.is_set():
            (self.sdir / "heartbeat").write_text(str(time.time()), encoding="utf-8")
            for req_path in sorted(self.sdir.glob("request_*.json")):
                nonce = req_path.stem.removeprefix("request_")
                req = json.loads(req_path.read_text(encoding="utf-8"))
                req_path.unlink()
                doc = dict(self.payload)
                doc["script"] = req["script"]
                doc["setup"] = req["setup"]
                Path(req["out"]).write_text(json.dumps(doc), encoding="utf-8")
                (self.sdir / f"done_{nonce}").write_text("done", encoding="utf-8")
                self.served += 1
            time.sleep(0.02)


@pytest.fixture
def fake_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    server = FakeServer(ms.session_dir())
    server.start()
    time.sleep(0.05)
    yield server
    server.stop_flag.set()
    server.join(timeout=2)


class TestRenderers:
    def test_server_script_protocol_pieces(self, tmp_path: Path) -> None:
        text = ms.render_server_script(tmp_path)
        assert "function pf_server" in text
        assert "heartbeat" in text
        assert "'stop'" in text
        assert "request_*.json" in text
        assert "pf_snapshot(pf_s_req.script, pf_s_req.setup, pf_s_req.out);" in text
        assert "pause(0.05);" in text

    def test_server_error_path_writes_valid_doc(self, tmp_path: Path) -> None:
        text = ms.render_server_script(tmp_path)
        assert "pf_s_doc.error = pf_s_err.message;" in text
        assert "pf_s_doc.variables = {};" in text


class TestProtocol:
    def test_round_trip(self, fake_session: FakeServer) -> None:
        assert ms.server_alive()
        snap = ms.request_snapshot(Path("/x/model.m"), Path("/x/setup.mat"), timeout=5)
        assert isinstance(snap, WorkspaceSnapshot)
        assert snap.script == "/x/model.m"
        assert snap.setup == "/x/setup.mat"

    def test_two_requests_isolated(self, fake_session: FakeServer) -> None:
        a = ms.request_snapshot(Path("/a.m"), None, timeout=5)
        b = ms.request_snapshot(None, Path("/b.mat"), timeout=5)
        assert a.script == "/a.m" and a.setup == ""
        assert b.script == "" and b.setup == "/b.mat"
        assert fake_session.served == 2

    def test_timeout_raises_actionable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        ms.session_dir().mkdir(parents=True, exist_ok=True)  # no server running
        with pytest.raises(mb.MatlabUnavailable, match="falling back"):
            ms.request_snapshot(Path("/x.m"), None, timeout=0.3)
        # the orphaned request was cleaned up
        assert not list(ms.session_dir().glob("request_*.json"))

    def test_server_alive_requires_fresh_heartbeat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        sdir = ms.session_dir()
        sdir.mkdir(parents=True, exist_ok=True)
        assert not ms.server_alive()
        beat = sdir / "heartbeat"
        beat.write_text("1", encoding="utf-8")
        assert ms.server_alive()
        import os

        old = time.time() - 60
        os.utime(beat, (old, old))
        assert not ms.server_alive()


class TestSnapshotAuto:
    def test_uses_warm_session_when_alive(self, fake_session: FakeServer) -> None:
        snap = mb.snapshot_auto(Path("/m/model.m"), config=mb.MatlabConfig(command=["sh"]))
        assert snap.script == "/m/model.m"
        assert fake_session.served == 1

    def test_falls_back_to_batch_when_no_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        called: dict[str, object] = {}

        def fake_batch(script, setup=None, config=None, force=False, log=None):  # type: ignore[no-untyped-def]
            called["script"] = script
            return WorkspaceSnapshot()

        monkeypatch.setattr(mb, "take_snapshot", fake_batch)
        mb.snapshot_auto(Path("/m/model.m"), config=mb.MatlabConfig(command=["sh"]))
        assert called["script"] == Path("/m/model.m")

    def test_config_flags_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = mb.MatlabConfig(command=["sh"], warm=True, auto_refresh=True)
        cfg.save()
        loaded = mb.MatlabConfig.load()
        assert loaded.warm is True
        assert loaded.auto_refresh is True


class TestLifecycle:
    def test_start_adopts_existing_server_without_launching(
        self, fake_session: FakeServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second owner adopts a live server instead of spawning a competitor."""
        launched: list[object] = []
        monkeypatch.setattr(ms.subprocess, "Popen", lambda *a, **k: launched.append(a))
        session = ms.MatlabSession(config=mb.MatlabConfig(command=["sh"]))
        session.start()
        assert session.is_alive()  # reports the adopted server
        assert launched == []  # never started its own MATLAB
        # stop() must not tear down a server it only adopted
        session.stop()
        assert ms.server_alive()  # the fake server is still running

    def test_stop_of_owned_server_signals_and_clears(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        ms.session_dir().mkdir(parents=True, exist_ok=True)
        session = ms.MatlabSession(config=mb.MatlabConfig(command=["sh"]))
        session._adopted = False
        session._proc = None
        session.stop()  # no server, no proc: writes a stop marker, no crash
        assert (ms.session_dir() / "stop").is_file()


def _matlab_live() -> bool:
    cfg = mb.MatlabConfig.load()
    return cfg.source != "default" and mb.fast_available(cfg)


@pytest.mark.tool("matlab")
@pytest.mark.skipif(not _matlab_live(), reason="no MATLAB on this machine — skipped per §8.2")
def test_live_warm_session_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real cold start once, then two near-instant snapshots, then clean stop.

    Runs in an *isolated* session dir so it never collides with a GUI 'keep
    warm' session, another pipeforge process, or a leftover server in the real
    ~/.config (the historical flake). The dir must stay under $HOME: a distrobox
    MATLAB shares home, not the /var pytest tmp dir — so tmp_path is unusable.
    """
    real_cfg = mb.MatlabConfig.load()  # the detected command, before we move XDG
    iso = Path.home() / ".cache" / "pipeforge-test-session" / secrets.token_hex(6)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(iso))
    if ms.server_alive():  # nothing should be alive in a fresh isolated dir
        pytest.skip("unexpected live server in the isolated session dir")
    fixtures = Path(__file__).parent.parent / "fixtures" / "matlab"
    session = ms.MatlabSession(config=real_cfg)
    session.start()
    try:
        assert ms.server_alive()
        t0 = time.monotonic()
        snap1 = ms.request_snapshot(fixtures / "demo.m", fixtures / "setup_demo.m")
        warm1 = time.monotonic() - t0
        assert snap1.error == ""
        assert snap1.get("cfg.gain") is not None
        t0 = time.monotonic()
        snap2 = ms.request_snapshot(None, fixtures / "setup_demo.m")
        warm2 = time.monotonic() - t0
        assert snap2.get("x") is not None
        # warm requests are far below any cold start (sanity bound, not a benchmark)
        assert warm1 < 15 and warm2 < 15, (warm1, warm2)
    finally:
        session.stop()
        shutil.rmtree(iso, ignore_errors=True)
    assert not ms.server_alive()
