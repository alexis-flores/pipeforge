"""Correspondence workspace: map MATLAB entities to their SV counterparts (MP-1).

Loads, together, the `.m` (→ DAG) and its `.sv` (→ module) plus the `.mat` and
its SV ``software`` mirror, and presents MATLAB-side and SV-side entities side by
side. Variable correspondences are **auto-proposed with a confidence tier**
(MP-2); the user links, unlinks, or marks-unmapped to produce the authoritative,
confirmed mapping the rest of the tool reads (MP-6). Operation grouping (MP-3) is
manual and arrives in a later phase.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.audit.engine import audit_source
from pipeforge.core.costmodel.model import CostModel
from pipeforge.core.frontend.dag import Dag
from pipeforge.core.mapping.model import CorrespondenceMap
from pipeforge.core.mapping.propose import Entity, propose_variables
from pipeforge.core.mapping.sources import matlab_entities, sv_entities
from pipeforge.core.mapping.validate import Coverage, coverage
from pipeforge.core.svlint.model import SvModule
from pipeforge.core.svlint.parse import parse_sv
from pipeforge.core.workspace.mat_loader import WorkspaceTree, load_mat
from pipeforge.core.workspace.sv_struct import parse_sv_software

_EMPTY_HINT = (
    "Load a MATLAB function and its SystemVerilog equivalent (and, optionally, "
    "the .mat workspace and its `software` mirror) to map names across the two "
    "domains. Variable pairs are proposed automatically; you confirm them."
)


def _entity_rows(table: QTableWidget, entities: list[Entity]) -> None:
    table.setRowCount(len(entities))
    for row, ent in enumerate(entities):
        table.setItem(row, 0, QTableWidgetItem(ent.name))
        table.setItem(row, 1, QTableWidgetItem(f"{ent.shape[0]}x{ent.shape[1]}"))


class MappingView(QWidget):
    def __init__(self, workspace: object | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self.cmap = CorrespondenceMap()
        self._matlab: list[Entity] = []
        self._sv: list[Entity] = []
        self._dag: Dag | None = None
        self._module: SvModule | None = None
        self.matlab_ops: list[str] = []  # DAG op node ids (MP-3 targets)
        self.sv_instances: list[str] = []  # SV instance names

        title = QLabel("Correspondence")
        title.setObjectName("viewTitle")
        self.meta = QLabel(_EMPTY_HINT)
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)

        self.matlab_table = QTableWidget(0, 2)
        self.matlab_table.setHorizontalHeaderLabels(["MATLAB", "shape"])
        self.sv_table = QTableWidget(0, 2)
        self.sv_table.setHorizontalHeaderLabels(["SystemVerilog", "shape"])
        sides = QHBoxLayout()
        sides.addWidget(self.matlab_table)
        sides.addWidget(self.sv_table)

        self.map_table = QTableWidget(0, 4)
        self.map_table.setHorizontalHeaderLabels(["MATLAB", "SV", "confidence", "status"])

        self.coverage_label = QLabel()  # MP-4 coverage meter
        self.coverage_label.setObjectName("muted")

        self.link_btn = QPushButton("Link")
        self.unlink_btn = QPushButton("Unlink")
        self.unmapped_btn = QPushButton("Mark unmapped")
        self.link_btn.clicked.connect(self._link_selected)
        self.unlink_btn.clicked.connect(self._unlink_selected)
        self.unmapped_btn.clicked.connect(self._mark_unmapped_selected)
        actions = QHBoxLayout()
        actions.addWidget(self.link_btn)
        actions.addWidget(self.unlink_btn)
        actions.addWidget(self.unmapped_btn)
        actions.addStretch(1)

        box = QVBoxLayout(self)
        box.addWidget(title)
        box.addWidget(self.meta)
        box.addLayout(sides)
        box.addWidget(QLabel("Proposed correspondences (confirm to make authoritative):"))
        box.addWidget(self.map_table)
        box.addLayout(actions)
        box.addWidget(self.coverage_label)

    # -- loading ---------------------------------------------------------------

    def load(
        self,
        *,
        m_source: str | None = None,
        sv_source: str | None = None,
        mat_path: Path | None = None,
        software_source: str | None = None,
        width: int = 16,
        scale: int = 12,
    ) -> None:
        """Load the four sources side by side and auto-propose variable pairs."""
        dag = None
        if m_source:
            dag = audit_source(m_source, "design.m", CostModel(width, scale)).dag
        module = parse_sv(sv_source)[0] if sv_source else None
        mat_tree: WorkspaceTree | None = load_mat(mat_path) if mat_path else None
        software = parse_sv_software(software_source) if software_source else None

        self._dag = dag
        self._module = module
        self._matlab = matlab_entities(dag, mat_tree)
        self._sv = sv_entities(module, software)
        # operation-grouping targets (MP-3/MP-4): DAG ops and SV instances
        self.matlab_ops = (
            [
                nid
                for nid, n in dag.nodes.items()
                if n.module not in ("", "input", "const", "reshape")
            ]
            if dag is not None
            else []
        )
        self.sv_instances = [i.name for i in module.instances] if module is not None else []
        _entity_rows(self.matlab_table, self._matlab)
        _entity_rows(self.sv_table, self._sv)

        self.cmap = CorrespondenceMap(variables=propose_variables(self._matlab, self._sv))
        self._refill_map()
        self._refresh_coverage()
        self.meta.setText(
            f"{len(self._matlab)} MATLAB entities, {len(self._sv)} SV entities — "
            f"{len(self.cmap.variables)} proposed correspondences"
        )

    def coverage_report(self) -> Coverage:
        """Ungrouped MATLAB ops and unassigned SV instances (MP-4)."""
        return coverage(self.cmap, self.matlab_ops, self.sv_instances)

    def add_group(self, matlab_op: str, sv_instances: list[str]) -> None:
        self.cmap.add_group(matlab_op, sv_instances)
        self._refresh_coverage()

    def _refresh_coverage(self) -> None:
        cov = self.coverage_report()
        self.coverage_label.setText(
            f"Coverage: {len(cov.ungrouped_ops)} op(s) ungrouped, "
            f"{len(cov.unassigned_instances)} SV instance(s) unassigned"
        )

    def _refill_map(self) -> None:
        rows = self.cmap.variables
        self.map_table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            for c, text in enumerate((v.matlab, v.sv, v.confidence, v.status)):
                self.map_table.setItem(r, c, QTableWidgetItem(text))

    # -- user actions (MP-2) ---------------------------------------------------

    def _selected_matlab(self) -> str:
        row = self.map_table.currentRow()
        item = self.map_table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None else ""

    def link(self, matlab: str, sv: str) -> None:
        self.cmap.link(matlab, sv)
        self._refill_map()

    def unlink(self, matlab: str) -> None:
        self.cmap.unlink(matlab)
        self._refill_map()

    def mark_unmapped(self, matlab: str) -> None:
        self.cmap.mark_unmapped(matlab)
        self._refill_map()

    def _link_selected(self) -> None:
        row = self.map_table.currentRow()
        if row < 0:
            return
        matlab_item = self.map_table.item(row, 0)
        sv_item = self.map_table.item(row, 1)
        if matlab_item and sv_item and matlab_item.text() and sv_item.text():
            self.link(matlab_item.text(), sv_item.text())

    def _unlink_selected(self) -> None:
        matlab = self._selected_matlab()
        if matlab:
            self.unlink(matlab)

    def _mark_unmapped_selected(self) -> None:
        matlab = self._selected_matlab()
        if matlab:
            self.mark_unmapped(matlab)

    def set_theme(self, _theme: object) -> None:  # parity with other views
        pass
