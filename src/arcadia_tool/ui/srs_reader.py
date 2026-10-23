"""Reading view of the imported SRS: the whole specification, chapter by chapter, item after item.

Items are shown with their full text in document order, can be filtered by chapter 9 category and
searched; several items can be selected (Shift+arrows, Ctrl/Shift+click) and deleted together.
"""
from html import escape

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QMenu, QMessageBox, QPushButton, QStyle, QStyledItemDelegate, QTabBar, QVBoxLayout, QWidget)

from arcadia_tool.importers.srs_pdf import chapter_of_item
from arcadia_tool.model.element import natural_key
from arcadia_tool.ui.element_editor import load_pixmap
from arcadia_tool.ui.srs_edit_mode import SrsEditMode, edit_mode_button
from arcadia_tool.ui.theme import ACCENT, ACCENT_SOFT, BORDER, MUTED, TEXT, icon

CATEGORIES = ("Bordo", "Terra", "Definizione", "Informativa", "Altro")
NO_CATEGORY = "Senza categoria"
CATEGORY_COLORS = {"Bordo": ("#1A5FB4", "#E3EEFB"), "Terra": ("#8A4B00", "#FDF0DC"),
                   "Definizione": ("#5E3C99", "#EFE8FA"), "Informativa": ("#4B5563", "#EEF1F5"),
                   "Altro": ("#6B7280", "#F3F4F6"), NO_CATEGORY: ("#B42318", "#FEE4E2")}
HEADINGS = {"Capitolo": 15, "Sezione": 12.5, "Titolo": 11}
ELEMENT_ROLE = Qt.UserRole
NUMBER_WIDTH = 150
INDENT = {"Voce": 28}
SLOW_LAYOUT_ITEMS = 300
FIGURE_SCALE = 1.6  # figures are rendered at 2x; shown slightly larger than on paper
HIGHLIGHT = "#FFE58F"


def document_order(model):
    """Requirements in specification order: depth-first along the parent relation, siblings by their position
    in the document (procedure rows S0, S1, D2… are not in alphabetical order), else by number."""
    elements = [e for e in model if e.kind == "requirement"]
    uuids = {e.uuid for e in elements}
    children = {}
    for e in elements:
        parent = e.get("parent")
        children.setdefault(parent if parent in uuids else None, []).append(e)
    for siblings in children.values():
        siblings.sort(key=lambda e: (e.get("sequence") is None, e.get("sequence") or 0,
                                     natural_key(e.get("id") or "")))
    ordered, stack = [], list(reversed(children.get(None, [])))
    while stack:
        e = stack.pop()
        ordered.append(e)
        stack.extend(reversed(children.get(e.uuid, [])))
    return ordered


def chapter_of(element):
    """The appendix of a chapter (A.3.x) is shown with its chapter."""
    return chapter_of_item(element.get("id"))


class SrsListModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.elements = []

    def set_elements(self, elements):
        self.beginResetModel()
        self.elements = elements
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.elements)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self.elements[index.row()]
        if role == ELEMENT_ROLE:
            return e
        if role == Qt.DisplayRole:
            return f"{e.get('id')} {e.get('title') or ''} {e.get('text') or ''}"
        return None


MARGIN_X = 14
PAD_TOP, PAD_BOTTOM, HEADING_PAD_TOP = 6, 8, 16
CHIPS_WIDTH = 140
CHIP_GAP = 4
WRAP = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop


