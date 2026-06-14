"""MATLAB↔SV correspondence (MP).

The most fragile assumption in every cross-domain capability is that the tool
can correctly map a MATLAB name/operation to its SV counterpart. The fix is to
invert the trust model: the tool *proposes* (variables only, with confidence
tiers), the user *confirms or overrides*, and the **confirmed** mapping — not the
auto-guess — is the source of truth every downstream capability reads (MP-6).

Operation grouping (MP-3) is fully manual: the tool does bookkeeping and
validation, never automatic matching.
"""

from __future__ import annotations

from pipeforge.core.mapping.consume import confirmed_sv, resolve_confirmed
from pipeforge.core.mapping.model import (
    CONFIDENT,
    CONFIRMED,
    DANGLING,
    PROPOSED,
    UNMAPPED,
    UNMATCHED,
    WEAK,
    CorrespondenceMap,
    OperationGroup,
    VarMapping,
)
from pipeforge.core.mapping.persist import SIDECAR_NAME, load_map, save_map, sidecar_for
from pipeforge.core.mapping.propose import Entity, propose_variables
from pipeforge.core.mapping.sources import matlab_entities, sv_entities
from pipeforge.core.mapping.staleness import (
    StalenessReport,
    check_staleness,
    content_hash,
    record_hashes,
)
from pipeforge.core.mapping.validate import Coverage, GroupValidation, coverage, validate_group

__all__ = [
    "CONFIDENT",
    "CONFIRMED",
    "DANGLING",
    "PROPOSED",
    "SIDECAR_NAME",
    "UNMAPPED",
    "UNMATCHED",
    "WEAK",
    "CorrespondenceMap",
    "Coverage",
    "Entity",
    "GroupValidation",
    "OperationGroup",
    "StalenessReport",
    "VarMapping",
    "check_staleness",
    "confirmed_sv",
    "content_hash",
    "coverage",
    "load_map",
    "matlab_entities",
    "propose_variables",
    "record_hashes",
    "resolve_confirmed",
    "save_map",
    "sidecar_for",
    "sv_entities",
    "validate_group",
]
