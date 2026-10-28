"""Semantic three-way merge of two states of a project (e.g. the versions received from the remote and those of
this PC), from the state they both come from.

The project is a set of files ({relative path: bytes}): one YAML file per element of the model, the settings
shared with the team (project.yaml, checks.yaml) and the images of the SRS items. A file changed on one side only
takes that side. A file changed on both sides is merged:

- an element field by field: a field changed on one side only takes that side; the references to other sheets
  (lists of uuids) take what each side added and removed;
- a settings file key by key, the same way (lists as sets, e.g. the exceptions of the checks);
- any other file only as a whole.

What both sides changed in different ways is a Conflict: it is resolved by a choice, «ours» (this PC) or
«theirs» (received), given in `choices` by the key of the conflict.

The automatic identifiers given on this PC to new elements that the other side has given to its own (e.g. two
SF-DF06-03 created on two branches) are renumbered automatically, with those depending on them (see
renumber_ids)."""
import json
from dataclasses import dataclass, field

import yaml

from arcadia_tool.model.element import Element, Model, is_empty
from arcadia_tool.model.identifiers import compute_id, is_automatic, matches_context
from arcadia_tool.model.schema import KINDS, KINDS_BY_NAME, REFS
from arcadia_tool.model.serialization import dumps, loads
from arcadia_tool.storage.repository import CHECKS_FILE, MODEL_DIR, PROJECT_FILE

OURS, THEIRS = "ours", "theirs"
SETTINGS_FILES = (PROJECT_FILE, CHECKS_FILE)
KIND_ORDER = {k.name: i for i, k in enumerate(KINDS)}  # parents before children: domains, functions, …


@dataclass
class Conflict:
    path: str
    field: str = None  # the field of the element (or key of a settings file, «a/b»); None: the whole file
    base: object = None
    ours: object = None  # value (or content of the file, None if deleted) on this PC
    theirs: object = None  # value received

    @property
    def key(self):
        return f"{self.path}#{self.field or ''}"

    @property
    def uuid(self):
        """The element of a conflict in the model, else None."""
        if self.path.startswith(MODEL_DIR + "/") and self.path.endswith(".yaml"):
            return self.path.rsplit("/", 1)[-1][:-5]
        return None


@dataclass
class MergeResult:
    files: dict
    conflicts: list = field(default_factory=list)  # still to resolve (no choice given)
    renumbered: list = field(default_factory=list)  # (uuid, old id, new id)
    received: list = field(default_factory=list)  # paths that take content from the other side
    merged: list = field(default_factory=list)  # paths merged field by field

    @property
    def resolved(self):
        return not self.conflicts


def _norm(value):
    return None if is_empty(value) else value


