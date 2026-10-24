import re
import uuid as uuidlib
from dataclasses import dataclass, field

from arcadia_tool.model.schema import KINDS_BY_NAME, REF, REFS, TABLE

LABEL_TEXT_LENGTH = 70
# Referred to by their ID only; their short name is shown where they are chosen (see Element.choice_label).
REFERRED_BY_ID = ("derived_requirement",)


def is_empty(value):
    return value is None or value == "" or value == [] or value == {} or value is False


def natural_key(text):
    """Sort key that orders 3.2 before 3.10 and SF-DF06-2 before SF-DF06-10."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", text)]


@dataclass
class Element:
    kind: str
    uuid: str = field(default_factory=lambda: str(uuidlib.uuid4()))
    values: dict = field(default_factory=dict)

    def get(self, name, default=None):
        value = self.values.get(name)
        return default if is_empty(value) else value

    def set(self, name, value):
        if is_empty(value):
            self.values.pop(name, None)
        else:
            self.values[name] = value

    @property
    def schema(self):
        return KINDS_BY_NAME[self.kind]

    @property
    def label(self):
        """How the element is referred to elsewhere (lists of references, table cells, diff…)."""
        ident = self.get("id", "")
        if ident and self.kind in REFERRED_BY_ID:
            return ident
        name = self.get("name") or self.get("title") or ""
        if not name and self.kind == "requirement" and self.get("text"):
            text = " ".join(self.get("text").split())
            name = text if len(text) <= LABEL_TEXT_LENGTH else text[:LABEL_TEXT_LENGTH].rstrip() + "…"
        if self.kind == "team" and self.values.get("design_authority"):
            name = f"{name} (Design Authority)".strip()  # recognised wherever a team is chosen or shown
        if ident and name:
            return f"{ident} {name}"
        return ident or name or f"({self.schema.label} senza nome)"

    @property
    def choice_label(self):
        """How the element is shown where it is chosen (drop-down lists, pickers, the model tree): also its
        short name when it is referred to by ID only («3.4.1.3-D1 – Conta le boe»)."""
        if self.kind in REFERRED_BY_ID and self.get("id") and self.get("name"):
            return f"{self.get('id')} – {self.get('name')}"
        return self.label

    def copy(self):
        return Element(self.kind, self.uuid, _deep_copy(self.values))


def _deep_copy(value):
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


class Model:
    """All elements of a project at one point in time, indexed by uuid."""

    def __init__(self, elements=()):
        self.elements = {e.uuid: e for e in elements}

    def __len__(self):
        return len(self.elements)

    def __iter__(self):
        return iter(self.elements.values())

    def get(self, uuid):
        return self.elements.get(uuid)

    def add(self, element):
        self.elements[element.uuid] = element

    def remove(self, uuid):
        self.elements.pop(uuid, None)

    def of_kind(self, *kinds):
        return sorted((e for e in self.elements.values() if e.kind in kinds), key=lambda e: natural_key(self.label(e)))

    def choice_label(self, element):
        """Label in drop-down lists and pickers (see Element.choice_label)."""
        return element.choice_label if element.kind in REFERRED_BY_ID else self.label(element)

    def label(self, element):
        """Element label; elements without id/name (e.g. SA-3 records) are named after what they refer to."""
        if element.get("id") or element.get("name") or element.get("title"):
            return element.label
        for f in element.schema.fields:
            if f.type == REF and element.get(f.name) in self.elements:
                return f"{element.schema.label} · {self.elements[element.get(f.name)].label}"
        return element.label

    def referencing(self, uuids):
        """Elements (outside `uuids`) that refer to any of `uuids` in a reference field or table column."""
        uuids = set(uuids)
        found = []
        for element in self.elements.values():
            if element.uuid in uuids:
                continue
            for f in element.schema.fields:
                value = element.values.get(f.name)
                if not value:
                    continue
                if f.type == REF:
                    hit = value in uuids
                elif f.type == REFS:
                    hit = any(v in uuids for v in value)
                elif f.type == TABLE:
                    ref_columns = [c.name for c in f.columns if c.type == REF]
                    hit = any(row.get(c) in uuids for row in value for c in ref_columns)
                else:
                    continue
                if hit:
                    found.append(element)
                    break
        return found

    def descendants(self, uuids, field="parent"):
        """`uuids` plus every element of the same kind whose `field` chain leads to one of them.

        Only the same kind: e.g. the derived requirements (SA-4) of an SRS item are not its sub-items.
        """
        kinds = {self.elements[u].kind for u in uuids if u in self.elements}
        children = {}
        for element in self.elements.values():
            parent = element.values.get(field)
            if parent and element.kind in kinds:
                children.setdefault(parent, []).append(element.uuid)
        result, stack = set(), list(uuids)
        while stack:
            uuid = stack.pop()
            if uuid not in result:
                result.add(uuid)
                stack.extend(children.get(uuid, []))
        return result

    def label_of(self, uuid):
        element = self.elements.get(uuid)
        return self.label(element) if element else None
