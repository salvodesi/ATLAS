"""«Importa clausole principali…» of a domain sheet (SA-1): the row «Sezioni SRS principali» of the sheet of the
domain in an Excel workbook chosen by the user, shown as a summary of the SRS items it maps (with their type and
category) before they are imported: the domain becomes their principal domain (matrix A4). Each item that can be
imported has a tick in the column «Importa», on at first: without it the item is not imported. The items allocated
to more than one domain (principal of another one in the model, or listed also in the sheet of another domain of
the workbook) are pointed out."""
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from arcadia_tool.model.srs_sections import parse_sections, resolve
from arcadia_tool.storage.domain_sheets import read_domain_sheets, sheet_of
from arcadia_tool.ui.srs_reader import document_order
from arcadia_tool.ui.srs_trace import contributed_items, principal_items
from arcadia_tool.ui.theme import MUTED, icon

NEW, REPLACED, ALREADY, MISSING, EXTERNAL = "new", "replaced", "already", "missing", "external"
OUTCOMES = {  # what the import does to a row: its text, its colour
    NEW: ("Da importare", "#166534"),
    REPLACED: ("Da importare: sostituisce {owner}", "#92400E"),
    ALREADY: ("Già principale di questo dominio", MUTED),
    MISSING: ("Non trovata tra le voci SRS del progetto", "#B42318"),
    EXTERNAL: ("Riferimento a un altro documento: non è una voce SRS", MUTED),
}
COLUMNS = ("Importa", "Voce SRS", "Titolo", "Tipo", "Categoria cap. 9", "Scritta come", "Allocata anche a", "Esito")
TICK, IDENT, TITLE, ALSO, OUTCOME = 0, 1, 2, 6, 7  # columns
OVERLAP_COLOR = "#92400E"


class Row(NamedTuple):
    outcome: str
    item: object  # the SRS item, or None
    ident: str  # its ID, or the text of a reference to another document
    written: str  # as written in the sheet (a group: 4.8.1–4.8.5)
    elsewhere: tuple = ()  # the other domains of the workbook whose sheets list it too

    @property
    def importable(self):
        return self.outcome in (NEW, REPLACED)

    @property
    def overlapping(self):
        """Allocated to more than one domain: pointed out."""
        return self.importable and (self.outcome == REPLACED or bool(self.elsewhere))


def section_ids(model, text, ordered=None):
    """The IDs of the sections and clauses of a row (its groups expanded)."""
    if ordered is None:
        ordered = [e.get("id") for e in document_order(model) if e.get("id")]
    return [i for r in resolve(parse_sections(text), ordered) for i in r.ids]


def summary_rows(model, domain, text, others=()):
    """The rows of a row of principal sections, each item once; others: the other sheets of the workbook (their
    sections allocate the same items to other domains)."""
    ordered = document_order(model)
    ids = [e.get("id") for e in ordered if e.get("id")]
    by_id = {e.get("id"): e for e in ordered if e.get("id")}
    listed = {}
    for s in others:
        for ident in section_ids(model, s.principal, ids):
            domains = listed.setdefault(ident, [])
            if s.ident not in domains:
                domains.append(s.ident)
    rows, seen = [], set()
    for ref in resolve(parse_sections(text), ids):
        if ref.external:
            rows.append(Row(EXTERNAL, None, ref.text, ref.text))
            continue
        for ident in ref.ids:
            if ident in seen:
                continue
            seen.add(ident)
            item = by_id.get(ident)
            elsewhere = tuple(listed.get(ident, ()))
            if item is None:
                rows.append(Row(MISSING, None, ident, ref.text, elsewhere))
            elif item.get("primary_domain") == domain.uuid:
                rows.append(Row(ALREADY, item, ident, ref.text, elsewhere))
            elif item.get("primary_domain") and model.get(item.get("primary_domain")) is not None:
                rows.append(Row(REPLACED, item, ident, ref.text, elsewhere))
            else:
                rows.append(Row(NEW, item, ident, ref.text, elsewhere))
    return rows


