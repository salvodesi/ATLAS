"""Presentation of a semantic model diff: grouped tree + detail of the selected change."""
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QSplitter,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from arcadia_tool.diff.semantic import (ADDED, CHANGE_LABELS, MODIFIED, REMOVED, count_label, format_value, is_text,
                                        word_diff)
from arcadia_tool.model.schema import KINDS_BY_NAME, MAP, MULTIENUM, REF, REFS, STRLIST, TABLE
from arcadia_tool.ui.theme import BORDER, CHANGE_BG, CHANGE_COLORS, MUTED, icon, kind_icon

CHANGE_ROLE = Qt.UserRole
CHANGE_ICONS = {ADDED: "mdi6.plus-circle-outline", REMOVED: "mdi6.minus-circle-outline",
                MODIFIED: "mdi6.circle-edit-outline"}

CSS = f"""
body {{ font-family: 'Segoe UI'; font-size: 10pt; color: #1F2933; }}
h2 {{ font-size: 13pt; margin: 0 0 2px 0; }}
.kind {{ color: {MUTED}; margin-bottom: 10px; }}
table.fields {{ border-collapse: collapse; width: 100%; }}
table.fields td {{ padding: 6px 8px; border-bottom: 1px solid {BORDER}; vertical-align: top; }}
td.name {{ color: {MUTED}; width: 30%; font-weight: 600; }}
.old {{ color: {CHANGE_COLORS[REMOVED]}; background: {CHANGE_BG[REMOVED]}; text-decoration: line-through; }}
.new {{ color: {CHANGE_COLORS[ADDED]}; background: {CHANGE_BG[ADDED]}; }}
.warn {{ color: {CHANGE_COLORS[MODIFIED]}; font-weight: 600; }}
table.rows {{ border-collapse: collapse; }}
table.rows th {{ background: #F6F8FA; color: {MUTED}; padding: 4px 6px; border: 1px solid {BORDER}; }}
table.rows td {{ padding: 4px 6px; border: 1px solid {BORDER}; }}
"""


def _flags(change):
    flags = []
    if change.renamed:
        flags.append("rinominato")
    if change.status_changed:
        flags.append("stato")
    if change.significant:
        flags.append("significativo")
    return " · ".join(flags)


def _cell_text(diff, column, row):
    value = (row or {}).get(column.name)
    if not value:
        return ""
    if isinstance(value, (list, tuple)):  # e.g. the IDs of the accounts of a member, one per PC
        return ", ".join(map(str, value))
    if value is True:  # a tick, e.g. «Invia sul ramo principale» of a member
        return "Sì"
    return diff.label_of(value) if column.type == REF else str(value)


def _field_html(diff, kind, fc):
    if is_text(fc):
        html = ""
        for op, text in word_diff(fc.before, fc.after):
            t = escape(text).replace("\n", "<br>")
            html += f"<span class='new'>{t}</span>" if op == "+" else f"<span class='old'>{t}</span>" if op == "-" else t
        return html
    if fc.type == TABLE:
        columns = KINDS_BY_NAME[kind].field(fc.name).columns
        head = "".join(f"<th>{escape(c.label)}</th>" for c in columns)
        body = ""
        for r in fc.rows:
            row = r.after if r.change != REMOVED else r.before
            cells = ""
            for c in columns:
                text = escape(_cell_text(diff, c, row))
                if r.change == MODIFIED and c.name in r.columns:
                    text = f"<span class='old'>{escape(_cell_text(diff, c, r.before))}</span> <span class='new'>{text}</span>"
                cells += f"<td>{text}</td>"
            style = f" style='background:{CHANGE_BG[r.change]}'" if r.change != MODIFIED else ""
            body += f"<tr{style}><td>{r.index + 1}</td>{cells}</tr>"
        return f"<table class='rows'><tr><th>#</th>{head}</tr>{body}</table>"
    if fc.type in (REFS, MULTIENUM, STRLIST, MAP):
        if fc.type == REFS:
            label = diff.label_of
        elif fc.type == MAP:
            label = lambda k: f"{k}: {(fc.after or {}).get(k, '')}"
        else:
            label = str
        items = [f"<span class='new'>+ {escape(label(x))}</span>" for x in fc.added_items]
        if fc.type == MAP:
            items += [f"<span class='old'>{escape(k)}: {escape(fc.before[k])}</span>" for k in fc.removed_items]
        else:
            items += [f"<span class='old'>{escape(label(x))}</span>" for x in fc.removed_items]
        return "<br>".join(items)
    before = escape(format_value(diff, fc.type, fc.before))
    after = escape(format_value(diff, fc.type, fc.after))
    return f"<span class='old'>{before}</span> → <span class='new'>{after}</span>"


