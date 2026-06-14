"""Map staleness detection (MP-5).

A stale map is worse than no map: it produces confident-looking wrong
comparisons. Sources are content-hashed; when a `.m`/`.sv`/struct changes, any
**confirmed** mapping that now references a renamed/removed entity is flagged
**dangling** and demoted so it is no longer used downstream — it requires
re-confirmation rather than being silently trusted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from pipeforge.core.mapping.model import (
    CONFIRMED,
    DANGLING,
    CorrespondenceMap,
    VarMapping,
)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class StalenessReport:
    changed_sources: list[str] = field(default_factory=list)
    dangling: list[VarMapping] = field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        return bool(self.dangling)


def record_hashes(cmap: CorrespondenceMap, sources: dict[str, str]) -> None:
    """Snapshot source content hashes into the map (call on save/confirm)."""
    cmap.source_hashes = {name: content_hash(text) for name, text in sources.items()}


def check_staleness(
    cmap: CorrespondenceMap,
    sources: dict[str, str],
    matlab_entities: set[str],
    sv_entities: set[str],
) -> StalenessReport:
    """Detect, flag, and demote confirmed mappings invalidated by a change (MP-5).

    A confirmed mapping is dangling when a source changed *and* one of its
    referenced entities no longer exists. Dangling mappings are set to
    ``DANGLING`` so :func:`resolve_confirmed` stops returning them until the
    user re-confirms.
    """
    changed = [
        name for name, text in sources.items() if cmap.source_hashes.get(name) != content_hash(text)
    ]
    report = StalenessReport(changed_sources=changed)
    if not changed:
        return report
    for v in cmap.variables:
        if v.status != CONFIRMED:
            continue
        missing = (v.matlab and v.matlab not in matlab_entities) or (
            v.sv and v.sv not in sv_entities
        )
        if missing:
            v.status = DANGLING  # never silently trusted again (§10)
            report.dangling.append(v)
    return report
