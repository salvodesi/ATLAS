"""Traceability to the SRS items, one window shared by two sheets:

- a functional domain (SA-1): principal and contributing domain of sections and clauses (matrix A4);
- a system function (SA-2): sections and clauses it is allocated to;
- a logical function (LA-2): sections and clauses, and the derived requirements (SA-4) it refines.
"""
from html import escape

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QTextDocument
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QTabBar, QTextBrowser, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout)

from arcadia_tool.ui.element_editor import load_pixmap
from arcadia_tool.ui.srs_reader import CATEGORIES, CATEGORY_COLORS, NO_CATEGORY, chapter_of, document_order
from arcadia_tool.ui.theme import ACCENT, ACCENT_SOFT, BORDER, MUTED, SURFACE, TEXT, icon

TAB_BG = "#E4E9F0"  # tabs not selected: a little darker than the dialog background
VIEWER_IMAGE_WIDTH = 760  # fits the viewer with the indentation of the list items

# Sections have three numbers (3.4.1), clauses more (3.4.1.3); chapters (3.4) only group them. List items,
# table rows and figures («Voce») are traced through their clause.
TRACEABLE = ("Sezione", "Titolo", "Requisito")
SHOWN = ("Capitolo",) + TRACEABLE
PRINCIPAL, CONTRIBUTES = 1, 2  # domain
ALLOCATED = 1  # function
PARENT = 1  # derived requirement
UUID_ROLE = Qt.UserRole
CATEGORY_COLUMN = 1  # chapter 9 category of the item, right after it
ROW_COLORS = {1: "#DCE8FA", 2: "#DDF3E4"}  # rows of the first column (principal, allocated) / of the second
SRS_FIELD = {"system_function": "sections", "logical_function": "detail_requirements"}  # SA-2 / LA-2


def principal_items(model, domain):
    return [e for e in document_order(model) if e.get("primary_domain") == domain.uuid]


def contributed_items(model, domain):
    return [e for e in document_order(model) if domain.uuid in (e.get("contributing_domains") or [])]


def allocated_items(model, function):
    """SRS sections and clauses of a system or logical function, in specification order."""
    sections = set(function.get(SRS_FIELD[function.kind]) or [])
    return [e for e in document_order(model) if e.uuid in sections]


def derived_of(model, function):
    """Derived requirements (SA-4) allocated to a logical function (LA-2): their «Funzione logica»."""
    return [d for d in model.of_kind("derived_requirement") if d.get("function") == function.uuid]


def _haystack(e):
    return " ".join(e.get(f) or "" for f in ("id", "name", "title", "text", "obligation")).lower()


def function_group(model, function):
    """Group of a function in the pickers: its domain (system function) or the system function it refines."""
    ref = function.get("domain") if function.kind == "system_function" else function.get("refines")
    return model.get(ref) if ref else None


def choose_element(project, element, field, parent=None):
    """Window to tick the one element of a reference field (e.g. the primary function of an SA-3 record);
    returns its uuid, None if nothing is ticked, or False if cancelled."""
    model = project.model
    f = element.schema.field(field)
    # Not itself (a parent function); `element` may be the draft copy of a sheet, hence the uuid.
    candidates = [e for e in model.of_kind(*f.ref_kinds) if e.uuid != element.uuid]
    functions = set(f.ref_kinds) <= {"system_function", "logical_function"}
    dialog = TickPickerDialog(
        project, f"{model.label(element)}: {f.label.lower()}",
        f"Spunta «{f.label}»: uno solo, spuntarne un altro sposta la scelta."
        + (" Le funzioni di sistema sono raggruppate per dominio, le funzioni logiche per funzione di sistema "
           "raffinata." if functions else ""),
        candidates, selected={element.get(field)} - {None}, single=True,
        group_of=(lambda e: function_group(model, e)) if functions else None, parent=parent)
    if not dialog.exec():
        return False
    return next(iter(dialog.selected), None)


def choose_logical_function(project, derived, parent=None):
    """Window to tick the logical function (LA-2) of a derived requirement; returns its uuid, None if no
    choice, or False if cancelled."""
    model = project.model
    functions = model.of_kind("logical_function")
    dialog = TickPickerDialog(
        project, f"{model.choice_label(derived)}: funzione logica",
        "Spunta la funzione logica (LA-2) a cui il requisito derivato è allocato: una sola, spuntarne un'altra "
        "sposta la scelta. Le funzioni sono raggruppate per funzione di sistema raffinata.",
        functions, selected={derived.get("function")} - {None}, single=True,
        group_of=lambda f: model.get(f.get("refines")) if f.get("refines") else None, parent=parent)
    if not dialog.exec():
        return False
    return next(iter(dialog.selected), None)


