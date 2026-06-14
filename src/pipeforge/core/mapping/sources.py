"""Extract mappable entities from the loaded design sources (MP-1/MP-2).

The correspondence workspace loads four sources — the `.m` (→ DAG), its `.sv`
(→ :class:`SvModule`), the `.mat` (→ :class:`WorkspaceTree`), and the SV
``software`` mirror (→ :class:`WorkspaceTree`). This module turns each side into
a flat list of :class:`Entity` so the auto-matcher can propose variable pairs.
"""

from __future__ import annotations

from pipeforge.core.frontend.dag import Dag
from pipeforge.core.mapping.propose import Entity
from pipeforge.core.svlint.model import SvModule
from pipeforge.core.workspace.mat_loader import WorkspaceTree


def matlab_entities(dag: Dag | None, tree: WorkspaceTree | None) -> list[Entity]:
    """MATLAB-side names: DAG inputs/output signals plus `.mat` field paths."""
    out: dict[str, Entity] = {}
    if dag is not None:
        for node in dag.inputs():
            out.setdefault(node.label, Entity(node.label, node.shape))
        for node in dag.outputs():
            if node.signal:
                out.setdefault(node.signal, Entity(node.signal, node.shape))
    if tree is not None:
        for path, fld in tree.fields.items():
            out.setdefault(path, Entity(path, fld.shape))
    return list(out.values())


def sv_entities(module: SvModule | None, software: WorkspaceTree | None) -> list[Entity]:
    """SV-side names: module ports plus `software` struct field paths."""
    out: dict[str, Entity] = {}
    if module is not None:
        for port in module.ports:
            out.setdefault(port.name, Entity(port.name, (1, 1)))
    if software is not None:
        for path, fld in software.fields.items():
            out.setdefault(path, Entity(path, fld.shape))
    return list(out.values())