def change_html(diff, change):
    color = CHANGE_COLORS[change.change]
    parts = [f"<style>{CSS}</style>",
             f"<h2 style='color:{color}'>{escape(change.label)}</h2>",
             f"<div class='kind'>{escape(KINDS_BY_NAME[change.kind].label)} · {CHANGE_LABELS[change.change].lower()}</div>",
             "<table class='fields'>"]
    if change.change != MODIFIED:
        element = change.element
        for f in element.schema.fields:
            value = element.values.get(f.name)
            if value:
                parts.append(f"<tr><td class='name'>{escape(f.label)}</td>"
                             f"<td>{escape(format_value(diff, f.type, value))}</td></tr>")
    else:
        for fc in change.fields:
            warn = " <span class='warn'>⚠ significativo</span>" if fc.significant else ""
            parts.append(f"<tr><td class='name'>{escape(fc.label)}{warn}</td>"
                         f"<td>{_field_html(diff, change.kind, fc)}</td></tr>")
    parts.append("</table>")
    return "".join(parts)


def summary_badge(change, count):
    label = QLabel(count_label(change, count))
    label.setStyleSheet(f"background:{CHANGE_BG[change]}; color:{CHANGE_COLORS[change]}; border-radius:10px;"
                        "padding:2px 10px; font-weight:600;")
    return label