class ItemDelegate(QStyledItemDelegate):
    """Draws an item like a page of the specification: number, full text, category chips.

    Painting uses plain QPainter text layout (no HTML documents): measuring thousands of items stays fast,
    and heights are cached per width.
    """

    def __init__(self, view, project=None):
        super().__init__(view)
        self.view = view
        self.project = project
        self._sizes = {}
        self._pixmaps = {}
        self.highlight = ""  # searched text, highlighted in the items (lower case)
        base = view.font()
        self.fonts = {"text": QFont(base), "bold": QFont(base), "italic": QFont(base), "chip": QFont(base)}
        self.fonts["bold"].setWeight(QFont.DemiBold)
        self.fonts["italic"].setItalic(True)
        self.fonts["chip"].setPointSizeF(base.pointSizeF() * 0.82)
        self.fonts["chip"].setWeight(QFont.DemiBold)
        for item_type, size in HEADINGS.items():
            f = QFont(base)
            f.setPointSizeF(size)
            f.setWeight(QFont.DemiBold)
            self.fonts[item_type] = f
        self.metrics = {key: QFontMetrics(f) for key, f in self.fonts.items()}
        self._chip_widths = {}

    def clear_cache(self):
        self._sizes.clear()

    def invalidate(self, uuid):
        for key in [k for k in self._sizes if k[0] == uuid]:
            del self._sizes[key]
        self._pixmaps.pop(uuid, None)

    def _pixmap(self, element):
        rel = element.values.get("figure")
        if not rel or self.project is None:
            return None
        if element.uuid not in self._pixmaps:
            self._pixmaps[element.uuid] = load_pixmap(self.project, rel)
        return self._pixmaps[element.uuid]

    @staticmethod
    def _image_size(pixmap, width):
        # Figures are rendered at 2x: show them at about their size on paper, never wider than the text.
        w = min(width, int(pixmap.width() / FIGURE_SCALE))
        return w, int(pixmap.height() * w / pixmap.width())

    def cached(self, uuid):
        return (uuid, self.view.viewport().width(), self.highlight) in self._sizes

    def _highlighted(self, key, colour, text, width):
        """Rich-text document of a block with the searched text highlighted, or None if it does not occur."""
        term = self.highlight
        if not term or term not in text.lower():
            return None
        lower, parts, start = text.lower(), [], 0
        while True:
            found = lower.find(term, start)
            if found < 0:
                parts.append(escape(text[start:]))
                break
            parts.append(escape(text[start:found]))
            parts.append(f"<span style='background-color:{HIGHLIGHT}; color:{TEXT};'>"
                         f"{escape(text[found:found + len(term)])}</span>")
            start = found + len(term)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.fonts[key])
        doc.setHtml(f"<div style='color:{colour};'>{''.join(parts).replace(chr(10), '<br>')}</div>")
        doc.setTextWidth(width)
        return doc

    # --- layout (shared by sizeHint and paint) ---------------------------------------------------------

    def _blocks(self, element):
        """(font key, colour, text) blocks of the body, in order."""
        title, text = element.get("title") or "", element.get("text") or ""
        if element.get("item_type") in HEADINGS:
            blocks = [(element.get("item_type"), TEXT, f"{element.get('id') or ''}   {title}".strip())]
            if text:
                blocks.append(("text", MUTED, text))
            return blocks
        blocks = []
        if title:
            blocks.append(("bold", TEXT, title))
        if text:
            blocks.append(("text", TEXT, text))
        if not blocks:
            blocks.append(("italic", MUTED, element.get("import_note") or "Nessun testo"))
        return blocks

    def _text_height(self, key, text, width):
        metrics = self.metrics[key]
        if "\n" not in text and metrics.horizontalAdvance(text) <= width:
            return metrics.height()  # one line: much cheaper than laying out the wrapped text
        return metrics.boundingRect(QRect(0, 0, width, 100000), WRAP, text).height()

    def _chip_width(self, category):
        if category not in self._chip_widths:
            self._chip_widths[category] = self.metrics["chip"].horizontalAdvance(category) + 14
        return self._chip_widths[category]

    def _chip_rows(self, categories, width):
        metrics = self.metrics["chip"]
        rows, row, used = [], [], 0
        for c in categories or [NO_CATEGORY]:
            w = self._chip_width(c)
            if row and used + w > width:
                rows.append(row)
                row, used = [], 0
            row.append((c, w))
            used += w + CHIP_GAP
        if row:
            rows.append(row)
        return rows, metrics.height() + 4

    def _layout(self, element, rect):
        heading = element.get("item_type") in HEADINGS
        left = rect.x() + MARGIN_X + INDENT.get(element.get("item_type"), 0)
        top = rect.y() + (HEADING_PAD_TOP if heading else PAD_TOP)
        right = rect.right() - MARGIN_X
        if heading:
            body_left, chips_left = left, None
        else:
            body_left, chips_left = left + NUMBER_WIDTH, right - CHIPS_WIDTH
        body_width = max((chips_left - 12 if chips_left else right) - body_left, 120)
        placed, y = [], top
        for key, colour, text in self._blocks(element):
            doc = self._highlighted(key, colour, text, body_width)
            if doc is not None:
                h = int(doc.size().height())
                placed.append(("rich", None, doc, QRect(body_left, y, body_width, h)))
            else:
                h = self._text_height(key, text, body_width)
                placed.append((key, colour, text, QRect(body_left, y, body_width, h)))
            y += h + 2
        pixmap = self._pixmap(element)
        if pixmap is not None and not pixmap.isNull():
            w, h = self._image_size(pixmap, body_width)
            placed.append(("image", None, pixmap, QRect(body_left, y + 4, w, h)))
            y += h + 10
        height = y - top
        chips = None
        if chips_left is not None:
            rows, chip_h = self._chip_rows(element.get("category"), CHIPS_WIDTH)
            chips = (chips_left, top, rows, chip_h)
            height = max(height, len(rows) * (chip_h + CHIP_GAP), self.metrics["bold"].height())
        return left, top, placed, chips, height + (top - rect.y()) + PAD_BOTTOM

    def sizeHint(self, option, index):
        element = index.data(ELEMENT_ROLE)
        width = self.view.viewport().width()
        key = (element.uuid, width, self.highlight)
        if key not in self._sizes:
            *_, height = self._layout(element, QRect(0, 0, width, 0))
            self._sizes[key] = QSize(width, height)
        return self._sizes[key]

    # --- painting ------------------------------------------------------------------------------------

    def paint(self, painter, option, index):
        element = index.data(ELEMENT_ROLE)
        rect = option.rect
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor(ACCENT_SOFT))
            painter.fillRect(rect.x(), rect.y(), 3, rect.height(), QColor(ACCENT))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor("#F6F8FB"))
        left, top, placed, chips, _ = self._layout(element, rect)
        if chips is not None:
            ident = element.get("id") or ""
            number_box = QRect(left, top, NUMBER_WIDTH - 10, rect.height())
            painter.setFont(self.fonts["bold"])
            if self.highlight and self.highlight in ident.lower():
                painter.fillRect(self.metrics["bold"].boundingRect(number_box, WRAP, ident).adjusted(-2, 0, 2, 0),
                                 QColor(HIGHLIGHT))
            painter.setPen(QColor(ACCENT))
            painter.drawText(number_box, WRAP, ident)
        for key, colour, content, box in placed:
            if key == "rich":
                painter.save()
                painter.translate(box.topLeft())
                content.drawContents(painter)
                painter.restore()
                continue
            if key == "image":
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(box, content)
                painter.setPen(QColor(BORDER))
                painter.drawRect(box.adjusted(-1, -1, 0, 0))
                continue
            painter.setFont(self.fonts[key])
            painter.setPen(QColor(colour))
            painter.drawText(box, WRAP, content)
        if chips is not None:
            chips_left, y, rows, chip_h = chips
            painter.setFont(self.fonts["chip"])
            painter.setRenderHint(QPainter.Antialiasing)
            for row in rows:
                x = chips_left + CHIPS_WIDTH - sum(w for _, w in row) - CHIP_GAP * (len(row) - 1)
                for c, w in row:
                    fg, bg = CATEGORY_COLORS.get(c, CATEGORY_COLORS["Altro"])
                    chip = QRect(x, y, w, chip_h)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(bg))
                    painter.drawRoundedRect(chip, 8, 8)
                    painter.setPen(QColor(fg))
                    painter.drawText(chip, Qt.AlignCenter, c)
                    x += w + CHIP_GAP
                y += chip_h + CHIP_GAP
        painter.setPen(QColor("#EEF1F5"))
        painter.drawLine(rect.x() + MARGIN_X, rect.bottom(), rect.right() - MARGIN_X, rect.bottom())
        painter.restore()