class ImportPrincipalDialog(QDialog):
    """The summary of the principal sections of a domain read from an Excel workbook, and «Importa»."""

    def __init__(self, project, domain, path, parent=None):
        super().__init__(parent)
        self.project, self.domain, self.path = project, domain, Path(path)
        self.changed = []
        self._entries = []  # (row, its item in the table)
        self.setWindowTitle("Importa clausole principali")
        self.sheets = read_domain_sheets(self.path)
        model = project.model
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Sezioni SRS principali di «{model.label(domain)}» da {self.path.name}",
                                objectName="cardTitle", wordWrap=True))
        row = QHBoxLayout()
        row.addWidget(QLabel("Foglio del dominio:"))
        self.sheet = QComboBox()
        for s in self.sheets:
            named = f"{s.ident} {s.name}".strip()
            self.sheet.addItem(named if s.sheet == s.ident else f"{named} (foglio {s.sheet})", s)
        found = sheet_of(self.sheets, domain)
        if found is not None:
            self.sheet.setCurrentIndex(self.sheets.index(found))
        self.sheet.currentIndexChanged.connect(lambda _i: self._show())
        row.addWidget(self.sheet, 1)
        layout.addLayout(row)
        self.warning = QLabel(objectName="muted", wordWrap=True)
        self.warning.setStyleSheet(f"color: {OVERLAP_COLOR};")
        layout.addWidget(self.warning)
        self.written = QLabel(objectName="muted", wordWrap=True)
        self.written.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.written)
        self.counts = QLabel(objectName="formLabel")
        layout.addWidget(self.counts)
        self.overlaps = QLabel(objectName="muted", wordWrap=True)
        self.overlaps.setStyleSheet(f"color: {OVERLAP_COLOR};")
        layout.addWidget(self.overlaps)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(COLUMNS)
        self.table.setAlternatingRowColors(True)
        header = self.table.header()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(TITLE, QHeaderView.Stretch)  # the free space
        for column, width in ((ALSO, 250), (OUTCOME, 250)):  # their full text in their tooltips
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.resizeSection(column, width)
        header.setStretchLastSection(False)
        self.table.itemChanged.connect(self._count)  # a tick taken off or put back
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        self.import_button = QPushButton(icon("mdi6.import", "white"), "Importa")
        self.import_button.setProperty("primary", True)
        buttons.addButton(self.import_button, QDialogButtonBox.AcceptRole)
        self.import_button.clicked.connect(self.import_sections)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(1100, 640)
        self._show()

    @property
    def rows(self):
        return [row for row, _entry in self._entries]

    def _also(self, row):
        """The other domains it is allocated to: principal in the model, listed in the workbook."""
        model = self.project.model
        owner = model.get(row.item.get("primary_domain")) if row.item is not None and \
            row.item.get("primary_domain") else None
        parts = []
        if owner is not None and owner.uuid != self.domain.uuid:
            parts.append(f"{model.label(owner)} (principale nel modello)")
        parts += [f"{d} (Excel)" for d in row.elsewhere if owner is None or owner.get("id") != d]
        return " · ".join(parts)

    def chosen(self):
        """The rows to import: those still ticked."""
        return [row for row, entry in self._entries if row.importable and entry.checkState(TICK) == Qt.Checked]

    def _show(self):
        model = self.project.model
        s = self.sheet.currentData()
        if not self.sheets:
            self.warning.setText("Il file non ha fogli con la riga «Sezioni SRS principali».")
        elif sheet_of(self.sheets, self.domain) is None:
            self.warning.setText(f"Nessun foglio è di «{model.label(self.domain)}» (per ID o nome): scegli quello da "
                                 "cui importare.")
        else:
            self.warning.setText(s.note if s is not None else "")
        self.warning.setVisible(bool(self.warning.text()))
        self.written.setText(f"Nel foglio: {s.principal or '(vuota)'}" if s is not None else "")
        others = [o for o in self.sheets if o is not s]
        rows = summary_rows(model, self.domain, s.principal, others) if s is not None else []
        self.table.blockSignals(True)
        self.table.clear()
        self._entries = []
        for row in rows:
            item = row.item
            text, color = OUTCOMES[row.outcome]
            owner = model.get(item.get("primary_domain")) if item is not None and item.get("primary_domain") else None
            entry = QTreeWidgetItem(["", row.ident, (item.get("title") or "") if item is not None else "",
                                     (item.get("item_type") or "") if item is not None else "",
                                     ", ".join(item.get("category") or []) if item is not None else "",
                                     row.written if row.written != row.ident else "", self._also(row),
                                     text.format(owner=model.label(owner) if owner is not None else "")])
            if row.importable:  # imported only with its tick (on at first)
                entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
                entry.setCheckState(TICK, Qt.Checked)
                entry.setToolTip(TICK, "Togli la spunta per non importarla")
            if row.overlapping:
                entry.setForeground(ALSO, QBrush(QColor(OVERLAP_COLOR)))
            entry.setForeground(OUTCOME, QBrush(QColor(color)))
            entry.setToolTip(OUTCOME, entry.text(OUTCOME))
            entry.setToolTip(ALSO, entry.text(ALSO))
            if item is not None:
                entry.setToolTip(TITLE, (item.get("text") or item.get("title") or "")[:600])
            self.table.addTopLevelItem(entry)
            self._entries.append((row, entry))
        self.table.blockSignals(False)
        self._count()

    def _count(self, *_args):
        rows = self.rows
        n = {k: sum(1 for r in rows if r.outcome == k) for k in OUTCOMES}
        overlapping = [r for r in rows if r.overlapping]
        chosen = self.chosen()
        self.counts.setText(f"{len(chosen)} da importare · {n[ALREADY]} già principali · {n[MISSING]} non trovate · "
                            f"{n[EXTERNAL]} altri documenti")
        ticked = sum(1 for r in overlapping if r in chosen)
        self.overlaps.setText(f"{len(overlapping)} voci sono allocate anche ad altri domini (colonna «Allocata anche "
                              f"a»), {ticked} con la spunta. Importata, una voce con un altro dominio principale passa "
                              "a questo dominio." if overlapping else "")
        self.overlaps.setVisible(bool(overlapping))
        self.import_button.setEnabled(bool(chosen))

    def import_sections(self):
        """The domain becomes the principal domain of the items chosen (one with another principal domain, ticked:
        it replaces it); its other principal and contributed items stay."""
        model = self.project.model
        principal = {e.uuid for e in principal_items(model, self.domain)} | {r.item.uuid for r in self.chosen()}
        contributing = {e.uuid for e in contributed_items(model, self.domain)}
        self.changed = self.project.trace_srs(self.domain, principal, contributing)
        self.accept()


def import_principal(project, domain, parent=None, path=None):
    """The workbook chosen by the user (path: given, without asking), then the summary. Returns the SRS items
    changed (empty if cancelled)."""
    if path is None:
        path, _ = QFileDialog.getOpenFileName(parent, "Importa clausole principali", str(project.path.parent),
                                              "Excel (*.xlsx *.xlsm)")
        if not path:
            return []
    try:
        dialog = ImportPrincipalDialog(project, domain, path, parent)
    except Exception as exc:  # not a workbook, locked by Excel…
        QMessageBox.warning(parent, "Importa clausole principali", f"Il file non si può leggere: {exc}")
        return []
    dialog.exec()
    return dialog.changed