class SrsItemViewer(QDialog):
    """Read-only full text of an SRS item: its text, its list items and bullets, its figures and tables.
    open_item (uuid → None), when given: the button «Apri la scheda della voce», to edit it in its sheet."""

    def __init__(self, project, parent=None, open_item=None):
        super().__init__(parent)
        self.project, self.open_item, self.element = project, open_item, None
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(900, 700)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        close = QPushButton("Chiudi")
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        self.sheet_button = QPushButton(icon("mdi6.open-in-app"), "Apri la scheda della voce")
        self.sheet_button.setToolTip("La scheda della voce SRS, dove si modifica")
        self.sheet_button.clicked.connect(lambda _=False: self.element is not None and
                                          self.open_item(self.element.uuid))
        self.sheet_button.setVisible(open_item is not None)
        buttons.addWidget(self.sheet_button)
        buttons.addStretch()
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.addWidget(self.browser, 1)
        layout.addLayout(buttons)

    def show_item(self, element, sub_items):
        self.element = element
        model = self.project.model
        document = self.browser.document()
        document.clear()
        self.setWindowTitle(f"{element.schema.label} · {model.label(element)}")
        parts = [f"<h2 style='color:{ACCENT}; margin-bottom:4px'>{escape(element.get('id') or '')} "
                 f"{escape(element.get('title') or '')}</h2>"]
        details = [element.get("item_type") or element.schema.label]
        if element.get("category"):
            details.append("Categoria: " + ", ".join(element.get("category")))
        if element.get("page"):
            details.append(f"pagina {element.get('page')}")
        if element.kind == "derived_requirement" and element.get("parent"):
            details.append(f"voce madre {model.label_of(element.get('parent'))}")
        parts.append(f"<p style='color:{MUTED}'>{escape(' · '.join(d for d in details if d))}</p>")
        parts.append(self._block(element, document))
        stack = [(sub, 1) for sub in reversed(sub_items.get(element.uuid, []))]
        while stack:  # list items in document order, with their own sub-items (bullets of a letter…)
            sub, depth = stack.pop()
            label = (sub.get("id") or "").partition(" ")[2]
            parts.append(f"<div style='margin-left:{24 * depth}px'>{self._block(sub, document, label)}</div>")
            stack.extend((s, depth + 1) for s in reversed(sub_items.get(sub.uuid, [])))
        self.browser.setHtml("".join(parts))
        self.show()
        self.raise_()
        self.activateWindow()

    def _block(self, element, document, label=""):
        html = ""
        prefix = f"<b>{escape(label)}</b>&nbsp; " if label and not element.get("figure") else ""
        text = element.get("text") or element.get("obligation")
        if text:
            html += f"<p>{prefix}" + escape(text).replace("\n", "<br>") + "</p>"
        elif element.get("title") and element.get("item_type") == "Voce":
            html += f"<p><i>{escape(element.get('title'))}</i></p>"  # caption of a figure or table
        pixmap = load_pixmap(self.project, element.get("figure"))
        if pixmap is not None:
            if pixmap.width() > VIEWER_IMAGE_WIDTH:
                pixmap = pixmap.scaledToWidth(VIEWER_IMAGE_WIDTH, Qt.SmoothTransformation)
            name = f"image:{element.uuid}"
            document.addResource(QTextDocument.ImageResource, QUrl(name), pixmap.toImage())
            html += f"<p><img src='{name}'></p>"
        return html


