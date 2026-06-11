"""Live MATLAB workspace bridge.

Takes a *snapshot* of a real MATLAB workspace: it runs an optional setup
step (a ``.m`` script or a ``.mat`` file), then the user's DSP script, then
walks every variable (recursing into struct fields) and writes one JSON
document that parses into :class:`WorkspaceSnapshot`.

MATLAB lives wherever the configured command template says — by default
inside the ``matlab-sandbox`` Distrobox container. All exchanged files live
under the user's config dir (home-shared with the container; never /tmp).
Snapshots are slow (MATLAB cold start), so they are cached by content key
and only retaken on explicit refresh (``force=True``).
"""

from __future__ import annotations

import contextlib
import glob
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pipeforge.core.frontend.varinfo import VALUE_CAP, WorkspaceSnapshot
from pipeforge.paths import config_dir

#: Last-resort fallback (and the example shown in error messages) when nothing
#: can be auto-detected. Real resolution happens in matlab_candidates().
DEFAULT_COMMAND = [
    "distrobox",
    "enter",
    "matlab-sandbox",
    "--",
    "/usr/local/MATLAB/R2026a/bin/matlab",
]

#: Conventional install locations, searched newest release first.
INSTALL_GLOBS = (
    "/usr/local/MATLAB/R20*/bin/matlab",
    "/opt/MATLAB/R20*/bin/matlab",
    "/Applications/MATLAB_R20*.app/bin/matlab",
)

#: Environment override: a shell-style command, e.g. "matlab" or
#: "ssh build-box matlab". Beats everything except explicit settings.
ENV_OVERRIDE = "PIPEFORGE_MATLAB"

#: subprocess budget: container auto-start + MATLAB cold start + script run
SNAPSHOT_TIMEOUT_S = 180


class MatlabUnavailable(RuntimeError):
    """MATLAB cannot be reached or the snapshot failed (C2: actionable)."""


