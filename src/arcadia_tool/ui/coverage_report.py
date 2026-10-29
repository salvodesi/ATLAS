"""«Report di copertura…» of the SRS items page: the clauses of board and of definition, covered and not covered,
section by section («Per sezione») and down to the last clause («Per clausola», with their chapter 9 category). An
item is covered first of all at the level of the domains (A4); the report also shows, for each item, whether it is
covered at the level of the system functions (SA-2) and of the derived requirements (SA-4), with the percentage of
each level and the coverage of the subset. Exported to Excel."""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from arcadia_tool.model.coverage import DERIVED, DOMAIN, FUNCTION, LEVELS, REPORT_CATEGORIES, coverage, \
    subset_coverage
from arcadia_tool.storage.coverage_report import domains_text, write_coverage
from arcadia_tool.ui.srs_reader import CATEGORY_COLORS, document_order
from arcadia_tool.ui.srs_trace import SHOWN, SrsItemViewer
from arcadia_tool.ui.theme import BORDER, MUTED, icon

COVERED, NOT_COVERED = "#166534", "#B42318"
# «Per clausola»: the sections, and under them their clauses down to the last one.
COLUMNS = ("Voce SRS", "Categoria", "Testo", "Dominio funzionale", "Funzioni di sistema", "Requisiti derivati",
           "Copertura")
IDENT, CATEGORY, TEXT, DOMAINS, FUNCTIONS, DERIVATIONS, STATE = range(len(COLUMNS))
# «Per sezione»: one row per section, the coverage of its clauses.
SECTION_COLUMNS = ("Sezione", "Titolo", "Clausole", "Dominio", "Funzione di sistema", "Requisito derivato",
                   "Scoperte")
SECTION_TIPS = ("", "", "Clausole della categoria nella sezione, fino all'ultima",
                "Clausole coperte a livello di dominio funzionale (A4): la copertura",
                "Clausole coperte a livello di funzione di sistema (SA-2)",
                "Clausole coperte a livello di requisito derivato (SA-4)", "Clausole senza dominio funzionale")
FILTERS = (("Tutte le voci", None), ("Coperte (dominio)", lambda r: r.covered),
           ("Scoperte (dominio)", lambda r: not r.covered),
           ("Senza funzione di sistema", lambda r: not r.at(FUNCTION)),
           ("Senza requisito derivato", lambda r: not r.at(DERIVED)))
UUID_ROLE = Qt.UserRole
NO_SECTION = "(fuori sezione)"


def reports(model):
    ordered = document_order(model)
    return [coverage(model, ordered, c) for c in REPORT_CATEGORIES]


def share(report, level):
    return f"{report.count(level)} ({report.percent(level):.1f}%)"


def _bold(entry, column):
    font = entry.font(column)
    font.setBold(True)
    entry.setFont(column, font)


