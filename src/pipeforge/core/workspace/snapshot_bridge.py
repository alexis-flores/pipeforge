"""Static snapshots from `.mat` files — no MATLAB required (WS-7).

The MATLAB bridge produces a :class:`WorkspaceSnapshot` (per-variable class,
shape, range, values) by running a live MATLAB. This module produces the
*same* snapshot from a `.mat` file using the pure-Python loader (scipy/h5py),
so shape-aware auditing, empirical ranges, and snapshot-driven optimization
work on machines with no MATLAB at all.

Every consumer downstream is unchanged: a snapshot is a snapshot. The one
honest difference: `fi` objects are opaque MCOS blobs in `.mat` files, so
fixed-point *type* metadata (FORMAT findings) still needs the live bridge —
classes, shapes, values, and min/max all come through.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from pipeforge.core.frontend.varinfo import VALUE_CAP, VarInfo, WorkspaceSnapshot
from pipeforge.core.workspace.mat_loader import WorkspaceTree, load_mat

#: marker for snapshots built statically (the GUI chip shows it distinctly)
STATIC_ORIGIN = "static .mat (no MATLAB)"


def snapshot_from_tree(tree: WorkspaceTree) -> WorkspaceSnapshot:
    """Convert a loaded workspace tree into an audit-consumable snapshot."""
    snap = WorkspaceSnapshot(
        matlab_version=STATIC_ORIGIN,
        setup=tree.source,
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    for path, fld in sorted(tree.fields.items()):
        if fld.text is not None or not fld.values:
            continue  # char/empty fields carry no numeric analysis value
        snap.variables[path] = VarInfo(
            name=path,
            class_name=fld.class_name,
            size=fld.shape,
            vmin=min(fld.values),
            vmax=max(fld.values),
            values=tuple(fld.values[:VALUE_CAP]),
            truncated=len(fld.values) > VALUE_CAP,
        )
    return snap


def snapshot_from_mat(path: str | Path) -> WorkspaceSnapshot:
    """Load a `.mat` (v5/v7/v7.3) straight into a snapshot (WS-7)."""
    return snapshot_from_tree(load_mat(path))
