"""The deletion of a functional domain (from the tree, from a view, approving its ADR): the impact on the model shown
first, the elements that would be left orphan each with what to do with it (see model.domain_deletion), chosen by the
user before the domain is removed, and the identifiers the deletion renumbers."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from arcadia_tool.model.domain_deletion import (DELETE, KEEP, decided_adrs, deletable, orphans, renumbering,
                                                second_references, unresolved)
from arcadia_tool.model.element import natural_key
from arcadia_tool.ui.element_editor import card
from arcadia_tool.ui.theme import icon

UUID_ROLE = Qt.UserRole
CHOOSE = None  # an orphan not resolved yet
SHOWN = 15  # mentions listed by name, the others counted


def orphan_text(model, element):
    """An orphan as listed: an SRS item by its number and the start of its text, the others by their label."""
    if element.kind == "requirement":
        text = " ".join((element.get("text") or element.get("title") or "").split())
        return f"{element.get('id') or ''}  {text[:90]}{'…' if len(text) > 90 else ''}".strip()
    return model.label(element)


def _names(model, elements):
    names = ", ".join((e.get("id") or model.label(e)) for e in elements[:SHOWN])
    return names + (f" e altri {len(elements) - SHOWN}" if len(elements) > SHOWN else "")


class DomainDeletionDialog(QDialog):
    """The impact of the deletion: the orphans grouped by kind, each with a choice to make (also one for the whole
    group): to pass to another domain, to stay without one, or to be deleted (a function or a derived requirement
    nothing else uses); the mentions of second order, removed; the decided ADRs, kept as they are; the identifiers
    renumbered. «Elimina» only when every orphan has its choice. approving: from the ADR of the deletion. skip: uuids
    not to list (elements deleted together with the domain)."""

    def __init__(self, project, domain, parent=None, approving=True, skip=()):
        super().__init__(parent)
        self.project, self.domain, self.skip = project, domain, set(skip)
        model = project.model
        self.setWindowTitle("Approva ed elimina il dominio" if approving else "Elimina il dominio")
        self.resize(960, 700)
        self.others = sorted((d for d in model.of_kind("domain") if d.uuid != domain.uuid and d.uuid not in self.skip),
                             key=lambda d: natural_key(d.get("id") or d.get("name") or ""))
        header, header_layout = card()
        header_layout.addWidget(QLabel(f"Eliminare il dominio «{model.label(domain)}»?", objectName="elementTitle"))
        self.groups = orphans(model, domain.uuid, self.skip)
        count = sum(len(elements) for _group, elements in self.groups)
        hint = QLabel(
            ("Questi elementi fanno riferimento al dominio e non possono essere ricollocati in automatico: scegli per "
             "ognuno cosa farne, o per un intero gruppo dalla sua riga. «Elimina» è possibile solo per funzioni e "
             "requisiti derivati che nessun altro elemento usa." if count else
             "Nessun elemento del modello resta senza dominio.")
            + (" Il dominio viene poi eliminato dal modello e l'ADR risulta decisa." if approving else
               " Il dominio viene poi eliminato dal modello."), objectName="muted")
        hint.setWordWrap(True)
        header_layout.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Elemento", "Cosa farne"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tree.header().resizeSection(1, 320)
        self.tree.header().setStretchLastSection(False)
        self.combos = {}  # uuid of an orphan → its combo
        bold = QFont()
        bold.setBold(True)
        for group, elements in self.groups:
            top = QTreeWidgetItem(self.tree, [f"{group.title} ({len(elements)})"])
            top.setFont(0, bold)
            can_delete = [e for e in elements if deletable(model, e, domain.uuid)]
            all_combo = self._combo(group, bool(can_delete), "Per tutti: ")
            self.tree.setItemWidget(top, 1, all_combo)
            children = []
            for element in elements:
                item = QTreeWidgetItem(top, [orphan_text(model, element)])
                item.setData(0, UUID_ROLE, element.uuid)
                item.setToolTip(0, model.label(element))
                combo = self._combo(group, element in can_delete)
                combo.currentIndexChanged.connect(self._update)
                self.tree.setItemWidget(item, 1, combo)
                self.combos[element.uuid] = combo
                children.append(combo)
            all_combo.activated.connect(lambda _i, source=all_combo, targets=children: self._apply_all(source,
                                                                                                    targets))
            top.setExpanded(True)
        mentions = []
        second = [e for e in second_references(model, domain.uuid) if e.uuid not in self.skip]
        if second:
            mentions.append("Il dominio viene tolto dove è solo citato (come contributore, come escluso, tra i domini "
                            f"di un team): {_names(model, second)}.")
        decided = [e for e in decided_adrs(model, domain.uuid) if e.uuid not in self.skip]
        if decided:
            mentions.append(f"Le ADR già decise che lo citano restano come sono, a memoria della decisione: "
                            f"{_names(model, decided)}.")
        self.mentions = QLabel(" ".join(mentions), objectName="muted")
        self.mentions.setWordWrap(True)
        self.mentions.setVisible(bool(mentions))
        self.numbers = QPlainTextEdit(readOnly=True, objectName="renumbering")
        self.numbers.setMaximumHeight(150)
        self.numbers_title = QLabel("NUMERAZIONE DOPO L'ELIMINAZIONE", objectName="sectionCaption")
        self.pending = QLabel(objectName="muted")
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(icon("mdi6.delete-outline", "white"), "Elimina il dominio")
        self.ok.setProperty("primary", True)
        self.ok.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.pending, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.mentions)
        layout.addWidget(self.numbers_title)
        layout.addWidget(self.numbers)
        layout.addLayout(buttons)
        self.tree.setVisible(bool(self.groups))
        self._update()

    def _combo(self, group, can_delete, prefix=""):
        model = self.project.model
        combo = QComboBox()
        combo.addItem(f"{prefix}scegli…" if prefix else "Scegli…", CHOOSE)
        for d in self.others:
            combo.addItem(f"{prefix}Passa a {model.label(d)}", d.uuid)
        combo.addItem(f"{prefix}{group.keep}", KEEP)
        if can_delete:
            combo.addItem(f"{prefix}Elimina", DELETE)
        return combo

    def _apply_all(self, source, targets):
        """The choice of a group to each of its elements (a deletion only to those that can be deleted)."""
        value = source.currentData()
        if value is CHOOSE:
            return
        for combo in targets:
            index = combo.findData(value)
            combo.blockSignals(True)  # the renumbering computed once, below
            combo.setCurrentIndex(index if index >= 0 else combo.findData(KEEP))
            combo.blockSignals(False)
        self._update()

    @property
    def choices(self):
        """{uuid of an orphan: KEEP, DELETE, the uuid of the domain it passes to, or None (not chosen yet)}."""
        return {uuid: combo.currentData() for uuid, combo in self.combos.items()}

    def _update(self):
        """«Elimina» once every orphan has its choice; the renumbering as it would be with them."""
        left = len(unresolved(self.choices))
        self.ok.setEnabled(not left)
        self.pending.setText(f"Da risolvere: {left} {'elemento' if left == 1 else 'elementi'}" if left else "")
        from arcadia_tool.ui.realigned import realigned_lines

        changes = renumbering(self.project.model, self.domain, self.choices, self.skip)
        self.numbers.setPlainText(realigned_lines(changes) if changes else
                                  "Nessun identificativo cambia: il dominio è l'ultimo della numerazione.")
