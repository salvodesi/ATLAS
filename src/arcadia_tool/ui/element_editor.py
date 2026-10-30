"""Form editor generated from the schema of the selected element.

A sheet opens read-only; in edit mode the changes stay in a draft until «Salva» applies them to the model and
saves the project.
"""
from html import escape

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImageReader, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStyle,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from arcadia_tool.checks import CHECKS_BY_CODE, count
from arcadia_tool.checks.fields import SRS_CARD
from arcadia_tool.model.identifiers import compute_id, is_automatic, matches_context, missing_context, rule
from arcadia_tool.model.teams import DA_FIELD, MEMBERS, da_teams, member_rows
from arcadia_tool.model.adr import approval_problems, approve_new_domain, can_approve, sections_taken
from arcadia_tool.model.element import is_empty
from arcadia_tool.model.schema import (ADR_DETAILS, BOOL, DA_DECISION, ENUM, IMAGE, INT, KINDS_BY_NAME, MAP, MULTIENUM, REF,
                                       REFS, STR, STRLIST, TABLE, TEXT, enum_option)
from arcadia_tool.storage.project import local_change
from arcadia_tool.ui.checks_panel import SEVERITY_COLORS, summary
from arcadia_tool.ui.dialogs import replace_page
from arcadia_tool.ui.rich_text import RichTextEdit
from arcadia_tool.ui.srs_edit_mode import SrsEditMode, edit_mode_button
from arcadia_tool.ui.theme import ACCENT_SOFT, BORDER, MUTED, SURFACE, icon, kind_icon, status_colors
from arcadia_tool.ui.theme import TEXT as TEXT_COLOR  # TEXT is also a field type of the schema

# Kinds whose elements are imported from the specification and are read-only outside the edit mode.
READ_ONLY_KINDS = ("requirement",)
# Sheets traced to the SRS items (and, for a derived requirement, to its logical function).
TRACE_CARDS = ("domain", "system_function", "logical_function", "derived_requirement")
FINDINGS_SHOWN = 8  # findings of the checks listed in the header of a sheet; the others are in the panel
# Kinds whose sheet has the sections in another order: an ADR shows first what it is about (SRS items, ADR).
SECTION_ORDER = {"adr": ("Identificazione", ADR_DETAILS, "Relazioni", "Descrizione", DA_DECISION)}
# The texts of the SRS items are those of the specification, imported: plain text, no styles.
PLAIN_TEXT_KINDS = ("requirement",)
HEADER = "@header"  # the header card of the sheet, in ElementEditor.widgets
HIGHLIGHT_COLOR = "#F79009"  # the field with the problem found by a check
HIGHLIGHT_MS = 2500

MAP_COLUMNS = 9
SECTIONS = (
    ("Identificazione", (STR, INT, BOOL, ENUM, MULTIENUM, STRLIST)),
    ("Descrizione", (TEXT,)),
    ("Relazioni", (REF, REFS)),
)


def _ref_choices(model, ref_kinds):
    return [(e.uuid, model.choice_label(e)) for e in model.of_kind(*ref_kinds)]


IMAGE_MAX_WIDTH = 900


def load_pixmap(project, rel):
    """Image of a project asset (also not yet saved, e.g. right after an import), or None."""
    data = project.asset_data(rel) if rel else None
    if not data:
        return None
    pixmap = QPixmap()
    return pixmap if pixmap.loadFromData(data) else None


def image_size(project, rel):
    """(width, height) of the image of a project asset, read from its header without decoding it; None if it is
    not an image. An asset not saved yet is read from memory."""
    if not rel:
        return None
    file = project.path / rel
    if rel in project.unsaved_assets() or not file.is_file():
        data = project.asset_data(rel)
        if not data:
            return None
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.ReadOnly)
        size = QImageReader(buffer).size()
    else:
        size = QImageReader(str(file)).size()
    return (size.width(), size.height()) if size.isValid() and size.width() > 0 else None


def compact_combo():
    """Combo box whose width does not grow with the longest item (labels of SRS items can be long)."""
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(24)
    combo.view().setTextElideMode(Qt.ElideRight)
    return combo


def card(title=None):
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    if title:
        layout.addWidget(QLabel(title.upper(), objectName="sectionCaption"))
    return frame, layout


class RefPicker(QDialog):
    """Searchable selection of elements (requirements can be thousands): multiple, or single."""

    def __init__(self, choices, selected, parent=None, single=False, title="Seleziona elementi"):
        super().__init__(parent)
        self.single = single
        self.setWindowTitle(title)
        self.resize(640, 620)
        self.filter = QLineEdit(placeholderText="Filtra…", objectName="search")
        self.filter.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.filter.setClearButtonEnabled(True)
        self.list = QListWidget()
        for uuid, label in choices:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, uuid)
            if not single:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if uuid in selected else Qt.Unchecked)
            self.list.addItem(item)
            if single and uuid in selected:
                self.list.setCurrentItem(item)
        if single:
            self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.filter.textChanged.connect(self._apply_filter)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addWidget(self.list)
        layout.addWidget(buttons)

    def _apply_filter(self, text):
        text = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text not in item.text().lower())

    def selected(self):
        if self.single:
            item = self.list.currentItem()
            return [item.data(Qt.UserRole)] if item and not item.isHidden() else []
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class RefsWidget(QWidget):
    changed = Signal()

    def __init__(self, model, ref_kinds, picker=None):
        super().__init__()
        self.model, self.ref_kinds, self.uuids = model, ref_kinds, []
        self.picker = picker  # function(uuids) → new uuids or None: another window to choose (the SRS items)
        self.list = QListWidget()
        self.list.setMaximumHeight(96)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(14, 14))
        edit = QPushButton(icon("mdi6.pencil-outline"), "Seleziona")
        remove = QPushButton(icon("mdi6.trash-can-outline"), "Rimuovi")
        edit.clicked.connect(self._pick)
        remove.clicked.connect(self._remove)
        buttons = QVBoxLayout()
        buttons.addWidget(edit)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

    def set_value(self, uuids):
        self.uuids = list(uuids or [])
        self.list.clear()
        for uuid in self.uuids:
            element = self.model.get(uuid)
            item = QListWidgetItem(self.model.label_of(uuid) or "(elemento inesistente)")
            if element:
                item.setIcon(kind_icon(element.kind))
            item.setData(Qt.UserRole, uuid)
            self.list.addItem(item)
        self._fit()

    def value(self):
        return list(self.uuids)

    def set_read_only(self, tip):
        """Only shown (e.g. computed by the tool): no buttons to change it, as high as its rows."""
        for button in self.findChildren(QPushButton):
            button.hide()
        self.list.setToolTip(tip)
        self.read_only = True
        self._fit()

    def _fit(self):
        if getattr(self, "read_only", False):
            rows = max(1, min(self.list.count(), 8))
            self.list.setFixedHeight(rows * (self.list.sizeHintForRow(0) if self.list.count() else 22) + 8)

    def _pick(self):
        if self.picker is not None:
            chosen = self.picker(self.uuids)
            if chosen is not None and chosen != self.uuids:
                self.set_value(chosen)
                self.changed.emit()
            return
        dialog = RefPicker(_ref_choices(self.model, self.ref_kinds), set(self.uuids), self)
        if dialog.exec():
            self.set_value(dialog.selected())
            self.changed.emit()

    def _remove(self):
        drop = {i.data(Qt.UserRole) for i in self.list.selectedItems()}
        self.set_value([u for u in self.uuids if u not in drop])
        self.changed.emit()


