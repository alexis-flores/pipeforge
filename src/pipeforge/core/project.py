"""Per-design project sidecar: `<stem>.pipeforge.toml` (PJ-1).

Ranges, format, cosim configuration, and device family are *inputs* the user
typed once; losing them on every restart taxes the whole tool. The sidecar
lives next to the `.m` (like `pipeforge.map.json` for mappings), is written
automatically when those inputs change, and is plain TOML so it diffs and
reviews like any other design file. Paths are stored relative to the sidecar.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SUFFIX = ".pipeforge.toml"


@dataclass
class CosimConfig:
    top: str = ""
    backend: str = "auto"
    cadence: str = "continuous"
    vectors: int = 256
    include: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Project:
    m: str = ""
    sv: str = ""
    width: int = 16
    scale: int = 12
    family: str = "xilinx7"
    ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    cosim: CosimConfig = field(default_factory=CosimConfig)

    def resolve(self, base: Path, rel: str) -> Path | None:
        return (base / rel).resolve() if rel else None


def sidecar_for(m_path: Path) -> Path:
    """The sidecar path for a design file: model.m -> model.pipeforge.toml."""
    return m_path.with_name(m_path.stem + SUFFIX)


def load_project(path: Path) -> Project:
    """Read a sidecar; unknown keys are ignored, missing ones default."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    design = data.get("design", {})
    project = Project(
        m=str(design.get("m", "")),
        sv=str(design.get("sv", "")),
        width=int(design.get("width", 16)),
        scale=int(design.get("scale", 12)),
        family=str(design.get("family", "xilinx7")),
    )
    for name, bounds in data.get("ranges", {}).items():
        if isinstance(bounds, list) and len(bounds) == 2:
            project.ranges[str(name)] = (float(bounds[0]), float(bounds[1]))
    cosim = data.get("cosim", {})
    project.cosim = CosimConfig(
        top=str(cosim.get("top", "")),
        backend=str(cosim.get("backend", "auto")),
        cadence=str(cosim.get("cadence", "continuous")),
        vectors=int(cosim.get("vectors", 256)),
        include=[str(x) for x in cosim.get("include", [])],
        sources=[str(x) for x in cosim.get("sources", [])],
    )
    return project


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps_project(p: Project) -> str:
    """Serialize (hand-rolled writer: the stdlib reads TOML but does not write)."""
    lines = [
        "# PipeForge design sidecar — written automatically; safe to edit or delete.",
        "[design]",
        f"m = {_toml_str(p.m)}",
        f"sv = {_toml_str(p.sv)}",
        f"width = {p.width}",
        f"scale = {p.scale}",
        f"family = {_toml_str(p.family)}",
        "",
        "[ranges]",
    ]
    for name, (lo, hi) in sorted(p.ranges.items()):
        lines.append(f"{name} = [{lo!r}, {hi!r}]")
    lines += [
        "",
        "[cosim]",
        f"top = {_toml_str(p.cosim.top)}",
        f"backend = {_toml_str(p.cosim.backend)}",
        f"cadence = {_toml_str(p.cosim.cadence)}",
        f"vectors = {p.cosim.vectors}",
        "include = [" + ", ".join(_toml_str(x) for x in p.cosim.include) + "]",
        "sources = [" + ", ".join(_toml_str(x) for x in p.cosim.sources) + "]",
    ]
    return "\n".join(lines) + "\n"


def save_project(p: Project, path: Path) -> None:
    path.write_text(dumps_project(p), encoding="utf-8")


def load_for_design(m_path: Path) -> Project | None:
    """The design's sidecar, when one exists and parses; never raises."""
    sidecar = sidecar_for(m_path)
    if not sidecar.is_file():
        return None
    try:
        return load_project(sidecar)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return None