def _distrobox_matlab_containers() -> list[str]:
    """Names of distrobox containers that look MATLAB-related (cheap, 2 s)."""
    if shutil.which("distrobox") is None:
        return []
    try:
        proc = subprocess.run(["distrobox", "list"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and "matlab" in parts[1].lower():
            names.append(parts[1])
    return names


def matlab_candidates() -> list[tuple[str, list[str]]]:
    """Ordered (source, command) candidates for locating MATLAB.

    Cheap by design — nothing here starts MATLAB. Order: env override,
    PATH, conventional install dirs (newest first), distrobox containers.
    """
    candidates: list[tuple[str, list[str]]] = []
    env = os.environ.get(ENV_OVERRIDE, "").strip()
    if env:
        with contextlib.suppress(ValueError):
            parsed = shlex.split(env)
            if parsed:
                candidates.append(("env", parsed))
    if shutil.which("matlab") is not None:
        candidates.append(("path", ["matlab"]))
    installs: list[str] = []
    for pattern in INSTALL_GLOBS:
        installs.extend(glob.glob(pattern))
    for exe in sorted(installs, reverse=True):  # newest release first
        if Path(exe).is_file():
            candidates.append(("install", [exe]))
    for name in _distrobox_matlab_containers():
        # matlab may not be on the container PATH; also try host-visible installs
        candidates.append(("distrobox", ["distrobox", "enter", name, "--", "matlab"]))
        for exe in sorted(installs, reverse=True):
            candidates.append(("distrobox", ["distrobox", "enter", name, "--", exe]))
    return candidates


def _plausible(command: list[str]) -> bool:
    if not command:
        return False
    head = command[0]
    if "/" in head:
        return Path(head).is_file()
    return shutil.which(head) is not None


def autodetect_command() -> tuple[str, list[str]]:
    """First plausible candidate, or the documented default."""
    for source, command in matlab_candidates():
        if _plausible(command):
            return source, command
    return "default", list(DEFAULT_COMMAND)


@dataclass
class MatlabConfig:
    command: list[str] = field(default_factory=lambda: list(DEFAULT_COMMAND))
    setup: Path | None = None  # per-project workspace setup (.m to run / .mat to load)
    source: str = "default"  # where the command came from (not persisted)

    @classmethod
    def load(cls) -> MatlabConfig:
        """Explicit settings always win; otherwise auto-detect for this machine."""
        path = config_dir() / "settings.json"
        cfg = cls()
        data: dict[str, object] = {}
        if path.is_file():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                data = json.loads(path.read_text(encoding="utf-8"))
        cmd = data.get("matlabCommand")
        if isinstance(cmd, list) and all(isinstance(c, str) for c in cmd) and cmd:
            cfg.command = list(cmd)
            cfg.source = "settings"
        else:
            cfg.source, cfg.command = autodetect_command()
        setup = data.get("matlabSetup")
        if isinstance(setup, str) and setup:
            cfg.setup = Path(setup)
        return cfg

    def save(self) -> None:
        path = config_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        data["matlabCommand"] = list(self.command)
        data["matlabSetup"] = str(self.setup) if self.setup else ""
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fast_available(config: MatlabConfig | None = None) -> bool:
    """Cheap availability check for the status dot (no MATLAB start)."""
    cfg = config if config is not None else MatlabConfig.load()
    return bool(cfg.command) and shutil.which(cfg.command[0]) is not None


def probe(config: MatlabConfig | None = None, timeout: float = SNAPSHOT_TIMEOUT_S) -> str:
    """Full probe: starts MATLAB and returns its version string (slow)."""
    cfg = config if config is not None else MatlabConfig.load()
    if not fast_available(cfg):
        raise MatlabUnavailable(
            f"'{cfg.command[0] if cfg.command else '?'}' is not on PATH. Configure the "
            "MATLAB command in Settings (default expects the matlab-sandbox distrobox)."
        )
    try:
        proc = subprocess.run(
            [*cfg.command, "-batch", "disp(version)"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MatlabUnavailable(f"MATLAB probe failed to launch: {exc}") from exc
    if proc.returncode != 0:
        raise MatlabUnavailable(
            "MATLAB probe failed: " + (proc.stderr or proc.stdout).strip()[-500:]
        )
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "unknown"


def detect_and_save(
    log: Callable[[str], None] | None = None,
    timeout: float = SNAPSHOT_TIMEOUT_S,
) -> tuple[MatlabConfig, str]:
    """Find a *working* MATLAB by probing each candidate; persist the winner.

    One-step setup for a fresh machine: walks env/PATH/install/distrobox
    candidates, runs the real version probe on each, and saves the first
    command that answers. Returns (config, version).
    """
    existing_setup = MatlabConfig.load().setup  # keep the project setup file
    tried: list[str] = []
    for source, command in matlab_candidates():
        if not _plausible(command):
            continue
        rendered = " ".join(command)
        if log:
            log(f"matlab detect: trying [{source}] {rendered}")
        cfg = MatlabConfig(command=list(command), setup=existing_setup, source=source)
        try:
            version = probe(cfg, timeout=timeout)
        except MatlabUnavailable as exc:
            tried.append(f"[{source}] {rendered}: {str(exc).splitlines()[0][:120]}")
            continue
        cfg.save()
        if log:
            log(f"matlab detect: saved [{source}] {rendered} ({version})")
        return cfg, version
    detail = "\n  ".join(tried) if tried else "(no plausible candidates found)"
    raise MatlabUnavailable(
        "No working MATLAB found. Tried:\n  "
        + detail
        + f"\nInstall MATLAB, set {ENV_OVERRIDE}, or configure the command in Settings."
    )


# ---------------------------------------------------------------------------
# Query script generation (pure; unit-tested without MATLAB)
# ---------------------------------------------------------------------------


def _mq(path: Path | str) -> str:
    """Quote a path for a single-quoted MATLAB string literal."""
    return str(path).replace("'", "''")


def render_query_script(script: Path, setup: Path | None, out_json: Path) -> str:
    """The pf_query function MATLAB runs to dump the workspace as JSON.

    Locals are pf_q_-prefixed and filtered out; the user script runs inside
    the function workspace so nothing leaks between snapshots. Script errors
    land in the JSON 'error' field instead of losing the whole snapshot.
    """
    setup_lit = _mq(setup) if setup is not None else ""
    return f"""function pf_query
% generated by PipeForge — workspace snapshot query. Do not edit.
pf_q_out = '{_mq(out_json)}';
pf_q_setup = '{setup_lit}';
pf_q_script = '{_mq(script)}';
pf_q_doc = struct();
pf_q_doc.matlab_version = version;
pf_q_doc.script = pf_q_script;
pf_q_doc.setup = pf_q_setup;
pf_q_doc.timestamp = char(datetime('now', 'Format', 'yyyy-MM-dd HH:mm:ss'));
pf_q_doc.error = '';
try
    if ~isempty(pf_q_setup)
        [~, ~, pf_q_ext] = fileparts(pf_q_setup);
        if strcmpi(pf_q_ext, '.mat')
            load(pf_q_setup);
        else
            run(pf_q_setup);
        end
    end
    run(pf_q_script);
catch pf_q_err
    pf_q_doc.error = pf_q_err.message;
end
pf_q_list = whos;
pf_q_vars = {{}};
for pf_q_i = 1:numel(pf_q_list)
    pf_q_name = pf_q_list(pf_q_i).name;
    if strncmp(pf_q_name, 'pf_q_', 5)
        continue
    end
    pf_q_vars = pf_describe(pf_q_vars, pf_q_name, eval(pf_q_name), 0);
end
pf_q_doc.variables = pf_q_vars;
pf_q_fh = fopen(pf_q_out, 'w');
fwrite(pf_q_fh, jsonencode(pf_q_doc));
fclose(pf_q_fh);
end

function vars = pf_describe(vars, name, value, depth)
CAP = {VALUE_CAP};
entry = struct();
entry.name = name;
entry.class = class(value);
entry.size = size(value);
entry.is_real = true;
entry.fi = [];
entry.min = [];
entry.max = [];
entry.values = [];
entry.truncated = false;
if isstruct(value)
    vars{{end+1}} = entry;
    if depth < 4 && isscalar(value)
        fn = fieldnames(value);
        for k = 1:numel(fn)
            vars = pf_describe(vars, [name '.' fn{{k}}], value.(fn{{k}}), depth + 1);
        end
    end
    return
end
if isa(value, 'embedded.fi')
    entry.fi = struct();
    entry.fi.width = double(value.WordLength);
    entry.fi.scale = double(value.FractionLength);
    entry.fi.signed = logical(issigned(value));
    value = double(value);
end
if isnumeric(value) || islogical(value)
    value = double(value);
    entry.is_real = isreal(value);
    if ~isreal(value)
        value = real(value);
    end
    flat = value(:);
    if ~isempty(flat)
        entry.min = min(flat);
        entry.max = max(flat);
        if numel(flat) > CAP
            entry.values = flat(1:CAP);
            entry.truncated = true;
        else
            entry.values = flat;
        end
    end
end
vars{{end+1}} = entry;
end
"""


# ---------------------------------------------------------------------------
# Snapshot runner + cache
# ---------------------------------------------------------------------------


def _cache_key(script: Path, setup: Path | None, command: list[str]) -> str:
    h = hashlib.sha256()
    for p in (script, setup):
        if p is None:
            h.update(b"<none>")
        else:
            h.update(str(p).encode())
            with contextlib.suppress(OSError):
                h.update(str(p.stat().st_mtime_ns).encode())
    h.update(repr(command).encode())
    return h.hexdigest()[:24]


def cache_dir() -> Path:
    return config_dir() / "matlab_cache"


def load_cached_snapshot(key: str) -> WorkspaceSnapshot | None:
    path = cache_dir() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return WorkspaceSnapshot.from_json(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def take_snapshot(
    script: Path,
    setup: Path | None = None,
    config: MatlabConfig | None = None,
    force: bool = False,
    log: Callable[[str], None] | None = None,
) -> WorkspaceSnapshot:
    """Snapshot the MATLAB workspace after running setup + script.

    Cached by (script, setup, mtimes, command); ``force=True`` is the
    explicit refresh. Raises MatlabUnavailable with an actionable message
    on any failure (C2).
    """
    cfg = config if config is not None else MatlabConfig.load()
    if setup is None:
        setup = cfg.setup
    script = script.resolve()
    if setup is not None:
        setup = setup.resolve()
        if not setup.is_file():
            raise MatlabUnavailable(f"setup file not found: {setup}")
    key = _cache_key(script, setup, cfg.command)
    if not force:
        cached = load_cached_snapshot(key)
        if cached is not None:
            if log:
                log(f"matlab: using cached snapshot {key} (refresh to retake)")
            return cached
    if not fast_available(cfg):
        raise MatlabUnavailable(
            f"'{cfg.command[0]}' is not on PATH. Configure the MATLAB command in "
            "Settings (default expects the matlab-sandbox distrobox)."
        )

    work = config_dir() / "matlab_work"  # under $HOME: shared with the container
    work.mkdir(parents=True, exist_ok=True)
    out_json = work / "pf_snapshot.json"
    out_json.unlink(missing_ok=True)
    (work / "pf_query.m").write_text(render_query_script(script, setup, out_json), encoding="utf-8")
    cmd = [*cfg.command, "-batch", f"cd('{_mq(work)}'); pf_query"]
    if log:
        log("matlab: " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=SNAPSHOT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise MatlabUnavailable(
            f"MATLAB snapshot timed out after {SNAPSHOT_TIMEOUT_S}s — is the "
            "matlab-sandbox container healthy?"
        ) from exc
    except OSError as exc:
        raise MatlabUnavailable(f"cannot launch MATLAB: {exc}") from exc
    if log:
        for line in (proc.stdout + proc.stderr).splitlines():
            log("matlab| " + line)
    if not out_json.is_file():
        tail = (proc.stderr or proc.stdout).strip()[-800:]
        raise MatlabUnavailable(
            f"MATLAB produced no snapshot (exit {proc.returncode}). Output tail:\n{tail}"
        )
    snapshot = WorkspaceSnapshot.from_json(out_json.read_text(encoding="utf-8"))
    if snapshot.error and log:
        log(f"matlab: script reported an error (partial snapshot): {snapshot.error}")
    cache_dir().mkdir(parents=True, exist_ok=True)
    (cache_dir() / f"{key}.json").write_text(snapshot.to_json(), encoding="utf-8")
    return snapshot
