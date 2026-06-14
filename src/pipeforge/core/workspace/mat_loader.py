"""Load a MATLAB `.mat` workspace into a dotted-path/shape tree (WS-1).

A `.mat` file carries both **constants/parameters** and **input/output test
vectors**, often inside a deeply nested struct. This loader walks that struct
and emits a flat map keyed by dotted path (``cfg.adc.vref``), each entry
carrying the double value(s) and the MATLAB shape.

Two on-disk formats exist (§10):
  * v5 / v7 — read with :func:`scipy.io.loadmat`;
  * v7.3 — HDF5, read with :mod:`h5py`.
Both are detected automatically; values are flattened in MATLAB **column-major**
order so they line up with the AR-3/AR-4 layout contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import scipy.io as sio
from scipy.io.matlab import mat_struct


@dataclass(frozen=True)
class WsField:
    """One workspace value addressed by its dotted path."""

    path: str  # e.g. 'cfg.adc.vref'
    shape: tuple[int, int]  # MATLAB (rows, cols); scalars are (1, 1)
    values: tuple[float, ...]  # column-major doubles (real part for complex)
    class_name: str = "double"  # originating MATLAB class
    text: str | None = None  # for char fields, the decoded string

    @property
    def is_scalar(self) -> bool:
        return self.shape == (1, 1)

    @property
    def numel(self) -> int:
        return self.shape[0] * self.shape[1]


@dataclass(frozen=True)
class WorkspaceTree:
    """All fields of a loaded `.mat`, keyed by dotted path."""

    source: str
    source_format: str  # 'v5' | 'v7.3' | 'sv'
    fields: dict[str, WsField]

    def get(self, path: str) -> WsField | None:
        return self.fields.get(path)

    def paths(self) -> list[str]:
        return sorted(self.fields)

    def constants(self) -> dict[str, WsField]:
        """Scalar parameters/constants (shape 1x1)."""
        return {p: f for p, f in self.fields.items() if f.is_scalar}

    def vectors(self) -> dict[str, WsField]:
        """Non-scalar values: input/output vectors and matrices."""
        return {p: f for p, f in self.fields.items() if not f.is_scalar}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DTYPE_CLASS = {
    "float64": "double",
    "float32": "single",
    "complex128": "double",
    "complex64": "double",
    "bool": "logical",
}


def _shape2d(shape: tuple[int, ...]) -> tuple[int, int]:
    """Collapse an N-D shape to (rows, cols); empty -> (1, 1)."""
    if not shape:
        return (1, 1)
    if len(shape) == 1:
        return (1, shape[0])
    rows = shape[0]
    cols = 1
    for d in shape[1:]:
        cols *= d
    return (rows, cols)


def _numeric_field(path: str, arr: np.ndarray, class_name: str) -> WsField:
    flat = np.asarray(arr).flatten(order="F")  # MATLAB column-major
    if np.iscomplexobj(flat):
        values = tuple(float(x.real) for x in flat)
    else:
        values = tuple(float(x) for x in flat)
    return WsField(path, _shape2d(np.asarray(arr).shape), values, class_name)


# ---------------------------------------------------------------------------
# v5 / v7 (scipy)
# ---------------------------------------------------------------------------


def _walk_v5(path: str, val: object, out: dict[str, WsField]) -> None:
    arr = np.asarray(val)
    if arr.dtype == object:  # struct (scalar) or unsupported cell
        if arr.size == 0:
            return
        first = arr.flat[0]
        if isinstance(first, mat_struct):
            for fname in first._fieldnames:
                _walk_v5(f"{path}.{fname}", getattr(first, fname), out)
        return  # cells/object arrays are out of scope
    if arr.dtype.kind in ("U", "S"):  # char / string
        text = "".join(str(x) for x in arr.flatten(order="F"))
        out[path] = WsField(path, (1, 1), (), "char", text=text)
        return
    out[path] = _numeric_field(path, arr, _DTYPE_CLASS.get(arr.dtype.name, arr.dtype.name))


def _load_v5(path: Path) -> dict[str, WsField]:
    raw = sio.loadmat(str(path), struct_as_record=False, squeeze_me=False)
    out: dict[str, WsField] = {}
    for name, val in raw.items():
        if name.startswith("__"):
            continue
        _walk_v5(name, val, out)
    return out


# ---------------------------------------------------------------------------
# v7.3 (HDF5 / h5py)
# ---------------------------------------------------------------------------


def _matlab_class(obj: h5py.HLObject) -> str:
    cls = obj.attrs.get("MATLAB_class")
    if isinstance(cls, bytes):
        return cls.decode("ascii", "replace")
    return str(cls) if cls is not None else ""


def _walk_v73(path: str, obj: h5py.HLObject, out: dict[str, WsField]) -> None:
    if isinstance(obj, h5py.Group):
        for name, child in obj.items():
            if name.startswith("#"):  # MATLAB internals (e.g. #refs#)
                continue
            _walk_v73(f"{path}.{name}" if path else name, child, out)
        return
    cls = _matlab_class(obj)
    # MATLAB stores arrays transposed (column-major) relative to HDF5 row-major.
    data = np.asarray(obj[()])
    if data.ndim >= 2:
        data = data.T
    if cls == "char":
        codes = np.asarray(data).flatten(order="F")
        text = "".join(chr(int(c)) for c in codes if int(c) != 0)
        out[path] = WsField(path, (1, 1), (), "char", text=text)
        return
    out[path] = _numeric_field(
        path, data, cls or _DTYPE_CLASS.get(data.dtype.name, data.dtype.name)
    )


def _load_v73(path: Path) -> dict[str, WsField]:
    out: dict[str, WsField] = {}
    with h5py.File(str(path), "r") as fh:
        _walk_v73("", fh, out)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_mat(path: str | Path) -> WorkspaceTree:
    """Load a `.mat` file (v5/v7 or v7.3) into a dotted-path workspace tree."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"no such .mat file: {p}")
    if h5py.is_hdf5(str(p)):
        return WorkspaceTree(str(p), "v7.3", _load_v73(p))
    return WorkspaceTree(str(p), "v5", _load_v5(p))
