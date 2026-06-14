"""Variable correspondence auto-proposal with confidence tiers (MP-2).

Variable matching is low-risk (name/shape/format are easy to eyeball), so it is
auto-proposed — but every proposal is a **draft**: the result carries a
confidence tier and is never used downstream until the user confirms it (MP-6).
Operation matching is deliberately *not* done here (MP-3 is fully manual).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeforge.core.mapping.model import (
    CONFIDENT,
    PROPOSED,
    UNMATCHED,
    WEAK,
    VarMapping,
)

_STAGE_SUFFIX = re.compile(r"_(?:0|N|\d+)$")


@dataclass(frozen=True)
class Entity:
    """A name to match, with the shape/format facts that grade confidence."""

    name: str  # original identifier (stored in the mapping)
    shape: tuple[int, int] = (1, 1)
    width: int | None = None  # fixed-point width, when known
    scale: int | None = None


def _norm(name: str) -> str:
    """Comparison key: dotted->underscore, lowercase, drop a stage suffix.

    So MATLAB ``cfg.gain`` and SV ``cfg_gain_0`` match, as do ``prod`` and
    ``prod_4``.
    """
    return _STAGE_SUFFIX.sub("", name.replace(".", "_").lower())


def _grade(matlab: Entity, sv: Entity) -> str:
    shape_ok = matlab.shape == sv.shape
    format_ok = (matlab.width, matlab.scale) == (sv.width, sv.scale)
    return CONFIDENT if shape_ok and format_ok else WEAK


def propose_variables(matlab: list[Entity], sv: list[Entity]) -> list[VarMapping]:
    """Draft MATLAB↔SV variable mappings with a confidence tier per pair (MP-2).

    Confident = name + shape + format agree; weak = name agrees but shape/format
    differ; unmatched = no counterpart on the other side. All drafts are
    ``status == PROPOSED`` — confirmation is the user's job.
    """
    sv_by_norm: dict[str, Entity] = {}
    for e in sv:
        sv_by_norm.setdefault(_norm(e.name), e)
    matlab_norms = {_norm(e.name) for e in matlab}

    out: list[VarMapping] = []
    matched_sv: set[str] = set()
    for me in matlab:
        key = _norm(me.name)
        se = sv_by_norm.get(key)
        if se is None:
            out.append(VarMapping(me.name, "", UNMATCHED, PROPOSED))
        else:
            matched_sv.add(key)
            out.append(VarMapping(me.name, se.name, _grade(me, se), PROPOSED))
    # SV entities with no MATLAB counterpart surface as unmatched too (coverage)
    for se in sv:
        if _norm(se.name) not in matlab_norms:
            out.append(VarMapping("", se.name, UNMATCHED, PROPOSED))
    return out
