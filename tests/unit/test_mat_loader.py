"""WS-1: `.mat` ingestion into a dotted-path/shape tree (v5 and v7.3)."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from pipeforge.core.workspace.mat_loader import load_mat

PARAMS = (
    Path(__file__).parent.parent.parent / "src" / "pipeforge" / "demos" / "matlab" / "params.mat"
)


@pytest.mark.req("WS-1")
def test_nested_struct_walk_dotted_paths() -> None:
    tree = load_mat(PARAMS)
    paths = set(tree.paths())
    # hierarchy is preserved and addressable by dotted path, at any depth
    assert {"filt.order", "filt.ripple", "cfg.fs", "cfg.adc.bits", "cfg.adc.vref"} <= paths
    assert {"cfg.agc.attack", "cfg.agc.release", "cfg.agc.enabled"} <= paths
    assert tree.get("cfg.adc.vref").values == (3.3,)
    assert tree.get("cfg.label").text == "demo channel"  # char field carried as text


@pytest.mark.req("WS-1")
def test_extracts_constants_and_io_vectors_with_shape() -> None:
    tree = load_mat(PARAMS)
    # (a) constants/parameters: scalar doubles with (1, 1) shape
    gain = tree.get("gain")
    assert gain.is_scalar and gain.shape == (1, 1) and gain.values == (0.5,)
    assert "gain" in tree.constants() and "filt.order" in tree.constants()

    # (b) named vectors/matrices: shape preserved, values column-major
    taps = tree.get("taps")
    assert taps.shape == (1, 4) and taps.values == (0.25, -0.5, 0.125, 0.0625)
    mixer = tree.get("mixer")
    assert mixer.shape == (2, 2)
    # MATLAB [0.7071 -0.7071; 0.7071 0.7071] flattened column-major
    assert mixer.values == (0.7071, 0.7071, -0.7071, 0.7071)
    assert "taps" in tree.vectors() and "mixer" in tree.vectors()


def _write_v73(path: Path) -> None:
    """Write a minimal MATLAB-v7.3-style HDF5 file (arrays stored transposed)."""
    with h5py.File(str(path), "w") as fh:
        fh.attrs["MATLAB_class"] = np.bytes_(b"struct")
        gain = fh.create_dataset("gain", data=np.array([[0.5]]))
        gain.attrs["MATLAB_class"] = np.bytes_(b"double")
        # MATLAB stores a 1x4 row vector transposed -> HDF5 shape (4, 1)
        taps = fh.create_dataset("taps", data=np.array([[0.25], [-0.5], [0.125], [0.0625]]))
        taps.attrs["MATLAB_class"] = np.bytes_(b"double")
        filt = fh.create_group("filt")
        filt.attrs["MATLAB_class"] = np.bytes_(b"struct")
        order = filt.create_dataset("order", data=np.array([[4.0]]))
        order.attrs["MATLAB_class"] = np.bytes_(b"double")


@pytest.mark.req("WS-1")
def test_handles_v73_hdf5_and_legacy_mat(tmp_path: Path) -> None:
    legacy = load_mat(PARAMS)
    assert legacy.source_format == "v5"

    v73_path = tmp_path / "params73.mat"
    _write_v73(v73_path)
    v73 = load_mat(v73_path)
    assert v73.source_format == "v7.3"
    # both formats yield the same dotted-path tree for the shared fields
    assert v73.get("gain").values == legacy.get("gain").values == (0.5,)
    assert v73.get("taps").shape == legacy.get("taps").shape == (1, 4)
    assert v73.get("taps").values == legacy.get("taps").values
    assert v73.get("filt.order").values == legacy.get("filt.order").values == (4.0,)