class _TraceDialog(QDialog):
    """The items are listed one chapter at a time (built when its tab is opened), down to the sections.

    The choice columns are drawn with icons, not item check boxes: with the theme style sheet Qt paints those
    as black squares, whether checked or not. Subclasses define the columns and what they mean.
    """
    COLUMNS = ()        # (state, header) of the choice columns; a row has one state or none
    OWNER_HEADER = ""   # last column: the element that owns the row besides the one being edited
    HINT = ""
    WITH_DERIVED = False  # derived requirements (SA-4) listed under their clause
    CHOOSABLE = TRACEABLE  # the kinds of item that can be chosen (e.g. only the sections, see TraceSectionsDialog)

    def __init__(self, project, owner, parent=None):
        super().__init__(parent)
        self.project, self.owner = project, owner
        model = project.model
        self.setWindowTitle("Tracciabilità verso le voci SRS")
        self.resize(1040, 760)
        self.icons = {True: icon("mdi6.checkbox-marked", ACCENT), False: icon("mdi6.checkbox-blank-outline", MUTED)}
        # Columns: the item, its chapter 9 category, the choices (one per state), the owner.
        self.column_of = {state: CATEGORY_COLUMN + 1 + i for i, (state, _) in enumerate(self.COLUMNS)}
        self.state_of = {column: state for state, column in self.column_of.items()}
        self.owner_column = CATEGORY_COLUMN + len(self.COLUMNS) + 1

        # Items in specification order per chapter, and the choices ({uuid: state or None}).
        self.by_chapter, self.state = {}, {}
        self.sub_items = {}  # list items, bullets, figures… of each clause, shown with its full text
        for e in document_order(model):
            if e.get("item_type") not in SHOWN:
                self.sub_items.setdefault(e.get("parent"), []).append(e)
                continue
            self.by_chapter.setdefault(chapter_of(e), []).append(e)
            if e.get("item_type") in self.CHOOSABLE:
                self.state[e.uuid] = self.initial_state(e)
        if self.WITH_DERIVED:
            for d in model.of_kind("derived_requirement"):
                self._add_derived(d)
        self._items = {}
        self.created = []  # derived requirements created from this window

        header = QFrame(objectName="card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        title = f"{model.label(owner)}: {self.TITLE}" if owner is not None else self.TITLE.capitalize()
        header_layout.addWidget(QLabel(title, objectName="elementTitle"))
        hint = QLabel(self.HINT, objectName="muted")
        hint.setWordWrap(True)
        header_layout.addWidget(hint)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setCursor(Qt.PointingHandCursor)
        # On the dialog grey the default tabs look like plain text: drawn as raised tabs, the current one white.
        self.tabs.setStyleSheet(
            f"QTabBar::tab {{ background: {TAB_BG}; color: {MUTED}; border: 1px solid {BORDER}; border-bottom: none;"
            " border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 6px 14px; margin-right: 3px; }"
            f"QTabBar::tab:hover {{ background: {ACCENT_SOFT}; color: {TEXT}; }}"
            f"QTabBar::tab:selected {{ background: {SURFACE}; color: {ACCENT}; font-weight: 600;"
            f" border-bottom: 2px solid {ACCENT}; }}")
        for chapter in sorted(c for c in self.by_chapter if c is not None):
            i = self.tabs.addTab("")
            self.tabs.setTabData(i, chapter)
        if None in self.by_chapter:  # derived requirements without a parent item
            self.tabs.setTabData(self.tabs.addTab(""), None)
        self.search = QLineEdit(placeholderText="Cerca per numero o nel testo", objectName="search")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        # Out of the header card, on the dialog grey: a white field like the other inputs.
        self.search.setStyleSheet(f"QLineEdit {{ background: {SURFACE}; border: 1px solid {BORDER}; "
                                  "border-radius: 4px; padding: 4px 6px 4px 8px; }}")
        self.search.textChanged.connect(self._filter)
        self.search.textChanged.connect(self._update_counts)
        self.sections_only = QCheckBox("Solo sezioni")
        self.sections_only.toggled.connect(self._filter)
        self.only_traced = QCheckBox("Solo voci tracciate")
        self.only_traced.toggled.connect(self._filter)
        self.only_derived = QCheckBox("Solo requisiti derivati")
        self.only_derived.toggled.connect(self._filter)
        self.only_derived.setVisible(self.WITH_DERIVED)
        self.count = QLabel(objectName="muted")
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.sections_only)
        top.addWidget(self.only_derived)
        top.addWidget(self.only_traced)
        top.addSpacing(12)
        top.addWidget(self.count)
        # Filter on the chapter 9 category, like in the SUBSET-026 catalogue (derived requirements always shown).
        self.category_boxes = {}
        categories = QHBoxLayout()
        categories.addWidget(QLabel("Categoria:", objectName="muted"))
        for c in CATEGORIES + (NO_CATEGORY,):
            box = QCheckBox(c)
            box.setChecked(True)
            box.setStyleSheet(f"QCheckBox {{ color: {CATEGORY_COLORS[c][0]}; font-weight: 600; }}")
            box.toggled.connect(self._filter)
            self.category_boxes[c] = box
            categories.addWidget(box)
        categories.addStretch()

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Voce SRS", "Categoria cap. 9"] + [h for _, h in self.COLUMNS]
                                  + [self.OWNER_HEADER])
        self.tree.setUniformRowHeights(True)
        # Background set explicitly, like the SUBSET-026 catalogue: otherwise the list takes the dialog grey.
        self.tree.setStyleSheet(f"QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; "
                                "border-radius: 6px; }}")
        columns = self.tree.header()
        columns.setStretchLastSection(False)
        columns.setSectionResizeMode(0, QHeaderView.Stretch)
        columns.setSectionResizeMode(CATEGORY_COLUMN, QHeaderView.Interactive)
        columns.resizeSection(CATEGORY_COLUMN, 130)
        for c in self.state_of:
            columns.setSectionResizeMode(c, QHeaderView.Fixed)
            columns.resizeSection(c, 100)
        columns.setSectionResizeMode(self.owner_column, QHeaderView.Interactive)
        columns.resizeSection(self.owner_column, 240)
        self.tree.setColumnHidden(self.owner_column, not self.OWNER_HEADER)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        if self.WITH_DERIVED:
            self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._context_menu)
        self.viewer = None

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
        # Chapter tabs, search and filters right above the list they act on.
        table = QVBoxLayout()
        table.setSpacing(6)
        table.addWidget(self.tabs)
        table.addLayout(top)
        table.addLayout(categories)
        table.addWidget(self.tree, 1)
        layout.addLayout(table, 1)
        layout.addLayout(buttons)

        self._update_counts()
        self.tabs.currentChanged.connect(self._show_chapter)
        traced = [self._chapter(model.get(u)) for u, s in self.state.items() if s]
        first = next((i for i in range(self.tabs.count()) if self.tabs.tabData(i) in traced), 0)
        self.tabs.setCurrentIndex(first)
        self._show_chapter(first)

    @property
    def owner_uuid(self):
        return self.owner.uuid if self.owner is not None else None

    # --- what the columns mean (subclasses) ------------------------------------------------------------

    def initial_state(self, e):
        raise NotImplementedError

    def owner_after_apply(self, e, state):
        """The element shown in the last column, as it will be after «Applica» (None: nothing to show)."""
        raise NotImplementedError

    def stored_owner(self, e):
        """The element in the last column as it is saved now (to warn before replacing it)."""
        raise NotImplementedError

    def apply(self):
        raise NotImplementedError

    def count_text(self):
        raise NotImplementedError

    # --- one chapter at a time -----------------------------------------------------------------------

    def _chapter(self, e):
        """Chapter tab of a row; None for a derived requirement without its parent item."""
        if e.kind == "derived_requirement":
            parent = self.project.model.get(e.get("parent")) if e.get("parent") else None
            return chapter_of(parent) if parent is not None else None
        return chapter_of(e)

    def _add_derived(self, d):
        self.by_chapter.setdefault(self._chapter(d), []).append(d)
        self.state[d.uuid] = self.initial_state(d)

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        e = self.project.model.get(item.data(0, UUID_ROLE)) if item else None
        if e is None or e.kind != "requirement" or e.get("item_type") not in self.CHOOSABLE:
            return
        menu = QMenu(self)
        menu.addAction(icon("mdi6.call-split"), f"Deriva requisito da {e.get('id')}…",
                       lambda _=False: self.derive(e))
        menu.addAction(icon("mdi6.text-box-outline"), "Leggi il testo completo",
                       lambda _=False: self.show_item(e.uuid))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def derive(self, parent, obligation=None):
        """New derived requirement (SA-4) of an SRS item, allocated to this function (confirmed by «Applica»)."""
        if obligation is None:
            obligation, ok = QInputDialog.getMultiLineText(
                self, "Nuovo requisito derivato", f"Obbligo (una frase) derivato da {parent.get('id')}:")
            if not ok or not obligation.strip():
                return None
        derived = self.project.new_element("derived_requirement", parent=parent.uuid, obligation=obligation.strip())
        self.created.append(derived)
        self._add_derived(derived)
        self.state[derived.uuid] = ALLOCATED
        index = next(i for i in range(self.tabs.count()) if self.tabs.tabData(i) == self._chapter(derived))
        self._update_counts()
        if self.tabs.currentIndex() == index:
            self._show_chapter(index)
        else:
            self.tabs.setCurrentIndex(index)
        self.tree.scrollToItem(self._items[derived.uuid])
        return derived

    def _show_chapter(self, index):
        model = self.project.model
        chapter = self.tabs.tabData(index)
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self._items, parents = {}, {}
        for e in self.by_chapter.get(chapter, []):
            parent = parents.get(e.get("parent"))
            if parent is None and e.get("parent"):  # a derived requirement of a list item: under its clause
                ancestor = model.get(e.get("parent"))
                while ancestor is not None and ancestor.uuid not in parents:
                    ancestor = model.get(ancestor.get("parent")) if ancestor.get("parent") else None
                parent = parents.get(ancestor.uuid) if ancestor is not None else None
            label = model.choice_label(e)  # a derived requirement: ID and short name (if any)
            item = QTreeWidgetItem(parent or self.tree, [label])
            item.setData(0, UUID_ROLE, e.uuid)
            item.setToolTip(0, (e.get("text") or e.get("obligation") or e.get("title") or "")[:600])
            if e.kind == "derived_requirement":
                item.setIcon(0, icon("mdi6.call-split", MUTED))
            categories = e.get("category") or []
            if categories:  # Bordo, Terra, Definizione, Informativa… coloured like the chips of the catalogue
                item.setText(CATEGORY_COLUMN, ", ".join(categories))
                item.setForeground(CATEGORY_COLUMN, QColor(CATEGORY_COLORS.get(categories[0], (MUTED,))[0]))
            parents[e.uuid] = item
            if e.get("item_type") == "Capitolo":
                item.setExpanded(True)  # down to the sections (3.4.1)
                continue
            self._items[e.uuid] = item
            self._paint(item)
            if self.state.get(e.uuid) or e.kind == "derived_requirement":
                p = item.parent()
                while p is not None:  # traced items and derived requirements are visible
                    p.setExpanded(True)
                    p = p.parent()
        self.tree.setUpdatesEnabled(True)
        self._filter()

    def _paint(self, item):
        uuid = item.data(0, UUID_ROLE)
        state = self.state.get(uuid)
        for choice, column in self.column_of.items():
            item.setIcon(column, self.icons[state == choice])
            item.setToolTip(column, f"Clic per {'togliere' if state == choice else 'indicare'} la tracciatura")
        # The last column as it will be after «Applica»: the element being edited as soon as it is chosen.
        model = self.project.model
        e = model.get(uuid)
        owner = self.owner_after_apply(e, state)
        item.setText(self.owner_column, (model.label_of(owner) or "") if owner else "")
        font = item.font(self.owner_column)
        mine = owner is not None and owner == self.owner_uuid
        font.setBold(mine)
        item.setFont(self.owner_column, font)
        item.setForeground(self.owner_column, QColor(ACCENT if mine else MUTED))
        stored = self.stored_owner(e)
        if mine and stored not in (None, self.owner_uuid):
            item.setToolTip(self.owner_column, f"Sostituisce {model.label_of(stored)} (confermato con «Applica»)")
        else:
            item.setToolTip(self.owner_column, "")
        background = QBrush(QColor(ROW_COLORS[state])) if state in ROW_COLORS else QBrush()
        for column in range(self.tree.columnCount()):
            item.setBackground(column, background)

    def _clicked(self, item, column):
        if column in self.state_of and item.data(0, UUID_ROLE) in self.state:
            self.click(item, self.state_of[column])

    def click(self, item, choice):
        """A click on the box of a choice (PRINCIPAL, ALLOCATED…) of a row."""
        uuid = item.data(0, UUID_ROLE)
        # One choice per row: a click on another column moves it, on the same column removes it.
        self.state[uuid] = None if self.state[uuid] == choice else choice
        self._paint(item)
        self._update_counts()

    def _double_clicked(self, item, column):
        if column in self.state_of:
            return  # a double click on the boxes only toggles them
        self.show_item(item.data(0, UUID_ROLE))

    def show_item(self, uuid):
        """Full text of an SRS item, with its list items and images, in a window next to this one."""
        if self.viewer is None:
            self.viewer = SrsItemViewer(self.project, self)
        self.viewer.show_item(self.project.model.get(uuid), self.sub_items)

    def set_state(self, uuid, state):
        """The choice for a row (None: not traced), also of a chapter not shown."""
        self.state[uuid] = state
        if uuid in self._items:
            self._paint(self._items[uuid])
        self._update_counts()

    def chosen(self, state):
        return {u for u, s in self.state.items() if s == state}

    def _update_counts(self):
        self.count.setText(self.count_text())
        text = self.search.text().strip().lower()
        for i in range(self.tabs.count()):
            chapter = self.tabs.tabData(i)
            items = self.by_chapter.get(chapter, [])
            label = f"Capitolo {chapter}" if chapter is not None else "Requisiti derivati senza voce madre"
            traced = sum(1 for e in items if self.state.get(e.uuid))
            if traced:
                label += f" · {traced} tracciate"
            derived = sum(1 for e in items if e.kind == "derived_requirement")
            if derived and chapter is not None:
                label += f" · {derived} derivati"
            if text:  # where the searched text is, also in the chapters not shown
                found = sum(1 for e in items if e.uuid in self.state and text in _haystack(e))
                label += f" · {found} trovate"
            self.tabs.setTabText(i, label)

    def _filter(self, *_):
        text = self.search.text().strip().lower()
        only_traced, sections_only = self.only_traced.isChecked(), self.sections_only.isChecked()
        only_derived = self.only_derived.isChecked()
        wanted = {c for c, box in self.category_boxes.items() if box.isChecked()}
        by_category = wanted != set(self.category_boxes)
        filtered = bool(text or only_traced or sections_only or only_derived or by_category)
        model = self.project.model
        self.tree.setUpdatesEnabled(False)
        visible = set()
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            e = model.get(item.data(0, UUID_ROLE))
            match = not filtered
            if filtered:
                match = e.get("item_type") == "Sezione" if sections_only else e.uuid in self.state
                match = match and (not only_derived or e.kind == "derived_requirement")
                if by_category and e.kind == "requirement":
                    match = match and not wanted.isdisjoint(e.get("category") or (NO_CATEGORY,))
                match = match and (not only_traced or bool(self.state.get(e.uuid)))
                match = match and (not text or text in _haystack(e))
            if match:
                p = item
                while p is not None and id(p) not in visible:
                    visible.add(id(p))
                    p = p.parent()
            it += 1
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            item.setHidden(id(item) not in visible)
            if (filtered and id(item) in visible and item.childCount()
                    and (text or only_traced or only_derived or by_category)):
                item.setExpanded(True)
            it += 1
        self.tree.setUpdatesEnabled(True)

    def accept(self):
        model = self.project.model
        taken = [u for u, s in self.state.items() if s == self.COLUMNS[0][0]
                 and self.stored_owner(model.get(u)) not in (None, self.owner_uuid)]
        if taken:
            names = sorted({model.label_of(self.stored_owner(model.get(u))) or "" for u in taken})
            answer = QMessageBox.question(self, self.REPLACE_TITLE, self.REPLACE_TEXT.format(
                n=len(taken), names=", ".join(names)))
            if answer != QMessageBox.Yes:
                return
        self.changed = self.apply()
        super().accept()

    def reject(self):
        for derived in self.created:  # created here and not confirmed with «Applica»
            self.project.delete_element(derived.uuid)
        self.created = []
        super().reject()


