"""Actions on a row of the SRS catalogue (Voci SRS), without opening other sheets:

- a section (three numbers): its principal domain and the contributing ones (matrix A4);
- a clause (four numbers or more): the system functions that trace it, and one or more derived requirements.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from arcadia_tool.ui.rich_text import RichTextEdit, to_markdown
from arcadia_tool.ui.srs_trace import ROW_COLORS, TickPickerDialog, function_group
from arcadia_tool.ui.theme import ACCENT, BORDER, MUTED, SURFACE, icon

UUID_ROLE = Qt.UserRole
PRINCIPAL, CONTRIBUTES = 1, 2  # columns of the domains window
ID_COLUMN, NAME_COLUMN = 0, 1  # columns of the derivation window
TEXT_ROLE = Qt.UserRole + 1  # the obligation of a row of the derivation window (written in the box below)


def item_title(item):
    return f"{item.get('id') or ''} {item.get('title') or ''}".strip()


class ItemDomainsDialog(QDialog):
    """Domains of a section: one principal (P), any contributing (C), as in the matrix sections × domains (A4)."""

    def __init__(self, project, item, parent=None):
        super().__init__(parent)
        self.project, self.item = project, item
        self.principal = item.get("primary_domain")
        self.contributing = set(item.get("contributing_domains") or [])
        self.setWindowTitle(f"Domini della sezione {item.get('id')}")
        self.resize(720, 560)
        self.icons = {True: icon("mdi6.checkbox-marked", ACCENT), False: icon("mdi6.checkbox-blank-outline", MUTED)}

        header = QFrame(objectName="card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.addWidget(QLabel(item_title(item), objectName="elementTitle"))
        note = QLabel("Matrice sezioni × domini (A4): ogni sezione ha esattamente un dominio principale; gli altri "
                      "domini coinvolti contribuiscono. Clicca nelle colonne per scegliere.", objectName="muted")
        note.setWordWrap(True)
        header_layout.addWidget(note)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Dominio funzionale", "Principale", "Contribuisce"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet(f"QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; "
                                "border-radius: 6px; }}")
        columns = self.tree.header()
        columns.setStretchLastSection(False)
        columns.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (PRINCIPAL, CONTRIBUTES):
            columns.setSectionResizeMode(c, QHeaderView.Fixed)
            columns.resizeSection(c, 110)
        self.rows = {}
        for d in project.model.of_kind("domain"):
            row = QTreeWidgetItem(self.tree, [project.model.label(d)])
            row.setData(0, UUID_ROLE, d.uuid)
            self.rows[d.uuid] = row
        self.tree.itemClicked.connect(self._clicked)
        self.empty = QLabel("Nessun dominio funzionale: crealo prima nel modello (SA-1).", objectName="muted")
        self.empty.setVisible(not self.rows)

        apply = QPushButton(icon("mdi6.check", "white"), "Applica")
        apply.setProperty("primary", True)
        apply.clicked.connect(self.accept)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.empty)
        layout.addLayout(buttons)
        self._paint()

    def _paint(self):
        for uuid, row in self.rows.items():
            principal, contributes = uuid == self.principal, uuid in self.contributing
            row.setIcon(PRINCIPAL, self.icons[principal])
            row.setIcon(CONTRIBUTES, self.icons[contributes])
            colour = ROW_COLORS[1] if principal else ROW_COLORS[2] if contributes else None
            for column in range(3):
                row.setBackground(column, QBrush(QColor(colour)) if colour else QBrush())

    def _clicked(self, row, column):
        uuid = row.data(0, UUID_ROLE)
        if column == PRINCIPAL:
            self.principal = None if self.principal == uuid else uuid
            self.contributing.discard(uuid)  # a domain is principal or contributing, not both
        elif column == CONTRIBUTES:
            if uuid in self.contributing:
                self.contributing.discard(uuid)
            else:
                self.contributing.add(uuid)
                if self.principal == uuid:
                    self.principal = None
        self._paint()

    def chosen(self):
        return self.principal, [d for d in self.rows if d in self.contributing]


def choose_functions(project, item, parent=None):
    """The system functions that trace a clause directly (ticks, grouped by domain). None if cancelled."""
    model = project.model
    functions = model.of_kind("system_function")
    direct = [f.uuid for f in functions if item.uuid in (f.get("sections") or [])]
    dialog = TickPickerDialog(
        project, f"Funzioni di sistema per {item.get('id')}",
        "Le funzioni di sistema che concorrono a realizzare la clausola (tracciabilità SA-2). Le funzioni che "
        "tracciano già l'intera sezione la coprono anche senza spunta.",
        functions, selected=direct, group_of=lambda f: function_group(model, f), parent=parent)
    return dialog.selected if dialog.exec() else None


class DeriveDialog(QDialog):
    """One or more derived requirements (SA-4) of a clause. A row per requirement with its ID («<voce>-Dn», given at
    once) and its optional short name; the obligation of the selected row is written in the box below the table."""

    def __init__(self, project, item, parent=None):
        super().__init__(parent)
        self.project, self.item = project, item
        self.setWindowTitle(f"Deriva requisiti da {item.get('id')}")
        self.resize(860, 640)
        header = QFrame(objectName="card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.addWidget(QLabel(item_title(item), objectName="elementTitle"))
        text = QLabel((item.get("text") or "")[:900], objectName="muted")
        text.setWordWrap(True)
        header_layout.addWidget(text)
        note = QLabel("Un requisito derivato per riga, con un solo obbligo che spetta a un solo dominio (B5 domanda "
                      "4). L'ID è assegnato in automatico; l'obbligo della riga selezionata si scrive sotto la "
                      "tabella. Funzione logica, dominio e motivazione si completano poi nella scheda.",
                      objectName="muted")
        note.setWordWrap(True)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["ID", "Nome sintetico"])
        self.table.horizontalHeaderItem(NAME_COLUMN).setToolTip("Facoltativo: mostrato con l'ID dove il requisito "
                                                                 "derivato si sceglie")
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(ID_COLUMN, QHeaderView.Interactive)
        header_view.resizeSection(ID_COLUMN, 220)
        header_view.setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.currentCellChanged.connect(self._row_changed)
        self.text_label = QLabel(objectName="formLabel")
        self.text = RichTextEdit(height=110)  # with styles, as the obligation in the sheet
        self.text.setPlaceholderText("L'obbligo del requisito derivato, in una frase.")
        self.text.changed.connect(self._text_changed)
        self.free_numbers = self._free_numbers()
        self.add_row()  # one row; more with «Aggiungi riga»
        add = QPushButton(icon("mdi6.plus"), "Aggiungi riga")
        add.clicked.connect(self.add_row)
        remove = QPushButton(icon("mdi6.minus"), "Rimuovi riga")
        remove.clicked.connect(self.remove_row)
        rows = QHBoxLayout()
        rows.addWidget(add)
        rows.addWidget(remove)
        rows.addStretch()
        self.decompose = QCheckBox("Registra nel registro SA-3 la voce come «Scomposta in requisiti derivati» "
                                   "(domanda B5 n. 4)")
        self.decompose.setChecked(True)

        self.create_button = QPushButton(icon("mdi6.call-split", "white"), "Crea requisiti derivati")
        self.create_button.setProperty("primary", True)
        self.create_button.clicked.connect(self._create)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        self.error = QLabel(objectName="muted")
        self.error.setStyleSheet("color: #B42318;")
        buttons = QHBoxLayout()
        buttons.addWidget(self.error, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(note)
        layout.addWidget(self.table, 1)
        layout.addLayout(rows)
        layout.addWidget(self.text_label)
        layout.addWidget(self.text)
        layout.addWidget(self.decompose)
        layout.addLayout(buttons)
        self.created, self.changed = [], []

    def _free_numbers(self):
        """The n of the free «<voce>-Dn», in order, as the project assigns them (the first free each time)."""
        prefix = f"{self.item.get('id')}-D"
        used = {int(i[len(prefix):]) for i in (e.get("id") or "" for e in self.project.model)
                if i.startswith(prefix) and i[len(prefix):].isdigit()}

        def numbers():
            n = 0
            while True:
                n += 1
                if n not in used:
                    yield n
        return numbers

    def _number(self, row):
        numbers = self.free_numbers()
        for _ in range(row):
            next(numbers)
        return next(numbers)

    def add_row(self):
        """A new derived requirement: its row, with its ID at once, selected to write its obligation."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        ident = QTableWidgetItem("")
        ident.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)  # assigned by the tool, not editable
        ident.setForeground(QColor(ACCENT))
        ident.setData(TEXT_ROLE, "")  # the obligation of the row, shown in the box below
        self.table.setItem(row, ID_COLUMN, ident)
        self.table.setItem(row, NAME_COLUMN, QTableWidgetItem(""))
        self._number_rows()
        self.table.setCurrentCell(row, NAME_COLUMN)
        self.text.setFocus()
        return row

    def remove_row(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.rowCount() > 1:  # at least one row
            self.table.removeRow(row)
            self._number_rows()
            self._row_changed(self.table.currentRow())

    def _cell(self, row, column):
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _obligation(self, row):
        item = self.table.item(row, ID_COLUMN)
        return (item.data(TEXT_ROLE) or "").strip() if item is not None else ""

    def _number_rows(self):
        """The ID of each row, in order: the IDs the requirements will have."""
        for row in range(self.table.rowCount()):
            self.table.item(row, ID_COLUMN).setText(f"{self.item.get('id')}-D{self._number(row)}")

    def _row_changed(self, row, *_):
        """Another row selected: the box shows (and edits) its obligation."""
        if 0 <= row < self.table.rowCount():  # set_markdown: shown, not an edit of the row
            self.text.setEnabled(True)
            self.text.set_markdown(self.table.item(row, ID_COLUMN).data(TEXT_ROLE) or "")
            self.text_label.setText(f"Obbligo di {self._cell(row, ID_COLUMN)} (una frase)")
        else:
            self.text.setEnabled(False)
            self.text.set_markdown("")
            self.text_label.setText("Obbligo (una frase)")

    def _text_changed(self):
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, ID_COLUMN)
            item.setData(TEXT_ROLE, to_markdown(self.text.editor.document()))
            item.setToolTip(self.text.plain_text())
            self.error.setText("")

    def set_obligation(self, row, text):
        """Write the obligation of a row (as the user does, selecting it and typing in the box)."""
        self.table.setCurrentCell(row, NAME_COLUMN)
        self.text.editor.setPlainText(text)

    def ids(self):
        return [self._cell(row, ID_COLUMN) for row in range(self.table.rowCount())]

    def obligations(self):
        return [(self._cell(row, NAME_COLUMN), self._obligation(row)) for row in range(self.table.rowCount())]

    def _create(self):
        missing = [row for row in range(self.table.rowCount()) if not self._obligation(row)]
        if missing:
            self.error.setText("Scrivi l'obbligo di " + ", ".join(self._cell(r, ID_COLUMN) for r in missing) +
                               " (o rimuovi la riga).")
            self.table.setCurrentCell(missing[0], NAME_COLUMN)
            self.text.setFocus()
            return
        self.created, self.changed = self.project.derive_requirements(self.item, self.obligations(),
                                                                      self.decompose.isChecked())
        self.accept()
