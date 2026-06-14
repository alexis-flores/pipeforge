"""The single sanctioned path for reading correspondence downstream (MP-6).

WS reconciliation, the WS-5 oracle, bisection's node→instance binding, the
audit/lint, and the timeline MUST resolve MATLAB↔SV correspondence **only**
through these functions, which expose **confirmed** mappings exclusively. An
unconfirmed auto-proposal is never returned — using a guess as if confirmed is
the defect this layer exists to prevent (§10).
"""

from __future__ import annotations

from pipeforge.core.mapping.model import CorrespondenceMap


def resolve_confirmed(cmap: CorrespondenceMap, matlab: str) -> str | None:
    """The confirmed SV counterpart of a MATLAB entity, or None.

    None means "no confirmed mapping" — callers must treat that as *unknown*,
    never fall back to an auto-proposed guess.
    """
    return cmap.resolve(matlab)


def confirmed_sv(cmap: CorrespondenceMap) -> dict[str, str]:
    """All confirmed MATLAB->SV pairs as a dict (proposals excluded)."""
    return {v.matlab: v.sv for v in cmap.confirmed() if v.matlab and v.sv}