class TickPickerDialog(QDialog):
    """Choice of model elements with search and ticks, in the style of the traceability windows (e.g. the
    logical function of a derived requirement, grouped under the system function it refines)."""

    def __init__(self, project, title, hint, elements, selected=(), single=False, group_of=None, parent=None):
        super().__init__(parent)
        self.project, self.single = project, single
        self.selected = set(selected)
        model = project.model
        self.setWindowTitle(title)
        self.resize(820, 620)
        self.icons = {True: icon("mdi6.checkbox-marked", ACCENT), False: icon("mdi6.checkbox-blank-outline", MUTED)}

        header = QFrame(objectName="card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.addWidget(QLabel(title, objectName="elementTitle"))
        note = QLabel(hint, objectName="muted")
        note.setWordWrap(True)
        header_layout.addWidget(note)
        self.search = QLineEdit(placeholderText="Cerca per ID o nome", objectName="search")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(f"QLineEdit {{ background: {SURFACE}; border: 1px solid {BORDER}; "
                                  "border-radius: 4px; padding: 4px 6px 4px 8px; }}")
        self.search.textChanged.connect(self._filter)
        self.count = QLabel(objectName="muted")
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addSpacing(12)
        top.addWidget(self.count)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Elemento", "Scelta"])
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet(f"QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; "
                                "border-radius: 6px; }}")
        columns = self.tree.header()
        columns.setStretchLastSection(False)
        columns.setSectionResizeMode(0, QHeaderView.Stretch)
        columns.setSectionResizeMode(1, QHeaderView.Fixed)
        columns.resizeSection(1, 90)
        self.items, groups = {}, {}
        for e in elements:
            group = group_of(e) if group_of else None
            parent_item = self.tree
            if group is not None:
                if group.uuid not in groups:
                    groups[group.uuid] = QTreeWidgetItem(self.tree, [model.choice_label(group)])
                    groups[group.uuid].setForeground(0, QColor(MUTED))
                    groups[group.uuid].setExpanded(True)
                parent_item = groups[group.uuid]
            item = QTreeWidgetItem(parent_item, [model.choice_label(e)])
            item.setData(0, UUID_ROLE, e.uuid)
            item.setToolTip(0, (e.get("description") or e.get("obligation") or "")[:600])
            self.items[e.uuid] = item
            self._paint(item)
        self.tree.itemClicked.connect(self._clicked)
        self.empty = QLabel("Nessun elemento da scegliere: crealo prima nel modello.", objectName="muted")
        self.empty.setVisible(not elements)

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
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.empty)
        layout.addLayout(buttons)
        self._update_count()

    def _paint(self, item):
        chosen = item.data(0, UUID_ROLE) in self.selected
        item.setIcon(1, self.icons[chosen])
        background = QBrush(QColor(ROW_COLORS[1])) if chosen else QBrush()
        for column in range(2):
            item.setBackground(column, background)

    def _clicked(self, item, column):
        uuid = item.data(0, UUID_ROLE)
        if column != 1 or uuid is None:
            return
        if uuid in self.selected:
            self.selected.discard(uuid)
        else:
            if self.single:  # one choice: the previous one is removed
                previous, self.selected = self.selected, set()
                for other in previous:
                    self._paint(self.items[other])
            self.selected.add(uuid)
        self._paint(item)
        self._update_count()

    def _update_count(self):
        n = len(self.selected)
        self.count.setText("Nessuna scelta" if not n else "1 scelto" if n == 1 else f"{n} scelti")

    def _filter(self, text):
        text = text.strip().lower()
        model = self.project.model
        for uuid, item in self.items.items():
            item.setHidden(bool(text) and text not in _haystack(model.get(uuid)) and
                           text not in model.choice_label(model.get(uuid)).lower())
        for i in range(self.tree.topLevelItemCount()):  # a group is shown if something in it is
            group = self.tree.topLevelItem(i)
            if group.childCount():
                group.setHidden(all(group.child(c).isHidden() for c in range(group.childCount())))


