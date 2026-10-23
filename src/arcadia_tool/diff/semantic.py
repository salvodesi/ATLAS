"""Semantic diff between two model states (two saved versions, or saved vs working copy).

Elements are matched by uuid, so renames and renumbering are reported as modifications
of the same element, not as a deletion plus a creation.
"""
import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

from arcadia_tool.model.element import is_empty
from arcadia_tool.model.schema import (BOOL, KINDS_BY_NAME, MAP, MULTIENUM, REF, REFS, STRLIST, TABLE, TEXT)

ADDED = "added"
REMOVED = "removed"
MODIFIED = "modified"

CHANGE_LABELS = {ADDED: "Aggiunto", REMOVED: "Cancellato", MODIFIED: "Modificato"}
CHANGE_COUNT_LABELS = {ADDED: ("aggiunto", "aggiunti"), REMOVED: ("cancellato", "cancellati"),
                       MODIFIED: ("modificato", "modificati")}


def count_label(change, count):
    singular, plural = CHANGE_COUNT_LABELS[change]
    return f"{count} {singular if count == 1 else plural}"

RENAME_FIELDS = ("id", "name", "title")

_TOKEN = re.compile(r"\w+|[^\w\s]+|\s+")


@dataclass
class RowChange:
    index: int
    change: str
    before: dict | None
    after: dict | None
    columns: list = field(default_factory=list)


@dataclass
class FieldChange:
    name: str
    label: str
    type: str
    before: object
    after: object
    significant: bool = False
    added_items: list = field(default_factory=list)
    removed_items: list = field(default_factory=list)
    rows: list = field(default_factory=list)


@dataclass
class ElementChange:
    uuid: str
    kind: str
    change: str
    before: object
    after: object
    fields: list = field(default_factory=list)
    label_before: str = ""
    label_after: str = ""

    @property
    def element(self):
        return self.after or self.before

    @property
    def label(self):
        if self.change == MODIFIED and self.label_before != self.label_after:
            return f"{self.label_before} → {self.label_after}"
        return self.label_after or self.label_before

    @property
    def renamed(self):
        return any(f.name in RENAME_FIELDS for f in self.fields)

    @property
    def status_changed(self):
        return any(f.name == "status" for f in self.fields)

    @property
    def significant(self):
        return any(f.significant for f in self.fields)


@dataclass
class ModelDiff:
    before: object
    after: object
    changes: list

    def __bool__(self):
        return bool(self.changes)

    def label_of(self, uuid):
        return self.after.label_of(uuid) or self.before.label_of(uuid) or "(elemento inesistente)"

    def summary(self):
        return Counter(c.change for c in self.changes)

    def by_kind(self):
        groups = {}
        for c in self.changes:
            groups.setdefault(c.kind, []).append(c)
        return groups


def _norm(value):
    return None if is_empty(value) else value


def _list(value):
    return list(value) if value else []


def _diff_rows(before, after, columns):
    rows = []
    before, after = _list(before), _list(after)
    for i in range(max(len(before), len(after))):
        b = before[i] if i < len(before) else None
        a = after[i] if i < len(after) else None
        if b is None:
            rows.append(RowChange(i, ADDED, None, a))
        elif a is None:
            rows.append(RowChange(i, REMOVED, b, None))
        else:
            changed = [c.name for c in columns if _norm(b.get(c.name)) != _norm(a.get(c.name))]
            changed += sorted(k for k in set(a) | set(b)
                              if k not in {c.name for c in columns} and _norm(a.get(k)) != _norm(b.get(k)))
            if changed:
                rows.append(RowChange(i, MODIFIED, b, a, changed))
    return rows


def _diff_field(f, before, after):
    change = FieldChange(f.name, f.label, f.type, before, after, f.significant)
    if f.type in (REFS, MULTIENUM, STRLIST):
        b, a = _list(before), _list(after)
        change.added_items = [x for x in a if x not in b]
        change.removed_items = [x for x in b if x not in a]
    elif f.type == MAP:
        b, a = before or {}, after or {}
        change.added_items = [k for k in a if k not in b or a[k] != b[k]]
        change.removed_items = [k for k in b if k not in a]
    elif f.type == TABLE:
        change.rows = _diff_rows(before, after, f.columns)
    return change


def _diff_element(before, after):
    schema = KINDS_BY_NAME[after.kind]
    changes = []
    known = set()
    for f in schema.fields:
        known.add(f.name)
        b, a = _norm(before.values.get(f.name)), _norm(after.values.get(f.name))
        if b != a:
            changes.append(_diff_field(f, b, a))
    for name in sorted((set(before.values) | set(after.values)) - known):
        b, a = _norm(before.values.get(name)), _norm(after.values.get(name))
        if b != a:
            changes.append(FieldChange(name, name, "str", b, a))
    return changes


def diff_models(before, after):
    changes = []
    for uuid in before.elements.keys() | after.elements.keys():
        b, a = before.get(uuid), after.get(uuid)
        if b is None:
            changes.append(ElementChange(uuid, a.kind, ADDED, None, a))
        elif a is None:
            changes.append(ElementChange(uuid, b.kind, REMOVED, b, None))
        else:
            fields = _diff_element(b, a)
            if fields:
                changes.append(ElementChange(uuid, a.kind, MODIFIED, b, a, fields))
    for c in changes:
        c.label_before = before.label(c.before) if c.before else ""
        c.label_after = after.label(c.after) if c.after else ""
    order = {k: i for i, k in enumerate(KINDS_BY_NAME)}
    changes.sort(key=lambda c: (order.get(c.kind, 99), c.label))
    return ModelDiff(before, after, changes)


def format_value(diff, field_type, value):
    """Human-readable rendering of a field value, resolving references to labels."""
    if is_empty(value):
        return "—"
    if field_type == REF:
        return diff.label_of(value)
    if field_type == REFS:
        return ", ".join(diff.label_of(v) for v in value)
    if field_type in (MULTIENUM, STRLIST):
        return ", ".join(value)
    if field_type == MAP:
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if field_type == BOOL:
        return "Sì" if value else "No"
    if field_type == TABLE:
        return f"{len(value)} righe"
    return str(value)


def word_diff(before, after):
    """Word-level diff for long texts: list of (op, text) with op in {'=', '+', '-'}."""
    a = _TOKEN.findall(before or "")
    b = _TOKEN.findall(after or "")
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(("=", "".join(a[i1:i2])))
        else:
            if i2 > i1:
                ops.append(("-", "".join(a[i1:i2])))
            if j2 > j1:
                ops.append(("+", "".join(b[j1:j2])))
    return ops


def is_text(field_change):
    return field_change.type == TEXT