class TableWidget(QWidget):
    changed = Signal()

    def __init__(self, model, field, choices=None):
        super().__init__()
        self.model, self.columns = model, field.columns
        # function(column) → [(value, label)]: the list of a column whose choices depend on the element
        self.choices = choices
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels([c.label for c in self.columns])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)  # readable headers
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(180)
        self.table.itemChanged.connect(lambda _: self.changed.emit())
        add = QPushButton(icon("mdi6.plus"), "Aggiungi riga")
        remove = QPushButton(icon("mdi6.trash-can-outline"), "Elimina riga")
        add.clicked.connect(self._add_clicked)
        remove.clicked.connect(self._remove_row)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def _add_clicked(self):
        self._add_row({})
        self.changed.emit()

    def _add_row(self, row):
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c, col in enumerate(self.columns):
            value = row.get(col.name, "")
            if col.choices or col.type in (ENUM, REF):
                combo = compact_combo()
                self._fill_combo(combo, col, value)
                combo.currentIndexChanged.connect(lambda _: self.changed.emit())
                self.table.setCellWidget(r, c, combo)
            else:
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.table.blockSignals(False)

    def _column_choices(self, col):
        if col.choices:
            return self.choices(col) if self.choices else []
        return [(o, o) for o in col.options] if col.type == ENUM else _ref_choices(self.model, col.ref_kinds)

    def _fill_combo(self, combo, col, value):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for data, label in self._column_choices(col):
            combo.addItem(label, data)
        if value and combo.findData(value) < 0:  # no longer among the choices (e.g. a domain renamed above)
            combo.addItem(f"{self.model.label_of(value) or value} (non più disponibile)", value)
        combo.setCurrentIndex(max(combo.findData(value), 0) if value else 0)
        combo.blockSignals(False)

    def refresh_choices(self):
        """The lists of the columns that depend on the element follow it (the current values are kept)."""
        for c, col in enumerate(self.columns):
            if not col.choices:
                continue
            for r in range(self.table.rowCount()):
                combo = self.table.cellWidget(r, c)
                if combo is not None:
                    self._fill_combo(combo, col, combo.currentData())

    def _remove_row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()} or {self.table.rowCount() - 1}, reverse=True)
        for r in rows:
            if r >= 0:
                self.table.removeRow(r)
        self.changed.emit()

    def set_value(self, rows):
        self.table.setRowCount(0)
        for row in rows or []:
            self._add_row(row)

    def value(self):
        rows = []
        for r in range(self.table.rowCount()):
            row = {}
            for c, col in enumerate(self.columns):
                widget = self.table.cellWidget(r, c)
                item = self.table.item(r, c)
                value = widget.currentData() if widget else (item.text().strip() if item else "")
                if value:
                    row[col.name] = value
            rows.append(row)
        return rows


class StatusCombo(QComboBox):
    """State selector coloured like a status chip."""

    def __init__(self, options, current):
        super().__init__()
        self.addItem("Nessuno stato", None)
        for option in options:
            self.addItem(option, option)
        self.setItemDelegate(_StatusItemDelegate(self))
        self.setCurrentIndex(max(self.findData(current), 0) if current else 0)
        self.setMinimumWidth(150)
        self.currentIndexChanged.connect(self._restyle)
        self._restyle()

    def _restyle(self, *_):
        fg, bg = status_colors(self.currentData())
        self.setStyleSheet(
            f"QComboBox {{ background:{bg}; color:{fg}; border:1px solid {bg}; border-radius:12px;"
            f" padding:3px 30px 3px 12px; font-weight:600; }}"
            "QComboBox::drop-down { border: none; }"
            # The list must not inherit the colour of the closed box (it made some states unreadable).
            f"QComboBox QAbstractItemView {{ background:{SURFACE}; color:{TEXT_COLOR}; border:1px solid {BORDER};"
            " padding: 4px; outline: none; }")


class _StatusItemDelegate(QStyledItemDelegate):
    """Rows of the open state list: each state as a chip in its own colours; the row under the mouse (or
    selected with the keyboard) dark on light blue, so that its text is always readable."""
    HEIGHT = 28

    def paint(self, painter, option, index):
        active = option.state & (QStyle.State_Selected | QStyle.State_MouseOver)
        fg, bg = status_colors(index.data(Qt.UserRole))
        rect = option.rect.adjusted(2, 2, -2, -2)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ACCENT_SOFT if active else bg))
        painter.drawRoundedRect(rect, 5, 5)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT_COLOR if active else fg))
        painter.drawText(rect.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, index.data() or "")
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width() + 24, self.HEIGHT)


# Fields in a card of their own shown right after the description, instead of at the end of the sheet.
AFTER_DESCRIPTION = {"team": ("members",)}


class _ViewModeGuard(QObject):
    """On a sheet shown read-only: an attempt to change a field asks to switch to edit mode (and is ignored)."""
    TEXT_INPUTS = (QLineEdit, QPlainTextEdit, QTextEdit)
    EDIT_KEYS = (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Up,
                 Qt.Key_Down)

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Wheel and isinstance(watched, (QComboBox, QSpinBox)):
            return True  # the wheel would change the value
        attempt = False
        if kind == QEvent.KeyPress:
            text_key = bool(event.text()) and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)
            attempt = text_key or event.key() in self.EDIT_KEYS
        elif kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            attempt = not isinstance(watched, self.TEXT_INPUTS)  # a click in a text only selects it
        if attempt:
            self.editor.ask_to_edit()
            return True
        return False