class TraceParentDialog(_TraceDialog):
    """Derived requirement (SA-4): the SRS section or clause it is derived from, one only.

    owner None: choice for a derived requirement still to be created (see `parent`); nothing is changed."""
    FIELD = "parent"  # the reference set by the window
    COLUMNS = ((PARENT, "Voce madre"),)
    OWNER_HEADER = ""
    HINT = ("Spunta la sezione (es. 3.4.1) o la clausola (es. 3.4.1.3) da cui il requisito è derivato: una sola, "
            "spuntarne un'altra sposta la scelta. Doppio clic su una riga per leggerne il testo completo.")
    REPLACE_TITLE = REPLACE_TEXT = ""

    @property
    def TITLE(self):
        return "voce madre" if self.owner is not None else "voce madre del nuovo requisito derivato"

    def initial_state(self, e):
        return PARENT if self.owner is not None and e.uuid == self.owner.get(self.FIELD) else None

    def stored_owner(self, e):
        return None

    def owner_after_apply(self, e, state):
        return None

    def click(self, item, choice):
        uuid = item.data(0, UUID_ROLE)
        for other, state in self.state.items():  # one item only: the previous choice is removed
            if state and other != uuid:
                self.set_state(other, None)
        self.set_state(uuid, None if self.state[uuid] == PARENT else PARENT)

    def count_text(self):
        chosen = self.chosen(PARENT)
        model = self.project.model
        caption = self.COLUMNS[0][1]
        return f"{caption}: {model.label(model.get(next(iter(chosen))))}" if chosen else "Nessuna voce scelta"

    @property
    def parent(self):
        chosen = self.chosen(PARENT)
        return next(iter(chosen)) if chosen else None

    def apply(self):
        if self.owner is None:
            return []
        parent, current = self.parent, self.owner.get(self.FIELD)
        if parent is None and current and current not in self.state:
            parent = current  # a list item (not offered here) stays chosen unless another one is
        if parent == current:
            return []
        self.owner.set(self.FIELD, parent)
        if self.project.model.get(self.owner.uuid) is self.owner:
            self.project.update(self.owner)  # a derived requirement: assigns the ID «<voce>-Dn» if it had none
        # else: the draft of a sheet in edit mode, applied with its «Salva»
        return [self.owner]


