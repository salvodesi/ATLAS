"""Reading view of the imported SRS: the whole specification, chapter by chapter, item after item.

Items are shown with their full text in document order, can be filtered by chapter 9 category and
searched; several items can be selected (Shift+arrows, Ctrl/Shift+click) and deleted together. From the row of a
section its domains are chosen (A4), from the row of a clause its system functions and its derived requirements.
"""
import re
from html import escape

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut, QTextDocument
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
# Actions in the row of a section (domains, A4) and of a clause (system functions, derived requirements).
ROW_ACTIONS = {"section": (("domains", "Domini…", "Alloca la sezione ai domini funzionali (principale e "
                                                   "contributori)"),),
               "clause": (("functions", "Funzioni…", "Alloca la clausola alle funzioni di sistema"),
                          ("derive", "Deriva…", "Deriva uno o più requisiti dalla clausola"))}
ACTION_GAP = 6


def row_kind(element):
    """«section» for a section (three numbers), «clause» for a clause (four numbers or more), else None."""
    item_type = element.get("item_type")
    if item_type == "Sezione":
        return "section"
    if item_type in ("Requisito", "Titolo"):
        number = re.split(r"[\s\-(]", element.get("id") or "", maxsplit=1)[0]
        if len([p for p in number.split(".") if p]) >= 4:
            return "clause"
    return None