class ElementEditor(QScrollArea):
    """Sheet of an element. It opens read-only: «Modifica» (or an attempt to change a field) switches to edit
    mode, where the changes are kept in a draft copy of the element until «Salva» applies them to the model and
    saves the project; «Annulla» discards them."""
    element_changed = Signal(object)
    back_requested = Signal(str)  # uuid of the element being left
    open_requested = Signal(str)  # another element to show (e.g. an SRS item traced by a domain)
    adr_requested = Signal(str)  # «Nuova ADR…» of a domain or a function sheet: its uuid
    elements_created = Signal()  # e.g. derived requirements created from the allocation window
    dirty_changed = Signal(bool)  # the draft has (True) or no longer has changes not yet saved
    saved = Signal()  # «Salva»: the changes are in the model, the project is to be saved
    abandoned = Signal(object)  # «Annulla» on an element just created and never saved: it is to be removed

    def __init__(self, srs_edit_mode=None):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.project = self.element = self.draft = None
        self.getters = {}
        self.read_only = False
        self.editing = self.dirty = self._building = False
        self.back_label = None  # set when the page was opened from another view (e.g. the SUBSET-026 catalogue)
        self.findings_for = None  # function(uuid) → findings of the checks about the sheet (shown in its header)
        # function(kind, field=None) → why the user may not change sheets of this kind, or that field of them
        # (e.g. the teams, and the team of a domain: only the DA), or None
        self.edit_denied = None
        # function(draft) → True if saving the sheet would leave the user outside the project (see teams.locks_out)
        self.locks_out = None
        # function() → the name of the user if a member of the Design Authority, else None: who approves an ADR
        self.approver = None
        # The element was just created («Nuovo…») and its sheet never saved: «Annulla» removes it.
        self.unsaved_new = False
        self.highlight = None  # frame around the field shown by reveal (removed after a moment)
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._apply)
        self._guard = _ViewModeGuard(self)
        self.srs_edit_mode = srs_edit_mode or SrsEditMode()
        self.srs_edit_mode.changed.connect(self._edit_mode_changed)
        self.clear()

    def set_back(self, label):
        """Show (label) or hide (None) the button that goes back to the view the page was opened from."""
        self.back_label = label
        if self.element is not None:
            self._build()

    def _edit_mode_changed(self, _enabled):
        if self.element is not None and self.element.kind in READ_ONLY_KINDS:
            self._build()

    # --- view and edit mode -------------------------------------------------------------------------

    def denied(self):
        """Why the sheet shown may not be changed by the user, or None."""
        return self.edit_denied(self.element.kind) if self.edit_denied and self.element is not None else None

    def field_denied(self, name):
        """Why the field of the sheet shown may not be changed by the user, or None."""
        if not self.edit_denied or self.element is None:
            return None
        return self.edit_denied(self.element.kind, name)

    def ask_to_edit(self):
        reason = self.denied()
        if reason:
            QMessageBox.information(self, "Scheda in sola lettura", reason)
            return
        answer = QMessageBox.question(self, "Scheda in sola lettura",
                                      f"«{self.project.model.label(self.element)}» è in sola lettura. Passare in "
                                      "modalità modifica?")
        if answer == QMessageBox.Yes:
            QTimer.singleShot(0, self.start_editing)  # not while the event of the old page is handled

    def start_editing(self):
        if self.element is not None and not self.editing and not self.denied():
            self.editing = True
            self._build()

    @local_change
    def approve(self):
        """The Design Authority approves the ADR of a new domain: the domain is created (see
        model.adr.approve_new_domain), after a confirmation that says what changes."""
        element, model = self.element, self.project.model
        problems = approval_problems(model, element)
        if problems:
            QMessageBox.warning(self, "Approva ADR", "Non è possibile approvare l'ADR:\n" + "\n".join(problems))
            return
        sections = [model.get(u) for u in element.get("sections_allocated") or [] if model.get(u) is not None]
        taken = sections_taken(model, element)
        team = model.get(element.get("team_proposed"))
        lines = [f"Nome: {element.get('new_domain_name')} (l'ID DFnn viene assegnato ora)",
                 f"Sezioni allocate: {len(sections)}",
                 f"Team: {model.label(team) if team is not None else 'nessuno'}"]
        if taken:
            moved = ", ".join(f"{s.get('id')} (da {d.get('id') if d is not None else '?'})" for s, d in taken)
            lines.append(f"Passano al nuovo dominio come principale, togliendolo al dominio attuale: {moved}")
        if QMessageBox.question(self, "Approva ADR", "Approvare l'ADR e creare il nuovo dominio funzionale?\n\n"
                                + "\n".join(lines)) != QMessageBox.Yes:
            return
        domain, changed = approve_new_domain(self.project, element)
        self.draft = element.copy()
        for e in [domain, *changed, element]:
            self.element_changed.emit(e)
        self.elements_created.emit()
        self.saved.emit()  # the project is saved
        self._build()
        QMessageBox.information(self, "Approva ADR", f"ADR approvata: creato il dominio "
                                f"{model.label(domain)}.")

    @local_change
    def save_changes(self):
        """«Salva»: the draft becomes the element in the model; the project is then saved (signal saved)."""
        if self.element is None:
            return
        self.flush()
        if self.dirty and self.locks_out is not None and self.locks_out(self.draft):
            from arcadia_tool.ui.team_members import own_id_error
            own_id_error(self)
            return  # not saved: the sheet stays in edit mode
        if self.dirty:
            moved = self._single_design_authority()
            if moved is None:
                return  # not saved: the sheet stays in edit mode
            previous = self.element.copy()
            for name in list(self.draft.values) + list(self.element.values):  # fields the user may not change
                if self.field_denied(name) and self.draft.values.get(name) != self.element.values.get(name):
                    self.draft.set(name, self.element.values.get(name))
            self.element.values = self.draft.copy().values
            # May assign the identifier, once its context is known; may change other elements kept in step
            # (e.g. the team assigned to a domain lists it among its domains).
            kept_in_step = self.project.update(self.element, previous) or []
            self.element_changed.emit(self.element)
            for other in [*moved, *kept_in_step]:
                self.element_changed.emit(other)
        self.unsaved_new = False
        self._end_editing()
        self.saved.emit()

    def _single_design_authority(self):
        """A team saved as Design Authority while another one is: the DA moves to this team if the user agrees.
        Returns the teams that are no longer DA, or None if the sheet is not to be saved."""
        if self.draft.kind != "team" or not self.draft.get(DA_FIELD):
            return []
        others = [t for t in da_teams(self.project.model) if t.uuid != self.element.uuid]
        if not others:
            return []
        names = ", ".join(f"«{self.project.model.label(t)}»" for t in others)
        answer = QMessageBox.question(
            self, "Design Authority",
            f"La Design Authority è già il team {names}: può essercene una sola.\n\nSpostare la Design Authority "
            f"al team «{self.project.model.label(self.draft)}»?")
        if answer != QMessageBox.Yes:
            return None
        for t in others:
            t.set(DA_FIELD, False)
            self.project.update(t)
        return others

    def cancel_changes(self, ask=True):
        """«Annulla»: back to the element as it is in the model."""
        if self.element is None:
            return
        self._timer.stop()
        if ask and self.dirty and QMessageBox.question(
                self, "Annulla le modifiche", "Scartare le modifiche non salvate della scheda?") != QMessageBox.Yes:
            return
        if self.unsaved_new:  # never saved: the element itself goes away
            self._set_dirty(False)
            self.abandoned.emit(self.element)
            return
        self._end_editing()

    def _end_editing(self):
        self.editing = False
        self.draft = self.element.copy()
        self._set_dirty(False)
        self._build()

    def _set_dirty(self, dirty):
        if dirty != self.dirty:
            self.dirty = dirty
            self.dirty_changed.emit(dirty)

    def refresh(self):
        """Rebuild the sheet (e.g. other elements changed); without changes in progress, from the model."""
        if self.element is None:
            return
        self.flush()
        if not self.dirty:
            self.draft = self.element.copy()
        self._build()

    def _guard_view_mode(self, page):
        """Read-only sheet: inputs cannot change, and an attempt asks to switch to edit mode."""
        kept = [w for w in page.findChildren(QWidget) if w.property("keepEnabled")]
        for w in page.findChildren(QWidget):
            if any(k is w or k.isAncestorOf(w) for k in kept):
                continue
            if isinstance(w, RichTextEdit):
                w.setReadOnly(True)  # the formatted text, without its toolbar
            elif isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox)):
                w.setReadOnly(True)
            elif isinstance(w, QTableWidget):
                w.setEditTriggers(QAbstractItemView.NoEditTriggers)
            if isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QCheckBox, QPushButton,
                              QTableWidget)):
                w.installEventFilter(self._guard)

    def _make_read_only(self, page):
        """Block every input of the page (texts stay selectable and readable, not greyed out)."""
        kept = [w for w in page.findChildren(QWidget) if w.property("keepEnabled")]
        for w in page.findChildren(QWidget):
            if any(k is w or k.isAncestorOf(w) for k in kept):
                continue
            if isinstance(w, RichTextEdit):
                w.setReadOnly(True)
            elif isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)):
                w.setReadOnly(True)
            elif isinstance(w, QSpinBox):
                w.setReadOnly(True)  # the arrows do nothing on a read-only spin box
            elif isinstance(w, QTableWidget):
                w.setEditTriggers(QAbstractItemView.NoEditTriggers)
            elif isinstance(w, (QComboBox, QCheckBox, QPushButton)):
                w.setEnabled(False)

    def clear(self):
        self._timer.stop()  # a draft not saved is not applied
        self.element = self.draft = None
        self.editing = False
        self._set_dirty(False)
        empty = QWidget()
        layout = QVBoxLayout(empty)
        layout.addStretch()
        pic = QLabel(alignment=Qt.AlignCenter)
        pic.setPixmap(icon("mdi6.file-tree-outline", "#B8C1CC").pixmap(64, 64))
        text = QLabel("Seleziona un elemento nel modello oppure creane uno nuovo.", alignment=Qt.AlignCenter,
                      objectName="muted")
        layout.addWidget(pic)
        layout.addWidget(text)
        layout.addStretch()
        replace_page(self, empty)

    def edit(self, project, element, editing=False):
        """Show an element: read-only, or directly in edit mode (e.g. a new element)."""
        self._timer.stop()
        self.project, self.element = project, element
        self.draft = element.copy()
        self.editing = editing and not self.denied()
        self._set_dirty(False)
        self._build()

    def _build(self):
        """The page, from the draft (the element with the changes in progress)."""
        self._building = True
        try:
            self._build_page()
        finally:
            self._building = False

    def _build_page(self):
        element = self.draft
        self.getters, self.widgets, self.field_labels = {}, {}, {}
        self._choice_sources = []  # (table field, refresh of a choice among its rows)
        self._computed = []  # (field, widget) of the fields computed from the others
        self._dynamic_tables = []  # tables whose lists depend on the element (see Column.choices)
        self.read_only = element.kind in READ_ONLY_KINDS and not self.srs_edit_mode.enabled
        schema = element.schema
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(14)
        header = self._header(element)
        self.widgets[HEADER] = header
        outer.addWidget(header)
        findings = self.findings_for(element.uuid) if self.findings_for else []
        if findings:
            outer.addWidget(self._findings_card(findings))

        status_field = schema.field("status")
        # Sections of the kind's own (e.g. the SA-3 register) come first, with their fields in schema order.
        own = [f.section for f in schema.fields if f.section and f.section not in dict(SECTIONS)]
        sections = [(title, ()) for title in dict.fromkeys(own)] + list(SECTIONS)
        if element.kind in SECTION_ORDER:  # another order for this kind (e.g. the relations of an ADR first)
            order = SECTION_ORDER[element.kind]
            sections.sort(key=lambda s: order.index(s[0]) if s[0] in order else len(order))
        for title, types in sections:
            # The fields of this element as it is (e.g. of the type of an ADR: see Field.when).
            fields = [f for f in schema.fields if (f.section == title or (not f.section and f.type in types))
                      and f is not status_field and not f.hidden and f.applies(element)
                      and not (f.by_tool and is_empty(element.values.get(f.name)))]
            if not fields:
                continue
            caption = f"Dettagli: {element.get('adr_type')}" if title == ADR_DETAILS else title
            frame, layout = card(caption)
            form = QFormLayout()
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setHorizontalSpacing(16)
            form.setVerticalSpacing(10)
            for f in fields:
                widget, getter = self._make_widget(f, element.values.get(f.name))
                self.widgets[f.name] = widget
                if f.stored:
                    self.getters[f.name] = getter
                if f.analysis:
                    widget.setProperty("keepEnabled", True)  # editable also on a read-only SRS item
                label = QLabel(f.label, objectName="formLabel")
                if f.by_tool:  # written by the tool: not changed by hand
                    widget.setEnabled(False)
                    widget.setToolTip("Assegnato dal tool")
                reason = self.field_denied(f.name) if self.editing else None
                if reason:  # e.g. the team of a domain: only the Design Authority assigns it
                    widget.setEnabled(False)
                    widget.setToolTip(reason)
                    label.setToolTip(reason)
                self.field_labels[f.name] = label
                if f.type == TABLE:  # a table in a section (e.g. the details of an ADR): the whole width
                    form.addRow(label)
                    form.addRow(widget)
                else:
                    form.addRow(label, widget)
            layout.addLayout(form)
            outer.addWidget(frame)
            if title == "Descrizione" and element.kind in TRACE_CARDS:
                trace = self._srs_trace_card()
                self.widgets[SRS_CARD] = trace
                outer.addWidget(trace)  # right after the description
            if title == "Descrizione":
                for name in AFTER_DESCRIPTION.get(element.kind, ()):  # e.g. the members of a team
                    outer.addWidget(self._field_card(schema.field(name), element))
        for f in schema.fields:
            if f.hidden or f.name in self.widgets or not f.applies(element):
                continue
            if f.type == IMAGE and not element.values.get(f.name):
                continue  # no empty image card on items without a figure
            if f.type in (MAP, TABLE, IMAGE):
                outer.addWidget(self._field_card(f, element))
        outer.addStretch()
        if not self.editing:
            self._guard_view_mode(page)
        elif self.read_only:
            self._make_read_only(page)
        position = self.verticalScrollBar().value()
        replace_page(self, page)
        self.verticalScrollBar().setValue(position)  # rebuilt in place (edit mode, a choice made…)

    def _field_card(self, f, element):
        """A field shown in a card of its own (a table, a map, an image)."""
        frame, layout = card(f.label)
        widget, getter = self._make_widget(f, element.values.get(f.name))
        self.getters[f.name] = getter
        self.widgets[f.name] = frame  # its card (shown by reveal)
        for name, refresh in self._choice_sources:
            if name == f.name and hasattr(widget, "changed"):
                widget.changed.connect(refresh)
        layout.addWidget(widget)
        return frame

    def _header(self, element):
        schema = element.schema
        frame, layout = card()
        if self.back_label:
            back = QPushButton(icon("mdi6.arrow-left", "#2457A6"), self.back_label)
            back.setProperty("flat", True)
            back.setProperty("keepEnabled", True)
            back.setShortcut(QKeySequence("Alt+Left"))
            back.setToolTip("Torna al punto del catalogo da cui hai aperto la voce (Alt+Freccia sinistra)")
            back.clicked.connect(lambda _checked=False: self.back_requested.emit(element.uuid))
            row = QHBoxLayout()
            row.addWidget(back)
            row.addStretch()
            layout.addLayout(row)
        top = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(kind_icon(element.kind).pixmap(18, 18))
        top.addWidget(pic)
        top.addWidget(QLabel(schema.label, objectName="kindLabel"))
        if schema.template:
            top.addWidget(QLabel(f"Template {schema.template}", objectName="badge"))
        top.addStretch()
        status_field = schema.field("status")
        if status_field:
            combo = StatusCombo(status_field.options, element.get("status"))
            combo.currentIndexChanged.connect(self._changed)
            self.getters["status"] = combo.currentData
            self.widgets["status"] = combo
            top.addWidget(QLabel("Stato", objectName="muted"))
            top.addWidget(combo)
        if element.kind in READ_ONLY_KINDS:
            self.edit_mode_button = edit_mode_button(self.srs_edit_mode)
            self.edit_mode_button.setProperty("keepEnabled", True)
            top.addWidget(self.edit_mode_button)
        top.addSpacing(8)
        if self.editing:
            self.cancel_button = QPushButton(icon("mdi6.close"), "Annulla")
            self.cancel_button.setToolTip("Scarta le modifiche non salvate della scheda")
            self.cancel_button.clicked.connect(lambda _=False: self.cancel_changes())
            self.save_button = QPushButton(icon("mdi6.content-save-outline", "white"), "Salva")
            self.save_button.setProperty("primary", True)
            self.save_button.setToolTip("Salva le modifiche di questa scheda (Ctrl+S); «Salva» nella barra in alto salva tutto il modello")
            self.save_button.clicked.connect(lambda _=False: self.save_changes())
            buttons = (self.cancel_button, self.save_button)
        else:
            self.modify_button = QPushButton(icon("mdi6.pencil-outline"), "Modifica")
            self.modify_button.setToolTip("Passa in modalità modifica delle informazioni della scheda")
            self.modify_button.clicked.connect(lambda _=False: self.start_editing())
            reason = self.denied()
            if reason:
                self.modify_button.setEnabled(False)
                self.modify_button.setToolTip(reason)
            buttons = (self.modify_button,)
            if can_approve(element) and self.approver is not None and self.approver():
                self.approve_button = QPushButton(icon("mdi6.check-decagram-outline", "white"),
                                                  "Approva e crea il dominio")
                self.approve_button.setProperty("primary", True)
                self.approve_button.setToolTip("Design Authority: approva l'ADR e crea il nuovo dominio funzionale "
                                               "(con l'ID assegnato dal tool), la missione, il team e le sezioni "
                                               "proposti")
                self.approve_button.clicked.connect(lambda _=False: self.approve())
                buttons = (self.approve_button, self.modify_button)
        for button in buttons:
            button.setProperty("keepEnabled", True)
            top.addWidget(button)
        layout.addLayout(top)
        self.title = QLabel(self.project.model.choice_label(element), objectName="elementTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        mode = QLabel("In modifica: le modifiche si applicano con «Salva»." if self.editing else
                      "In sola lettura: solo i membri della Design Authority modificano i team." if self.denied()
                      else "In sola lettura: premi «Modifica» per cambiare le informazioni.", objectName="muted")
        layout.addWidget(mode)
        if self.read_only and self.editing:
            note = QLabel("Voce importata dalla specifica: è in sola lettura. Attiva la modalità modifica per "
                          "cambiarla.", objectName="muted")
            note.setWordWrap(True)
            layout.addWidget(note)
        return frame

    def reveal(self, field):
        """Scroll to a field of the sheet (or «@srs», its traceability card) and highlight it for a moment: where a
        check found the problem. Unknown or hidden fields shown elsewhere: their card, else the top of the sheet."""
        if self.element is None:
            return
        target = self.widgets.get(field)
        schema_field = self.element.schema.field(field) if field and field != SRS_CARD else None
        if target is None and schema_field is not None and schema_field.hidden:
            target = self.widgets.get(SRS_CARD)  # e.g. the SRS items of a function, the parent of a derived one
        if target is None:
            target = self.widgets.get(HEADER)
        if target is None:
            return
        label = self.field_labels.get(field)
        QTimer.singleShot(0, lambda: self._highlight(target, label))

    def _highlight(self, target, label=None):
        page = self.widget()
        if page is None or not page.isAncestorOf(target):
            return  # the page was rebuilt in the meantime
        self.ensureWidgetVisible(target, 40, 80)
        rect = target.geometry()
        rect.moveTopLeft(target.parentWidget().mapTo(page, rect.topLeft()))
        if label is not None and page.isAncestorOf(label):
            label_rect = label.geometry()
            label_rect.moveTopLeft(label.parentWidget().mapTo(page, label_rect.topLeft()))
            rect = rect.united(label_rect)
        overlay = QFrame(page)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setStyleSheet(f"QFrame {{ border: 2px solid {HIGHLIGHT_COLOR}; border-radius: 6px; "
                              "background: rgba(247, 144, 9, 28); }")
        overlay.setGeometry(rect.adjusted(-6, -4, 6, 4))
        overlay.show()
        overlay.raise_()
        self.highlight = overlay
        QTimer(overlay, singleShot=True, interval=HIGHLIGHT_MS, timeout=overlay.deleteLater).start()

    def update_findings(self):
        """The checks were run again: the sheet shows its findings (not while it is being edited)."""
        if self.element is not None and not self.editing:
            self.refresh()

    def _findings_card(self, findings):
        frame, layout = card(f"Verifiche · {summary(count(findings))}")
        model = self.project.model
        shown = findings[:FINDINGS_SHOWN]
        lines = []
        for f in shown:
            color = SEVERITY_COLORS[f.severity]
            others = ", ".join(f"<a href='{u}'>{escape(model.label(model.get(u)))}</a>" for u in f.related
                               if model.get(u) is not None)
            lines.append(f"<p style='margin:2px 0'><b style='color:{color}'>{f.code}</b> "
                         f"<span style='color:{MUTED}'>{escape(CHECKS_BY_CODE[f.code].title)}</span><br>"
                         f"{escape(f.message)}" + (f"<br><span style='color:{MUTED}'>Schede coinvolte:</span> {others}"
                                                   if others else "") + "</p>")
        if len(findings) > len(shown):
            lines.append(f"<p style='color:{MUTED}'>… e altre {len(findings) - len(shown)} segnalazioni: vedi il "
                         "pannello Verifiche.</p>")
        text = QLabel("".join(lines))
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        text.linkActivated.connect(self.open_requested)
        text.setProperty("keepEnabled", True)
        layout.addWidget(text)
        return frame

    def _id_widget(self):
        """Automatic identifier: read-only, with an explicit «Rinumera» when the context has changed."""
        self.id_edit = QLineEdit(self.draft.get("id") or "", readOnly=True, objectName="readonly")
        self.renumber_button = QPushButton(icon("mdi6.refresh"), "Rinumera")
        self.renumber_button.setToolTip("Riassegna l'ID secondo il contesto attuale (es. dopo lo spostamento "
                                        "in un altro dominio)")
        self.renumber_button.clicked.connect(self._renumber)
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.id_edit, 1)
        row.addWidget(self.renumber_button)
        self._refresh_id()
        return w, lambda: self.draft.get("id")

    def _refresh_id(self):
        model, element = self.project.model, self.draft
        self.id_edit.setText(element.get("id") or "")
        missing = missing_context(element, model)
        self.id_edit.setPlaceholderText(
            f"Verrà assegnato dopo aver indicato: {', '.join(missing)}" if missing else "Assegnato automaticamente")
        self.renumber_button.setVisible(bool(element.get("id")) and rule(element, model) is not None
                                        and not matches_context(element, model))

    def _renumber(self):
        """New identifier for the current context, in the draft (applied with «Salva»)."""
        self.flush()
        new_id = compute_id(self.draft, self.project.model)
        if new_id and new_id != self.draft.get("id"):
            self.draft.set("id", new_id)
            self._draft_changed()

    def _srs_trace_card(self):
        """Traced SRS items of the sheet, opened in their own window; edited with the «Traccia…» window.

        SA-1 domain: sections of which it is principal, sections and clauses to which it contributes.
        SA-2 / LA-2 function: sections and clauses it is allocated to, derived requirements (SA-4)."""
        from arcadia_tool.ui import srs_trace

        model, element = self.project.model, self.element
        if element.kind == "derived_requirement":
            return self._derived_trace_card()
        if element.kind == "domain":
            title, label, tip = ("Tracciabilità verso le voci SRS (A4)", "Traccia sezioni e clausole SRS…",
                                 "Collega il dominio alle sezioni (es. 3.4.1) o alle clausole (es. 3.4.1.3)")
            columns = (("srsPrincipal", "Sezioni SRS principali", srs_trace.principal_items(model, element)),
                       ("srsContributing", "Sezioni e clausole SRS a cui contribuisce",
                        srs_trace.contributed_items(model, element)))
        elif element.kind == "system_function":
            title, label, tip = ("Allocazione alle voci SRS", "Alloca a sezioni e clausole SRS…",
                                 "Alloca la funzione a sezioni (es. 3.4.1) o clausole (es. 3.4.1.3)")
            columns = (("srsAllocated", "Sezioni e clausole SRS", srs_trace.allocated_items(model, element)),)
        else:  # logical function: also the derived requirements it refines (LA-2)
            title, label, tip = ("Allocazione alle voci SRS e ai requisiti derivati",
                                 "Alloca a sezioni, clausole e requisiti derivati…",
                                 "Alloca la funzione a sezioni (es. 3.4.1), clausole (es. 3.4.1.3) o requisiti "
                                 "derivati (SA-4)")
            columns = (("srsAllocated", "Sezioni e clausole SRS", srs_trace.allocated_items(model, element)),
                       ("derivedAllocated", "Requisiti derivati (SA-4)", srs_trace.derived_of(model, element)))
        frame, layout = card(title)
        has_srs = bool(model.of_kind("requirement"))
        button = QPushButton(icon("mdi6.link-variant-plus"), label)
        button.setEnabled(has_srs)
        button.setToolTip(tip if has_srs else "Importa prima le voci SRS (menu Progetto › Importa voci SRS)")
        button.clicked.connect(self._trace_srs)
        row = QHBoxLayout()
        row.addWidget(button)
        if element.kind == "domain":  # the principal sections written in its SA-1 sheet in Excel
            imported = QPushButton(icon("mdi6.microsoft-excel"), "Importa clausole principali…")
            imported.setEnabled(has_srs)
            imported.setToolTip("Legge la riga «Sezioni SRS principali» del foglio del dominio in un file Excel "
                                "(SA-1), ne mostra le voci e le importa come sezioni principali del dominio"
                                if has_srs else "Importa prima le voci SRS (menu Progetto › Importa voci SRS)")
            imported.clicked.connect(lambda _=False: self._import_principal())
            row.addWidget(imported)
        if element.kind == "system_function":  # the catalogue of the functions of the teams, SA-2 in Excel
            imported = QPushButton(icon("mdi6.microsoft-excel"), "Importa funzioni da Excel SA-2…")
            imported.setToolTip("Legge il catalogo delle funzioni di sistema (un foglio per dominio) e, dopo un "
                                "riepilogo, crea le funzioni nei loro domini, con gli ID dati da ATLAS, allocate "
                                "alle clausole indicate dai team")
            imported.clicked.connect(lambda _=False: self._import_functions())
            row.addWidget(imported)
        row.addStretch()
        layout.addLayout(row)
        lists = QHBoxLayout()
        for name, title, items in columns:
            column = QVBoxLayout()
            column.addWidget(QLabel(f"{title} ({len(items)})", objectName="formLabel"))
            view = QListWidget(objectName=name)
            view.setMinimumHeight(120)
            view.setMaximumHeight(240)
            for e in items:
                entry = QListWidgetItem(model.label(e))  # a derived requirement: its ID only
                entry.setData(Qt.UserRole, e.uuid)
                entry.setToolTip((e.get("text") or e.get("obligation") or e.get("title") or "")[:600])
                view.addItem(entry)
            if not items:
                view.addItem(QListWidgetItem("Nessuna voce tracciata"))
                view.setEnabled(False)
            view.setToolTip("Doppio clic per aprire la voce")
            view.itemDoubleClicked.connect(lambda entry: entry.data(Qt.UserRole)
                                           and self.open_requested.emit(entry.data(Qt.UserRole)))
            column.addWidget(view)
            lists.addLayout(column, 1)
        layout.addLayout(lists)
        return frame

    def _derived_trace_card(self):
        """SA-4: the SRS item the requirement is derived from and its logical function, each chosen in a window
        with search and ticks."""
        model, element = self.project.model, self.draft
        frame, layout = card("Tracciabilità")
        rows = (
            ("parentItem", "Voce madre", element.get("parent"), "Scegli la voce madre…", self._choose_parent,
             bool(model.of_kind("requirement")), "Importa prima le voci SRS (menu File › Importa SRS)"),
            ("logicalFunction", "Funzione logica (LA-2)", element.get("function"), "Scegli la funzione logica…",
             self._choose_function, bool(model.of_kind("logical_function")),
             "Crea prima le funzioni logiche (LA-2) nel modello"),
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(16)
        for name, label, uuid, button_text, action, enabled, why in rows:
            target = model.get(uuid) if uuid else None
            shown = QLineEdit(model.choice_label(target) if target else "", readOnly=True, objectName="readonly")
            shown.setAccessibleName(name)
            shown.setPlaceholderText("Non indicata")
            shown.setToolTip((target.get("text") or target.get("title") or "")[:600] if target else "")
            button = QPushButton(icon("mdi6.link-variant-plus"), button_text)
            button.setEnabled(enabled)
            button.setToolTip("" if enabled else why)
            button.clicked.connect(action)
            line = QHBoxLayout()
            line.addWidget(shown, 1)
            line.addWidget(button)
            if target is not None:
                line.addWidget(self._open_button(target))
            form.addRow(QLabel(label, objectName="formLabel"), line)
            self.widgets[name] = shown
        layout.addLayout(form)
        return frame

    def _open_button(self, target):
        """Opens a referenced element in its own window; usable also on a read-only sheet."""
        read = QPushButton(icon("mdi6.open-in-new"), "")
        read.setToolTip("Apri in una finestra")
        read.setProperty("keepEnabled", True)
        read.clicked.connect(lambda _=False, u=target.uuid: self.open_requested.emit(u))
        return read

    def _choose_parent(self):
        from arcadia_tool.ui.srs_trace import TraceParentDialog

        self.flush()
        dialog = TraceParentDialog(self.project, self.draft, self)  # sets the draft, applied with «Salva»
        if dialog.exec() and dialog.changed:
            self._draft_changed()

    def _choose_function(self):
        from arcadia_tool.ui.srs_trace import choose_logical_function

        self.flush()
        chosen = choose_logical_function(self.project, self.draft, self)
        if chosen is not False and chosen != self.draft.get("function"):
            self.draft.set("function", chosen)
            self._draft_changed()

    @local_change
    def _import_principal(self, path=None):
        """«Importa clausole principali…»: the domain becomes the principal domain of the sections of its row in
        the Excel sheet (after a summary); saved with the «Salva» of the sheet."""
        from arcadia_tool.ui.import_principal import import_principal

        self.flush()
        changed = import_principal(self.project, self.element, self, path)
        for item in changed:
            self.element_changed.emit(item)
        if changed:  # saved with the «Salva» of the sheet, Ctrl+S or the «Salva» of the toolbar
            self._build()
        return changed

    @local_change
    def _import_functions(self, path=None):
        """«Importa funzioni da Excel SA-2…»: the functions of the catalogue in their domains, allocated to their
        clauses (after a summary); saved with the «Salva» of the sheet, Ctrl+S or the «Salva» of the toolbar."""
        from arcadia_tool.ui.import_functions import import_functions, summary

        self.flush()
        created, changed, deleted = import_functions(self.project, self, path)
        if self.element is not None and self.element in changed:
            self.draft.set("sections", self.element.get("sections"))
            self._build()
        for element in changed:
            self.element_changed.emit(element)
        if created or deleted:
            self.elements_created.emit()  # the model tree, the lists, the views (this sheet, if its function went)
        if created or changed or deleted:
            QMessageBox.information(self, "Importa funzioni di sistema",
                                    f"{summary(created, changed, deleted)}.\nSalva la scheda (Ctrl+S) o usa «Salva» "
                                    "nella barra in alto per scrivere le modifiche su disco.")
        return created, changed, deleted

    @local_change
    def _trace_srs(self):
        """The traceability windows apply their choices with their own «Applica» (they change also other
        elements, e.g. the allocation of the SRS items to the domain)."""
        from arcadia_tool.ui.srs_trace import SRS_FIELD, TraceFunctionDialog, TraceSrsDialog

        self.flush()
        dialog_class = TraceSrsDialog if self.element.kind == "domain" else TraceFunctionDialog
        dialog = dialog_class(self.project, self.element, self)
        if dialog.exec():
            if dialog.created:
                self.elements_created.emit()
            for item in dialog.changed:
                self.element_changed.emit(item)
            if self.element.kind in SRS_FIELD:  # its own list, set by the window
                self.draft.set(SRS_FIELD[self.element.kind], self.element.get(SRS_FIELD[self.element.kind]))
            self._build()  # shows the new lists

    def _picker_widget(self, f, value):
        """A reference chosen in a window with search and ticks (one element): the choice and «Scegli…»."""
        model = self.project.model
        target = model.get(value) if value else None
        shown = QLineEdit(model.choice_label(target) if target else (value or ""), readOnly=True,
                          objectName="readonly")
        shown.setPlaceholderText("Non indicato")
        shown.setToolTip((target.get("text") or target.get("description") or "")[:600] if target else "")
        button = QPushButton(icon("mdi6.link-variant-plus"), "Scegli…")
        button.setEnabled(bool(model.of_kind(*f.ref_kinds)))
        button.setToolTip(f"Scegli «{f.label}» in una finestra con ricerca" if button.isEnabled()
                          else "Nessun elemento da scegliere nel modello")
        button.clicked.connect(lambda _=False: self._pick(f))
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(shown, 1)
        row.addWidget(button)
        if target is not None:
            row.addWidget(self._open_button(target))
        return w, lambda: self.draft.get(f.name)

    def _pick(self, f):
        from arcadia_tool.ui.srs_trace import ITEM_DIALOGS, TraceItemDialog, choose_element

        self.flush()
        if f.ref_kinds == ("requirement",):  # SRS item: chapter tabs, search, ticks, full text
            dialog = ITEM_DIALOGS.get(f.name, TraceItemDialog)(self.project, self.draft, self)  # sets the draft
            changed = dialog.exec() and dialog.changed
        else:
            chosen = choose_element(self.project, self.draft, f.name, self)
            changed = chosen is not False and chosen != self.draft.get(f.name)
            if changed:
                self.draft.set(f.name, chosen)
        if changed:
            self._draft_changed()

    def _derived_widget(self, f):
        """Read-only copy of a field of the referenced element (the referent of the domain's team)."""
        ref, source = f.derived_from
        w = QLineEdit(readOnly=True, objectName="readonly")
        ref_field = self.element.schema.field(ref)
        source_label = KINDS_BY_NAME[ref_field.ref_kinds[0]].field(source).label.lower()

        def reference():
            return self.getters[ref]() if ref in self.getters else self.draft.get(ref)

        def current():
            target = self.project.model.get(reference()) if reference() else None
            return target.get(source) if target is not None else None

        def refresh(*_):
            value = current()
            w.setText(", ".join(value) if isinstance(value, list) else value or "")
            w.setPlaceholderText(f"Non indicato in «{ref_field.label}»" if reference()
                                 else f"Scegli «{ref_field.label}»")

        w.setToolTip(f"Automatico: {source_label} indicato nella scheda di «{ref_field.label}».")
        if isinstance(self.widgets.get(ref), QComboBox):  # a picker field refreshes the whole page instead
            self.widgets[ref].currentIndexChanged.connect(refresh)
        refresh()
        return w, current

    ADR_COLUMNS = ("Esito", "ID", "Titolo", "Tipo", "Stato", "Decisione DA")
    OUTCOME_COLORS = {"Attiva": ("#1E40AF", "#DBEAFE"), "Approvata": ("#166534", "#DCFCE7"),
                      "Respinta": ("#B42318", "#FEE4E2"), "Superata": ("#374151", "#E5E7EB")}

    def _adrs_widget(self):
        """The ADR about the domain or the system function (attive, approvate, respinte, superate), a double click
        opens one; «Nuova ADR…» creates one from the sheet (its type chosen first). Usable also on a read-only
        sheet: the ADR is another element."""
        w = QWidget()
        w.setProperty("keepEnabled", True)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        table = QTableWidget(0, len(self.ADR_COLUMNS))
        table.setHorizontalHeaderLabels(self.ADR_COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        table.setToolTip("Doppio clic su una riga per aprire l'ADR")
        table.cellDoubleClicked.connect(
            lambda row, _c: self.open_requested.emit(table.item(row, 1).data(Qt.UserRole)))
        self.adrs_table = table
        self.adrs_empty = QLabel(objectName="muted")
        new = QPushButton(icon("mdi6.plus"), "Nuova ADR…")
        what = "il dominio" if self.element.kind == "domain" else "la funzione"
        new.setToolTip(f"Crea una decisione architetturale che riguarda {what}: prima se ne sceglie il tipo")
        new.clicked.connect(lambda _=False: self.adr_requested.emit(self.element.uuid))
        denied = self.edit_denied("adr") if self.edit_denied else None
        new.setEnabled(not denied)
        if denied:
            new.setToolTip(denied)
        self.adrs_new = new
        row = QHBoxLayout()
        row.addWidget(self.adrs_empty, 1)
        row.addWidget(new)
        layout.addWidget(table)
        layout.addLayout(row)
        self.refresh_adrs()
        return w, lambda: [table.item(r, 1).data(Qt.UserRole) for r in range(table.rowCount())]

    def refresh_adrs(self):
        """The table of the ADR of the sheet, as the model is now (an ADR created, decided, deleted)."""
        from arcadia_tool.model.adr import outcome, related_adrs

        table = getattr(self, "adrs_table", None)
        if table is None or self.element is None:
            return
        try:
            table.rowCount()
        except RuntimeError:  # the page was built again: its table is gone
            return
        model = self.project.model
        adrs = related_adrs(model, self.element)
        table.setRowCount(0)
        for adr in adrs:
            r = table.rowCount()
            table.insertRow(r)
            state = outcome(adr)
            values = (state, adr.get("id") or "", adr.get("title") or "", adr.get("adr_type") or "",
                      adr.get("status") or "", adr.get("da_decision") or "")
            for c, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.UserRole, adr.uuid)
                cell.setToolTip(model.label(adr))
                table.setItem(r, c, cell)
            fg, bg = self.OUTCOME_COLORS[state]
            table.item(r, 0).setForeground(QBrush(QColor(fg)))
            table.item(r, 0).setBackground(QBrush(QColor(bg)))
            for c in (4, 5):
                if values[c]:
                    fg, bg = status_colors(values[c])
                    table.item(r, c).setForeground(QBrush(QColor(fg)))
        rows = min(max(len(adrs), 1), 8)  # as high as its rows, up to 8 (then it scrolls)
        table.setFixedHeight(table.horizontalHeader().sizeHint().height() + rows * 30 + 4)
        table.verticalHeader().setDefaultSectionSize(30)
        table.setVisible(bool(adrs))
        what = "il dominio" if self.element.kind == "domain" else "la funzione"
        counts = {s: sum(1 for a in adrs if outcome(a) == s) for s in self.OUTCOME_COLORS}
        self.adrs_empty.setText(f"Nessuna ADR riguarda {what}." if not adrs else " · ".join(
            f"{n} {s.lower()[:-1] + ('a' if n == 1 else 'e')}" for s, n in counts.items() if n))

    def _show_computed_ref(self, f, widget, uuid):
        """An element read from the model; the domain of an SRS item taken from the section containing it says so."""
        from arcadia_tool.model.adr import allocated_from

        model = self.project.model
        text, tip = (model.label_of(uuid) if uuid else ""), "Letto dal modello"
        sources = allocated_from(model, self.draft) if f.computed == "item_primary" else []
        if uuid and sources:
            names = ", ".join(s.get("id") or "" for s in sources)
            text += f"  (da {names})"
            tip = (f"Domini presi da {names}: la sezione o la clausola che contiene la voce, che non ne ha di "
                   "propri (A4).")
        widget.setText(text)
        widget.setToolTip(tip)
        widget.setProperty("uuid", uuid)

    def _member_widget(self, f, value):
        """A member of the team chosen in another field of the sheet (the member of the team proposing an ADR)."""
        from arcadia_tool.model.teams import member_names

        w = compact_combo()
        team_label = self.element.schema.field(f.members_of).label

        def refresh(*_):
            getter = self.getters.get(f.members_of)
            uuid = getter() if getter else self.draft.get(f.members_of)
            team = self.project.model.get(uuid) if uuid else None
            selected = w.currentData() if w.count() else value
            w.blockSignals(True)
            w.clear()
            w.addItem("", None)
            for name in (member_names(team) if team is not None else []):
                w.addItem(name, name)
            if selected and w.findData(selected) < 0:
                w.addItem(f"{selected} (non è tra i membri del team)", selected)
            w.setCurrentIndex(max(w.findData(selected), 0) if selected else 0)
            w.blockSignals(False)
            w.setToolTip(f"Si sceglie tra i membri del team indicato in «{team_label}»" if team is not None else
                         f"Scegli prima il team in «{team_label}»")

        refresh()
        source = self.widgets.get(f.members_of)
        if isinstance(source, QComboBox):
            source.currentIndexChanged.connect(refresh)
        w.currentIndexChanged.connect(self._changed)
        return w, w.currentData

    def _choice_widget(self, f, value):
        """A text chosen among the values of a list field of the same element (the referent among the members)."""
        w = compact_combo()
        source_label = self.element.schema.field(f.choices_from).label

        def options():
            getter = self.getters.get(f.choices_from)
            values = getter() if getter else (self.draft.get(f.choices_from) or [])
            # rows (the members of a team): their names
            return [v.get("name") if isinstance(v, dict) else v for v in values if v and
                    (not isinstance(v, dict) or v.get("name"))]

        def refresh(*_):
            selected = w.currentData() if w.count() else value
            w.blockSignals(True)
            w.clear()
            w.addItem("", None)
            for name in options():
                w.addItem(name, name)
            if selected and w.findData(selected) < 0:
                w.addItem(f"{selected} (non è tra i {source_label.lower()})", selected)
            w.setCurrentIndex(max(w.findData(selected), 0) if selected else 0)
            w.blockSignals(False)

        w.setToolTip(f"Si sceglie tra i «{source_label}» indicati sopra.")
        refresh()
        source = self.widgets.get(f.choices_from)
        if source is not None:
            source.textChanged.connect(refresh)
        else:  # a table built after (in its own card, e.g. the members of a team): connected then
            self._choice_sources.append((f.choices_from, refresh))
        w.currentIndexChanged.connect(self._changed)
        return w, w.currentData

    def _make_widget(self, f, value):
        model = self.project.model
        if f.computed == "related_adrs":  # the ADR about the domain or the function: a table, and a new one
            return self._adrs_widget()
        if f.computed:  # computed from the other fields (e.g. the SRS items of the domains merged)
            from arcadia_tool.model.adr import COMPUTED
            if f.type == REFS:
                w = RefsWidget(model, f.ref_kinds)
                w.set_value(COMPUTED[f.computed](model, self.draft))
                w.set_read_only("Calcolato dal tool")
            elif f.type == REF:  # an element (e.g. the principal domain an SRS item has now)
                uuid = COMPUTED[f.computed](model, self.draft)
                w = QLineEdit(readOnly=True, objectName="readonly")
                w.setPlaceholderText("Nessuno")
                self._show_computed_ref(f, w, uuid)
                self._computed.append((f, w))
                return w, lambda: w.property("uuid")
            else:  # a text (e.g. the mission the domain has now)
                w = RichTextEdit(COMPUTED[f.computed](model, self.draft))
                w.setReadOnly(True)
                w.setProperty("keepEnabled", True)
                w.setToolTip("Letto dalla scheda del dominio")
            self._computed.append((f, w))
            return w, (w.value if f.type == REFS else w.markdown)
        if f.type == STR and f.name == "id" and is_automatic(self.element.kind):
            return self._id_widget()
        if f.derived_from:
            return self._derived_widget(f)
        if f.choices_from:
            return self._choice_widget(f, value)
        if f.members_of:
            return self._member_widget(f, value)
        if f.picker:
            return self._picker_widget(f, value)
        if f.type == STR:
            w = QLineEdit(value or "")
            if self.element.schema.id_format and f.name == "id":
                w.setPlaceholderText(f"es. {self.element.schema.id_format}")
            w.textChanged.connect(self._changed)
            return w, lambda: w.text().strip()
        if f.type == TEXT and self.element.kind in PLAIN_TEXT_KINDS:
            w = QPlainTextEdit(value or "")
            w.setFixedHeight(84)
            w.textChanged.connect(self._changed)
            return w, lambda: w.toPlainText().strip()
        if f.type == TEXT:  # free text with styles (bold, lists…), stored as Markdown
            w = RichTextEdit(value or "")
            w.changed.connect(self._changed)
            return w, w.markdown
        if f.type == INT:
            w = QSpinBox(maximum=100000)
            w.setSpecialValueText("—")
            w.setValue(value or 0)
            w.valueChanged.connect(self._changed)
            return w, lambda: w.value() or None
        if f.type == BOOL:
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(self._changed)
            return w, w.isChecked
        if f.type in (ENUM, REF):
            w = compact_combo()
            w.addItem("", None)
            if f.type == ENUM:
                choices, value = [(o, o) for o in f.options], enum_option(f, value)
            else:
                choices = _ref_choices(model, f.ref_kinds)
            for data, label in choices:
                if data != self.element.uuid:
                    w.addItem(label, data)
                    w.setItemData(w.count() - 1, label, Qt.ToolTipRole)
            if value and w.findData(value) < 0:
                w.addItem(model.label_of(value) or f"{value} (inesistente)", value)
            w.setCurrentIndex(max(w.findData(value), 0) if value else 0)
            w.currentIndexChanged.connect(self._changed)
            if any(o.when and o.when[0] == f.name for o in self.element.schema.fields):
                # It decides which fields the sheet has (the type of an ADR): the page follows it.
                w.currentIndexChanged.connect(lambda _i, name=f.name: self._controller_changed(name))
            return w, w.currentData
        if f.type == MULTIENUM:
            w = QWidget()
            layout = QGridLayout(w)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setHorizontalSpacing(16)
            # Short options on one row (or a few), long ones (e.g. the criteria A2) one under the other in two
            # columns: the sheet never gets wider than the window.
            per_row = 2 if max((len(o) for o in f.options), default=0) > 20 else 9
            boxes = []
            for i, option in enumerate(f.options):
                box = QCheckBox(option)
                box.setChecked(option in (value or []))
                box.toggled.connect(self._changed)
                layout.addWidget(box, *divmod(i, per_row))
                boxes.append(box)
            layout.setColumnStretch(per_row, 1)
            return w, lambda: [b.text() for b in boxes if b.isChecked()]
        if f.type == STRLIST:
            w = QLineEdit(", ".join(value or []))
            w.setPlaceholderText("valori separati da virgola")
            w.textChanged.connect(self._changed)
            return w, lambda: [s.strip() for s in w.text().split(",") if s.strip()]
        if f.type == MAP:
            w = QWidget()
            grid = QGridLayout(w)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            combos = {}
            for i, key in enumerate(f.options):
                combo = QComboBox()
                combo.addItems(["", "X", "O"])
                combo.setCurrentText((value or {}).get(key, ""))
                combo.currentIndexChanged.connect(self._changed)
                row, col = divmod(i, MAP_COLUMNS)
                label = QLabel(key, alignment=Qt.AlignCenter)
                label.setStyleSheet(f"color:{MUTED}; font-weight:600;")
                grid.addWidget(label, row * 2, col)
                grid.addWidget(combo, row * 2 + 1, col)
                combos[key] = combo
            return w, lambda: {k: c.currentText() for k, c in combos.items() if c.currentText()}
        if f.type == REFS:
            picker = None
            if f.ref_kinds == ("requirement",):  # SRS items: ticks, chapters, search, as elsewhere
                from arcadia_tool.ui.srs_trace import choose_items
                picker = lambda uuids, name=f.name, only=f.sections_only: choose_items(
                    self.project, self.draft, name, uuids, self, sections_only=only)
            w = RefsWidget(model, f.ref_kinds, picker)
            w.set_value(value)
            w.changed.connect(self._changed)
            return w, w.value
        if f.type == TABLE and self.element.kind == "team" and f.name == MEMBERS:
            from arcadia_tool.ui.team_members import MembersWidget
            w = MembersWidget(model)
            w.set_value(member_rows(self.draft))

            def locks_out(rows):
                if self.locks_out is None:
                    return False
                draft = self.draft.copy()
                draft.set(MEMBERS, rows)
                return self.locks_out(draft)
            w.locks_out = locks_out
            w.changed.connect(self._changed)
            return w, w.value
        if f.type == TABLE and any(c.choices for c in f.columns):
            from arcadia_tool.model.adr import CHOICES
            w = TableWidget(model, f, choices=lambda col: CHOICES[col.choices](model, self.draft))
            w.set_value(value)
            w.changed.connect(self._changed)
            self._dynamic_tables.append(w)
            return w, w.value
        if f.type == TABLE:
            w = TableWidget(model, f)
            w.set_value(value)
            w.changed.connect(self._changed)
            return w, w.value
        if f.type == IMAGE:
            w = QLabel(alignment=Qt.AlignLeft)
            pixmap = load_pixmap(self.project, value)
            if pixmap is None:
                w.setText(f"Immagine non trovata: {value}")
                w.setObjectName("muted")
            else:
                w.setPixmap(pixmap if pixmap.width() <= IMAGE_MAX_WIDTH
                            else pixmap.scaledToWidth(IMAGE_MAX_WIDTH, Qt.SmoothTransformation))
            w.setToolTip(value or "")
            return w, lambda: value
        raise ValueError(f"Tipo di campo non gestito: {f.type}")

    def _changed(self, *_):
        if self._building or not self.editing:
            return  # values set while the page is built, or a read-only sheet
        self._set_dirty(True)
        self._timer.start()

    def _controller_changed(self, name):
        """A field that decides which fields the sheet has (the type of an ADR) changed: the fields that no longer
        apply are emptied, after a confirmation if they have values, and the page is built again."""
        if self._building or not self.editing:
            return
        before = self.draft.copy()
        self._apply()
        lost = [f for f in self.draft.schema.fields if f.when and f.when[0] == name and not f.applies(self.draft)
                and not is_empty(self.draft.values.get(f.name))]
        if lost:
            labels = ", ".join(f"«{f.label}»" for f in lost)
            answer = QMessageBox.question(self, "Cambio di tipo",
                                          f"Con il nuovo tipo questi campi non servono più e vengono svuotati: "
                                          f"{labels}. Continuare?")
            if answer != QMessageBox.Yes:
                self.draft = before
                self._build()
                return
            for f in lost:
                self.draft.set(f.name, None)
        self._set_dirty(True)
        self._build()

    def _draft_changed(self):
        """A choice made in a window (voce madre, funzione…) changed the draft: show it."""
        self._set_dirty(True)
        self._build()

    def discard_pending(self):
        """Forget the changes not saved (the element was deleted)."""
        self._timer.stop()
        self.element = self.draft = None
        self._set_dirty(False)

    def flush(self):
        """Copy the values being typed into the draft (they reach the model only with «Salva»)."""
        if self._timer.isActive():
            self._timer.stop()
            self._apply()

    def _apply(self):
        if self.draft is None:
            return
        schema = self.draft.schema
        names = [n for n in self.getters if not self.read_only or (schema.field(n) and schema.field(n).analysis)]
        for name in names:
            if not schema.field(name) or not schema.field(name).computed:
                self.draft.set(name, self.getters[name]())
        for f, widget in getattr(self, "_computed", []):  # follow the fields they are computed from
            from arcadia_tool.model.adr import COMPUTED
            value = COMPUTED[f.computed](self.project.model, self.draft)
            if f.type == REFS:
                widget.set_value(value)
            elif f.type == REF:
                self._show_computed_ref(f, widget, value)
            elif value != widget.markdown():
                widget.set_markdown(value)
        for table in getattr(self, "_dynamic_tables", []):  # the lists of their cells follow the element
            table.refresh_choices()
        if is_automatic(self.draft.kind) and hasattr(self, "id_edit"):
            self._refresh_id()
        self.title.setText(self.project.model.choice_label(self.draft))


class ElementWindow(QDialog):
    """An element in its own window (e.g. an SRS item traced by the domain shown in the main page)."""

    def __init__(self, srs_edit_mode=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(900, 760)
        self.editor = ElementEditor(srs_edit_mode)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

    def show_element(self, project, element):
        if self.editor.element is not element and not resolve_unsaved(self.editor, self):
            return
        if self.editor.element is not element:
            self.editor.edit(project, element)
        self.setWindowTitle(f"{element.schema.label} · {project.model.label(element)}")
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if not resolve_unsaved(self.editor, self):
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):  # Esc: like closing the window
        if resolve_unsaved(self.editor, self):
            super().reject()


def resolve_unsaved(editor, parent, what=None):
    """Before a sheet with changes not saved is closed: save or discard them. False if the user cancels."""
    if not editor.dirty or editor.element is None:
        return True
    name = editor.project.model.label(editor.element)
    box = QMessageBox(QMessageBox.Question, "Modifiche non salvate",
                      what or f"La scheda «{name}» ha modifiche non salvate.", parent=parent)
    box.setInformativeText("Salvarle o scartarle?")
    save = box.addButton("Salva", QMessageBox.AcceptRole)
    discard = box.addButton("Scarta", QMessageBox.DestructiveRole)
    box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(save)
    box.exec()
    if box.clickedButton() is save:
        editor.save_changes()
        return True
    if box.clickedButton() is discard:
        editor.cancel_changes(ask=False)
        return True
    return False