class TraceItemDialog(TraceParentDialog):
    """SA-3 trace record: the SRS section or clause it records the outcome of («ID voce»), one only."""
    FIELD = "requirement"
    COLUMNS = ((PARENT, "Voce tracciata"),)
    TITLE = "voce SRS tracciata"
    HINT = ("Spunta la sezione (es. 3.4.1) o la clausola (es. 3.4.1.3) di cui l'esito registra la tracciatura: "
            "una sola, spuntarne un'altra sposta la scelta. Doppio clic su una riga per leggerne il testo "
            "completo.")


class TraceClauseDialog(TraceParentDialog):
    """Request for clarification (X-2): the SRS section or clause it is about, one only."""
    FIELD = "clause"
    COLUMNS = ((PARENT, "Clausola"),)
    TITLE = "clausola della richiesta di chiarimento"
    HINT = ("Spunta la sezione (es. 3.4.1) o la clausola (es. 3.4.1.3) su cui si chiede il chiarimento: una sola, "
            "spuntarne un'altra sposta la scelta. Doppio clic su una riga per leggerne il testo completo.")


class TraceImplItemDialog(TraceParentDialog):
    """ADR of a choice left to the implementation (X-1): the SRS section or clause leaving it, one only."""
    FIELD = "impl_item"
    COLUMNS = ((PARENT, "Voce"),)
    TITLE = "sezione o clausola che lascia la scelta"
    HINT = ("Spunta la sezione (es. 3.4.1) o la clausola (es. 3.4.1.3) che lascia la scelta all'implementazione: "
            "una sola, spuntarne un'altra sposta la scelta. Doppio clic su una riga per leggerne il testo completo.")