class SrsView(QListView):
    def resizeEvent(self, event):
        if event.size().width() != event.oldSize().width():
            self.itemDelegate().clear_cache()
            super().resizeEvent(event)
            self.scheduleDelayedItemsLayout()
        else:
            super().resizeEvent(event)


class SrsReader(QWidget):
    open_element = Signal(str)
    derive_requested = Signal(str)  # a derived requirement (SA-4) to create from an SRS item
    elements_deleted = Signal()

    def __init__(self, project, edit_mode=None):
        super().__init__()
        self.project = project
        self.chapter = None
        self._pending_refresh = True
        self.edit_mode = edit_mode or SrsEditMode()
        self.edit_mode.changed.connect(self._selection_changed)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._chapter_changed)

        self.search = QLineEdit(placeholderText="Cerca nel testo, per numero o per variabile", objectName="search")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.category_boxes = {}
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Categoria:", objectName="muted"))
        for c in CATEGORIES + (NO_CATEGORY,):
            box = QCheckBox(c)
            box.setChecked(True)
            box.toggled.connect(self.refresh)
            fg, _ = CATEGORY_COLORS[c]
            box.setStyleSheet(f"QCheckBox {{ color: {fg}; font-weight: 600; }}")
            self.category_boxes[c] = box
            filters.addWidget(box)
        filters.addSpacing(16)
        self.show_headings = QCheckBox("Mostra titoli e sezioni")
        self.show_headings.setChecked(True)
        self.show_headings.toggled.connect(self.refresh)
        filters.addWidget(self.show_headings)
        filters.addStretch()

        self.count = QLabel(objectName="muted")
        self.delete_button = QPushButton(icon("mdi6.trash-can-outline"), "Elimina selezionate")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_selected)
        self.edit_mode_button = edit_mode_button(self.edit_mode)
        top_row = QHBoxLayout()
        top_row.addWidget(self.search, 1)
        top_row.addWidget(self.count)
        top_row.addWidget(self.edit_mode_button)
        top_row.addWidget(self.delete_button)

        self.model = SrsListModel()
        self.view = SrsView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(ItemDelegate(self.view, project))
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Always shown: otherwise its appearance narrows the view and every item is measured again.
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.view.setStyleSheet(f"QListView {{ background: white; border: 1px solid {BORDER}; border-radius: 6px; }}")
        self.view.doubleClicked.connect(lambda index: self.open_element.emit(index.data(ELEMENT_ROLE).uuid))
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence.Delete, self.view, activated=self.delete_selected)

        hint = QLabel("Selezione multipla: Maiusc + frecce, Ctrl + clic o Maiusc + clic (Ctrl + A per tutte). "
                      "Doppio clic apre la voce, clic destro per derivare un requisito. "
                      "In modalità modifica, Canc elimina le voci selezionate.",
                      objectName="muted")
        header = QFrame(objectName="card")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel(f"{project.baseline or 'SUBSET-026'}", objectName="elementTitle")
        header_layout.addWidget(title)
        header_layout.addWidget(self.tabs)
        header_layout.addLayout(top_row)
        header_layout.addLayout(filters)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(self.view, 1)
        layout.addWidget(hint)
        self.reload()

    # --- data ----------------------------------------------------------------------------------

    def reload(self):
        """Re-read the requirements from the model (after an import or a deletion)."""
        self.all = document_order(self.project.model)
        # What the filters need, computed once per item instead of at every filter change.
        self.rows = []
        self.parents = {e.uuid: e.values.get("parent") for e in self.all}
        for e in self.all:
            values = e.values
            self.rows.append((e, chapter_of(e), values.get("item_type") in HEADINGS,
                              frozenset(values.get("category") or ()) or frozenset((NO_CATEGORY,)),
                              f"{values.get('id') or ''} {values.get('title') or ''} {values.get('text') or ''}".lower()))
        counts = {}
        for _, chapter, *_ in self.rows:
            if chapter is not None:
                counts[chapter] = counts.get(chapter, 0) + 1
        chapters = sorted(counts)
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self.tabs.addTab(f"Tutti ({len(self.all)})")
        self.tabs.setTabData(0, None)
        for c in chapters:
            i = self.tabs.addTab(f"Capitolo {c} ({counts[c]})")
            self.tabs.setTabData(i, c)
        index = next((i for i in range(self.tabs.count()) if self.tabs.tabData(i) == self.chapter), 0)
        self.tabs.setCurrentIndex(index)
        self.chapter = self.tabs.tabData(index)
        self.tabs.blockSignals(False)
        self._update_category_counts()
        self.refresh()

    def _update_category_counts(self):
        counts = dict.fromkeys(self.category_boxes, 0)
        for _, chapter, heading, categories, _ in self.rows:
            if not heading and (self.chapter is None or chapter == self.chapter):
                for c in categories:
                    if c in counts:
                        counts[c] += 1
        for c, box in self.category_boxes.items():
            box.setText(f"{c} ({counts[c]})")

    def _chapter_changed(self, index):
        self.chapter = self.tabs.tabData(index)
        self._update_category_counts()
        self.refresh()

    def selected_categories(self):
        return {c for c, box in self.category_boxes.items() if box.isChecked()}

    def showEvent(self, event):
        super().showEvent(event)
        if self._pending_refresh:
            self.refresh()

    def refresh(self, *_):
        if not self.isVisible():
            # Item heights depend on the final width of the view: lay out only once it is shown.
            self._pending_refresh = True
            return
        self._pending_refresh = False
        wanted = self.selected_categories()
        text = self.search.text().strip().lower()
        filtered = bool(text) or wanted != set(self.category_boxes)
        items, needed_headings = set(), set()
        for e, chapter, heading, categories, haystack in self.rows:
            if heading or (self.chapter is not None and chapter != self.chapter):
                continue
            if categories.isdisjoint(wanted) or (text and text not in haystack):
                continue
            items.add(e.uuid)
            if filtered:
                # With a filter, keep only the headings that contain something that is shown.
                parent = self.parents.get(e.uuid)
                while parent and parent not in needed_headings:
                    needed_headings.add(parent)
                    parent = self.parents.get(parent)
        shown = []
        for e, chapter, heading, _, _ in self.rows:
            if self.chapter is not None and chapter != self.chapter:
                continue
            if heading:
                if self.show_headings.isChecked() and (not filtered or e.uuid in needed_headings):
                    shown.append(e)
            elif e.uuid in items:
                shown.append(e)
        # Heights are cached per item and width: only items never measured cost time (first opening).
        delegate = self.view.itemDelegate()
        delegate.highlight = text
        slow = sum(1 for e in shown if not delegate.cached(e.uuid)) > SLOW_LAYOUT_ITEMS
        if slow:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.model.set_elements(shown)
            self.view.doItemsLayout()
        finally:
            if slow:
                QApplication.restoreOverrideCursor()
        self.count.setText("1 voce" if len(items) == 1 else f"{len(items)} voci")
        self._selection_changed()

    def reveal(self, uuid):
        """Select and show an item (e.g. when coming back from its page); keeps filters and position."""
        row = next((i for i, e in enumerate(self.model.elements) if e.uuid == uuid), None)
        if row is None:
            return
        index = self.model.index(row)
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index, QAbstractItemView.PositionAtCenter)
        self.view.setFocus()

    def element_changed(self, element):
        """An item was edited elsewhere (e.g. in the editor): re-measure and repaint it."""
        if element.kind != "requirement":
            return
        self.view.itemDelegate().invalidate(element.uuid)
        row = next((i for i, e in enumerate(self.model.elements) if e.uuid == element.uuid), None)
        if row is not None:
            index = self.model.index(row)
            self.model.dataChanged.emit(index, index)
            self.view.scheduleDelayedItemsLayout()

    # --- selection and deletion ---------------------------------------------------------------------

    def selected_elements(self):
        return [i.data(ELEMENT_ROLE) for i in sorted(self.view.selectionModel().selectedRows(), key=lambda i: i.row())]

    def _selection_changed(self, *_):
        n = len(self.view.selectionModel().selectedRows())
        self.delete_button.setEnabled(n > 0 and self.edit_mode.enabled)
        self.delete_button.setText(f"Elimina selezionate ({n})" if n else "Elimina selezionate")
        self.delete_button.setToolTip("" if self.edit_mode.enabled else
                                      "Attiva la modalità modifica per eliminare le voci SRS.")

    def context_menu(self, element):
        menu = QMenu(self)
        label = element.get("id") or ""
        menu.addAction(icon("mdi6.arrow-right-bold-box-outline"), f"Vai alla voce {label}",
                       lambda _=False: self.open_element.emit(element.uuid))
        menu.addAction(icon("mdi6.call-split"), f"Deriva requisito da {label}…",
                       lambda _=False: self.derive_requested.emit(element.uuid))
        menu.addSeparator()
        n = len(self.view.selectionModel().selectedRows())
        delete = menu.addAction(icon("mdi6.trash-can-outline"), f"Elimina selezionate ({n})",
                                lambda _=False: self.delete_selected())
        delete.setEnabled(self.edit_mode.enabled)
        if not self.edit_mode.enabled:
            delete.setText(f"{delete.text()} – attiva la modalità modifica")
        return menu

    def _context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        if not self.view.selectionModel().isSelected(index):
            self.view.setCurrentIndex(index)  # right click outside the selection: act on that item
        self.context_menu(index.data(ELEMENT_ROLE)).exec(self.view.viewport().mapToGlobal(pos))

    def delete_selected(self):
        selected = self.selected_elements()
        if not selected or not self.edit_mode.enabled:
            return
        if confirm_delete(self, self.project, [e.uuid for e in selected]):
            self.elements_deleted.emit()


def confirm_delete(parent, project, uuids, what=None):
    """Ask before deleting SRS items (and the items they contain); returns True if deleted."""
    model = project.model
    targets = model.descendants(uuids)
    contained = len(targets) - len(set(uuids))
    references = model.referencing(targets)
    message = what or f"Eliminare {len(set(uuids))} voci SRS selezionate?"
    details = []
    if contained:
        details.append(f"Verranno eliminate anche {contained} voci contenute (sotto-voci, righe di tabella).")
    if references:
        details.append(f"{len(references)} elementi del modello (es. esiti di tracciatura, funzioni) fanno "
                       "riferimento a queste voci: i riferimenti resteranno senza destinazione.")
    details.append("L'eliminazione diventa definitiva solo al salvataggio; puoi sempre reimportare le voci.")
    box = QMessageBox(QMessageBox.Warning, "Elimina voci SRS", message, QMessageBox.Yes | QMessageBox.Cancel, parent)
    box.setInformativeText("\n\n".join(details))
    box.button(QMessageBox.Yes).setText(f"Elimina {len(targets)} voci")
    box.setDefaultButton(QMessageBox.Cancel)
    if box.exec() != QMessageBox.Yes:
        return False
    project.delete_elements(targets)
    return True
