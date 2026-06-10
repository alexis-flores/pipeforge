"""Audit engine tests (AU-2, AU-3, AU-4)."""

from __future__ import annotations

import json

import pytest

from pipeforge.core.audit.engine import Audit, audit_source
from pipeforge.core.audit.report import render_json, render_text
from pipeforge.core.costmodel.model import CostModel

CM = CostModel(16, 12)


def audit(src: str) -> Audit:
    return audit_source(src, "test.m", CM)


def tags(a: Audit) -> set[str]:
    return {f.tag for f in a.findings}


@pytest.mark.req("AU-2")
class TestSchedule:
    def test_ready_times_and_critical_path(self) -> None:
        a = audit("t = x .* y;\nu = t + z;\nv = u ./ w;")
        readys = [s.ready for s in a.dag.statements]
        assert readys == [4, 5, 5 + CM.div_lat]
        assert a.total_latency == 5 + CM.div_lat
        chain = a.critical_path()
        assert chain[0].module == "input"
        assert chain[-1].module == "elem_sdiv"

    def test_census_highlights_dividers(self) -> None:
        a = audit("p = a ./ b;\nq = c ./ d;\nr = e .* f;")
        assert a.census["elem_sdiv"] == 2
        assert a.census["elem_smul"] == 1
        assert a.divider_count == 2

    def test_parallel_chains_max(self) -> None:
        a = audit("p = a .* b;\nq = sqrt(c);\nr = p + q;")
        assert a.total_latency == CM.sqrt_lat + 1


@pytest.mark.req("AU-3")
class TestFindings:
    def test_recip(self) -> None:
        a = audit("ux = x ./ n;\nuy = y ./ n;")
        f = next(f for f in a.findings if f.tag == "RECIP")
        assert "2 divisions" in f.message
        assert "elem_sinv" in f.suggestion
        assert f.savings == CM.div_lat - CM.mul_lat

    def test_cdiv_power_of_two(self) -> None:
        a = audit("y = x / 8;")
        f = next(f for f in a.findings if f.tag == "CDIV")
        assert "elem_rshift by 3" in f.suggestion
        assert f.savings == CM.div_lat - 1

    def test_cdiv_general_constant(self) -> None:
        a = audit("y = x / 3;")
        f = next(f for f in a.findings if f.tag == "CDIV")
        assert "1/3" in f.suggestion
        assert f.savings == CM.div_lat - CM.mul_lat

    def test_serdiv(self) -> None:
        a = audit("y = a / b / c;")
        assert "SERDIV" in tags(a)

    def test_pow(self) -> None:
        a = audit("y = x ^ 4;")
        f = next(f for f in a.findings if f.tag == "POW")
        assert f.savings == CM.mul_lat  # 3 naive muls vs 2 by squaring

    def test_pow_square_suggests_ssqr(self) -> None:
        a = audit("y = x ^ 2;")
        f = next(f for f in a.findings if f.tag == "POW")
        assert "elem_ssqr" in f.suggestion

    def test_cse(self) -> None:
        a = audit("s1 = (u + v) .* k1;\ns2 = (u + v) .* k2;")
        f = next(f for f in a.findings if f.tag == "CSE")
        assert "(u + v)" in f.message

    def test_fuse(self) -> None:
        a = audit("t = a + b + c;")
        f = next(f for f in a.findings if f.tag == "FUSE")
        assert "matadd3" in f.suggestion

    def test_fuse_sub_variants(self) -> None:
        a = audit("t = a + b - c;")
        f = next(f for f in a.findings if f.tag == "FUSE")
        assert "matadd3b1" in f.suggestion
        a = audit("t = a - b - c;")
        f = next(f for f in a.findings if f.tag == "FUSE")
        assert "matadd3b2" in f.suggestion

    def test_feedback(self) -> None:
        a = audit("acc = acc + x;")
        f = next(f for f in a.findings if f.tag == "FEEDBACK")
        assert "initiation interval is 1" in f.message

    def test_no_false_recip_on_constants(self) -> None:
        a = audit("p = a / 4;\nq = b / 4;")
        assert "RECIP" not in tags(a)

    def test_findings_each_carry_line_savings_suggestion(self) -> None:
        src = (
            "ux = x ./ n;\nuy = y ./ n;\np = a / 8;\nw = c / d / e;\n"
            "q = r ^ 4;\ns1 = (u + v) .* k1;\ns2 = (u + v) .* k2;\n"
            "t = a + b + c;\nacc = acc + t;"
        )
        a = audit(src)
        assert tags(a) == {"RECIP", "CDIV", "SERDIV", "POW", "CSE", "FUSE", "FEEDBACK"}
        for f in a.findings:
            assert f.line > 0
            assert f.message
            assert f.suggestion


@pytest.mark.req("AU-4")
class TestOutputs:
    def test_structured_text_and_json_agree(self) -> None:
        a = audit("y = a ./ b;")
        text = render_text(a)
        payload = json.loads(render_json(a))
        assert "elem_sdiv" in text
        assert payload["census"]["elem_sdiv"] == 1
        assert payload["dividers"] == 1
        assert payload["statements"][0]["target"] == "y"

    def test_json_nodes_have_stable_ids(self) -> None:
        a = audit("t = a + b;\ny = t .* c;")
        payload = json.loads(render_json(a))
        ids = [n["id"] for n in payload["nodes"]]
        assert ids == sorted(ids)  # creation order, stable
        roots = {s["root"] for s in payload["statements"]}
        assert roots <= set(ids)

    def test_empty_file(self) -> None:
        a = audit("")
        assert a.total_latency == 0
        assert "(none)" in render_text(a)