class CategoryPage(QWidget):
    """The clauses of a category: the percentages of the three levels, then two views: «Per sezione» (the coverage
    of each section) and «Per clausola» (the sections and their clauses down to the last one), with a filter and a
    search."""

    def __init__(self, model, report, show_item=None):
        super().__init__()
        self.model, self.report, self.show_item = model, report, show_item
        layout = QVBoxLayout(self)
        tiles = QGridLayout()
        for c, (level, label) in enumerate(LEVELS):
            tiles.addWidget(self._tile(f"Coperte · {label}", report.count(level), report.percent(level),
                                       main=level == DOMAIN), 0, c)
        uncovered = len(report.uncovered)
        tiles.addWidget(self._tile("Scoperte (dominio)", uncovered,
                                   100.0 * uncovered / report.total if report.total else 0.0, bad=True), 0, len(LEVELS))
        layout.addLayout(tiles)
        self.views = QTabWidget()
        self.views.setDocumentMode(True)
        self.by_section = self._section_table()
        self.views.addTab(self.by_section, icon("mdi6.format-list-numbered"), "Per sezione")
        clauses = QWidget()
        clauses_layout = QVBoxLayout(clauses)
        clauses_layout.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        self.filter = QComboBox()
        for label, _test in FILTERS:
            self.filter.addItem(label)
        self.filter.currentIndexChanged.connect(self._apply)
        self.search = QLineEdit(placeholderText="Cerca per numero, categoria, testo, dominio o funzione",
                                objectName="search")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply)
        self.shown = QLabel(objectName="muted")
        row.addWidget(self.filter)
        row.addWidget(self.search, 1)
        row.addWidget(self.shown)
        clauses_layout.addLayout(row)
        self.table = self._clause_tree()
        clauses_layout.addWidget(self.table, 1)
        self.views.addTab(clauses, icon("mdi6.file-tree-outline"), "Per clausola")
        layout.addWidget(self.views, 1)
        if not report.rows:
            self.views.hide()
            layout.addWidget(QLabel(f"Nessuna voce di categoria {report.category} tra le voci SRS del progetto.",
                                    objectName="muted", alignment=Qt.AlignCenter), 1)
        self._apply()

    def _tile(self, title, count, percent, main=False, bad=False):
        tile = QFrame(objectName="card")
        tile.setStyleSheet(f"QFrame#card {{ border: 1px solid {BORDER}; border-radius: 6px; background: white; }}")
        box = QVBoxLayout(tile)
        box.setContentsMargins(12, 8, 12, 8)
        box.addWidget(QLabel(title, objectName="muted"))
        color = NOT_COVERED if bad and count else COVERED if main and count == self.report.total else "#1F3A5F"
        value = QLabel(f"{percent:.1f}%")
        value.setStyleSheet(f"font-size: {18 if main else 15}pt; font-weight: 700; color: {color};")
        box.addWidget(value)
        box.addWidget(QLabel(f"{count} di {self.report.total} voci", objectName="muted"))
        return tile

    # --- per section -----------------------------------------------------------------------------------

    def _section_table(self):
        table = QTreeWidget()
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)
        table.setHeaderLabels(SECTION_COLUMNS)
        for c, tip in enumerate(SECTION_TIPS):
            table.headerItem().setToolTip(c, tip)
        header = table.header()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        table.setToolTip("Doppio clic: il testo della sezione · clic destro: le sue clausole")
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos: self._section_menu(table, pos))
        for s in self.report.sections():
            uncovered = len(s.uncovered)
            entry = QTreeWidgetItem([s.section.get("id") if s.section is not None else NO_SECTION,
                                     (s.section.get("title") or "") if s.section is not None else "", str(s.total),
                                     share(s, DOMAIN), share(s, FUNCTION), share(s, DERIVED), str(uncovered)])
            entry.setData(0, UUID_ROLE, s.section.uuid if s.section is not None else None)
            entry.setForeground(3, QBrush(QColor(COVERED if s.count(DOMAIN) == s.total else
                                                 NOT_COVERED if not s.count(DOMAIN) else "#92400E")))
            _bold(entry, 3)
            if uncovered:
                entry.setForeground(6, QBrush(QColor(NOT_COVERED)))
            for c in range(2, 7):
                entry.setTextAlignment(c, Qt.AlignCenter)
            table.addTopLevelItem(entry)
        table.itemDoubleClicked.connect(self._double_clicked)
        return table

    def _section_menu(self, table, pos):
        entry = table.itemAt(pos)
        if entry is None:
            return
        uuid = entry.data(0, UUID_ROLE)
        menu = QMenu(self)
        menu.addAction(icon("mdi6.file-tree-outline"), "Mostra le clausole della sezione",
                       lambda: self.show_section(uuid))
        if uuid:
            menu.addAction(icon("mdi6.text-box-outline"), "Leggi la sezione", lambda: self.show_item(uuid))
        menu.exec(table.viewport().mapToGlobal(pos))

    def show_section(self, uuid):
        """«Per clausola», on the clauses of a section."""
        self.views.setCurrentIndex(1)
        node = self._section_nodes.get(uuid)
        if node is not None:
            node.setExpanded(True)
            self.table.setCurrentItem(node)
            self.table.scrollToItem(node, QAbstractItemView.PositionAtTop)

    # --- per clause --------------------------------------------------------------------------------------

    def _clause_tree(self):
        tree = QTreeWidget()
        tree.setAlternatingRowColors(True)
        tree.setExpandsOnDoubleClick(False)  # the double click reads the item; only the arrow opens and closes it
        tree.setHeaderLabels(COLUMNS)
        header = tree.header()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(IDENT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(CATEGORY, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(TEXT, QHeaderView.Stretch)
        header.setSectionResizeMode(STATE, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        for column, width in ((DOMAINS, 220), (FUNCTIONS, 220), (DERIVATIONS, 150)):
            header.resizeSection(column, width)
        tree.itemDoubleClicked.connect(self._double_clicked)
        self._section_nodes, self._clauses = {}, []
        entries = {}
        for s in self.report.sections():
            node = QTreeWidgetItem([s.section.get("id") if s.section is not None else NO_SECTION, "",
                                    (s.section.get("title") or "") if s.section is not None else "",
                                    "", "", "", f"{s.count(DOMAIN)} di {s.total} coperte"])
            node.setData(0, UUID_ROLE, s.section.uuid if s.section is not None else None)
            for c in range(len(COLUMNS)):
                _bold(node, c)
            node.setForeground(STATE, QBrush(QColor(COVERED if s.count(DOMAIN) == s.total else NOT_COVERED)))
            tree.addTopLevelItem(node)
            self._section_nodes[s.section.uuid if s.section is not None else None] = node
            for r in s.rows:  # in the order of the specification: a clause after the one containing it
                entry = self._entry(r)
                parent = entries.get(r.parent.item.uuid) if r.parent is not None else None
                (parent or node).addChild(entry)
                entries[r.item.uuid] = entry
                self._clauses.append(entry)
        tree.expandAll()  # down to the last clause
        return tree

    def _entry(self, row):
        model = self.model
        text = " ".join((row.item.get("text") or row.item.get("title") or "").split())
        categories = row.item.get("category") or []
        entry = QTreeWidgetItem([row.item.get("id") or "", ", ".join(categories), text[:200],
                                 domains_text(model, row) or "—",
                                 ", ".join(model.label(f) for f in row.functions) or "—",
                                 ", ".join(model.label(d) for d in row.derived) or "—",
                                 "Coperta" if row.covered else "Scoperta"])
        entry.setData(0, UUID_ROLE, row.item.uuid)
        if categories:
            entry.setForeground(CATEGORY, QBrush(QColor(CATEGORY_COLORS.get(categories[0], (MUTED,))[0])))
        entry.setToolTip(TEXT, text[:800])
        for column in (DOMAINS, FUNCTIONS, DERIVATIONS):
            entry.setToolTip(column, entry.text(column))
            if entry.text(column) == "—":
                entry.setForeground(column, QBrush(QColor(MUTED)))
        entry.setForeground(STATE, QBrush(QColor(COVERED if row.covered else NOT_COVERED)))
        _bold(entry, STATE)
        entry.row = row
        return entry

    def _apply(self, *_args):
        test = FILTERS[self.filter.currentIndex()][1]
        words = self.search.text().lower().split()
        matching = set()
        for entry in self._clauses:
            haystack = " ".join(entry.text(c) for c in range(len(COLUMNS))).lower()
            if (test is None or test(entry.row)) and all(w in haystack for w in words):
                matching.add(id(entry))
        # A clause is shown when it matches, or when a clause inside it does (to reach it); a section when any does.
        for entry in reversed(self._clauses):
            inside = any(not entry.child(i).isHidden() for i in range(entry.childCount()))
            entry.setHidden(id(entry) not in matching and not inside)
        for node in self._section_nodes.values():
            node.setHidden(not any(not node.child(i).isHidden() for i in range(node.childCount())))
        self.shown.setText(f"{len(matching)} di {self.report.total}")

    def _double_clicked(self, entry, _column):
        """A section or a clause: its full text in a window of its own (from there, its sheet)."""
        uuid = entry.data(0, UUID_ROLE)
        if self.show_item is not None and uuid:
            self.show_item(uuid)


class CoverageReportDialog(QDialog):
    """The report: the coverage of the subset, a tab for the clauses of board and one for those of definition."""

    def __init__(self, project, open_item=None, parent=None):
        super().__init__(parent)
        self.project, self.open_item = project, open_item
        self.viewer = None
        self.sub_items = {}  # list items, bullets, figures… of each item, shown with its full text
        for e in document_order(project.model):
            if e.get("item_type") not in SHOWN:
                self.sub_items.setdefault(e.get("parent"), []).append(e)
        self.setWindowTitle("Report di copertura delle voci SRS")
        model = project.model
        self.reports = reports(model)
        covered, total, percent = subset_coverage(self.reports)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Copertura delle voci SRS di bordo e di definizione", objectName="cardTitle"))
        self.subset = QLabel(f"Copertura del subset a livello di dominio: {percent:.1f}% ({covered} di {total} "
                             "voci)")
        self.subset.setStyleSheet(f"font-size: 13pt; font-weight: 700; "
                                  f"color: {COVERED if total and covered == total else '#1F3A5F'};")
        layout.addWidget(self.subset)
        layout.addWidget(QLabel("Una voce è coperta se ha un dominio funzionale (principale o contributore), suo o "
                                "della sezione che la contiene (A4). Per ogni voce sono indicate anche le funzioni "
                                "di sistema (SA-2) e i requisiti derivati (SA-4) che la coprono, suoi o della "
                                "sezione. Doppio clic su una sezione o una clausola per leggerla in una finestra a "
                                "parte, da cui aprirne la scheda.", objectName="muted", wordWrap=True))
        self.tabs = QTabWidget()
        self.pages = {}
        for report in self.reports:
            page = CategoryPage(model, report, self.show_item)
            self.pages[report.category] = page
            index = self.tabs.addTab(page, f"{report.category} ({report.count(DOMAIN)}/{report.total} coperte)")
            self.tabs.tabBar().setTabTextColor(index, QColor(CATEGORY_COLORS[report.category][0]))
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Chiudi")
        export = QPushButton(icon("mdi6.microsoft-excel"), "Esporta in Excel…")
        export.setToolTip("Salva il report in un file Excel: riepilogo e un foglio per categoria")
        export.clicked.connect(lambda _=False: self.export())
        buttons.addButton(export, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(1200, 720)

    def show_item(self, uuid):
        """The full text of a section or a clause, in a window of its own; its button opens the sheet."""
        element = self.project.model.get(uuid)
        if element is None:
            return None
        if self.viewer is None:
            self.viewer = SrsItemViewer(self.project, self, open_item=self.open_item)
        self.viewer.show_item(element, self.sub_items)
        return self.viewer

    def export(self, path=None):
        """The report in an Excel file chosen by the user (path: given, without asking)."""
        if path is None:
            suggested = str(self.project.path.parent / f"Copertura_SRS_{date.today():%Y-%m-%d}.xlsx")
            path, _ = QFileDialog.getSaveFileName(self, "Esporta il report di copertura", suggested,
                                                  "Excel (*.xlsx)")
            if not path:
                return None
        try:
            write_coverage(self.project.model, self.reports, path, self.project.name)
        except OSError as exc:
            QMessageBox.critical(self, "Esporta il report di copertura", f"Il file non è stato salvato: {exc}")
            return None
        QMessageBox.information(self, "Esporta il report di copertura", f"Report salvato in:\n{path}")
        return path
