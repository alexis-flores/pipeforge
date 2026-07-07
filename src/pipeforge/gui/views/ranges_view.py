"""Ranges view (RP-1…RP-5 GUI): declare input ranges, see overflow hazards.

Per-input min/max entry (or one click to adopt measured MATLAB ranges),
interval propagation through the DAG, a per-node table flagging overflow and
divide-by-near-zero, and a WIDTH/SCALE recommendation that can be adopted as
the workspace format. Row selection is synced to the shared node selection so
the inspector and timelines follow.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pipeforge.core.audit.engine import Audit
from pipeforge.core.ranges.interval import Interval
from pipeforge.core.ranges.propagate import (
    RangeError,
    RangeReport,
    propagate,
    ranges_from_snapshot,
    recommend_format,
)
from pipeforge.gui.theme.tokens import Theme
from pipeforge.gui.workspace import Workspace

_HINT = (
    "Open a MATLAB file, give each input a min and max, then Propagate to see "
    "every value's range — and whether the current WIDTH/SCALE can overflow."
)


def _fmt_bound(x: float) -> str:
    if x != x or abs(x) == float("inf"):
        return "∞" if x > 0 else "-∞"
    return f"{x:.6g}"


class RangesView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("view")
        self._ws = workspace
        self._report: RangeReport | None = None
        self._row_nids: list[str] = []
        self._remembered: dict[str, tuple[str, str]] = {}  # input -> (min, max) text

        title = QLabel("Ranges")
        title.setObjectName("viewTitle")
        self.summary = QLabel(_HINT)
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)

        # -- input ranges (editable) ----------------------------------------
        self.inputs_table = QTableWidget(0, 3)
        self.inputs_table.setHorizontalHeaderLabels(["Input", "Min", "Max"])
        vh = self.inputs_table.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        self.inputs_table.setAlternatingRowColors(True)
        hh = self.inputs_table.horizontalHeader()
        if hh is not None:
            hh.setStretchLastSection(True)

        self.snapshot_btn = QPushButton("From MATLAB snapshot")
        self.snapshot_btn.setToolTip(
            "Fill min/max from the measured values in the live MATLAB snapshot "
            "(observed, not proven — widen for safety margins)"
        )
        self.snapshot_btn.clicked.connect(self._fill_from_snapshot)
        self.propagate_btn = QPushButton("Propagate")
        self.propagate_btn.clicked.connect(self.run_propagation)
        input_actions = QHBoxLayout()
        input_actions.addWidget(self.snapshot_btn)
        input_actions.addStretch(1)
        input_actions.addWidget(self.propagate_btn)

        inputs_panel = QWidget()
        inputs_box = QVBoxLayout(inputs_panel)
        inputs_box.setContentsMargins(0, 0, 0, 0)
        inputs_box.setSpacing(8)
        inputs_label = QLabel("Input ranges")
        inputs_label.setObjectName("sectionTitle")
        inputs_box.addWidget(inputs_label)
        inputs_box.addWidget(self.inputs_table, 1)
        inputs_box.addLayout(input_actions)

        # -- propagated results ----------------------------------------------
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(
            ["Signal", "Range", "Int bits", "Overflow", "÷ near 0"]
        )
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        rvh = self.results_table.verticalHeader()
        if rvh is not None:
            rvh.setVisible(False)
        self.results_table.setAlternatingRowColors(True)
        rhh = self.results_table.horizontalHeader()
        if rhh is not None:
            rhh.setStretchLastSection(True)
        self.results_table.cellClicked.connect(self._on_row)

        results_panel = QWidget()
        results_box = QVBoxLayout(results_panel)
        results_box.setContentsMargins(0, 0, 0, 0)
        results_box.setSpacing(8)
        results_label = QLabel("Propagated ranges")
        results_label.setObjectName("sectionTitle")
        results_box.addWidget(results_label)
        results_box.addWidget(self.results_table, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(inputs_panel)
        split.addWidget(results_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)

        # -- recommendation ----------------------------------------------------
        self.budget_edit = QLineEdit("0.01")
        self.budget_edit.setMaximumWidth(90)
        self.budget_edit.setToolTip("absolute error budget for the recommendation")
        self.recommend_btn = QPushButton("Recommend WIDTH/SCALE")
        self.recommend_btn.clicked.connect(self._recommend)
        self.adopt_btn = QPushButton("Adopt")
        self.adopt_btn.setEnabled(False)
        self.adopt_btn.clicked.connect(self._adopt)
        self.recommend_label = QLabel("")
        self.recommend_label.setObjectName("muted")
        self.recommend_label.setWordWrap(True)
        rec_row = QHBoxLayout()
        rec_row.addWidget(QLabel("Error budget"))
        rec_row.addWidget(self.budget_edit)
        rec_row.addWidget(self.recommend_btn)
        rec_row.addWidget(self.adopt_btn)
        rec_row.addStretch(1)
        self._recommended: tuple[int, int] | None = None

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 16, 24, 16)
        box.setSpacing(8)
        box.addWidget(title)
        box.addWidget(self.summary)
        box.addWidget(split, 1)
        box.addLayout(rec_row)
        box.addWidget(self.recommend_label)

        workspace.auditChanged.connect(self._on_audit)
        workspace.formatChanged.connect(lambda _w, _s: self._rerun_if_ready())
        workspace.snapshotChanged.connect(lambda _s: self._sync_snapshot_btn())
        self._sync_snapshot_btn()

    def set_theme(self, _theme: Theme) -> None:
        pass

    # -- inputs ---------------------------------------------------------------

    def _on_audit(self, audit: object) -> None:
        self._remember_inputs()
        if not isinstance(audit, Audit):
            self.inputs_table.setRowCount(0)
            self.results_table.setRowCount(0)
            self._report = None
            self.summary.setText(_HINT)
            return
        names = [n.label for n in audit.dag.inputs()]
        self.inputs_table.setRowCount(len(names))
        for r, name in enumerate(names):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.inputs_table.setItem(r, 0, item)
            lo, hi = self._remembered.get(name, ("", ""))
            if not lo and not hi and name in self._ws.project_ranges:
                plo, phi = self._ws.project_ranges[name]  # restored sidecar (PJ-1)
                lo, hi = f"{plo:.6g}", f"{phi:.6g}"
            self.inputs_table.setItem(r, 1, QTableWidgetItem(lo))
            self.inputs_table.setItem(r, 2, QTableWidgetItem(hi))
        if not self._has_all_ranges():
            self.summary.setText(
                f"{audit.filename}: {len(names)} input(s) — enter min/max for each "
                "(or take them from a MATLAB snapshot), then Propagate."
            )
        self._rerun_if_ready()

    def _remember_inputs(self) -> None:
        for r in range(self.inputs_table.rowCount()):
            name_item = self.inputs_table.item(r, 0)
            lo_item = self.inputs_table.item(r, 1)
            hi_item = self.inputs_table.item(r, 2)
            if name_item is None:
                continue
            lo = lo_item.text().strip() if lo_item else ""
            hi = hi_item.text().strip() if hi_item else ""
            if lo or hi:
                self._remembered[name_item.text()] = (lo, hi)

    def declared_ranges(self) -> dict[str, Interval] | None:
        """Parse the inputs table; None (with a summary message) if incomplete."""
        out: dict[str, Interval] = {}
        for r in range(self.inputs_table.rowCount()):
            name_item = self.inputs_table.item(r, 0)
            lo_item = self.inputs_table.item(r, 1)
            hi_item = self.inputs_table.item(r, 2)
            if name_item is None:
                continue
            name = name_item.text()
            lo_text = lo_item.text().strip() if lo_item else ""
            hi_text = hi_item.text().strip() if hi_item else ""
            if not lo_text or not hi_text:
                self.summary.setText(f"input '{name}' needs both a min and a max")
                return None
            try:
                lo, hi = float(lo_text), float(hi_text)
                out[name] = Interval(lo, hi)
            except ValueError as exc:
                self.summary.setText(f"input '{name}': {exc}")
                return None
        return out

    def _has_all_ranges(self) -> bool:
        for r in range(self.inputs_table.rowCount()):
            for c in (1, 2):
                item = self.inputs_table.item(r, c)
                if item is None or not item.text().strip():
                    return False
        return self.inputs_table.rowCount() > 0

    def _sync_snapshot_btn(self) -> None:
        self.snapshot_btn.setEnabled(self._ws.snapshot is not None)

    def _fill_from_snapshot(self) -> None:
        audit = self._ws.audit
        if audit is None or self._ws.snapshot is None:
            return
        measured = ranges_from_snapshot(audit.dag, self._ws.snapshot)
        if not measured:
            self.summary.setText(
                "the snapshot has no min/max for these inputs — refresh from "
                "MATLAB (Ctrl+Shift+M) with the script loaded"
            )
            return
        for r in range(self.inputs_table.rowCount()):
            name_item = self.inputs_table.item(r, 0)
            if name_item is None or name_item.text() not in measured:
                continue
            iv = measured[name_item.text()]
            self.inputs_table.setItem(r, 1, QTableWidgetItem(f"{iv.lo:.6g}"))
            self.inputs_table.setItem(r, 2, QTableWidgetItem(f"{iv.hi:.6g}"))
        self.summary.setText(
            "filled from measured MATLAB values (observed, not proven) — widen "
            "them for safety margin, then Propagate"
        )

    # -- propagation ------------------------------------------------------------

    def _rerun_if_ready(self) -> None:
        if self._ws.audit is not None and self._has_all_ranges():
            self.run_propagation()

    def run_propagation(self) -> None:
        audit = self._ws.audit
        if audit is None:
            self.summary.setText(_HINT)
            return
        declared = self.declared_ranges()
        if declared is None:
            return
        try:
            report = propagate(audit.dag, declared, self._ws.cost_model)
        except RangeError as exc:
            self.summary.setText(f"range analysis: {exc}")
            return
        self._report = report
        self._fill_results(report)
        # persist the declared ranges (PJ-1) and badge the timelines (RP GUI)
        self._ws.set_project_ranges({k: (iv.lo, iv.hi) for k, iv in declared.items()})
        self._ws.rangeFlagsChanged.emit(
            frozenset(n.nid for n in report.overflow_nodes),
            frozenset(n.nid for n in report.hazard_nodes),
        )
        overflow = len(report.overflow_nodes)
        hazards = len(report.hazard_nodes)
        if overflow or hazards:
            self._ws.toast(
                "warning",
                f"Ranges: {overflow} overflow risk(s), {hazards} ÷-near-zero hazard(s) "
                f"at {report.fmt_width}/{report.fmt_scale} — badges are on the timeline",
            )
        self._ws.log_activity(
            "warning" if (overflow or hazards) else "success",
            f"Ranges propagated @ {report.fmt_width}/{report.fmt_scale}",
            f"{overflow} overflow, {hazards} ÷-near-zero — LEFT ≥ {report.required_left} needed; "
            "declared ranges saved to the sidecar",
        )
        fmt = f"{report.fmt_width}/{report.fmt_scale}"
        verdict = (
            f"⚠ {overflow} value(s) can overflow {fmt}" if overflow else f"✓ no overflow at {fmt}"
        )
        if hazards:
            verdict += f" — ⚠ {hazards} divide-by-near-zero hazard(s)"
        self.summary.setText(
            f"{audit.filename} @ {fmt}: {verdict}. Needs LEFT ≥ {report.required_left} "
            f"(integer bits incl. sign)."
        )

    def _fill_results(self, report: RangeReport) -> None:
        rows = list(report.nodes.values())
        self._row_nids = [nr.nid for nr in rows]
        self.results_table.setRowCount(len(rows))
        for r, nr in enumerate(rows):
            interval = f"[{_fmt_bound(nr.interval.lo)}, {_fmt_bound(nr.interval.hi)}]"
            cells = (
                nr.signal,
                interval,
                str(nr.integer_bits) if nr.integer_bits < 64 else "unbounded",
                "⚠ overflow" if nr.overflow_risk else "",
                "⚠ hazard" if nr.near_zero_divisor else "",
            )
            for c, text in enumerate(cells):
                self.results_table.setItem(r, c, QTableWidgetItem(text))
        self.results_table.resizeColumnsToContents()

    def _on_row(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._row_nids):
            self._ws.select_node(self._row_nids[row])

    # -- recommendation ------------------------------------------------------------

    def _recommend(self) -> None:
        audit = self._ws.audit
        if audit is None:
            self.summary.setText(_HINT)
            return
        declared = self.declared_ranges()
        if declared is None:
            return
        try:
            budget = float(self.budget_edit.text())
            if budget <= 0:
                raise ValueError("budget must be positive")
        except ValueError:
            self.recommend_label.setText("enter a positive error budget, e.g. 0.01")
            return
        try:
            rec = recommend_format(
                audit.dag,
                declared,
                self._ws.cost_model,
                budget,
                snapshot=self._ws.snapshot,
            )
        except (RangeError, ValueError) as exc:
            self.recommend_label.setText(f"cannot recommend: {exc}")
            return
        met = "meets the budget" if rec.meets_budget else "budget UNMET (see rationale)"
        self.recommend_label.setText(
            f"{rec.width}/{rec.scale} — {rec.rationale} — validated SQNR "
            f"{rec.validated_sqnr_db:.1f} dB, {met}"
        )
        self._recommended = (rec.width, rec.scale)
        self.adopt_btn.setEnabled(True)
        self.adopt_btn.setText(f"Adopt {rec.width}/{rec.scale}")

    def _adopt(self) -> None:
        if self._recommended is not None:
            self._ws.set_format(*self._recommended)