# The window to choose an SRS item, for each reference field to the specification chosen with ticks.
ITEM_DIALOGS = {"requirement": TraceItemDialog, "clause": TraceClauseDialog, "parent": TraceParentDialog,
                "impl_item": TraceImplItemDialog}


class TraceItemsDialog(_TraceDialog):
    """A list of SRS sections and clauses of a sheet (e.g. those an ADR is about, the clauses of an exchange):
    any number, with ticks, as in the other traceability windows."""
    COLUMNS = ((PARENT, "Scelta"),)
    OWNER_HEADER = ""
    REPLACE_TITLE = REPLACE_TEXT = ""

    def __init__(self, project, owner, field, parent=None):
        self.FIELD = field
        label = owner.schema.field(field).label
        self.TITLE = label.lower()
        self.HINT = (f"Spunta le sezioni (es. 3.4.1) e le clausole (es. 3.4.1.3) di «{label}»: quante servono, un "
                     "clic sulla spunta la toglie. Doppio clic su una riga per leggerne il testo completo.")
        super().__init__(project, owner, parent)

    def initial_state(self, e):
        return PARENT if e.uuid in (self.owner.get(self.FIELD) or []) else None

    def stored_owner(self, e):
        return None

    def owner_after_apply(self, e, state):
        return None

    def click(self, item, choice):
        uuid = item.data(0, UUID_ROLE)
        self.set_state(uuid, None if self.state[uuid] == PARENT else PARENT)

    def count_text(self):
        n = len(self.chosen(PARENT))
        return "Nessuna voce scelta" if not n else "1 voce scelta" if n == 1 else f"{n} voci scelte"

    @property
    def selected(self):
        """The chosen items in specification order; those of the list not offered here (list items) are kept."""
        current = list(self.owner.get(self.FIELD) or [])
        kept = [u for u in current if u not in self.state]
        chosen = [e.uuid for e in document_order(self.project.model) if self.state.get(e.uuid) == PARENT]
        return kept + chosen

    def apply(self):
        value, current = self.selected, list(self.owner.get(self.FIELD) or [])
        if value == current:
            return []
        self.owner.set(self.FIELD, value)
        if self.project.model.get(self.owner.uuid) is self.owner:
            self.project.update(self.owner)
        return [self.owner]


class TraceSectionsDialog(TraceItemsDialog):
    """Only the sections (three numbers, e.g. 3.4.1), with ticks: e.g. those allocated to a new domain."""
    CHOOSABLE = ("Sezione",)

    def __init__(self, project, owner, field, parent=None):
        super().__init__(project, owner, field, parent)
        label = owner.schema.field(field).label
        self.HINT = (f"Spunta le sezioni (tre numeri, es. 3.4.1) di «{label}»: quante servono, un clic sulla spunta "
                     "la toglie. Doppio clic su una riga per leggerne il testo completo.")

    def count_text(self):
        n = len(self.chosen(PARENT))
        return "Nessuna sezione scelta" if not n else "1 sezione scelta" if n == 1 else f"{n} sezioni scelte"


class TraceReallocItemsDialog(TraceItemsDialog):
    """ADR of a reallocation (X-1): the SRS clauses to reallocate (or a section), one or more, provided they belong
    to the same section: those of another section are refused, with the advice to open a separate ADR."""

    def __init__(self, project, owner, field, parent=None):
        super().__init__(project, owner, field, parent)
        self.HINT = ("Spunta le clausole (es. 3.4.1.3) da riallocare, o la sezione (es. 3.4.1): una o più, purché "
                     "della stessa sezione; per voci di sezioni diverse apri ADR separate. Doppio clic su una riga "
                     "per leggerne il testo completo.")

    def click(self, item, choice):
        from arcadia_tool.model.adr import same_section, section_of

        model = self.project.model
        uuid = item.data(0, UUID_ROLE)
        if self.state[uuid] != PARENT:
            chosen = [model.get(u) for u in self.chosen(PARENT)]
            if chosen and not same_section(model, [*chosen, model.get(uuid)]):
                section, other = section_of(model, chosen[0]), section_of(model, model.get(uuid))

                def named(s):
                    return f"alla sezione {s.get('id')}" if s is not None else "a nessuna sezione"
                QMessageBox.warning(
                    self, "Sezioni o clausole da riallocare",
                    f"Non è possibile aggiungere «{model.label_of(uuid)}»: appartiene {named(other)}, mentre le voci "
                    f"già scelte appartengono {named(section)}.\n\nUna ADR di riallocazione riguarda voci di una sola "
                    "sezione: per riallocare voci di sezioni diverse apri ADR separate, una per sezione.")
                return
        super().click(item, choice)


# Windows for a list field of SRS items with a rule of its own.
ITEMS_DIALOGS = {"realloc_item": TraceReallocItemsDialog}


