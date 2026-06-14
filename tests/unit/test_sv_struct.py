"""WS-2: parse the SV `software` struct mirror into a dotted-path/shape tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.core.workspace.sv_struct import SvStructError, load_sv_software, parse_sv_software

FIXTURE = Path(__file__).parent.parent / "fixtures" / "workspace" / "software.sv"


@pytest.mark.req("WS-2")
def test_software_struct_parsed_to_dotted_paths() -> None:
    tree = load_sv_software(FIXTURE)
    assert tree.source_format == "sv"
    paths = set(tree.paths())
    # nested fields are addressable by the same dotted scheme as the .mat (WS-1)
    assert {"gain", "fc", "taps", "filt.order", "filt.ripple"} <= paths
    assert {"cfg.fs", "cfg.adc.bits", "cfg.adc.vref", "mixer"} <= paths

    # scalars, vectors, and a matrix carry value + shape, matrix column-major
    assert tree.get("gain").shape == (1, 1) and tree.get("gain").values == (0.5,)
    assert tree.get("cfg.adc.vref").values == (3.3,)
    taps = tree.get("taps")
    assert taps.shape == (1, 4) and taps.values == (0.25, -0.5, 0.125, 0.0625)
    mixer = tree.get("mixer")
    assert mixer.shape == (2, 2)
    assert mixer.values == (0.7071, 0.7071, -0.7071, 0.7071)  # column-major


@pytest.mark.req("WS-2")
def test_missing_software_pattern_raises() -> None:
    with pytest.raises(SvStructError):
        parse_sv_software("module m; endmodule")
