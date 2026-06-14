"""Workspace ingestion: `.mat` files and SV `software` struct mirrors (WS).

The `.mat` workspace struct and its hand-written SystemVerilog `software`
mirror are the upstream data source the rest of v1.1 reasons about. This layer
loads both into one dotted-path/shape representation so they are field-
comparable (WS-1, WS-2); reconciliation and the datapath oracle build on it.
"""

from __future__ import annotations

from pipeforge.core.workspace.mat_loader import WorkspaceTree, WsField, load_mat
from pipeforge.core.workspace.sv_struct import load_sv_software, parse_sv_software

__all__ = [
    "WorkspaceTree",
    "WsField",
    "load_mat",
    "load_sv_software",
    "parse_sv_software",
]