def _key(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _merge_set(base, ours, theirs):
    """Three-way merge of two lists as sets: what each side added and removed; the order of ours, then theirs."""
    base_keys = {_key(v) for v in base or []}
    ours_keys = {_key(v) for v in ours or []}
    theirs_keys = {_key(v) for v in theirs or []}
    removed = (base_keys - ours_keys) | (base_keys - theirs_keys)
    result, seen = [], set()
    for v in [*(ours or []), *(theirs or [])]:
        k = _key(v)
        if k not in removed and k not in seen:
            seen.add(k)
            result.append(v)
    return result


class _Merger:
    def __init__(self, choices):
        self.choices = choices or {}
        self.conflicts = []

    def pick(self, conflict):
        choice = self.choices.get(conflict.key)
        if choice == OURS:
            return conflict.ours
        if choice == THEIRS:
            return conflict.theirs
        self.conflicts.append(conflict)
        return conflict.ours  # unresolved: ours until a choice is given

    def value(self, path, name, base, ours, theirs, as_set=False):
        b, o, t = _norm(base), _norm(ours), _norm(theirs)
        if _key(o) == _key(t):
            return o
        if _key(o) == _key(b):
            return t
        if _key(t) == _key(b):
            return o
        if as_set and all(v is None or isinstance(v, list) for v in (b, o, t)):
            return _merge_set(b, o, t)
        if isinstance(o, dict) and isinstance(t, dict) and (b is None or isinstance(b, dict)):
            return self.mapping(path, o, t, b or {}, prefix=f"{name}/")
        return self.pick(Conflict(path, name, b, o, t))

    def mapping(self, path, ours, theirs, base, prefix=""):
        result = {}
        for k in dict.fromkeys([*ours, *theirs, *base]):
            v = self.value(path, f"{prefix}{k}", base.get(k), ours.get(k), theirs.get(k), as_set=True)
            if v is not None:
                result[k] = v
        return result

    def element(self, path, base, ours, theirs):
        schema = KINDS_BY_NAME[ours.kind]
        b = base.values if base is not None else {}
        names = [f.name for f in schema.fields]
        names += sorted((set(b) | set(ours.values) | set(theirs.values)) - set(names))
        values = {}
        for name in names:
            f = schema.field(name)
            v = self.value(path, name, b.get(name), ours.values.get(name), theirs.values.get(name),
                           as_set=f is not None and f.type == REFS)
            if v is not None:
                values[name] = v
        return Element(ours.kind, ours.uuid, values)


def _text(data):
    return data.decode("utf-8") if data is not None else None


def merge_files(base, ours, theirs, choices=None):
    """base, ours, theirs: {relative path: bytes}. Returns a MergeResult; its `files` are the merged project
    (with the conflicts not yet resolved as on this PC)."""
    merger = _Merger(choices)
    result = MergeResult({})
    for path in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(path), ours.get(path), theirs.get(path)
        if o == t:
            data = o
        elif o == b:
            data = t
            result.received.append(path)
        elif t == b:
            data = o
        elif o is not None and t is not None and path.endswith(".yaml") and (
                path.startswith(MODEL_DIR + "/") or path in SETTINGS_FILES):
            data = _merge_yaml(merger, path, b, o, t)
            result.merged.append(path)
        else:  # deleted on one side and changed on the other, or a file that is not merged by parts
            data = merger.pick(Conflict(path, None, b, o, t))
            if merger.choices.get(f"{path}#") == THEIRS:
                result.received.append(path)
        if data is not None:
            result.files[path] = data
    result.conflicts = merger.conflicts
    return result


def _merge_yaml(merger, path, base, ours, theirs):
    if path in SETTINGS_FILES:
        load = lambda data: (yaml.safe_load(_text(data)) or {}) if data is not None else {}
        value = merger.mapping(path, load(ours), load(theirs), load(base))
        return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).encode("utf-8")
    merged = merger.element(path, loads(_text(base)) if base is not None else None, loads(_text(ours)),
                            loads(_text(theirs)))
    return dumps(merged).encode("utf-8")


def _is_model_file(path):
    return path.startswith(MODEL_DIR + "/") and path.endswith(".yaml")


def renumber_ids(result, base, theirs):
    """Automatic identifiers used twice after the merge: the element received keeps its identifier, the one of
    this PC gets the next free one; then the elements of this PC whose identifier depends on a renumbered one
    (e.g. the logical functions of a renumbered system function) follow it. Changes result.files and
    result.renumbered."""
    ours_only = {p for p in result.files if _is_model_file(p) and p not in theirs and p not in base}
    changed_here = {p for p in result.files if _is_model_file(p) and result.files[p] != theirs.get(p)}
    if not changed_here:
        return
    elements = {p: loads(_text(d)) for p, d in result.files.items() if _is_model_file(p)}
    if not any(is_automatic(elements[p].kind) for p in changed_here):
        return
    model = Model(list(elements.values()))
    by_id = {}
    for p, e in elements.items():
        if is_automatic(e.kind) and e.get("id"):
            by_id.setdefault((e.kind, e.get("id")), []).append(p)
    renumber = set()
    for (kind, ident), paths in by_id.items():
        if len(paths) < 2:
            continue
        fixed = [p for p in paths if p in theirs and elements[p].get("id") == _id_of(theirs[p])]
        keep = fixed[0] if fixed else sorted(paths, key=lambda p: p not in ours_only)[0]
        renumber |= {p for p in paths if p != keep and p in changed_here}
    for _ in range(5):  # a renumbered parent changes the identifiers of its children: a few rounds
        if not renumber:
            break
        for p in sorted(renumber, key=lambda p: KIND_ORDER.get(elements[p].kind, 99)):
            e = elements[p]
            old = e.get("id")
            e.set("id", None)
            new = compute_id(e, model)
            e.set("id", new or old)
            if new and new != old:
                result.renumbered.append((e.uuid, old, new))
                result.files[p] = dumps(e).encode("utf-8")
        renumber = {p for p in ours_only if is_automatic(elements[p].kind) and elements[p].get("id")
                    and not matches_context(elements[p], model)}


def _id_of(data):
    return loads(_text(data)).get("id")
