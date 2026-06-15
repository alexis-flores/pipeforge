"""Correspondence workspace GUI tests (MP-1, MP-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytestqt")
from pytestqt.qtbot import QtBot

from pipeforge.core.mapping.model import CONFIRMED, PROPOSED, UNMAPPED
from pipeforge.gui.views.mapping_view import MappingView

PARAMS = (
    Path(__file__).parent.parent.parent / "src" / "pipeforge" / "demos" / "matlab" / "params.mat"
)
SOFTWARE = Path(__file__).parent.parent / "fixtures" / "workspace" / "software.sv"

M_SRC = "prod = a .* b;\ny = prod + c;"
SV_SRC = (Path(__file__).parent.parent / "fixtures" / "cosim" / "sample.sv").read_text(
    encoding="utf-8"
)


@pytest.mark.req("MP-1")
def test_loads_m_sv_mat_software_side_by_side(qtbot: QtBot) -> None:
    view = MappingView()
    qtbot.addWidget(view)
    view.load(
        m_source=M_SRC,
        sv_source=SV_SRC,
        mat_path=PARAMS,
        software_source=SOFTWARE.read_text(encoding="utf-8"),
    )
    # both domains are populated side by side
    assert view.matlab_table.rowCount() > 0
    assert view.sv_table.rowCount() > 0
    matlab_names = {
        view.matlab_table.item(r, 0).text() for r in range(view.matlab_table.rowCount())
    }
    sv_names = {view.sv_table.item(r, 0).text() for r in range(view.sv_table.rowCount())}
    assert {"a", "b", "c", "y"} <= matlab_names  # DAG inputs + output
    assert "gain" in matlab_names  # .mat fields included
    assert {"a_0", "b_0", "c_0"} <= sv_names  # SV ports
    assert "filt.order" in sv_names  # `software` mirror fields included
    # variable correspondences were auto-proposed
    assert len(view.cmap.variables) > 0


@pytest.mark.req("MP-2")
def test_user_link_unlink_mark_unmapped(qtbot: QtBot) -> None:
    view = MappingView()
    qtbot.addWidget(view)
    view.load(m_source=M_SRC, sv_source=SV_SRC)

    # a confident proposal exists (a <-> a_0) but is NOT yet authoritative
    assert view.cmap.resolve("a") is None

    view.link("a", "a_0")  # user confirms
    assert view.cmap.find("a").status == CONFIRMED
    assert view.cmap.resolve("a") == "a_0"

    view.unlink("a")  # user breaks it
    entry = view.cmap.find("a")
    assert entry.status == PROPOSED and entry.sv == ""
    assert view.cmap.resolve("a") is None

    view.mark_unmapped("c")  # user declares no SV counterpart
    assert view.cmap.find("c").status == UNMAPPED

    # the proposals table reflects the confirmed/edited state
    assert view.map_table.rowCount() == len(view.cmap.variables)


@pytest.mark.req("MP-4")
def test_coverage_meter_unmapped_instances_and_ops(qtbot: QtBot) -> None:
    view = MappingView()
    qtbot.addWidget(view)
    view.load(m_source=M_SRC, sv_source=SV_SRC)

    # before any grouping: every op is ungrouped and every instance unassigned
    cov = view.coverage_report()
    assert len(cov.ungrouped_ops) == len(view.matlab_ops) > 0
    assert len(cov.unassigned_instances) == len(view.sv_instances) > 0
    assert not cov.complete

    # grouping one op to its instance shrinks both sides of the meter
    op = view.matlab_ops[0]
    inst = view.sv_instances[0]
    view.add_group(op, [inst])
    cov2 = view.coverage_report()
    assert op not in cov2.ungrouped_ops
    assert inst not in cov2.unassigned_instances
    assert "ungrouped" in view.coverage_label.text()


@pytest.mark.req("MP-6")
def test_sidecar_save_load_roundtrip_in_gui(qtbot: QtBot, tmp_path: Path) -> None:
    view = MappingView()
    qtbot.addWidget(view)
    view.load(m_source=M_SRC, sv_source=SV_SRC)
    view.link("a", "a_0")  # user confirms a mapping
    sidecar = tmp_path / "pipeforge.map.json"
    view.save_sidecar(sidecar)
    assert sidecar.is_file()  # persisted to disk (MP-6)

    fresh = MappingView()
    qtbot.addWidget(fresh)
    fresh.load(m_source=M_SRC, sv_source=SV_SRC)
    assert fresh.cmap.resolve("a") is None  # not confirmed in the fresh view
    fresh.load_sidecar(sidecar)
    assert fresh.cmap.resolve("a") == "a_0"  # confirmed mapping restored


@pytest.mark.req("MP-3")
def test_operation_grouping_in_gui(qtbot: QtBot) -> None:
    view = MappingView()
    qtbot.addWidget(view)
    view.load(m_source=M_SRC, sv_source=SV_SRC)
    assert view.ops_combo.count() == len(view.matlab_ops) > 0  # ops offered
    assert view.instances_list.count() == len(view.sv_instances)

    op = view.matlab_ops[0]
    view.ops_combo.setCurrentText(op)
    view.instances_list.item(0).setSelected(True)
    view._group_selected()
    assert view.cmap.group_for(op) is not None  # manual group created
    assert op not in view.coverage_report().ungrouped_ops  # coverage updated