def choose_items(project, element, field, current, parent=None, sections_only=False):
    """SRS items of a list field of a sheet (its draft), chosen with ticks: the new list, or None if cancelled.
    sections_only: only the sections (three numbers) can be chosen."""
    probe = element.copy()  # the window works on a copy: the sheet applies the choice with its «Salva»
    probe.set(field, list(current))
    dialog_class = ITEMS_DIALOGS.get(field) or (TraceSectionsDialog if sections_only else TraceItemsDialog)
    dialog = dialog_class(project, probe, field, parent)
    return dialog.selected if dialog.exec() else None


class TraceSrsDialog(_TraceDialog):
    """Functional domain (SA-1): principal and contributing domain of sections and clauses (A4)."""
    TITLE = "sezioni e clausole SRS"
    COLUMNS = ((PRINCIPAL, "Principale"), (CONTRIBUTES, "Contribuisce"))
    OWNER_HEADER = "Dominio principale attuale"
    HINT = ("Clic su «Principale» se il dominio è il dominio principale della voce (uno solo per voce), su "
            "«Contribuisce» se vi contribuisce. Le sezioni hanno tre numeri (es. 3.4.1), le clausole di più "
            "(es. 3.4.1.3). Doppio clic su una riga per leggerne il testo completo.")
    REPLACE_TITLE = "Dominio principale già assegnato"
    REPLACE_TEXT = ("{n} voci hanno già un altro dominio principale ({names}). Ogni voce ha un solo dominio "
                    "principale: sostituirlo con questo dominio?")

    @property
    def domain(self):
        return self.owner

    def initial_state(self, e):
        if e.get("primary_domain") == self.domain.uuid:
            return PRINCIPAL
        return CONTRIBUTES if self.domain.uuid in (e.get("contributing_domains") or []) else None

    def stored_owner(self, e):
        return e.get("primary_domain")

    def owner_after_apply(self, e, state):
        if state == PRINCIPAL:
            return self.domain.uuid
        stored = e.get("primary_domain")
        return stored if stored != self.domain.uuid else None

    def count_text(self):
        return f"{len(self.chosen(PRINCIPAL))} principali · {len(self.chosen(CONTRIBUTES))} contributi"

    def selection(self):
        """(uuids of which the domain is principal, uuids to which it contributes)."""
        return self.chosen(PRINCIPAL), self.chosen(CONTRIBUTES)

    def apply(self):
        return self.project.trace_srs(self.domain, *self.selection())


class TraceFunctionDialog(_TraceDialog):
    """System function (SA-2): the sections and clauses it is allocated to.

    Logical function (LA-2): also the derived requirements (SA-4), listed under the clause they come from. A
    derived requirement has one logical function: choosing it here moves it, after a confirmation."""
    COLUMNS = ((ALLOCATED, "Allocata"),)
    REPLACE_TITLE = "Requisito derivato già allocato"
    REPLACE_TEXT = ("{n} requisiti derivati sono già allocati a un'altra funzione logica ({names}). Un requisito "
                    "derivato ha una sola funzione logica: spostarli su questa?")

    @property
    def function(self):
        return self.owner

    @property
    def WITH_DERIVED(self):
        return self.function.kind == "logical_function"

    @property
    def TITLE(self):
        return ("allocazione a sezioni, clausole e requisiti derivati" if self.WITH_DERIVED
                else "allocazione a sezioni e clausole SRS")

    @property
    def OWNER_HEADER(self):
        return "Funzione logica del requisito derivato" if self.WITH_DERIVED else ""

    @property
    def HINT(self):
        if not self.WITH_DERIVED:
            return ("Clic su «Allocata» per allocare la funzione alla sezione (es. 3.4.1) o alla clausola "
                    "(es. 3.4.1.3). Doppio clic su una riga per leggerne il testo completo.")
        return ("Clic su «Allocata» per allocare la funzione alla sezione (es. 3.4.1), alla clausola (es. 3.4.1.3) "
                "o al requisito derivato (sotto la sua voce madre, con l'icona a forcella; una sola funzione logica "
                "per requisito). Clic destro su una voce per derivarne un nuovo requisito, doppio clic per leggerne "
                "il testo completo.")

    def initial_state(self, e):
        if e.kind == "derived_requirement":
            return ALLOCATED if e.get("function") == self.function.uuid else None
        return ALLOCATED if e.uuid in (self.function.get(SRS_FIELD[self.function.kind]) or []) else None

    def stored_owner(self, e):
        return e.get("function") if e.kind == "derived_requirement" else None

    def owner_after_apply(self, e, state):
        """The logical function of a derived requirement as it will be after «Applica»."""
        if e.kind != "derived_requirement":
            return None
        if state == ALLOCATED:
            return self.function.uuid
        stored = e.get("function")
        return stored if stored != self.function.uuid else None

    def count_text(self):
        model = self.project.model
        chosen = [model.get(u) for u in self.chosen(ALLOCATED)]
        derived = sum(1 for e in chosen if e.kind == "derived_requirement")
        text = f"{len(chosen) - derived} sezioni e clausole"
        return f"{text} · {derived} requisiti derivati" if self.WITH_DERIVED else text

    def apply(self):
        model = self.project.model
        chosen = self.chosen(ALLOCATED)
        srs = {u for u in chosen if model.get(u).kind == "requirement"}
        return self.project.allocate_function(self.function, srs, chosen - srs, shown=set(self.state))
