"""Merge of imported SRS items into a project: preview first, then apply.

Items are matched by their identifier (clause number). Nothing is deleted automatically: items that are
no longer in the imported chapters are only reported.
"""
import bisect
import hashlib
import re
from dataclasses import dataclass, field, replace

from arcadia_tool.importers.srs_pdf import APPENDIX, SrsItem, _item_type, chapter_of_item
from arcadia_tool.model.element import natural_key

FIELDS = ("title", "text", "item_type", "page", "baseline", "category", "import_note", "srs_refs", "figure",
          "sequence")
FIGURES_DIR = "assets/figures"


def figure_path(ident, png):
    """Project-relative path of a figure image; the content hash in the name makes a changed image visible."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ident).strip("_")
    return f"{FIGURES_DIR}/{safe}-{hashlib.sha1(png).hexdigest()[:10]}.png"
# Fields written by earlier versions of the import and no longer used: a re-import removes them.
OBSOLETE_FIELDS = ("mode_availability",)
PLACEHOLDER_NOTE = "Voce presente solo nel capitolo 9 (tabella, figura o riga di procedura): contenuto da completare."
NOT_IN_CH9_NOTE = ("Voce non presente nel capitolo 9: classificazione da verificare (se necessario con una "
                   "richiesta di chiarimento X-2).")


@dataclass
class PlannedItem:
    id: str
    values: dict
    parent_id: str | None
    replaces_id: str | None
    image: bytes | None = None  # PNG of a figure or table, saved at values["figure"]


@dataclass
class ImportPlan:
    new: list = field(default_factory=list)
    updates: list = field(default_factory=list)      # (element, PlannedItem, changed field names)
    unchanged: int = 0
    missing: list = field(default_factory=list)      # existing elements no longer in the imported chapters
    chapters: list = field(default_factory=list)
    # List items and bullets found in the text but not in chapter 9: their text stays in the clause.
    discarded: list = field(default_factory=list)
    # List items and bullets renamed after chapter 9 ({name in the text: chapter 9 id}).
    renamed: dict = field(default_factory=dict)

    @property
    def warnings(self):
        items = [p for p in self.new] + [p for _, p, _ in self.updates]
        return [p for p in items if p.values.get("import_note")]

    def __bool__(self):
        return bool(self.new or self.updates)


def chapter_of_id(ident):
    return chapter_of_item(ident)  # also «A.3.4.1» (appendix to chapter 3) → 3


def document_key(ident):
    """Specification order: chapter, then its appendix (A.3.x right after chapter 3), then clause number."""
    ident = ident or ""
    appendix = ident.startswith(APPENDIX)
    return chapter_of_id(ident) or 0, appendix, natural_key(ident.removeprefix(APPENDIX) if appendix else ident)


def preview_key(ident, sequence):
    """Document position when known (procedure rows are not in alphabetical order), else the clause number."""
    chapter, appendix, key = document_key(ident)
    return chapter, sequence is None, sequence or 0, appendix, key


FIGURE_LABEL = re.compile(r"(Figure|Table)\s*(\d+[a-z]?)$")
ROW_ID = re.compile(r"-R\d+$")  # rows of the active functions table, a project convention


def _synthetic(item):
    """Items created by the import for structure only (the «A.3» root of the appendix)."""
    return item.item_type == "Capitolo" and re.fullmatch(r"A\.\d+", item.id or "") is not None


def _figure_label(ident):
    m = FIGURE_LABEL.search(ident)
    return (chapter_of_id(ident), m.group(1), m.group(2)) if m else None


def _align_figures(incoming, classification):
    """Use the chapter 9 id of a figure when the text attaches it to another clause.

    Chapter 9 sometimes refers a figure to the next clause or to a list item («3.5.3.8 Figure 3» while the
    caption follows 3.5.3.7): if the label (chapter + «Figure 3») is unique in chapter 9, its id wins.
    """
    by_label = {}
    for key in classification:
        label = _figure_label(key)
        if label:
            by_label.setdefault(label, []).append(key)
    for ident in list(incoming):
        label = _figure_label(ident)
        if not label or ident in classification:
            continue
        keys = by_label.get(label, [])
        if len(keys) != 1:
            # Chapter 9 may name a captioned figure just «<clause> Table» (the 4.6.2 transitions table).
            base = ident.split(" ", 1)[0]
            keys = [k for k in (f"{base} Table", f"{base} Figure") if k in classification]
        if len(keys) == 1 and keys[0] not in incoming:
            item = incoming.pop(ident)
            item.id, item.parent = keys[0], None
            incoming[item.id] = item


# List items and bullets, as named by the parser («3.6.5.1.4 a)», «3.10.2.2 1st bullet») and by chapter 9
# (which may nest them: «3.5.3.7 d) 1st bullet», «3.6.1.3 3rd bullet 1st hyphen»).
SUB_ITEM_SUFFIX = re.compile(r"^(?:[a-z]{1,2}\)|\d+(?:st|nd|rd|th) bul)")


def _sub_items_by_clause(idents):
    by_clause = {}
    for ident in idents:
        clause, _, suffix = ident.partition(" ")
        # «3.6.2.3.1.1 1st bullet Figure 9» is a figure, not a bullet
        if suffix and SUB_ITEM_SUFFIX.match(suffix) and not re.search(r"Figure|Table|footnote", suffix):
            by_clause.setdefault(clause, []).append(ident)
    return by_clause


def _reconcile_sub_items(incoming, classification):
    """Chapter 9 is the official list of items: list items and bullets follow it.

    For each clause that chapter 9 classifies, the list items and bullets found in the text are compared, in
    order, with those listed in chapter 9:
    - same number: they take the chapter 9 names (the PDF may show bullets where chapter 9 counts letters, or
      nest bullets under a letter: «3.5.3.7 1st bullet» → «3.5.3.7 d) 1st bullet»);
    - different number: those with a name unknown to chapter 9 are not items (a wrapped «b)).», a legend line).
    In both cases the text stays in the clause. Returns (renamed {old: new}, discarded ids).
    """
    listed = _sub_items_by_clause(classification)
    found = _sub_items_by_clause(incoming)
    renamed, discarded = {}, []
    for clause, parsed in found.items():
        if clause not in classification:
            continue
        official = listed.get(clause, [])
        if parsed == official:
            continue
        if len(parsed) == len(official):
            items = [incoming.pop(i) for i in parsed]
            for item, new_id in zip(items, official):
                if item.id != new_id:
                    renamed[item.id] = new_id
                item.id, item.parent = new_id, None
                incoming[new_id] = item
            continue
        for ident in parsed:
            if ident not in classification:
                del incoming[ident]
                discarded.append(ident)
    return renamed, discarded


def _placeholder(ident, parsed, positions):
    base = ident.split(" ", 1)[0]
    if " " in ident:
        item_type, sequence = "Voce", _approximate_sequence(base, parsed)
    else:
        item_type, sequence = _item_type(base, bold=False), positions.before(ident)
    return SrsItem(ident, item_type, warnings=[PLACEHOLDER_NOTE], sequence=sequence)


class _Positions:
    """Document positions of the parsed items, looked up by clause number."""

    def __init__(self, parsed):
        pairs = sorted((document_key(i.id), i.sequence) for i in parsed if i.sequence)
        self.keys = [k for k, _ in pairs]
        self.latest, latest = [], 0
        for _, sequence in pairs:
            latest = max(latest, sequence)
            self.latest.append(latest)

    def before(self, ident):
        """Position of a clause missing from the text (e.g. «5.2»): after the items with a lower number."""
        n = bisect.bisect_left(self.keys, document_key(ident))
        return self.latest[n - 1] if n else 0


def _from_row(ident, incoming):
    """A list item of a procedure row («5.11.2.2 S140 a)»): its lines move from the row text to an item."""
    row_id, _, letter = ident.rpartition(" ")
    row = incoming.get(row_id)
    if row is None or not re.fullmatch(r"[a-z]\)", letter):
        return None
    lines = (row.text or "").splitlines()
    own = [line for line in lines if line.startswith(letter + " ")]
    if len(own) != 1:
        return None
    row.text = "\n".join(line for line in lines if line is not own[0])
    return SrsItem(ident, "Voce", text=own[0].removeprefix(letter).strip(), page=row.page, parent=row_id,
                   sequence=row.sequence)


def _approximate_sequence(base, parsed):
    """Position of an item missing from the text: after the parsed items of its clause (or of its parents)."""
    while base:
        found = [i.sequence for i in parsed
                 if i.sequence and (i.id == base or i.id.startswith((base + " ", base + ".")))]
        if found:
            return max(found)
        base = base.rsplit(".", 1)[0] if "." in base else None
    return 0


def _clause_texts(incoming, discarded):
    """Clause texts without their list items, except those that are not items (discarded by chapter 9)."""
    kept = set(discarded)
    return {ident: item.without_sub_items(kept) for ident, item in incoming.items() if item.own_text is not None}


def plan_import(model, chapters, classification=None, baseline=""):
    """chapters: {chapter number: [SrsItem]}; classification: {item id: Classification} from chapter 9."""
    existing = {e.get("id"): e for e in model.of_kind("requirement") if e.get("id")}
    incoming = {}
    for items in chapters.values():
        for item in items:
            first = incoming.get(item.id)
            if first is None:
                incoming[item.id] = replace(item)  # a copy: the parsed items are not modified
            elif item.text:
                # The same list letter used twice in one clause (two lists): keep both texts on one item.
                first.text = f"{first.text}\n{item.text}".strip()
    discarded, renamed = [], {}
    if classification:
        _align_figures(incoming, classification)
        renamed, discarded = _reconcile_sub_items(incoming, classification)
        in_scope = set(chapters) | {chapter_of_id(i) for i in existing}
        parsed = list(incoming.values())
        positions = _Positions(parsed)
        for ident in classification:
            if chapter_of_id(ident) not in in_scope or ident in incoming:
                continue
            item = _from_row(ident, incoming)
            if item is not None:
                incoming[ident] = item
            elif ident not in existing:
                incoming[ident] = _placeholder(ident, parsed, positions)
    clause_texts = _clause_texts(incoming, discarded)

    planned = []
    for ident, item in incoming.items():
        notes = list(item.warnings)
        category, replaces = None, None
        if classification is not None:
            c = classification.get(ident)
            # Sub-items (list items, bullets, table rows) inherit the classification of what contains them.
            parent_c = _inherited(classification, item.parent_id) if item.item_type == "Voce" else None
            if c:
                category, replaces = c.categories, c.replaces
            elif parent_c:
                source, parent_c = parent_c
                category = parent_c.categories
                if not ROW_ID.search(ident):
                    # Table rows («4.5.2-R49») inherit the table classification by convention: nothing to check.
                    notes.append(f"Categoria ereditata da {source}.")
            elif not _synthetic(item):
                notes.append(NOT_IN_CH9_NOTE)
        extra = {k: v for k, v in item.extra.items() if k != "figure_png" and not k.startswith("_")}
        values = {"title": item.title, "text": clause_texts.get(ident, item.text), "item_type": item.item_type,
                  "page": item.page or None, "baseline": baseline, "category": category,
                  "import_note": " ".join(notes), "sequence": item.sequence or None, **extra}
        image = item.extra.get("figure_png")
        if image:
            values["figure"] = figure_path(ident, image)
        planned.append(PlannedItem(ident, values, item.parent_id, replaces, image))

    # Classification-only refresh for existing items of chapters that are not re-imported.
    if classification:
        for ident, element in existing.items():
            if ident not in incoming and ident in classification:
                c = classification[ident]
                planned.append(PlannedItem(ident, {"category": c.categories}, None, c.replaces))

    plan = ImportPlan(chapters=sorted(chapters), discarded=sorted(discarded, key=document_key), renamed=renamed)
    planned.sort(key=lambda p: preview_key(p.id, p.values.get("sequence")))  # specification order
    for p in planned:
        element = existing.get(p.id)
        if element is None:
            plan.new.append(p)
            continue
        if element.get("category_note"):
            p.values.pop("category", None)  # manual classification wins over the import
        changed = [f for f in FIELDS if f in p.values and p.values[f] is not None
                   and (p.values[f] or None) != (element.get(f) or None)]
        for f in OBSOLETE_FIELDS:
            if element.get(f):
                p.values[f] = None
                changed.append(f)
        if p.parent_id and _id_of(model, element.get("parent")) != _resolve_parent(p.parent_id, existing, incoming):
            changed.append("parent")
        if (p.replaces_id and (p.replaces_id in existing or p.replaces_id in incoming)
                and _id_of(model, element.get("replaces")) != p.replaces_id):
            changed.append("replaces")
        if changed:
            plan.updates.append((element, p, changed))
        else:
            plan.unchanged += 1
    if chapters:
        plan.missing = [e for ident, e in existing.items()
                        if chapter_of_id(ident) in chapters and ident not in incoming
                        and not (e.get("import_note") or "").startswith(PLACEHOLDER_NOTE[:20])]
        plan.missing.sort(key=lambda e: document_key(e.get("id")))
    return plan


def _id_of(model, uuid):
    element = model.get(uuid) if uuid else None
    return element.get("id") if element else None


def _ancestors(ident):
    """«4.5.2.1 Table» → 4.5.2.1 Table, 4.5.2.1, 4.5.2, 4.5, 4."""
    while ident:
        yield ident
        if " " in ident:
            ident = ident.split(" ", 1)[0]
        else:
            ident = ident.rsplit(".", 1)[0] if "." in ident else None


def _inherited(classification, parent_id):
    """Classification of the nearest classified container of a sub-item: (its id, Classification)."""
    for ident in _ancestors(parent_id):
        if ident in classification:
            return ident, classification[ident]
        if " " not in ident:
            return None  # stop at the clause: a section's category does not apply to its items
    return None


def _resolve_parent(parent_id, *known):
    """Nearest ancestor that exists (the specification sometimes skips a level, e.g. 3.4.2 → 3.4.2.1.1)."""
    for ident in _ancestors(parent_id):
        if any(ident in k for k in known):
            return ident
    return None


def apply_import(project, plan):
    """Create and update the requirement elements; returns (created, updated)."""
    by_id = {e.get("id"): e for e in project.model.of_kind("requirement") if e.get("id")}
    created = []
    for p in plan.new:
        element = project.new_element("requirement", id=p.id, **{k: v for k, v in p.values.items() if v})
        if p.image:
            project.set_asset(p.values["figure"], p.image)
        by_id[p.id] = element
        created.append((element, p))
    for element, p, changed in plan.updates:
        for name in changed:
            if name in p.values:
                element.set(name, p.values[name])
        if "figure" in changed and p.image:
            project.set_asset(p.values["figure"], p.image)
        project.update(element)
    for element, p in created + [(e, p) for e, p, _ in plan.updates]:
        parent = _resolve_parent(p.parent_id, by_id) if p.parent_id else None
        if parent and parent != p.id:
            element.set("parent", by_id[parent].uuid)
        if p.replaces_id and p.replaces_id in by_id:
            element.set("replaces", by_id[p.replaces_id].uuid)
        project.update(element)
    return len(plan.new), len(plan.updates)
