"""CS-7: codegen probe wrapper exposes internal signals as output ports."""

from __future__ import annotations

import pytest

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.codegen.emitter import generate_sv, probe_port
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.svlint.checks import lint_source

CM = CostModel(16, 12)
SRC = "prod = a .* b;\ny = prod + c;"


@pytest.mark.req("CS-7")
def test_probe_wrapper_exposes_named_signals() -> None:
    audit = audit_source(SRC, "sample.m", CM)
    prod_nid = audit.dag.statements[0].root  # the intermediate 'prod'
    sv = generate_sv(audit, "gen_probed", probes=[prod_nid])

    port = probe_port(prod_nid)
    assert f"output [g.WIDTH-1:0] {port}_N" in sv  # exposed as an output port
    assert f"assign {port}_N =" in sv  # driven from the internal signal
    # the probe is aligned to the final stage, so it samples valid-gated
    assert f".DELAY({CM.add_lat})" in sv  # prod (cycle 4) piped to y's stage (5)

    # instrumented RTL still passes the linter (no convention violations)
    result = lint_source(sv, "gen_probed.sv", CM)
    assert result.findings == [], [f"{f.check}: {f.message}" for f in result.findings]


@pytest.mark.req("CS-7")
def test_no_probes_is_unchanged() -> None:
    audit = audit_source(SRC, "sample.m", CM)
    assert generate_sv(audit, "m") == generate_sv(audit, "m", probes=[])
    assert "probe_" not in generate_sv(audit, "m")
