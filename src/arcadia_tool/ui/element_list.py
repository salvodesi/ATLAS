"""A tab with the elements of a kind as a table (SA-1, the functional domains; X-1, the architectural decisions;
X-2, the requests for clarification): their main fields, a button to open each of them (and one to delete it), and
one to create a new one. The status of a domain is changed on its row. Opened with a double click on the kind in
the model tree."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit,
                               QMessageBox, QPushButton, QStackedWidget, QTabBar, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from arcadia_tool.model.adr import ACTIVE, APPROVED, REJECTED, SUPERSEDED, outcome
from arcadia_tool.model.element import natural_key
from arcadia_tool.model.schema import KINDS_BY_NAME, derived_value
from arcadia_tool.ui.theme import BORDER, icon, kind_icon, status_colors

UUID_ROLE = Qt.UserRole
OUTCOME_ROLE = Qt.UserRole + 1  # of the row of an ADR: which of its lists it is in
VALUE_ROLE = Qt.UserRole + 2  # of a cell of a reference: the uuid it shows (for the filters of the column)
# The lists of the ADR: (name, outcome, what is in it); None: all of them.
ADR_LISTS = (("Tutte", None, "Tutte le ADR"),
             ("In revisione", ACTIVE, "Non ancora decise: proposte, in revisione o revisionate dalla DA con commenti"),
             ("Approvate", APPROVED, "Decise, o accolte dalla DA"),
             ("Respinte", REJECTED, "Respinte dalla DA"),
             ("Superate", SUPERSEDED, "Sostituite da una decisione successiva"))
# The kinds shown as a table: their columns (fields of the schema); the first wide one takes the free space.
LIST_COLUMNS = {
    "domain": ("id", "name", "team", "referent", "status"),
    "system_function": ("id", "name", "domain", "srs_count", "derived_count", "status"),
    "clarification": ("id", "recipient", "clause", "status"),  # the SRS clause the request is about
    "adr": ("id", "title", "adr_type", "adr_domains", "proposer", "proposer_member", "status", "da_decision"),
    "derived_requirement": ("id", "name", "parent", "system_function", "domain"),
    # SA-3: one row per SRS item traced (a record has no ID of its own: the number of its item comes first).
    "trace_record": ("requirement", "category", "functions", "outcome", "domain"),
}
# The columns a kind is filtered by, with ticks among all the elements of a kind (what the drop-down list says when
# none is ticked; the kind of the choices; the title of a window with search, for many choices).
PICK_FILTERS = {"derived_requirement": (("parent", "Tutte le voci madri", "requirement", "le voci madri"),
                                        ("system_function", "Tutte le funzioni", "system_function",
                                         "le funzioni di sistema"),
                                        ("domain", "Tutti i domini", "domain", "i domini funzionali")),
                # The functions: primary or secondary; the domain: the principal one of the item; the outcomes.
                "trace_record": (("requirement", "Tutte le voci", "requirement", "le voci SRS"),
                                 ("functions", "Tutte le funzioni", "system_function", "le funzioni di sistema"),
                                 ("domain", "Tutti i domini", "domain", "i domini funzionali"),
                                 ("outcome", "Tutti gli esiti", "@outcome", "gli esiti"))}
WIDE = ("recipient", "title", "name", "functions")  # the first one of a kind takes the free space
STATUS_ON_ROW = ("domain", "system_function")  # the status chosen on the row, from a drop-down list
# Only «Apri»: a domain or a function is deleted from its sheet, the tree or the views.
NOT_DELETED_HERE = ("domain", "system_function")
# Columns computed from the model, not fields of the sheet.
COMPUTED_COLUMNS = ("srs_count", "derived_count", "adr_domains", "functions")
# How an element is called: one, many, the button to create one, the empty list, the search.
NAMES = {
    "domain": ("dominio", "domini", "Nuovo dominio", "Nessun dominio funzionale",
               "Cerca per ID, nome, team, responsabile o stato", "Nuovo dominio funzionale"),
    "system_function": ("funzione", "funzioni", "Nuova funzione", "Nessuna funzione di sistema",
                        "Cerca per ID, nome, dominio o stato", "Nuova funzione di sistema"),
    "clarification": ("richiesta", "richieste", "Nuova richiesta", "Nessuna richiesta di chiarimento",
                      "Cerca per ID, destinatario, clausola o stato", "Nuova richiesta di chiarimento"),
    "adr": ("ADR", "ADR", "Nuova ADR", "Nessuna decisione architetturale",
            "Cerca per ID, titolo, tipo, team, membro o stato", "Nuova decisione architetturale (ADR)"),
    "derived_requirement": ("requisito derivato", "requisiti derivati", "Nuovo requisito derivato",
                            "Nessun requisito derivato", "Cerca per ID, nome, voce madre, funzione o dominio",
                            "Nuovo requisito derivato"),
    "trace_record": ("esito", "esiti", "Nuovo esito", "Nessun esito di tracciatura",
                     "Cerca per voce, categoria, funzione, esito o dominio", "Nuovo esito di tracciatura"),
}
COLUMN_LABELS = {"id": "ID", "recipient": "Destinatario della richiesta", "adr_type": "Tipo",
                 "name": "Nome del dominio", "referent": "Responsabile", "proposer": "Team proponente",
                 "proposer_member": "Membro proponente", "da_decision": "Decisione DA", "adr_domains": "DF impattati",
                 "srs_count": "Sezioni e clausole SRS", "derived_count": "Requisiti derivati",
                 "parent": "Voce madre", "system_function": "Funzione di sistema"}
# The heading of a column for a kind, when not the general one.
KIND_LABELS = {("system_function", "name"): "Nome (verbo + oggetto)",
               ("derived_requirement", "name"): "Nome sintetico", ("trace_record", "requirement"): "Voce SRS",
               ("trace_record", "domain"): "Dominio principale",
               ("trace_record", "functions"): "Funzioni di sistema", ("derived_requirement", "domain"): "Domini",
               ("derived_requirement", "system_function"): "Funzioni di sistema"}
# Shown in colour like the status (the decision of the DA: accolta, respinta…).
COLOURED = ("status", "da_decision")
TOOLTIP_FIELDS = {"clarification": "problem", "adr": "context", "domain": "mission",
                  "derived_requirement": "obligation", "trace_record": "notes"}
# Columns the list is sorted by, with a click on their heading (at first: by ID).
SORTABLE = {"adr": ("id", "adr_type", "adr_domains", "proposer", "proposer_member", "status", "da_decision"),
            "derived_requirement": ("id", "parent", "system_function", "domain"),
            "trace_record": ("requirement", "outcome", "domain")}
FIRST_SORT = {"trace_record": "requirement"}  # the column sorted at first, when not the ID
# The button of a filter, when not the heading of its column (the functions of a record: primary or secondary).
FILTER_LABELS = {}


def derived_domain(model, derived):
    """The domain of a derived requirement: its own, else that of its system function."""
    if derived.get("domain"):
        return derived.get("domain")
    from arcadia_tool.model.links import derived_functions
    functions = derived_functions(derived)
    function = model.get(functions[0]) if functions else None
    return function.get("domain") if function is not None else None


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
        self._kept_row = None  # the row whose status was just chosen: kept selected when the list is rebuilt

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
        self.filters = None
        if kind == "adr":  # conditions on the columns, in AND and OR, under the search
            from arcadia_tool.ui.filter_builder import FilterBuilder

            self.filters = FilterBuilder([(c, self._header(c)) for c in self.columns], self._column_values)
            self.filters.changed.connect(lambda: self._filter(self.search.text()))
            header_layout.addWidget(self.filters)
        # Filters with ticks on some columns (the derived requirements: by parent item, system function, domain).
        self.pickers = {}
        if kind in PICK_FILTERS:
            from arcadia_tool.ui.multi_pick import FilterButton

            picks = QHBoxLayout()
            for column, empty, choice_kind, what in PICK_FILTERS[kind]:
                pick = FilterButton(FILTER_LABELS.get((kind, column)) or self._header(column), empty,
                                    lambda values, k=choice_kind, w=what: self._choose(k, w, values))
                pick.changed.connect(lambda: self._filter(self.search.text()))
                self.pickers[column] = pick
                picks.addWidget(pick)
                picks.addSpacing(18)
            picks.addStretch()
            header_layout.addLayout(picks)

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
            elif name in ("id", "status", "da_decision", *COMPUTED_COLUMNS):
                columns.setSectionResizeMode(c, QHeaderView.ResizeToContents)
            else:  # another text (the decider of an ADR): a width of its own, changeable by dragging
                columns.setSectionResizeMode(c, QHeaderView.Interactive)
                # a domain: room for its name; a record: many columns
                columns.resizeSection(c, 170 if kind == "domain" else 150 if kind == "trace_record" else 220)
        columns.setSectionResizeMode(len(self.columns), QHeaderView.Fixed)
        columns.setMinimumSectionSize(90)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.sortable = SORTABLE.get(kind, ())
        self.sort_column, self.sort_order = FIRST_SORT.get(kind, "id"), Qt.AscendingOrder
        if self.sortable:
            columns.setSectionsClickable(True)
            columns.setSortIndicatorShown(True)
            columns.setSortIndicator(self.columns.index(self.sort_column), Qt.AscendingOrder)
            columns.sortIndicatorChanged.connect(self._sort_chosen)
            for c, name in enumerate(self.columns):
                if name in self.sortable:
                    self.table.horizontalHeaderItem(c).setToolTip(f"Clic per ordinare per {self._header(name)}")

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

        self.outcome_tabs = None
        if kind == "adr":
            self.outcome_tabs = QTabBar(drawBase=False)
            for i, (name, _outcome, tip) in enumerate(ADR_LISTS):
                self.outcome_tabs.addTab(name)
                self.outcome_tabs.setTabToolTip(i, tip)
            self.outcome_tabs.currentChanged.connect(lambda _i: self._filter(self.search.text()))
        self.body = QStackedWidget()
        self.body.addWidget(self.table)
        self.body.addWidget(self.empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(header)
        if self.outcome_tabs is not None:
            layout.addWidget(self.outcome_tabs)
        layout.addWidget(self.body, 1)
        self.reload()

    def _header(self, column):
        return KIND_LABELS.get((self.kind, column)) or COLUMN_LABELS.get(column) or self.schema.field(column).label

    def _text(self, element, column):
        """What a cell shows: the label of a referenced element (the team recipient of a request), else the
        value; a recipient written as text by earlier versions; the columns computed from the model."""
        model = self.project.model
        if column == "srs_count":  # the sections and clauses of a function
            return str(len(element.get("sections") or []))
        if column == "derived_count":  # the derived requirements mapped on it
            from arcadia_tool.model.links import derived_functions
            return str(sum(1 for d in model.of_kind("derived_requirement") if element.uuid in derived_functions(d)))
        if self.kind == "derived_requirement" and column == "domain":  # those of its functions
            return ", ".join(self._label_of(u) for u in self._cell_value(element, column))
        if self.kind == "trace_record" and column == "functions":  # all those traced to its item
            return ", ".join(self._label_of(u) for u in self._cell_value(element, column))
        if self.kind == "derived_requirement" and column == "system_function":  # one or more
            return ", ".join(self._label_of(u) for u in self._cell_value(element, column))
        if self.kind == "trace_record" and column == "domain":  # the principal domain of the item traced
            return self._label_of(self._cell_value(element, column))
        if column == "adr_domains":  # the domains an ADR is about
            from arcadia_tool.model.adr import impacted_domains
            return ", ".join(d.get("id") or model.label(d) for d in impacted_domains(model, element))
        field = self.schema.field(column)
        value = derived_value(model, element, field) if field is not None and field.derived_from else             element.get(column)  # the referent of a domain: from its team
        if field is not None and field.type == "ref":
            target = model.get(value) if value else None
            if target is not None:
                return self._label_of(value)
            return element.get(f"{column}_text") or ""
        if field is not None and field.type == "refs":  # the labels of the elements (e.g. the functions of a record)
            return ", ".join(self._label_of(u) for u in value or [])
        return value if isinstance(value, str) else ", ".join(map(str, value or []))

    def _label_of(self, uuid):
        """A referenced element as a cell shows it: an SRS item by its number, the others by their label."""
        model = self.project.model
        target = model.get(uuid) if uuid else None
        if target is None:
            return ""
        return (target.get("id") or model.label(target)) if target.kind == "requirement" else model.label(target)

    def _cell_value(self, element, column):
        """The uuid a cell of a reference column shows (the domain of a derived requirement: also from its
        function)."""
        if self.kind == "derived_requirement" and column == "domain":
            from arcadia_tool.model.links import derived_domains
            return derived_domains(self.project.model, element)
        if self.kind == "derived_requirement" and column == "system_function":
            from arcadia_tool.model.links import derived_functions
            return derived_functions(element)
        if self.kind == "trace_record" and column == "domain":
            from arcadia_tool.model.adr import principal_of
            item = self.project.model.get(element.get("requirement") or "")
            return principal_of(self.project.model, item) if item is not None else None
        if self.kind == "trace_record" and column == "functions":
            from arcadia_tool.model.links import traced_functions_by_item
            if getattr(self, "_traced", None) is None:  # once per reload, for all the rows
                self._traced = traced_functions_by_item(self.project.model)
            return list(self._traced.get(element.get("requirement"), []))
        return element.get(column)

    @staticmethod
    def _values(value):
        """The uuids of a cell: one, or the list of a column with more (the functions of a derived requirement)."""
        return set(value) if isinstance(value, (list, tuple)) else ({value} if value else set())

    def _fill_pickers(self, elements):
        """How the values of the filters are said once chosen: all the elements of their kind in the model (the SRS
        items by their number); those ticked stay ticked."""
        model = self.project.model
        for column, _empty, kind, _title in PICK_FILTERS.get(self.kind, ()):
            pick = self.pickers[column]
            if kind == "@outcome":  # the outcomes of the record, in their order
                choices = [(o, o) for o in self.schema.field("outcome").options]
            elif kind == "function":  # system and logical
                choices = sorted(((e.uuid, model.label(e), e.get("id"))
                                  for e in model.of_kind("system_function", "logical_function")),
                                 key=lambda c: natural_key(c[1].lower()))
            elif kind == "requirement":
                items = [e for e in model.of_kind(kind) if e.get("item_type") != "Capitolo"]
                items.sort(key=lambda e: natural_key(e.get("id") or ""))
                choices = [(e.uuid, e.get("id") or self._srs_label(e)) for e in items]
            else:
                choices = sorted(((e.uuid, model.label(e), e.get("id")) for e in model.of_kind(kind)),
                                 key=lambda c: natural_key(c[1].lower()))
            if getattr(pick, "_shown_choices", None) == choices:
                continue  # the same (thousands, the SRS items): not built again at each change
            pick._shown_choices = choices
            pick.blockSignals(True)
            pick.set_choices(choices)
            pick.blockSignals(False)

    def _choose(self, kind, what, current):
        """The window to tick the values of a filter, as elsewhere in the tool: the SRS items in the traceability
        window (chapters, search, categories), the system functions grouped by domain, the domains."""
        from arcadia_tool.ui import srs_trace

        model, title = self.project.model, f"{self.schema.plural} · filtro"
        if kind == "requirement":
            return srs_trace.pick_srs_items(self.project, title, what, current, self)
        if kind == "@outcome":
            from arcadia_tool.ui.element_editor import RefPicker
            outcomes = [(o, o) for o in self.schema.field("outcome").options]
            dialog = RefPicker(outcomes, set(current), self, title=f"{title}: {what}")
            return dialog.selected() if dialog.exec() else None
        kinds = ("system_function", "logical_function") if kind == "function" else (kind,)
        elements = model.of_kind(*kinds)
        group_of = (lambda e: srs_trace.function_group(model, e)) if kind in ("function", "system_function") else None
        how_many = "quante" if what.startswith("le ") else "quanti"
        return srs_trace.pick_elements(self.project, f"{title}: {what}", f"Spunta {what} da mostrare: {how_many} "
                                       "servono, un clic sulla spunta la toglie.", elements, current, self, group_of)

    @staticmethod
    def _srs_label(item):
        text = " ".join((item.get("title") or item.get("text") or "").split())
        return f"{item.get('id') or ''}  {text[:80]}{'…' if len(text) > 80 else ''}".strip()

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
        choice.currentTextChanged.connect(lambda text, u=element.uuid: setattr(self, "_kept_row", u))
        choice.currentTextChanged.connect(lambda text, u=element.uuid: self.status_changed.emit(u, text))
        return choice

    @staticmethod
    def _color_choice(choice):
        color = status_colors(choice.currentText())[0] if choice.currentText() else "#6B7280"
        choice.setStyleSheet(f"QComboBox {{ color: {color}; font-weight: 600; }}")

    def _sort_chosen(self, column, order):
        """A click on a heading: the list sorted by that column (again: the other way round); a column that does
        not sort keeps the order there is."""
        columns = self.table.horizontalHeader()
        name = self.columns[column] if column < len(self.columns) else None
        if name not in self.sortable:
            columns.blockSignals(True)
            columns.setSortIndicator(self.columns.index(self.sort_column), self.sort_order)
            columns.blockSignals(False)
            return
        self.sort_column, self.sort_order = name, order
        self.reload()

    def sort_by(self, column, order=Qt.AscendingOrder):
        """Sorted by a column, as with a click on its heading."""
        self.table.horizontalHeader().setSortIndicator(self.columns.index(column), order)

    def _sorted(self, elements):
        """In the order chosen: by ID, else by the column (the empty ones last), then by ID."""
        by_id = sorted(elements, key=lambda e: natural_key(e.get("id") or ""))
        if self.sort_column == "id":
            return by_id if self.sort_order == Qt.AscendingOrder else by_id[::-1]
        field = self.schema.field(self.sort_column)
        if field is not None and field.type == "enum":  # in the order of the options (Proposta, In revisione DA…)
            states, name = list(field.options), self.sort_column
            key = lambda e: states.index(e.get(name)) if e.get(name) in states else len(states)  # noqa: E731
        else:
            key = lambda e: natural_key(self._text(e, self.sort_column).lower())  # noqa: E731
        filled = [e for e in by_id if self._text(e, self.sort_column)]
        filled.sort(key=key, reverse=self.sort_order == Qt.DescendingOrder)
        return filled + [e for e in by_id if not self._text(e, self.sort_column)]

    def reload(self):
        """The elements of the kind, from the model (after a change, a creation or a deletion). The list stays where
        it was: the same scroll position and the same row (the one selected, or whose status was just chosen)."""
        model = self.project.model
        self._traced = None  # the functions traced to the SRS items, as the model is now
        elements = self._sorted(model.of_kind(self.kind))
        scroll = self.table.verticalScrollBar().value()
        current = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        keep = self._kept_row or (current.data(UUID_ROLE) if current is not None else None)
        self._kept_row = None
        self.table.setRowCount(0)
        actions_width = 0
        for e in elements:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, name in enumerate(self.columns):
                value = self._text(e, name)
                cell = QTableWidgetItem(value)
                cell.setData(UUID_ROLE, e.uuid)
                if name in self.pickers:
                    cell.setData(VALUE_ROLE, self._cell_value(e, name))
                if c == 0:
                    cell.setIcon(kind_icon(self.kind))
                if name == "id":
                    if self.kind == "adr":
                        cell.setData(OUTCOME_ROLE, outcome(e))
                if name == "status" and self.kind in STATUS_ON_ROW:
                    self.table.setCellWidget(r, c, self._status_choice(e))  # the text under it: for the search
                elif name in COLOURED and value:
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
        self._fill_pickers(elements)
        if self.filters is not None:
            self.filters.setVisible(bool(elements))
            self.filters.refresh_values()
        if self.outcome_tabs is not None:
            self.outcome_tabs.setVisible(bool(elements))
            found = [outcome(e) for e in elements]
            for i, (name, which, _tip) in enumerate(ADR_LISTS):
                self.outcome_tabs.setTabText(i, f"{name} ({found.count(which) if which else len(found)})")
        self._filter(self.search.text())
        row = next((r for r in range(self.table.rowCount()) if self.table.item(r, 0).data(UUID_ROLE) == keep), None)
        if row is not None:
            self.table.blockSignals(True)
            self.table.setCurrentCell(row, 0)
            self.table.blockSignals(False)

        def restore():  # once the rows are laid out (the range of the scroll bar is known)
            try:
                self.table.verticalScrollBar().setValue(scroll)
            except RuntimeError:  # the tab was closed meanwhile
                pass
        restore()
        QTimer.singleShot(0, restore)

    def _column_values(self, column):
        """The values of a column in the list, to choose from in a condition."""
        from arcadia_tool.ui.filter_builder import distinct_values

        c = self.columns.index(column)
        return distinct_values(self.table.item(r, c).text() for r in range(self.table.rowCount()))

    def _filter(self, text):
        from arcadia_tool.model.filters import evaluate

        words = text.lower().split()
        which = ADR_LISTS[self.outcome_tabs.currentIndex()][1] if self.outcome_tabs is not None else None
        conditions = self.filters.conditions if self.filters is not None else []
        picked = {self.columns.index(c): set(p.values) for c, p in self.pickers.items() if p.values}
        shown = 0
        for r in range(self.table.rowCount()):
            haystack = " ".join(self.table.item(r, c).text() for c in range(len(self.columns))).lower()
            hidden = (bool(words) and not all(w in haystack for w in words)) or \
                (which is not None and self.table.item(r, 0).data(OUTCOME_ROLE) != which) or \
                not evaluate(conditions, lambda column, r=r: self.table.item(r, self.columns.index(column)).text()) \
                or any(not self._values(self.table.item(r, c).data(VALUE_ROLE)) & values
                       for c, values in picked.items())
            self.table.setRowHidden(r, hidden)
            shown += not hidden
        total = self.table.rowCount()
        self.count.setText(f"{shown} di {total}" if words or which or conditions or picked else
                           f"1 {self.one}" if total == 1 else f"{total} {self.many}")

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
