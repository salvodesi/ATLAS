"""Left panel, in two tabs: «Modello», the navigator phase → element kind → elements (nested when a kind has a
parent of the same kind), and «Viste grafiche», the graphic views of the SA grouped by type. The tabs are chosen
from the bar of icons at its left (ui.activity_bar), which also closes and opens the panel."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QTabBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from arcadia_tool.model.diagrams import BREAKDOWN_TYPES, BREAKDOWN_VIEWS, DIAGRAM, VIEW_GROUPS, views_of
from arcadia_tool.model.element import natural_key
from arcadia_tool.model.identifiers import CREATION_CONTEXT
from arcadia_tool.ui.element_list import LIST_COLUMNS
from arcadia_tool.model.schema import DIAGRAM_TYPES, GROUPS, KINDS, KINDS_BY_NAME
from arcadia_tool.ui.element_editor import RefPicker
from arcadia_tool.ui.srs_edit_mode import SrsEditMode
from arcadia_tool.ui.srs_reader import confirm_delete
from arcadia_tool.ui.theme import ACCENT, GROUP_ICONS, MUTED, icon, kind_icon

KIND_ROLE = Qt.UserRole
UUID_ROLE = Qt.UserRole + 1
# Tab «Viste grafiche»: on a group, the type of its views; on a functional breakdown, the kind of its SA.
VIEWS_ROLE = Qt.UserRole + 2
BREAKDOWN_ROLE = Qt.UserRole + 3
MODEL_TAB, VIEWS_TAB = 0, 1
# Kinds shown first in their group of the tree (the others in the order of the schema): the external actors
# before the domains (SA-1), as the context of the system comes before its decomposition.
TREE_FIRST = ("external_actor",)
# Not in the tree of the elements: the views have their own tab.
NOT_IN_TREE = (DIAGRAM,)


TAB_ICONS = ("mdi6.file-tree-outline", "mdi6.vector-polyline")


def _navigator():
    tree = QTreeWidget(objectName="navigator")  # the style of the navigator (see theme)
    tree.setColumnCount(2)
    tree.setHeaderHidden(True)
    tree.header().setStretchLastSection(False)
    tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
    tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
    tree.setIndentation(14)
    tree.setUniformRowHeights(True)
    tree.setContextMenuPolicy(Qt.CustomContextMenu)
    return tree


def _search(placeholder):
    line = QLineEdit(placeholderText=placeholder, objectName="search")
    line.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
    line.setClearButtonEnabled(True)
    return line


def _self_parent_field(kind):
    f = kind.field("parent")
    return f if f is not None and f.ref_kinds == (kind.name,) else None


def _branches(item):
    """The item and every descendant that has children."""
    stack = [item]
    while stack:
        current = stack.pop()
        if current.childCount():
            yield current
            stack.extend(current.child(i) for i in range(current.childCount()))


def _fully_expanded(item):
    return all(branch.isExpanded() for branch in _branches(item))


def _set_expanded(item, expanded):
    for branch in _branches(item):
        branch.setExpanded(expanded)


class ModelTree(QFrame):
    element_selected = Signal(object)
    model_changed = Signal()
    srs_reader_requested = Signal()
    srs_window_requested = Signal()  # the SRS catalogue in a separate window
    import_requested = Signal()  # «Importa SRS…»: the SRS items from the PDFs of the SUBSET-026
    functions_import_requested = Signal()  # «Importa funzioni…» of SA-2: the catalogue in Excel of the teams
    element_created = Signal(str)  # «Nuovo…»: the uuid of the element just created (its sheet opens next)
    list_requested = Signal(str)  # a kind whose elements are shown as a table in a tab (e.g. X-2)
    breakdown_requested = Signal(str)  # the functional breakdown of the SA of this kind (SA-1 or SA-2)
    view_created = Signal(str)  # «Nuova vista»: the uuid of the view, created and to be saved with the project

    def __init__(self, srs_edit_mode=None):
        super().__init__(objectName="panel")
        self.project = None
        self.edit_denied = None  # function(kind) → why the user may not create or delete it, or None
        self.locks_out = None  # function(team without members) → True if deleting it leaves the user outside
        self.srs_edit_mode = srs_edit_mode or SrsEditMode()
        # Two tabs: the elements of the model, and the graphic views (kept apart from the elements).
        self.tabs = QTabBar()
        self.tabs.addTab(icon("mdi6.file-tree-outline"), "Modello")
        self.tabs.addTab(icon("mdi6.vector-polyline"), "Viste grafiche")
        self.tabs.setExpanding(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)  # a narrow panel shortens the titles, both tabs stay in sight
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.currentChanged.connect(lambda index: self.pages.setCurrentIndex(index))
        self.tabs.currentChanged.connect(lambda index: self.caption.setText(self.tabs.tabText(index).upper()))
        self.tabs.hide()  # chosen from the bar of icons (ActivityBar): the name of the one shown on top
        self.caption = QLabel(self.tabs.tabText(0).upper(), objectName="sectionCaption")

        self.filter = _search("Cerca per ID o nome")
        self.filter.textChanged.connect(self._apply_filter)
        self.tree = _navigator()
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.setExpandsOnDoubleClick(False)
        model_page = QWidget()
        model_layout = QVBoxLayout(model_page)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(8)
        model_layout.addWidget(self.filter)
        model_layout.addWidget(self.tree, 1)

        self.views_filter = _search("Cerca una vista")
        self.views_filter.textChanged.connect(self._apply_views_filter)
        self.new_view_button = QPushButton(icon("mdi6.plus", "white"), "Nuova vista…")
        self.new_view_button.setProperty("primary", True)
        self.new_view_button.setToolTip("Nuovo dataflow funzionale, catena funzionale o scenario di scambio")
        self.new_view_button.clicked.connect(lambda _checked=False: self.create_view())
        self.views = _navigator()
        self.views.customContextMenuRequested.connect(self._views_menu)
        self.views.currentItemChanged.connect(self._view_changed)
        self.views.itemClicked.connect(lambda item, _column: self._view_changed(item, None))  # also once selected
        views_page = QWidget()
        views_layout = QVBoxLayout(views_page)
        views_layout.setContentsMargins(0, 0, 0, 0)
        views_layout.setSpacing(8)
        views_layout.addWidget(self.views_filter)
        views_layout.addWidget(self.new_view_button)
        views_layout.addWidget(self.views, 1)

        self.pages = QStackedWidget()
        self.pages.addWidget(model_page)
        self.pages.addWidget(views_page)
        # Elements are created and deleted from the context menu; below the tree the window puts its own
        # buttons (see add_footer).
        self.footer = QHBoxLayout()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.tabs)
        layout.addWidget(self.caption)
        layout.addWidget(self.pages, 1)
        layout.addLayout(self.footer)
        self._kind_items = {}
        self._items = {}
        self._view_groups = {}  # diagram type (None: the functional breakdown) → its group in «Viste grafiche»
        self._view_items = {}  # uuid of a view → its item

    def add_footer(self, widget):
        self.footer.addWidget(widget)

    def set_project(self, project):
        self.project = project
        self.reload()

    # --- building ------------------------------------------------------------------------------

    def reload(self, select_uuid=None):
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        expanded = {k for k, item in self._kind_items.items() if item.isExpanded()}
        self.tree.clear()
        self._kind_items, self._items = {}, {}
        if self.project is not None:
            self._build(expanded)
        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)
        self._apply_filter(self.filter.text())
        self._build_views()
        if select_uuid in self._items or select_uuid in self._view_items:
            self.select(select_uuid)

    def _build(self, expanded):
        bold = QFont()
        bold.setWeight(QFont.DemiBold)
        muted = QBrush(QColor(MUTED))
        groups = {}
        for g in GROUPS:
            item = QTreeWidgetItem(self.tree, [g, ""])
            item.setIcon(0, icon(GROUP_ICONS[g], "#3D4B5C"))
            item.setFont(0, bold)
            item.setFlags(Qt.ItemIsEnabled)
            item.setExpanded(True)
            groups[g] = item
        model = self.project.model
        kinds = [k for k in KINDS if k.name not in NOT_IN_TREE]
        for k in sorted(kinds, key=lambda k: TREE_FIRST.index(k.name) if k.name in TREE_FIRST else len(TREE_FIRST)):
            elements = model.of_kind(k.name)
            title = f"{k.template} · {k.plural}" if k.template else k.plural
            kind_item = QTreeWidgetItem(groups[k.group], [title, str(len(elements))])
            kind_item.setIcon(0, kind_icon(k.name))
            kind_item.setForeground(1, muted)
            kind_item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            kind_item.setData(0, KIND_ROLE, k.name)
            self._kind_items[k.name] = kind_item
            parent_field = _self_parent_field(k)
            if parent_field is None:
                for e in elements:
                    self._add(kind_item, e)
            else:
                uuids = {e.uuid for e in elements}
                children = {}
                for e in elements:
                    parent = e.get(parent_field.name)
                    children.setdefault(parent if parent in uuids else None, []).append(e)
                self._add_nested(kind_item, None, children)
            kind_item.setExpanded(k.name in expanded)

    def _build_views(self):
        """Tab «Viste grafiche»: the functional breakdown of SA-1 and SA-2, then the views of the users, a group for
        each type (with its SA)."""
        collapsed = {t for t, item in self._view_groups.items() if not item.isExpanded()}
        current = self.views.currentItem()
        current = (current.data(0, UUID_ROLE) or current.data(0, BREAKDOWN_ROLE)) if current else None
        self.views.blockSignals(True)
        self.views.clear()
        self._view_groups, self._view_items = {}, {}
        if self.project is not None:
            bold = QFont()
            bold.setWeight(QFont.DemiBold)
            muted, accent = QBrush(QColor(MUTED)), QBrush(QColor(ACCENT))
            for title, diagram_type in VIEW_GROUPS:
                views = views_of(self.project.model, diagram_type)
                group = QTreeWidgetItem(self.views, [title, str(len(views))])
                group.setFont(0, bold)
                group.setIcon(0, icon("mdi6.view-grid-outline" if diagram_type in BREAKDOWN_TYPES
                                      else "mdi6.vector-polyline", "#3D4B5C"))
                group.setForeground(1, muted)
                group.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                group.setData(0, VIEWS_ROLE, diagram_type)
                group.setFlags(Qt.ItemIsEnabled)
                self._view_groups[diagram_type] = group
                # First, the breakdown of the whole model of its SA.
                for kind, (name, _all_open, group_type) in BREAKDOWN_VIEWS.items():
                    if group_type == diagram_type:
                        item = QTreeWidgetItem(group, [name, "tutto il modello"])
                        item.setIcon(0, icon("mdi6.view-grid-outline", ACCENT))
                        item.setForeground(0, accent)
                        item.setForeground(1, muted)
                        item.setData(0, BREAKDOWN_ROLE, kind)
                        item.setToolTip(0, f"{KINDS_BY_NAME[kind].template}: i domini funzionali e le loro "
                                           "funzioni di sistema")
                        if current == kind:
                            self.views.setCurrentItem(item)
                for view in views:
                    item = QTreeWidgetItem(group, [view.get("name") or "(vista senza nome)", ""])
                    item.setIcon(0, icon("mdi6.vector-polyline", ACCENT))
                    item.setForeground(0, accent)
                    item.setData(0, KIND_ROLE, DIAGRAM)
                    item.setData(0, UUID_ROLE, view.uuid)
                    item.setToolTip(0, view.get("description") or view.get("name") or "")
                    self._view_items[view.uuid] = item
                    if current == view.uuid:
                        self.views.setCurrentItem(item)
                if diagram_type not in BREAKDOWN_TYPES and not views:
                    empty = QTreeWidgetItem(group, ["nessuna vista: clic destro per crearne una"])
                    empty.setForeground(0, muted)
                    empty.setFlags(Qt.ItemIsEnabled)
                group.setExpanded(diagram_type not in collapsed)
        self.views.blockSignals(False)
        self._apply_views_filter(self.views_filter.text())

    def _apply_views_filter(self, text):
        text = text.lower().strip()
        for group in self._view_groups.values():
            shown = 0
            for i in range(group.childCount()):
                child = group.child(i)
                hidden = bool(text) and text not in child.text(0).lower()
                child.setHidden(hidden)
                shown += not hidden
            group.setHidden(bool(text) and not shown)

    def _add(self, parent_item, element):
        label = self.project.model.choice_label(element)  # elements are chosen here: with their short name
        item = QTreeWidgetItem(parent_item, [label, ""])
        item.setData(0, KIND_ROLE, element.kind)
        item.setData(0, UUID_ROLE, element.uuid)
        item.setToolTip(0, element.get("text") or label)
        self._items[element.uuid] = item
        return item

    def _add_nested(self, parent_item, parent_uuid, children):
        # Imported SRS items keep their position in the document (procedure rows S0, S1, D2…).
        def key(e):
            return e.get("sequence") is None, e.get("sequence") or 0, natural_key(e.get("id") or e.label)

        for e in sorted(children.get(parent_uuid, []), key=key):
            item = self._add(parent_item, e)
            self._add_nested(item, e.uuid, children)

    def refresh_label(self, element):
        item = self._items.get(element.uuid)
        if item is not None:
            item.setText(0, self.project.model.choice_label(element))
        view = self._view_items.get(element.uuid)
        if view is not None:
            view.setText(0, element.get("name") or "(vista senza nome)")

    def clear_selection(self):
        for tree in (self.tree, self.views):
            tree.blockSignals(True)  # the page is already closed: nothing to announce
            tree.setCurrentItem(None)
            tree.clearSelection()
            tree.blockSignals(False)

    def select(self, uuid):
        if uuid in self._view_items:  # a view: in its tab
            self.tabs.setCurrentIndex(VIEWS_TAB)
            self.views.setCurrentItem(self._view_items[uuid])
            self.views.scrollToItem(self._view_items[uuid])
            return
        item = self._items.get(uuid)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def current_element(self):
        item = self.tree.currentItem()
        uuid = item.data(0, UUID_ROLE) if item else None
        return self.project.model.get(uuid) if uuid and self.project else None

    # --- filtering -----------------------------------------------------------------------------

    def _apply_filter(self, text):
        text = text.lower().strip()

        def visit(item):
            matches = bool(text) and text in item.text(0).lower()
            any_child = False
            for i in range(item.childCount()):
                any_child |= visit(item.child(i))
            visible = not text or matches or any_child
            item.setHidden(not visible)
            if text and any_child:
                item.setExpanded(True)
            return visible

        self.tree.setUpdatesEnabled(False)
        for kind_item in self._kind_items.values():
            for i in range(kind_item.childCount()):
                visit(kind_item.child(i))
            kind_item.setHidden(False)
        self.tree.setUpdatesEnabled(True)

    # --- actions -------------------------------------------------------------------------------

    def _current_changed(self, current, _previous):
        uuid = current.data(0, UUID_ROLE) if current else None
        self.element_selected.emit(self.project.model.get(uuid) if uuid and self.project else None)

    def _view_changed(self, current, _previous):
        """A click in «Viste grafiche»: the view opens (a functional breakdown, or a view of the users)."""
        if current is None or self.project is None:
            return
        if current.data(0, BREAKDOWN_ROLE):
            self.breakdown_requested.emit(current.data(0, BREAKDOWN_ROLE))
        elif current.data(0, UUID_ROLE):
            self.element_selected.emit(self.project.model.get(current.data(0, UUID_ROLE)))

    def _double_clicked(self, item, _column):
        kind = item.data(0, KIND_ROLE)
        if kind == "requirement" and not item.data(0, UUID_ROLE):
            self.srs_reader_requested.emit()
        elif kind in LIST_COLUMNS and not item.data(0, UUID_ROLE):
            self.list_requested.emit(kind)  # a tab with its elements as a table, instead of the branch
        elif item.childCount():
            # The whole branch: expanded at once, or collapsed again if it is already fully expanded.
            self.tree.setUpdatesEnabled(False)
            _set_expanded(item, not _fully_expanded(item))
            self.tree.setUpdatesEnabled(True)

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item or not item.data(0, KIND_ROLE) or not self.project:
            return
        kind = item.data(0, KIND_ROLE)
        uuid = item.data(0, UUID_ROLE)
        menu = QMenu(self)
        locked = kind == "requirement" and not self.srs_edit_mode.enabled
        if kind == "requirement" and not uuid:
            menu.addAction(icon("mdi6.file-import-outline"), "Importa SRS…",
                           lambda _=False: self.import_requested.emit())
            menu.addSeparator()
            menu.addAction(icon("mdi6.book-open-page-variant-outline"), "Consulta il SUBSET-026",
                           lambda _=False: self.srs_reader_requested.emit())
            menu.addAction(icon("mdi6.open-in-new"), "Apri in altra finestra",
                           lambda _=False: self.srs_window_requested.emit())
            toggle = menu.addAction(icon("mdi6.lock-open-variant-outline"), "Modalità modifica delle voci SRS")
            toggle.setCheckable(True)
            toggle.setChecked(self.srs_edit_mode.enabled)
            toggle.toggled.connect(self.srs_edit_mode.set_enabled)
            delete_all = menu.addAction(icon("mdi6.delete-sweep-outline"), "Elimina tutte le voci SRS…",
                                        lambda _=False: self.delete_all_requirements())
            # Enabled also in read-only mode: it offers to switch to edit mode (a greyed entry looked broken).
            delete_all.setEnabled(bool(self.project.model.of_kind("requirement")))
            menu.addSeparator()
        denied = self.edit_denied(kind) if self.edit_denied else None
        if kind == "system_function" and not uuid:
            imported = menu.addAction(icon("mdi6.file-import-outline"), "Importa funzioni…",
                                      lambda _=False: self.functions_import_requested.emit())
            imported.setEnabled(not denied)
            imported.setToolTip(denied or "")
            menu.addSeparator()
        if denied:
            menu.setToolTipsVisible(True)
        new = menu.addAction(icon("mdi6.plus"), f"Nuovo: {KINDS_BY_NAME[kind].label}",
                             lambda _=False: self.create(kind))
        new.setEnabled(not locked and not denied)
        new.setToolTip(denied or "")
        if uuid:
            element = self.project.model.get(uuid)
            for child_kind, field in CREATION_CONTEXT.items():
                if kind in KINDS_BY_NAME[child_kind].field(field).ref_kinds:
                    label = f"Nuovo: {KINDS_BY_NAME[child_kind].label} per {element.get('id') or ''}".strip()
                    menu.addAction(icon("mdi6.subdirectory-arrow-right"), label,
                                   lambda _=False, ck=child_kind, f=field: self.create(ck, {f: uuid}))
            menu.addSeparator()
            delete = menu.addAction(icon("mdi6.trash-can-outline"), "Elimina", lambda _=False: self._delete_selected())
            delete.setEnabled(not locked and not denied)
            delete.setToolTip(denied or "")
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _views_menu(self, pos):
        """Menu of «Viste grafiche»: on a group, a new view of its type; on a view, open, rename, delete; on the
        functional breakdown, open."""
        if self.project is None:
            return
        item = self.views.itemAt(pos)
        menu = QMenu(self)
        if item is not None and item.data(0, BREAKDOWN_ROLE):
            menu.addAction(icon("mdi6.open-in-app"), "Apri",
                           lambda _=False: self.breakdown_requested.emit(item.data(0, BREAKDOWN_ROLE)))
        elif item is not None and item.data(0, UUID_ROLE):
            view = self.project.model.get(item.data(0, UUID_ROLE))
            menu.addAction(icon("mdi6.open-in-app"), "Apri", lambda _=False: self.element_selected.emit(view))
            menu.addAction(icon("mdi6.rename-outline"), "Rinomina…", lambda _=False: self.rename_view(view))
            menu.addSeparator()
            menu.addAction(icon("mdi6.trash-can-outline"), "Elimina la vista",
                           lambda _=False: self.delete_element(view))
        else:
            group = item if item is None or item.parent() is None else item.parent()
            diagram_type = group.data(0, VIEWS_ROLE) if group is not None else None
            # On a group, «Nuova vista…» of its type; elsewhere, one for each group.
            for title, t in VIEW_GROUPS:
                if t == diagram_type or not diagram_type:
                    label = "Nuova vista…" if diagram_type else f"Nuova vista in {title}…"
                    menu.addAction(icon("mdi6.plus"), label,
                                   lambda _=False, t=t: self.create_view(t))
        menu.exec(self.views.viewport().mapToGlobal(pos))

    def create_view(self, diagram_type=None):
        """«Nuova vista»: asks its name and, for a chain or a scenario, the chain; the type too, only from
        «+ Nuova vista…» (from the group of an SA it is the type of the group). It opens to be composed with the
        elements of the model."""
        from arcadia_tool.ui.diagrams import NewViewDialog
        dialog = NewViewDialog(self.project.model, [diagram_type] if diagram_type else DIAGRAM_TYPES, self)
        if not dialog.exec():
            return None
        view = self.project.new_element(DIAGRAM, **dialog.values())
        self.view_created.emit(view.uuid)
        self.reload(select_uuid=view.uuid)
        self.model_changed.emit()
        return view

    def rename_view(self, view):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Rinomina la vista", "Nome della vista:", text=view.get("name") or "")
        if not ok or not name.strip() or name.strip() == view.get("name"):
            return
        previous = view.copy()
        view.set("name", name.strip())
        self.project.update(view, previous)
        self.reload(select_uuid=view.uuid)
        self.model_changed.emit()

    def _new_from_selection(self):
        item = self.tree.currentItem()
        if self.project and item and item.data(0, KIND_ROLE):
            self.create(item.data(0, KIND_ROLE))
        elif self.project:
            QMessageBox.information(self, "Nuovo elemento", "Seleziona nel modello il tipo di elemento da creare.")

    def _ask_context(self, kind):
        """For kinds that belong to another element (e.g. a system function to a domain) ask which one."""
        field = KINDS_BY_NAME[kind].field(CREATION_CONTEXT[kind])
        candidates = self.project.model.of_kind(*field.ref_kinds)
        if kind == "derived_requirement" and candidates:
            # The SRS item is chosen like in the other traceability windows: chapters, search, ticks.
            from arcadia_tool.ui.srs_trace import TraceParentDialog
            dialog = TraceParentDialog(self.project, None, self)
            return {field.name: dialog.parent} if dialog.exec() and dialog.parent else None
        if not candidates:
            needed = " / ".join(KINDS_BY_NAME[k].label for k in field.ref_kinds)
            QMessageBox.information(self, "Nuovo elemento",
                                    f"Per creare un elemento «{KINDS_BY_NAME[kind].label}» serve prima: {needed}.")
            return None
        current = self.current_element()
        preselect = {current.uuid} if current and current.kind in field.ref_kinds else set()
        if kind == "clarification":
            # Possible recipients: the Design Authority first, then the teams.
            candidates = sorted(candidates, key=lambda t: not t.get("design_authority"))
            preselect = {c.uuid for c in candidates[:1] if c.get("design_authority")} or preselect
        picker = RefPicker([(e.uuid, self.project.model.choice_label(e)) for e in candidates], preselect, self,
                           single=True, title=f"{KINDS_BY_NAME[kind].label}: {field.label}")
        if not picker.exec() or not picker.selected():
            return None
        return {field.name: picker.selected()[0]}

    def _locked(self, kind):
        """Imported SRS items can be created or deleted only in edit mode; the teams only by the members of the
        Design Authority (see edit_denied)."""
        denied = self.edit_denied(kind) if self.edit_denied else None
        if denied:
            QMessageBox.information(self, "Team", denied)
            return True
        if kind == "requirement" and not self.srs_edit_mode.enabled:
            QMessageBox.information(self, "Voci SRS in sola lettura",
                                    "Le voci SRS importate sono in sola lettura. Attiva la modalità modifica "
                                    "(pagina SUBSET-026, pagina della voce o clic destro su «Voci SRS»).")
            return True
        return False

    def create(self, kind, context=None):
        if self._locked(kind):
            return
        if kind == "adr" and not (context or {}).get("adr_type"):
            # The type first: it gives the template of the sheet (filled from the element selected, if any).
            from arcadia_tool.model.adr import adr_defaults, suggested_type
            from arcadia_tool.ui.adr_types import AdrTypeDialog
            dialog = AdrTypeDialog(self, preselect=suggested_type(self.current_element()))
            if not dialog.exec():
                return
            context = {**adr_defaults(self.project.model, dialog.adr_type, self.current_element()),
                       **(context or {})}
        if context is None and kind in CREATION_CONTEXT:
            context = self._ask_context(kind)
            if context is None:
                return
        element = self.project.new_element(kind, **(context or {}))
        self.element_created.emit(element.uuid)  # before its sheet opens (with the selection)
        self.reload(select_uuid=element.uuid)
        self.model_changed.emit()

    def delete_all_requirements(self):
        uuids = [e.uuid for e in self.project.model.of_kind("requirement")]
        if not uuids:
            return
        if not self.srs_edit_mode.enabled:
            answer = QMessageBox.question(self, "Voci SRS in sola lettura",
                                          "Le voci SRS importate sono in sola lettura. Attivare la modalità "
                                          "modifica per eliminarle?")
            if answer != QMessageBox.Yes:
                return
            self.srs_edit_mode.set_enabled(True)
        if confirm_delete(self, self.project, uuids, f"Eliminare tutte le {len(uuids)} voci SRS?"):
            self.reload()
            self.element_selected.emit(None)
            self.model_changed.emit()

    def _delete_selected(self):
        self.delete_element(self.current_element())

    def delete_element(self, element):
        """Delete an element of the model, after a confirmation (also from the table of a kind, e.g. X-2)."""
        if element is None or self._locked(element.kind):
            return False
        if element.kind == "team" and self.locks_out is not None:
            gone = element.copy()
            gone.set("members", [])
            if self.locks_out(gone):  # the team with the ID of the user (e.g. the DA): they would be left outside
                from arcadia_tool.ui.team_members import own_id_error
                own_id_error(self)
                return False
        answer = QMessageBox.question(self, "Elimina", f"Eliminare «{self.project.model.label(element)}»?")
        if answer != QMessageBox.Yes:
            return False
        self.project.delete_element(element.uuid)
        self.reload()
        self.element_selected.emit(None)
        self.model_changed.emit()
        return True