class ItemDelegate(QStyledItemDelegate):
    """Draws an item like a page of the specification: number, full text, category chips.

    Painting uses plain QPainter text layout (no HTML documents): measuring thousands of items stays fast,
    and heights are cached per width.
    """

    action_clicked = Signal(str, str)  # uuid of the item, action (see ROW_ACTIONS)

    def __init__(self, view, project=None):
        super().__init__(view)
        self.view = view
        self.project = project
        self.links = None  # function(element) → what the item is allocated to, shown in its row of actions
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
        actions = None
        kind = row_kind(element)
        if kind:  # a line below the text: what the item is allocated to, and the buttons to change it
            line_h = self.metrics["chip"].height() + 8
            line_top = top + height + 4
            x, buttons = right, []
            for name, label, _ in reversed(ROW_ACTIONS[kind]):
                w = self.metrics["chip"].horizontalAdvance(label) + 22
                x -= w
                buttons.insert(0, (name, label, QRect(x, line_top, w, line_h)))
                x -= ACTION_GAP
            actions = (QRect(body_left, line_top, max(x - 8 - body_left, 40), line_h), buttons)
            height += line_h + 6
        return left, top, placed, chips, actions, height + (top - rect.y()) + PAD_BOTTOM

    def button_at(self, index, pos):
        """Action of the button of the row under a point of the viewport, or None."""
        element = index.data(ELEMENT_ROLE)
        if element is None or not row_kind(element):
            return None
        *_, actions, _ = self._layout(element, self.view.visualRect(index))
        for name, _, box in actions[1] if actions else ():
            if box.contains(pos):
                return name
        return None

    def editorEvent(self, event, model, option, index):
        """A click on a button of a row runs its action (and does not change the selection)."""
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            name = self.button_at(index, event.position().toPoint())
            if name is not None:
                if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    self.action_clicked.emit(index.data(ELEMENT_ROLE).uuid, name)
                return True
        return super().editorEvent(event, model, option, index)

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
        left, top, placed, chips, actions, _ = self._layout(element, rect)
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
        if actions is not None:
            text_box, buttons = actions
            painter.setFont(self.fonts["chip"])
            painter.setPen(QColor(MUTED))
            text = self.links(element) if self.links else ""
            painter.drawText(text_box, Qt.AlignLeft | Qt.AlignVCenter,
                             self.metrics["chip"].elidedText(text, Qt.ElideRight, text_box.width()))
            painter.setRenderHint(QPainter.Antialiasing)
            for _, label, box in buttons:
                painter.setPen(QColor(ACCENT))
                painter.setBrush(QColor("white"))
                painter.drawRoundedRect(box.adjusted(0, 0, -1, -1), 6, 6)
                painter.drawText(box, Qt.AlignCenter, label)
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
    window_toggled = Signal()  # «Apri in altra finestra» / «Riporta nelle schede»
    elements_changed = Signal(list)  # elements changed from a row (domains of a section, functions of a clause)
    elements_created = Signal()  # derived requirements created from a row

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
        self.window_button = QPushButton()
        self.window_button.clicked.connect(self.window_toggled)
        self.set_detached(False)
        top_row = QHBoxLayout()
        top_row.addWidget(self.search, 1)
        top_row.addWidget(self.count)
        top_row.addWidget(self.edit_mode_button)
        top_row.addWidget(self.delete_button)
        top_row.addWidget(self.window_button)

        self.model = SrsListModel()
        self.view = SrsView()
        self.view.setModel(self.model)
        self.delegate = ItemDelegate(self.view, project)
        self.delegate.links = self._links_text
        self.delegate.action_clicked.connect(self.run_action)
        self.view.setItemDelegate(self.delegate)
        self._links = {}
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Always shown: otherwise its appearance narrows the view and every item is measured again.
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.view.setStyleSheet(f"QListView {{ background: white; border: 1px solid {BORDER}; border-radius: 6px; }}")
        self.view.doubleClicked.connect(self._double_clicked)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence.Delete, self.view, activated=self.delete_selected)

        hint = QLabel("Sezioni: «Domini…» le alloca ai domini funzionali. Clausole: «Funzioni…» le alloca alle "
                      "funzioni di sistema, «Deriva…» crea uno o più requisiti derivati. Doppio clic apre la voce. "
                      "Selezione multipla: Maiusc + frecce, Ctrl + clic o Maiusc + clic (Ctrl + A per tutte); in "
                      "modalità modifica, Canc elimina le voci selezionate.",
                      objectName="muted")
        hint.setWordWrap(True)
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
        self._rebuild_links()
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

    def set_detached(self, detached):
        """The catalogue is shown in its own window (detached) or in a tab of the main window."""
        self.detached = detached
        if detached:
            self.window_button.setIcon(icon("mdi6.dock-window"))
            self.window_button.setText("Riporta nelle schede")
            self.window_button.setToolTip("Riporta le voci SRS in una scheda della finestra principale")
        else:
            self.window_button.setIcon(icon("mdi6.open-in-new"))
            self.window_button.setText("Apri in altra finestra")
            self.window_button.setToolTip("Stacca le voci SRS in una finestra separata, da tenere affiancata alle "
                                          "schede (es. su un secondo schermo)")

    def reveal(self, uuid):
        """Select and show an item (e.g. when coming back from its page); keeps filters and position."""
        row = next((i for i, e in enumerate(self.model.elements) if e.uuid == uuid), None)
        if row is None:
            return
        index = self.model.index(row)
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index, QAbstractItemView.PositionAtCenter)
        self.view.setFocus()

    # --- allocation from the rows --------------------------------------------------------------------

    def _rebuild_links(self):
        """What the rows show: system functions tracing each item directly, derived requirements of each item."""
        functions, derived = {}, {}
        for sf in self.project.model.of_kind("system_function"):
            for uuid in sf.get("sections") or []:
                functions.setdefault(uuid, []).append(sf)
        for d in self.project.model.of_kind("derived_requirement"):
            if d.get("parent"):
                derived.setdefault(d.get("parent"), []).append(d)
        self._links = {"functions": functions, "derived": derived}

    def _short(self, uuid):
        e = self.project.model.get(uuid)
        return (e.get("id") or self.project.model.label(e)) if e is not None else "?"

    def _links_text(self, element):
        kind = row_kind(element)
        if kind == "section":
            parts = []
            if element.get("primary_domain"):
                parts.append(f"{self._short(element.get('primary_domain'))} (principale)")
            parts += [f"{self._short(d)} (contributo)" for d in element.get("contributing_domains") or []]
            return "Domini: " + " · ".join(parts) if parts else "Nessun dominio allocato"
        if kind == "clause":
            functions = self._links.get("functions", {})
            direct = [f.get("id") or f.label for f in functions.get(element.uuid, [])]
            inherited = []
            parent = element.get("parent")
            while parent:  # functions tracing a section (or a clause) that contains it
                inherited += [f.get("id") or f.label for f in functions.get(parent, []) if
                              (f.get("id") or f.label) not in direct + inherited]
                parent = self.parents.get(parent)
            parts = direct + [f"{i} (sezione)" for i in inherited]
            text = "Funzioni: " + " · ".join(parts) if parts else "Nessuna funzione di sistema"
            derived = [d.get("id") or "?" for d in self._links.get("derived", {}).get(element.uuid, [])]
            if derived:
                text += "   ·   Derivati: " + ", ".join(derived)
            return text
        return ""

    def run_action(self, uuid, name):
        """«Domini…» of a section, «Funzioni…» or «Deriva…» of a clause."""
        from arcadia_tool.ui.srs_row_actions import DeriveDialog, ItemDomainsDialog, choose_functions

        item = self.project.model.get(uuid)
        if item is None:
            return
        if name == "domains":
            dialog = ItemDomainsDialog(self.project, item, self)
            if not dialog.exec():
                return
            changed = self.project.allocate_item(item, *dialog.chosen())
        elif name == "functions":
            chosen = choose_functions(self.project, item, self)
            if chosen is None:
                return
            changed = self.project.trace_item_to_functions(item, chosen)
        elif name == "derive":
            dialog = DeriveDialog(self.project, item, self)
            if not dialog.exec():
                return
            self._rebuild_links()
            self.view.viewport().update()
            self.elements_changed.emit([*dialog.changed])
            self.elements_created.emit()
            return
        else:
            return
        self._rebuild_links()
        self.view.viewport().update()
        if changed:
            self.elements_changed.emit(changed)

    def _double_clicked(self, index):
        pos = self.view.viewport().mapFromGlobal(QCursor.pos())
        if self.delegate.button_at(index, pos) is None:  # a double click on a button is not «open the item»
            self.open_element.emit(index.data(ELEMENT_ROLE).uuid)

    def element_changed(self, element):
        """An item was edited elsewhere (e.g. in the editor): re-measure and repaint it. A function, a derived
        requirement or a domain changed: the rows that show it are repainted."""
        if element.kind in ("system_function", "derived_requirement", "domain"):
            self._rebuild_links()
            self.view.viewport().update()
            return
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
        kind = row_kind(element)
        if kind:
            menu.addSeparator()
        if kind == "section":
            menu.addAction(icon("mdi6.sitemap-outline"), "Alloca ai domini funzionali…",
                           lambda _=False: self.run_action(element.uuid, "domains"))
        elif kind == "clause":
            menu.addAction(icon("mdi6.function-variant"), "Alloca alle funzioni di sistema…",
                           lambda _=False: self.run_action(element.uuid, "functions"))
            menu.addAction(icon("mdi6.call-split"), "Deriva più requisiti…",
                           lambda _=False: self.run_action(element.uuid, "derive"))
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


class SrsReaderWindow(QWidget):
    """Separate window of the SRS catalogue («Apri in altra finestra»). Closing it closes the catalogue, as
    closing its tab does."""
    closed = Signal()

    def __init__(self, reader, title, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(title)
        self.resize(1200, 860)
        self.reader = reader
        self.releasing = False  # set when the catalogue goes back to a tab: closing is not closing it
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(reader)
        reader.show()  # hidden by the tab widget it was taken from

    def release(self):
        """Give the catalogue back (to a tab) and close the window."""
        self.releasing = True
        self.layout().removeWidget(self.reader)
        self.reader.setParent(None)
        self.close()
        return self.reader

    def closeEvent(self, event):
        super().closeEvent(event)
        if not self.releasing:
            self.closed.emit()


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
