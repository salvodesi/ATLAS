"""Presentation of a semantic model diff: grouped tree + detail of the selected change."""
from html import escape

from PySide6.QtCore import Qt
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
    def __init__(self, diff, before_label, after_label):
        super().__init__()
        self.diff = diff
        counts = diff.summary()
        header = QHBoxLayout()
        title = QLabel(f"<b>{escape(before_label)}</b>  →  <b>{escape(after_label)}</b>")
        header.addWidget(title)
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
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail)
        splitter.setSizes([560, 520])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)
        self._populate()

    def _populate(self, *_):
        self.tree.clear()
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
            for c in shown:
                item = QTreeWidgetItem(group, [c.label, CHANGE_LABELS[c.change], _flags(c)])
                item.setIcon(0, icon(CHANGE_ICONS[c.change], CHANGE_COLORS[c.change]))
                item.setForeground(1, QBrush(QColor(CHANGE_COLORS[c.change])))
                item.setForeground(2, QBrush(QColor(MUTED)))
                item.setData(0, CHANGE_ROLE, c)
                first = first or item
        if first:
            self.tree.setCurrentItem(first)

    def _show_detail(self, current, _previous):
        change = current.data(0, CHANGE_ROLE) if current else None
        if change:
            self.detail.setHtml(change_html(self.diff, change))
