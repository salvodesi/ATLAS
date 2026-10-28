"""Nuova ADR: the type of decision, chosen first; it gives the template of the sheet (its own fields), shown here
before the ADR is created."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from arcadia_tool.model.adr import common_fields, type_fields
from arcadia_tool.model.schema import ADR_AREAS, ADR_TYPES, DOMAIN_ADR_TYPES, MULTIENUM, REF, REFS, TABLE
from arcadia_tool.ui.theme import MUTED, icon

TYPE_ICONS = {True: "mdi6.shape-outline", False: "mdi6.file-document-edit-outline"}


def field_hint(f):
    if f.computed:
        return "calcolato dal tool"
    if f.type == TABLE:
        return f"tabella: {', '.join(c.label for c in f.columns)}"
    if f.type in (REF, REFS):
        return "scelta tra gli elementi del modello"
    if f.type == MULTIENUM:
        return "spunte"
    return ""


class AdrTypeDialog(QDialog):
    """adr_type: the type chosen, on OK."""

    def __init__(self, parent=None, preselect=None):
        super().__init__(parent)
        self.adr_type = None
        self.setWindowTitle("Nuova decisione architetturale (ADR)")
        self.resize(1040, 620)
        intro = QLabel("Scegli il tipo di decisione: la scheda dell'ADR avrà i campi propri di quel tipo, oltre a "
                       "quelli comuni a tutte le ADR.", objectName="muted")
        intro.setWordWrap(True)
        self.types = QListWidget()
        self.types.setWordWrap(True)
        self.types.setSpacing(2)
        when_of = dict(ADR_TYPES)
        for area, types in ADR_AREAS:  # the types grouped by where they apply (SA, LA, generali)
            header = QListWidgetItem(area.upper())
            header.setFlags(Qt.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setForeground(QColor(MUTED))
            self.types.addItem(header)
            for name in types:
                item = QListWidgetItem(icon(TYPE_ICONS[name in DOMAIN_ADR_TYPES]), f"{name}\n{when_of[name]}")
                item.setData(Qt.UserRole, name)
                item.setToolTip(when_of[name])
                self.types.addItem(item)
        self.types.currentItemChanged.connect(lambda item, _old: self._preview(item))
        self.types.itemDoubleClicked.connect(lambda _item: self._accept())
        self.preview = QLabel(alignment=Qt.AlignTop | Qt.AlignLeft)
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.RichText)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("CAMPI DEL MODELLO", objectName="sectionCaption"))
        right_layout.addWidget(self.preview, 1)
        splitter = QSplitter()
        splitter.addWidget(self.types)
        splitter.addWidget(right)
        splitter.setSizes([560, 460])
        self.create_button = QPushButton(icon("mdi6.plus", "white"), "Crea ADR")
        self.create_button.setProperty("primary", True)
        self.create_button.clicked.connect(self._accept)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        # The type suggested by the element selected, else the first one; the list shown from its first type.
        rows = {self.types.item(r).data(Qt.UserRole): r for r in range(self.types.count())
                if self.types.item(r).data(Qt.UserRole)}
        self.types.setCurrentRow(rows.get(preselect, min(rows.values())))

    def type_rows(self):
        """The rows of the types (the others are the headers of the areas)."""
        return [r for r in range(self.types.count()) if self.types.item(r).data(Qt.UserRole)]

    def showEvent(self, event):
        super().showEvent(event)
        self.types.scrollToTop()

    def _preview(self, item):
        if item is None or not item.data(Qt.UserRole):
            self.preview.setText("")
            return
        name = item.data(Qt.UserRole)
        own = [f for f in type_fields(name) if not f.by_tool]  # those the tool writes: not to fill
        rows = "".join(f"<li><b>{f.label}</b>" + (f" <span style='color:{MUTED}'>· {field_hint(f)}</span>"
                                                    if field_hint(f) else "") + "</li>" for f in own)
        own_html = (f"<p><b>Dettagli: {name}</b></p><ul>{rows}</ul>" if own else
                    f"<p><b>Dettagli: {name}</b></p><p style='color:{MUTED}'>Nessun campo proprio: solo i campi "
                    "comuni.</p>")
        shared = common_fields(name)
        common = ("<ul>" + "".join(f"<li>{f.label}" + (f" <span style='color:{MUTED}'>· {field_hint(f)}</span>"
                                                        if field_hint(f) else "") + "</li>" for f in shared) + "</ul>"
                  if shared else f"<p style='color:{MUTED}'>Solo l'identificazione (ID, titolo, stato, "
                                 "proponente; la data della decisione la mette il tool).</p>")
        self.preview.setText(f"{own_html}<p><b>Campi comuni</b></p>{common}")

    def _accept(self):
        item = self.types.currentItem()
        if item is not None and item.data(Qt.UserRole):
            self.adr_type = item.data(Qt.UserRole)
            self.accept()