class DiffView(QWidget):
    """The changes between two states. needs (to choose them, e.g. to publish some only): {uuid: the uuids of the
    changes it needs} (see storage.selective); each change has a tick, «chosen» the uuids ticked: leaving one out
    leaves out those that need it, choosing one chooses those it needs (told in `note`)."""
    selection_changed = Signal()

    def __init__(self, diff, before_label, after_label, needs=None, locked=None, linked_text="Si pubblica insieme a: ",
                 follow_texts=("Selezionate anche, perché servono: ", "Escluse anche, perché ne dipendono: ")):
        super().__init__()
        self.diff = diff
        self.needs = needs
        self.locked = locked or {}  # {uuid: why it cannot be ticked}: it can only follow what it is linked to
        self.linked_text = linked_text
        self.follow_texts = follow_texts  # the note when ticking one ticks others, and when leaving one out does
        self.chosen = {c.uuid for c in diff.changes} if needs is not None else set()
        self._ticking = False
        self.note = QLabel(objectName="muted")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        counts = diff.summary()
        header = QHBoxLayout()
        self.title = QLabel(f"<b>{escape(before_label)}</b>  →  <b>{escape(after_label)}</b>")
        header.addWidget(self.title)
        header.addStretch()
        for k in (ADDED, MODIFIED, REMOVED):
            header.addWidget(summary_badge(k, counts.get(k, 0)))

        self.search = QLineEdit(placeholderText="Filtra per ID o nome", objectName="search")
        self.search.addAction(icon("mdi6.magnify"), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.change_filter = QComboBox()
        self.change_filter.addItem("Tutte le modifiche", None)
        for k in (ADDED, MODIFIED, REMOVED):
            self.change_filter.addItem(icon(CHANGE_ICONS[k], CHANGE_COLORS[k]), CHANGE_LABELS[k], k)
        self.only_significant = QCheckBox("Solo modifiche significative")
        self.search.textChanged.connect(self._populate)
        self.change_filter.currentIndexChanged.connect(self._populate)
        self.only_significant.toggled.connect(self._populate)
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.change_filter)
        filters.addWidget(self.only_significant)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Elemento", "Modifica", "Note"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.currentItemChanged.connect(self._show_detail)
        self.detail = QTextBrowser()
        self.splitter = splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail)
        splitter.setSizes([560, 520])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.note)
        if needs is not None:
            self.tree.itemChanged.connect(self._ticked)
        self._populate()

    def _populate(self, *_):
        """The changes shown (the filters); their ticks as chosen (not a choice of the user while they are made)."""
        self._ticking = True
        try:
            self._fill()
        finally:
            self._ticking = False

    @staticmethod
    def _sorts(kind, changes):
        """The changes of a kind in groups of their own: the graphic views by their type (as the groups of «Viste
        grafiche»: SA-5 Dataflow funzionali, SA-7 Catene funzionali…); [(None, changes)] for the other kinds."""
        if kind != "diagram":
            return [(None, changes)]
        from arcadia_tool.model import diagrams as dg
        titles = {t: title for title, t in dg.VIEW_GROUPS}
        titles.setdefault(dg.DIAGRAM_SCENARIO, "SA-7 Scenari di scambio")  # of an earlier version
        groups = {}
        for c in changes:
            t = c.element.get("diagram_type") if c.element is not None else None
            groups.setdefault(titles.get(t, t or "Altre viste"), []).append(c)
        order = list(titles.values())
        return sorted(groups.items(), key=lambda g: (order.index(g[0]) if g[0] in order else len(order), g[0]))

    def _fill(self):
        self.tree.clear()
        self.change_items = []
        text = self.search.text().lower()
        wanted = self.change_filter.currentData()
        if not self.diff.changes:
            self.detail.setHtml(f"<style>{CSS}</style><p class='kind'>Nessuna differenza tra i due stati del modello.</p>")
            return
        first = None
        for kind, changes in self.diff.by_kind().items():
            shown = [c for c in changes
                     if (not wanted or c.change == wanted)
                     and (not self.only_significant.isChecked() or c.significant or c.change != MODIFIED)
                     and (not text or text in c.label.lower())]
            if not shown:
                continue
            group = QTreeWidgetItem(self.tree, [f"{KINDS_BY_NAME[kind].plural}", str(len(shown)), ""])
            group.setIcon(0, kind_icon(kind))
            group.setExpanded(True)
            parents = {}
            for title, of_sort in self._sorts(kind, shown):
                if title is None:
                    parents.update({c.uuid: group for c in of_sort})
                    continue
                sort = QTreeWidgetItem(group, [title, str(len(of_sort)), ""])
                sort.setIcon(0, icon("mdi6.vector-polyline", MUTED))
                sort.setExpanded(True)
                if self.needs is not None:
                    sort.setFlags(sort.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                parents.update({c.uuid: sort for c in of_sort})
            for c in shown:
                item = QTreeWidgetItem(parents[c.uuid], [c.label, CHANGE_LABELS[c.change], _flags(c)])
                self.change_items.append(item)
                item.setIcon(0, icon(CHANGE_ICONS[c.change], CHANGE_COLORS[c.change]))
                item.setForeground(1, QBrush(QColor(CHANGE_COLORS[c.change])))
                item.setForeground(2, QBrush(QColor(MUTED)))
                item.setData(0, CHANGE_ROLE, c)
                if self.needs is not None:
                    if c.uuid not in self.locked:
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.Checked if c.uuid in self.chosen else Qt.Unchecked)
                    linked = self.needs.get(c.uuid)
                    if c.uuid in self.locked:
                        item.setToolTip(0, self.locked[c.uuid])
                    elif linked:
                        item.setToolTip(0, self.linked_text + ", ".join(
                            sorted(self.diff.label_of(u) for u in linked)))
                first = first or item
            if self.needs is not None:
                group.setFlags(group.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
        if first:
            self.tree.setCurrentItem(first)

    def _ticked(self, item, column):
        """A tick changed: the changes it needs (chosen), or those that need it (left out) follow."""
        change = item.data(0, CHANGE_ROLE)
        if self._ticking or column != 0 or change is None:
            return
        from arcadia_tool.storage.selective import dependents, required
        on = item.checkState(0) == Qt.Checked
        if on == (change.uuid in self.chosen):
            return
        if change.uuid in self.locked:  # e.g. ticked by its group: as it was
            self._refresh_ticks()
            return
        if on:
            moved = required(self.needs, [change.uuid]) - self.chosen
            self.chosen |= moved
        else:
            moved = dependents(self.needs, [change.uuid]) & self.chosen
            self.chosen -= moved
        others = sorted(self.diff.label_of(u) for u in moved - {change.uuid})
        self.note.setText((self.follow_texts[0 if on else 1] + ", ".join(others)) if others else "")
        self.note.setVisible(bool(others))
        self._refresh_ticks()
        self.selection_changed.emit()

    def _refresh_ticks(self):
        self._ticking = True
        try:
            for child in self.change_items:  # also those in the groups of a kind (the views by their type)
                change = child.data(0, CHANGE_ROLE)
                child.setCheckState(0, Qt.Checked if change.uuid in self.chosen else Qt.Unchecked)
        finally:
            self._ticking = False

    def set_chosen(self, uuids):
        """Choose these changes (with those they need, and leaving out what needs one left out)."""
        from arcadia_tool.storage.selective import required
        self.chosen = required(self.needs or {}, uuids)
        others = sorted(self.diff.label_of(u) for u in self.chosen - set(uuids))
        self.note.setText("Selezionate anche, perché legate: " + ", ".join(others) if others else "")
        self.note.setVisible(bool(others))
        self._refresh_ticks()
        self.selection_changed.emit()

    def _show_detail(self, current, _previous):
        change = current.data(0, CHANGE_ROLE) if current else None
        if change:
            self.detail.setHtml(change_html(self.diff, change))
