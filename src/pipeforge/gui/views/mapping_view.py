"""Correspondence workspace: map MATLAB entities to their SV counterparts (MP-1).

Loads, together, the `.m` (→ DAG) and its `.sv` (→ module) plus the `.mat` and
its SV ``software`` mirror, and presents MATLAB-side and SV-side entities side by
side. Variable correspondences are **auto-proposed with a confidence tier**
(MP-2); the user links, unlinks, or marks-unmapped to produce the authoritative,
confirmed mapping the rest of the tool reads (MP-6), persisted to the
``pipeforge.map.json`` sidecar. Operation grouping (MP-3) is manual: pick a
MATLAB op and one-or-more SV instances and group them.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
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
from pipeforge.core.mapping.persist import load_map, save_map, sidecar_for
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
        self.save_btn = QPushButton("Save map")
        self.load_btn = QPushButton("Load map")
        self.save_btn.clicked.connect(lambda: self.save_sidecar())
        self.load_btn.clicked.connect(lambda: self.load_sidecar())
        actions = QHBoxLayout()
        actions.addWidget(self.link_btn)
        actions.addWidget(self.unlink_btn)
        actions.addWidget(self.unmapped_btn)
        actions.addStretch(1)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.load_btn)

        # MP-3: manual operation grouping (one MATLAB op -> one-or-more instances)
        self.ops_combo = QComboBox()
        self.instances_list = QListWidget()
        self.instances_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.instances_list.setMaximumHeight(90)
        self.group_btn = QPushButton("Create group")
        self.group_btn.clicked.connect(self._group_selected)
        self.groups_label = QLabel()
        self.groups_label.setObjectName("muted")
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("MATLAB op:"))
        group_row.addWidget(self.ops_combo)
        group_row.addWidget(self.group_btn)
        group_row.addStretch(1)

        box = QVBoxLayout(self)
        box.addWidget(title)
        box.addWidget(self.meta)
        box.addLayout(sides)
        box.addWidget(QLabel("Proposed correspondences (confirm to make authoritative):"))
        box.addWidget(self.map_table)
        box.addLayout(actions)
        box.addWidget(self.coverage_label)
        box.addWidget(QLabel("Operation grouping (manual — select an op + SV instances):"))
        box.addLayout(group_row)
        box.addWidget(self.instances_list)
        box.addWidget(self.groups_label)

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

        self.ops_combo.clear()
        self.ops_combo.addItems(self.matlab_ops)
        self.instances_list.clear()
        self.instances_list.addItems(self.sv_instances)

        self.cmap = CorrespondenceMap(variables=propose_variables(self._matlab, self._sv))
        self._refill_map()
        self._refresh_coverage()
        self._refresh_groups()
        self.meta.setText(
            f"{len(self._matlab)} MATLAB entities, {len(self._sv)} SV entities — "
            f"{len(self.cmap.variables)} proposed correspondences"
        )

    # -- sidecar persistence (MP-6) -----------------------------------------

    def _sidecar_path(self) -> Path:
        m_path = getattr(self._ws, "m_path", None) if self._ws is not None else None
        return sidecar_for(Path(m_path)) if m_path else Path("pipeforge.map.json")

    def save_sidecar(self, path: Path | None = None) -> Path:
        """Persist the confirmed correspondence to pipeforge.map.json (MP-6)."""
        target = path or self._sidecar_path()
        save_map(self.cmap, target)
        self.meta.setText(f"saved correspondence to {target.name}")
        return target

    def load_sidecar(self, path: Path | None = None) -> None:
        target = path or self._sidecar_path()
        if target.is_file():
            self.cmap = load_map(target)
            self._refill_map()
            self._refresh_coverage()
            self._refresh_groups()

    def coverage_report(self) -> Coverage:
        """Ungrouped MATLAB ops and unassigned SV instances (MP-4)."""
        return coverage(self.cmap, self.matlab_ops, self.sv_instances)

    def _group_selected(self) -> None:
        op = self.ops_combo.currentText()
        instances = [i.text() for i in self.instances_list.selectedItems()]
        if op and instances:
            self.add_group(op, instances)

    def _refresh_groups(self) -> None:
        if not self.cmap.groups:
            self.groups_label.setText("No operation groups yet.")
            return
        lines = [f"{g.matlab_op} → {', '.join(g.sv_instances)}" for g in self.cmap.groups]
        self.groups_label.setText("Groups: " + "; ".join(lines))

    def add_group(self, matlab_op: str, sv_instances: list[str]) -> None:
        self.cmap.add_group(matlab_op, sv_instances)
        self._refresh_groups()
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
