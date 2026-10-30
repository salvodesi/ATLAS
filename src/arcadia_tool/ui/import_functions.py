"""«Importa funzioni…» of SA-2 (the model tree, a system function sheet): the catalogue of the system functions
hypothesised by the teams (one worksheet per domain), shown as the changes it makes to the model before they are
applied. Each function goes to the domain of its worksheet, with an ID given by ATLAS (those of the workbook are not
kept), and is allocated to the clauses of its row; the functions without clauses are imported too. A list item
written after a clause («3.5.3.4 b) f)») is traced with its clause.

The same workbook imported again: a function with the same name already in the domain is not overwritten, only its
clauses are aligned with its row (those no longer there removed, the new ones allocated); the functions of a domain
of the workbook that are no longer in it are deleted (those created in ATLAS, never imported, only if ticked)."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from arcadia_tool.model.srs_sections import parse_clauses, resolve
from arcadia_tool.storage.function_sheets import read_function_sheets
from arcadia_tool.ui.srs_reader import document_order
from arcadia_tool.ui.srs_trace import TRACEABLE
from arcadia_tool.ui.theme import MUTED, icon

NEW, UPDATED, PRESENT, DELETED, NO_DOMAIN = "new", "updated", "present", "deleted", "no_domain"
GREEN, AMBER, RED, BLUE = "#166534", "#92400E", "#B42318", "#1F3A5F"
FOUND, SUB_ITEM, MISSING, EXTERNAL, REMOVED = "found", "sub_item", "missing", "external", "removed"
CLAUSE_OUTCOMES = {
    FOUND: ("Trovata", GREEN),
    SUB_ITEM: ("Sottovoce: tracciata con la clausola {clause}", BLUE),
    MISSING: ("Non trovata tra le voci SRS del progetto", RED),
    EXTERNAL: ("Non è una voce SRS", MUTED),
    REMOVED: ("Non più nel file: si toglie l'allocazione", RED),
}
COLUMNS = ("Applica", "Funzione / clausola", "Clausole", "Stato nel foglio", "Note", "Cosa cambia nel modello")
TICK, NAME, CLAUSES, ORIGIN, NOTES, OUTCOME = range(len(COLUMNS))
STATES = {"propost": "Proposta", "rivist": "Rivista", "approvat": "Approvata"}


def _same(name):
    return " ".join((name or "").split()).lower()


def _clauses(n):
    return f"{n} clausola" if n == 1 else f"{n} clausole"


class PlannedFunction:
    """A function of the workbook, or one of the model no longer in it: what the import does with it."""

    def __init__(self, source, domain, existing, clauses, sheet=None):
        self.source, self.domain, self.existing = source, domain, existing
        self.sheet = source.sheet if source is not None else sheet
        self.clauses = clauses  # [(outcome, written, the SRS item traced or None)]
        self.traced = list({item.uuid: item for _o, _w, item in clauses if item is not None}.values())
        self.added, self.removed = set(), []  # an existing function: the clauses allocated / no longer allocated
        if domain is None:
            self.outcome = NO_DOMAIN
        elif source is None:
            self.outcome = DELETED
        elif existing is None:
            self.outcome = NEW
        else:
            allocated = list(existing.get("sections") or [])
            wanted = {item.uuid for item in self.traced}
            self.added = wanted - set(allocated)
            self.removed = [u for u in allocated if u not in wanted]
            self.outcome = UPDATED if self.added or self.removed else PRESENT

    @property
    def applicable(self):
        return self.outcome in (NEW, UPDATED, DELETED)

    @property
    def ticked(self):
        """At first: all the changes, except deleting a function created in ATLAS (never imported)."""
        return self.applicable and (self.outcome != DELETED or bool(self.existing.get("catalogue_id")))

    @property
    def sections(self):
        """The clauses of the function after the import: those kept in their order, then the new ones."""
        kept = [u for u in (self.existing.get("sections") or []) if u not in self.removed] if self.existing else []
        return kept + [item.uuid for item in self.traced if item.uuid not in kept]

    def describe(self):
        """(what changes in the model, its colour)."""
        if self.outcome == NO_DOMAIN:
            return f"Dominio {self.sheet} non presente nel modello: non si importa", RED
        if self.outcome == NEW:
            return f"Nuova funzione, allocata a {_clauses(len(self.traced))}", GREEN
        if self.outcome == DELETED:
            if self.existing.get("catalogue_id"):
                return "Non più nel file: si elimina dal modello", RED
            return "Creata in ATLAS, non è nel file: si elimina solo con la spunta", AMBER
        if self.outcome == PRESENT:
            return "Già nel modello, con le stesse clausole: nessuna modifica", MUTED
        changes = [f"si allocano {_clauses(len(self.added))}" if self.added else "",
                   f"si tolgono {_clauses(len(self.removed))}" if self.removed else ""]
        return "Già nel modello: " + ", ".join(c for c in changes if c), AMBER


def plan(model, functions, sheets=()):
    """What the import of the functions of the workbook does: their domain, the clauses they trace; the functions of
    the domains of the workbook (sheets: also those without functions) that are no longer in it."""
    ordered = document_order(model)
    ids = [e.get("id") for e in ordered if e.get("id")]
    by_id = {e.get("id"): e for e in ordered if e.get("id")}
    domains = {(d.get("id") or "").upper(): d for d in model.of_kind("domain")}
    planned, matched = [], set()
    for f in functions:
        domain = domains.get(f.sheet)
        existing = None
        if domain is not None:
            existing = next((sf for sf in model.of_kind("system_function") if sf.get("domain") == domain.uuid and
                             sf.uuid not in matched and _same(sf.get("name")) == _same(f.name)), None)
        if existing is not None:
            matched.add(existing.uuid)
        clauses = []
        for ref in resolve(parse_clauses(f.clauses), ids):
            if ref.external:
                clauses.append((EXTERNAL, ref.text, None))
                continue
            for ident in ref.ids:
                item = by_id.get(ident)
                # A list item, a bullet, a figure: traced with the clause containing it.
                while item is not None and item.get("item_type") not in TRACEABLE:
                    item = model.get(item.get("parent")) if item.get("parent") else None
                if item is None:
                    clauses.append((MISSING, ref.text if not ref.is_range else ident, None))
                else:
                    sub = bool(ref.sub_items) or item.get("id") != ident
                    clauses.append((SUB_ITEM if sub else FOUND, ref.text if not ref.is_range else ident, item))
        planned.append(PlannedFunction(f, domain, existing, clauses))
    for sheet in dict.fromkeys([*(f.sheet for f in functions), *sheets]):
        domain = domains.get(sheet)
        if domain is None:
            continue
        for sf in model.of_kind("system_function"):
            if sf.get("domain") == domain.uuid and sf.uuid not in matched:
                planned.append(PlannedFunction(None, domain, sf, [], sheet))
    return planned


class ImportFunctionsDialog(QDialog):
    """What the import changes in the model, by domain: each function with a tick («Applica», on at first) and its
    clauses."""

    def __init__(self, project, path, parent=None):
        super().__init__(parent)
        self.project, self.path = project, Path(path)
        self.created, self.changed, self.deleted = [], [], []
        self.setWindowTitle("Importa funzioni di sistema da Excel SA-2")
        sheets = []
        self.planned = plan(project.model, read_function_sheets(self.path, sheets), sheets)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Funzioni di sistema da {self.path.name}", objectName="cardTitle"))
        layout.addWidget(QLabel(
            "Ogni funzione va nel dominio del suo foglio, con l'ID dato da ATLAS (quelli del file non si usano), ed è "
            "allocata alle clausole della sua riga; si importano anche le funzioni senza clausole. Una sottovoce "
            "(«3.5.3.4 b) f)») è tracciata con la sua clausola. Una funzione già nel dominio con lo stesso nome non "
            "si sovrascrive: si allineano solo le sue clausole a quelle del file. Le funzioni dei domini del file che "
            "nel file non ci sono più si eliminano. Togli la spunta a ciò che non vuoi applicare; la freccia a "
            "sinistra mostra le clausole di ogni funzione e gli elementi impattati da un'eliminazione.",
            objectName="muted", wordWrap=True))
        self.counts = QLabel(objectName="formLabel", wordWrap=True)
        layout.addWidget(self.counts)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setExpandsOnDoubleClick(False)
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(TICK, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(CLAUSES, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        for column, width in ((ORIGIN, 150), (NOTES, 170), (OUTCOME, 330)):
            header.resizeSection(column, width)
        self._fill()
        self.tree.itemChanged.connect(self._count)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        self.import_button = QPushButton(icon("mdi6.import", "white"), "Importa")
        self.import_button.setProperty("primary", True)
        buttons.addButton(self.import_button, QDialogButtonBox.AcceptRole)
        self.import_button.clicked.connect(self.import_functions)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(1200, 700)
        self._count()

    def _child(self, row, name, outcome, color, tip=""):
        child = QTreeWidgetItem(["", name, "", "", "", outcome])
        child.setForeground(OUTCOME, QBrush(QColor(color)))
        child.setToolTip(OUTCOME, outcome)
        child.setFlags(child.flags() & ~Qt.ItemIsUserCheckable)
        if tip:
            child.setToolTip(NAME, tip[:600])
        row.addChild(child)
        return child

    def _fill(self):
        from arcadia_tool.ui.diagrams import deletion_impacts

        model = self.project.model
        self.entries = []  # (planned function, its row)
        groups = {}
        for p in self.planned:
            node = groups.get(p.sheet)
            if node is None:
                label = model.label(p.domain) if p.domain is not None else p.sheet
                node = QTreeWidgetItem(["", label])
                node.setFlags(node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                font = node.font(NAME)
                font.setBold(True)
                node.setFont(NAME, font)
                self.tree.addTopLevelItem(node)
                groups[p.sheet] = node
            text, color = p.describe()
            if p.source is not None:
                found = sum(1 for o, _w, _i in p.clauses if o in (FOUND, SUB_ITEM))
                row = QTreeWidgetItem(["", p.source.name, f"{found}/{len(p.clauses)}" if p.clauses else "—",
                                       p.source.origin, " · ".join(p.source.notes), text])
                row.setToolTip(NAME, f"{p.source.ident} nel file (riga {p.source.row})" +
                               (f" · nel modello: {p.existing.get('id')}" if p.existing is not None else ""))
            else:
                row = QTreeWidgetItem(["", model.label(p.existing), "", "", "", text])
                font = row.font(NAME)
                font.setStrikeOut(True)
                row.setFont(NAME, font)
            row.setToolTip(NOTES, row.text(NOTES))
            row.setForeground(OUTCOME, QBrush(QColor(color)))
            row.setToolTip(OUTCOME, text)
            if p.applicable:
                row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
                row.setCheckState(TICK, Qt.Checked if p.ticked else Qt.Unchecked)
            else:
                row.setFlags(row.flags() & ~Qt.ItemIsUserCheckable)
            node.addChild(row)
            allocated = set(p.existing.get("sections") or []) if p.existing is not None else set()
            for outcome, written, item in p.clauses:
                ctext, ccolor = CLAUSE_OUTCOMES[outcome]
                ctext = ctext.format(clause=item.get("id") if item is not None else "")
                if p.outcome == UPDATED and item is not None:
                    ctext += " · già allocata" if item.uuid in allocated else " · si alloca"
                self._child(row, written, ctext, ccolor,
                            (item.get("text") or item.get("title") or "") if item is not None else "")
            for uuid in p.removed:
                item = model.get(uuid)
                text_, color_ = CLAUSE_OUTCOMES[REMOVED]
                self._child(row, item.get("id") if item is not None else uuid, text_, color_,
                            (item.get("text") or item.get("title") or "") if item is not None else "")
            if p.outcome == DELETED:
                references, views = deletion_impacts(model, [p.existing.uuid])
                for e in references:
                    self._child(row, model.label(e), "Riferimento che resterà senza destinazione", AMBER)
                for v in views:
                    self._child(row, v.get("name") or "(vista senza nome)", "Vista da cui sparirà", AMBER)
            self.entries.append((p, row))
        for node in groups.values():
            if not any(p.applicable for p, row in self.entries if row.parent() is node):
                node.setFlags(node.flags() & ~Qt.ItemIsUserCheckable)
            node.setExpanded(True)

    def chosen(self):
        return [p for p, row in self.entries if p.applicable and row.checkState(TICK) == Qt.Checked]

    def _count(self, *_args):
        chosen = self.chosen()
        new = [p for p in chosen if p.outcome == NEW]
        updated = [p for p in chosen if p.outcome == UPDATED]
        deleted = [p for p in chosen if p.outcome == DELETED]
        added = sum(len(p.traced) for p in new) + sum(len(p.added) for p in updated)
        removed = sum(len(p.removed) for p in updated)
        same = sum(1 for p in self.planned if p.outcome == PRESENT)
        missing = sum(1 for p in self.planned for o, _w, _i in p.clauses if o == MISSING)
        no_domain = sorted({p.sheet for p in self.planned if p.outcome == NO_DOMAIN})
        in_file = sum(1 for p in self.planned if p.source is not None)
        text = f"{in_file} funzioni nel file · cosa cambia nel modello: {len(new)} nuove, {len(updated)} " \
               f"aggiornate, {len(deleted)} eliminate · allocazioni: +{added} −{removed} · {same} senza modifiche"
        if missing:
            text += f" · clausole non trovate: {missing}"
        if no_domain:
            text += f" · domini non presenti nel modello: {', '.join(no_domain)}"
        self.counts.setText(text)
        self.import_button.setEnabled(bool(chosen))

    def import_functions(self):
        """The changes chosen: the new functions created in their domain, the clauses of the others aligned with
        the workbook, those no longer in it deleted."""
        project = self.project
        for p in self.chosen():
            if p.outcome == NEW:
                values = {"name": p.source.name, "domain": p.domain.uuid, "sections": p.sections,
                          "catalogue_id": p.source.ident}
                if p.source.origin.lower() == "nuova":
                    values["is_new"] = True
                notes = ([f"Stato nel catalogo SA-2: {p.source.origin}."] if p.source.origin and
                         p.source.origin.lower() != "nuova" else []) + p.source.notes
                if notes:
                    values["notes"] = "\n\n".join(notes)
                status = next((s for k, s in STATES.items() if p.source.status.lower().startswith(k)), None)
                if status:
                    values["status"] = status
                self.created.append(project.new_element("system_function", **values))
            elif p.outcome == UPDATED:
                previous = p.existing.copy()
                p.existing.set("sections", p.sections)
                if not p.existing.get("catalogue_id"):
                    p.existing.set("catalogue_id", p.source.ident)
                self.changed += [p.existing, *(project.update(p.existing, previous) or [])]
        gone = [p.existing for p in self.chosen() if p.outcome == DELETED]
        if gone:
            self.deleted = [e.copy() for e in gone]
            project.delete_elements([e.uuid for e in gone])
        self.accept()


def import_functions(project, parent=None, path=None):
    """The workbook chosen by the user (path: given, without asking), then what changes. Returns (created, changed,
    deleted); all empty if cancelled."""
    if path is None:
        path, _ = QFileDialog.getOpenFileName(parent, "Importa funzioni di sistema da Excel SA-2",
                                              str(project.path.parent), "Excel (*.xlsx *.xlsm)")
        if not path:
            return [], [], []
    try:
        dialog = ImportFunctionsDialog(project, path, parent)
    except Exception as exc:  # not a workbook, locked by Excel…
        QMessageBox.warning(parent, "Importa funzioni di sistema", f"Il file non si può leggere: {exc}")
        return [], [], []
    if not dialog.planned:
        QMessageBox.information(parent, "Importa funzioni di sistema",
                                "Nel file non ci sono fogli di dominio (DF01…) con funzioni di sistema.")
        return [], [], []
    dialog.exec()
    return dialog.created, dialog.changed, dialog.deleted


def summary(created, changed, deleted):
    """What the import changed, for the message shown after it."""
    updated = len({e.uuid for e in changed if e.kind == "system_function"})
    return f"Funzioni create: {len(created)} · aggiornate nelle clausole: {updated} · eliminate: {len(deleted)}"
