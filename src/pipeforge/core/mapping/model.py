"""Correspondence data model: the persisted, user-authoritative map (MP-6).

A :class:`CorrespondenceMap` holds user-confirmed MATLAB↔SV **variable**
mappings (auto-proposed, then confirmed/overridden — MP-2) and hand-built
**operation groups** (MP-3, Phase E). Only ``status == CONFIRMED`` entries are
authoritative; everything downstream reads those via
:mod:`pipeforge.core.mapping.consume`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# mapping status (the trust axis: a draft is never used as if confirmed)
PROPOSED = "proposed"  # auto-matcher draft, not yet trusted
CONFIRMED = "confirmed"  # user-confirmed: authoritative
UNMAPPED = "unmapped"  # user marked intentionally unmapped (dead/absent)
DANGLING = "dangling"  # a source change invalidated this — needs re-confirmation (MP-5)

# proposal confidence tier (MP-2)
CONFIDENT = "confident"  # name + shape + format agree
WEAK = "weak"  # name agrees, shape/format differ
UNMATCHED = "unmatched"  # no counterpart


@dataclass
class VarMapping:
    """One MATLAB↔SV variable correspondence."""

    matlab: str  # MATLAB-side entity (dag signal or .mat dotted path); '' if none
    sv: str  # SV-side entity (port/signal or software dotted path); '' if none
    confidence: str = UNMATCHED  # proposal tier (MP-2)
    status: str = PROPOSED  # trust state (MP-6)

    @property
    def is_confirmed(self) -> bool:
        return self.status == CONFIRMED


@dataclass
class OperationGroup:
    """A manually-drawn one-MATLAB-op → one-or-more-SV-instances group (MP-3).

    Populated and validated in Phase E; carried here so the sidecar schema is
    forward-compatible.
    """

    matlab_op: str  # MATLAB op node id or label
    sv_instances: list[str] = field(default_factory=list)
    confirmed: bool = False


@dataclass
class CorrespondenceMap:
    """The full correspondence for one design, persisted to the sidecar (MP-6)."""

    variables: list[VarMapping] = field(default_factory=list)
    groups: list[OperationGroup] = field(default_factory=list)
    source_hashes: dict[str, str] = field(default_factory=dict)  # MP-5 staleness (Phase E)
    version: int = 1

    # -- authoritative reads (confirmed only) --------------------------------

    def confirmed(self) -> list[VarMapping]:
        """Only user-confirmed variable mappings — the source of truth (MP-6)."""
        return [v for v in self.variables if v.status == CONFIRMED]

    def resolve(self, matlab: str) -> str | None:
        """MATLAB entity -> confirmed SV counterpart, or None if not confirmed."""
        for v in self.confirmed():
            if v.matlab == matlab and v.sv:
                return v.sv
        return None

    def find(self, matlab: str) -> VarMapping | None:
        for v in self.variables:
            if v.matlab == matlab:
                return v
        return None

    # -- user actions (MP-2): link / unlink / mark-unmapped ------------------

    def link(self, matlab: str, sv: str) -> VarMapping:
        """Confirm a MATLAB↔SV pair (the user's authoritative decision)."""
        existing = self.find(matlab)
        if existing is None:
            existing = VarMapping(matlab, sv)
            self.variables.append(existing)
        existing.sv = sv
        existing.status = CONFIRMED
        return existing

    def unlink(self, matlab: str) -> None:
        """Break a pair: back to an unconfirmed, unmatched draft."""
        entry = self.find(matlab)
        if entry is not None:
            entry.sv = ""
            entry.status = PROPOSED
            entry.confidence = UNMATCHED

    def mark_unmapped(self, matlab: str) -> None:
        """Record that a MATLAB entity intentionally has no SV counterpart."""
        entry = self.find(matlab)
        if entry is None:
            entry = VarMapping(matlab, "")
            self.variables.append(entry)
        entry.sv = ""
        entry.status = UNMAPPED

    # -- operation groups (MP-3): manual only, never auto-proposed -----------

    def add_group(
        self, matlab_op: str, sv_instances: list[str], confirmed: bool = True
    ) -> OperationGroup:
        """Manually group one MATLAB op to one-or-more SV instances (MP-3).

        This is the *only* way a group is created — there is deliberately no
        automatic operation matching (§10).
        """
        group = OperationGroup(matlab_op, list(sv_instances), confirmed=confirmed)
        self.groups.append(group)
        return group

    def group_for(self, matlab_op: str) -> OperationGroup | None:
        for g in self.groups:
            if g.matlab_op == matlab_op:
                return g
        return None
