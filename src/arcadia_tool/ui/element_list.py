"""A tab with the elements of a kind as a table (SA-1, the functional domains; X-1, the architectural decisions;
X-2, the requests for clarification): their main fields, a button to open each of them (and one to delete it), and
one to create a new one. The status of a domain is changed on its row. Opened with a double click on the kind in
the model tree."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit,
                               QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from arcadia_tool.model.element import natural_key
from arcadia_tool.model.schema import ADR_AREAS, KINDS_BY_NAME, adr_area, derived_value
from arcadia_tool.ui.theme import BORDER, icon, kind_icon, status_colors

UUID_ROLE = Qt.UserRole
# The kinds shown as a table: their columns (fields of the schema); the first wide one takes the free space.
LIST_COLUMNS = {
    "domain": ("id", "name", "team", "referent", "status"),
    "clarification": ("id", "recipient", "status"),
    "adr": ("id", "title", "adr_area", "adr_type", "decision_date", "status"),
}
WIDE = ("recipient", "title", "name")
STATUS_ON_ROW = ("domain",)  # the status chosen on the row, from a drop-down list
NOT_DELETED_HERE = ("domain",)  # only «Apri»: a domain is deleted from its sheet, the tree or the views
# How an element is called: one, many, the button to create one, the empty list, the search.
NAMES = {
    "domain": ("dominio", "domini", "Nuovo dominio", "Nessun dominio funzionale",
               "Cerca per ID, nome, team, responsabile o stato", "Nuovo dominio funzionale"),
    "clarification": ("richiesta", "richieste", "Nuova richiesta", "Nessuna richiesta di chiarimento",
                      "Cerca per ID, destinatario o stato", "Nuova richiesta di chiarimento"),
    "adr": ("ADR", "ADR", "Nuova ADR", "Nessuna decisione architetturale",
            "Cerca per ID, titolo, tipo, data o stato", "Nuova decisione architetturale (ADR)"),
}
COLUMN_LABELS = {"id": "ID", "recipient": "Destinatario della richiesta", "adr_type": "Tipo",
                 "adr_area": "Ambito", "name": "Nome del dominio", "referent": "Responsabile"}
TOOLTIP_FIELDS = {"clarification": "problem", "adr": "context", "domain": "mission"}


class ElementListPage(QWidget):
    open_requested = Signal(str)  # uuid of the element to open in its sheet
    create_requested = Signal(str)  # kind of the element to create
    delete_requested = Signal(str)  # uuid of the element to delete (after a confirmation)
    status_changed = Signal(str, str)  # uuid, the status chosen on its row (a domain)
    edit_denied = None  # (kind, field) → why the user may not change it, or None

    def __init__(self, project, kind, parent=None):
        super().__init__(parent)
        self.project, self.kind = project, kind
        self.schema = KINDS_BY_NAME[kind]
        self.columns = LIST_COLUMNS[kind]
        self.one, self.many, new_label, empty_label, search_label, first_label = NAMES[kind]
        self.wide = next((c for c in self.columns if c in WIDE), self.columns[-1])

        header = QFrame(objectName="card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        title = f"{self.schema.template} · {self.schema.plural}" if self.schema.template else self.schema.plural
        self.new_button = QPushButton(icon("mdi6.plus", "white"), new_label)
        self.new_button.setProperty("primary", True)
        self.new_button.setToolTip(f"{first_label}: l'ID è assegnato in automatico e se ne apre la scheda")
        self.new_button.clicked.connect(lambda: self.create_requested.emit(self.kind))
        top = QHBoxLayout()
        top.addWidget(QLabel(title, objectName="elementTitle"), 1)
        if kind == "adr":
            self.export_button = QPushButton(icon("mdi6.microsoft-excel"), "Esporta ADR aperte…")
            self.export_button.setToolTip("Salva in un file Excel le ADR non ancora decise: ID, descrizione, team "
                                          "proponente e stato")
            self.export_button.clicked.connect(self.export_open)
            top.addWidget(self.export_button)
        top.addWidget(self.new_button)
        header_layout.addLayout(top)
        self.search = QLineEdit(placeholderText=search_label, objectName="search")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.count = QLabel(objectName="muted")
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addSpacing(12)
        row.addWidget(self.count)
        header_layout.addLayout(row)

        self.table = QTableWidget(0, len(self.columns) + 1)
        labels = [self._header(c) for c in self.columns] + [""]
        self.table.setHorizontalHeaderLabels(labels)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setStyleSheet(f"QTableWidget {{ background: white; border: 1px solid {BORDER}; "
                                 "border-radius: 6px; }}")
        columns = self.table.horizontalHeader()
        for c, name in enumerate(self.columns):
            if name == self.wide:  # the free space
                columns.setSectionResizeMode(c, QHeaderView.Stretch)
            elif name == "status" and kind in STATUS_ON_ROW:  # its drop-down list
                columns.setSectionResizeMode(c, QHeaderView.Interactive)
                columns.resizeSection(c, 170)
            elif name in ("id", "status"):
                columns.setSectionResizeMode(c, QHeaderView.ResizeToContents)
            else:  # another text (the decider of an ADR): a width of its own, changeable by dragging
                columns.setSectionResizeMode(c, QHeaderView.Interactive)
                columns.resizeSection(c, 170 if kind == "domain" else 220)  # a domain: room for its name
        columns.setSectionResizeMode(len(self.columns), QHeaderView.Fixed)
        columns.setMinimumSectionSize(90)
        self.table.cellDoubleClicked.connect(self._double_clicked)

        # Without elements: a message in the middle of the page and the button to create the first one.
        self.empty = QFrame(objectName="card")
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        picture = QLabel(alignment=Qt.AlignCenter)
        picture.setPixmap(kind_icon(kind).pixmap(48, 48))
        empty_layout.addWidget(picture)
        self.empty_text = QLabel(empty_label, alignment=Qt.AlignCenter, objectName="cardTitle")
        empty_layout.addWidget(self.empty_text)
        shown = ", ".join(self._header(c).lower() if c != "id" else "ID" for c in self.columns)
        hint = QLabel(f"Le {self.many} create compaiono qui, con {shown}.", alignment=Qt.AlignCenter,
                      objectName="muted")
        empty_layout.addWidget(hint)
        first = QPushButton(icon("mdi6.plus", "white"), first_label)
        first.setProperty("primary", True)
        first.clicked.connect(lambda: self.create_requested.emit(self.kind))
        empty_layout.addSpacing(8)
        empty_layout.addWidget(first, 0, Qt.AlignHCenter)
        empty_layout.addStretch()

        self.body = QStackedWidget()
        self.body.addWidget(self.table)
        self.body.addWidget(self.empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(self.body, 1)
        self.reload()

    def _header(self, column):
        return COLUMN_LABELS.get(column) or self.schema.field(column).label

    def _text(self, element, column):
        """What a cell shows: the label of a referenced element (the team recipient of a request), else the
        value; a recipient written as text by earlier versions."""
        model = self.project.model
        if column == "adr_area":  # where the type of the ADR applies (SA, LA, generali)
            return adr_area(element.get("adr_type"))
        field = self.schema.field(column)
        value = derived_value(model, element, field) if field is not None and field.derived_from else             element.get(column)  # the referent of a domain: from its team
        if field is not None and field.type == "ref":
            target = model.get(value) if value else None
            if target is not None:
                return model.label(target)
            return element.get(f"{column}_text") or ""
        return value if isinstance(value, str) else ", ".join(map(str, value or []))

    def _actions(self, element):
        """«Apri» and «Elimina» of a row."""
        label = self.project.model.label(element)
        open_button = QPushButton(icon("mdi6.open-in-app"), "Apri")
        open_button.setToolTip(f"Apri la scheda di {label}")
        open_button.clicked.connect(lambda _=False, u=element.uuid: self.open_requested.emit(u))
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)
        row.addWidget(open_button)
        if self.kind not in NOT_DELETED_HERE:
            delete = QPushButton(icon("mdi6.trash-can-outline"), "Elimina")  # the same style as «Apri»
            delete.setToolTip(f"Elimina {label}")
            delete.clicked.connect(lambda _=False, u=element.uuid: self.delete_requested.emit(u))
            row.addWidget(delete)
        return cell

    def _status_choice(self, element):
        """The status of the row, chosen from the states of the kind; its text in the colour of the status."""
        choice = QComboBox()
        choice.addItem("")
        states = list(self.schema.field("status").options)
        if element.get("status") and element.get("status") not in states:  # e.g. written by an earlier version
            states.append(element.get("status"))
        for i, state in enumerate(states, 1):
            choice.addItem(state)
            choice.setItemData(i, QColor(status_colors(state)[0]), Qt.ForegroundRole)
        choice.setCurrentText(element.get("status") or "")
        self._color_choice(choice)
        reason = self.edit_denied(self.kind, "status") if self.edit_denied else None
        choice.setEnabled(not reason)
        choice.setToolTip(reason or f"Stato di {self.project.model.label(element)}")
        choice.currentTextChanged.connect(lambda text, c=choice: self._color_choice(c))
        choice.currentTextChanged.connect(lambda text, u=element.uuid: self.status_changed.emit(u, text))
        return choice

    @staticmethod
    def _color_choice(choice):
        color = status_colors(choice.currentText())[0] if choice.currentText() else "#6B7280"
        choice.setStyleSheet(f"QComboBox {{ color: {color}; font-weight: 600; }}")

    def reload(self):
        """The elements of the kind, from the model (after a change, a creation or a deletion)."""
        model = self.project.model
        elements = sorted(model.of_kind(self.kind), key=lambda e: natural_key(e.get("id") or ""))
        if self.kind == "adr":  # grouped by area, in the order of the method (the ADR without a type last)
            areas = [area for area, _ in ADR_AREAS]
            elements.sort(key=lambda e: areas.index(adr_area(e.get("adr_type")))
                          if adr_area(e.get("adr_type")) else len(areas))
        self.table.setRowCount(0)
        actions_width = 0
        for e in elements:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, name in enumerate(self.columns):
                value = self._text(e, name)
                cell = QTableWidgetItem(value)
                cell.setData(UUID_ROLE, e.uuid)
                if name == "id":
                    cell.setIcon(kind_icon(self.kind))
                if name == "status" and self.kind in STATUS_ON_ROW:
                    self.table.setCellWidget(r, c, self._status_choice(e))  # the text under it: for the search
                elif name == "status" and value:
                    fg, bg = status_colors(value)
                    cell.setForeground(QBrush(QColor(fg)))
                    cell.setBackground(QBrush(QColor(bg)))
                tip = model.label(e)
                detail = e.get(TOOLTIP_FIELDS.get(self.kind, ""))
                if detail:
                    tip += "\n\n" + detail[:600]
                cell.setToolTip(tip)
                self.table.setItem(r, c, cell)
            actions = self._actions(e)
            actions_width = max(actions_width, actions.sizeHint().width())
            self.table.setCellWidget(r, len(self.columns), actions)
        # As wide as its buttons: their texts are never cut.
        self.table.horizontalHeader().resizeSection(len(self.columns), max(actions_width + 8, 120))
        self.body.setCurrentWidget(self.table if elements else self.empty)
        self.search.setVisible(bool(elements))  # nothing to search in an empty list
        self._filter(self.search.text())

    def _filter(self, text):
        words = text.lower().split()
        shown = 0
        for r in range(self.table.rowCount()):
            haystack = " ".join(self.table.item(r, c).text() for c in range(len(self.columns))).lower()
            hidden = bool(words) and not all(w in haystack for w in words)
            self.table.setRowHidden(r, hidden)
            shown += not hidden
        total = self.table.rowCount()
        self.count.setText(f"{shown} di {total}" if words else f"1 {self.one}" if total == 1 else f"{total} {self.many}")

    def export_open(self, path=None):
        """The open ADR in an Excel file, chosen by the user (path: given, without asking)."""
        from datetime import date

        from arcadia_tool.storage.adr_register import write_open_adrs

        if path is None:
            suggested = str(self.project.path.parent / f"ADR_aperte_{date.today():%Y-%m-%d}.xlsx")
            path, _ = QFileDialog.getSaveFileName(self, "Esporta le ADR aperte", suggested, "Excel (*.xlsx)")
            if not path:
                return None
        try:
            count = write_open_adrs(self.project.model, path, self.project.name)
        except OSError as exc:
            QMessageBox.critical(self, "Esporta le ADR aperte", f"Il file non è stato salvato: {exc}")
            return None
        QMessageBox.information(self, "Esporta le ADR aperte",
                                f"{'Nessuna ADR aperta' if not count else f'{count} ADR aperte'} salvate in:\n{path}")
        return count

    def _double_clicked(self, row, _column):
        item = self.table.item(row, 0)
        if item is not None:
            self.open_requested.emit(item.data(UUID_ROLE))
