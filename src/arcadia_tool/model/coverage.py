"""Coverage of the SRS items of a chapter 9 category (Bordo, Definizione): an item is covered first of all at the
level of the domains (matrix A4: its own domains, else those of the nearest section or clause containing it), then
at the level of the system functions (SA-2, which trace it or a part containing it) and of the derived requirements
(SA-4, derived from it or from a part containing it)."""
from dataclasses import dataclass, field

COUNTED_TYPES = ("Requisito",)  # the clauses: list items and table rows go with them, sections and titles group
REPORT_CATEGORIES = ("Bordo", "Definizione")
DOMAIN, FUNCTION, DERIVED = "domain", "function", "derived"
LEVELS = ((DOMAIN, "Dominio funzionale"), (FUNCTION, "Funzione di sistema"), (DERIVED, "Requisito derivato"))


@dataclass
class CoverageRow:
    item: object
    domains: list = field(default_factory=list)  # (domain, principal: bool), the principal first
    domains_from: object = None  # the section or clause they come from, when not the item itself
    functions: list = field(default_factory=list)
    derived: list = field(default_factory=list)
    section: object = None  # the section containing it (item type «Sezione»), if any
    parent: object = None  # the row of the clause of the report containing it, if any

    @property
    def covered(self):
        """Covered at the level of the domains: the coverage of the report."""
        return bool(self.domains)

    def at(self, level):
        return bool({DOMAIN: self.domains, FUNCTION: self.functions, DERIVED: self.derived}[level])


@dataclass
class Coverage:
    category: str
    rows: list

    @property
    def total(self):
        return len(self.rows)

    def count(self, level=DOMAIN):
        return sum(1 for r in self.rows if r.at(level))

    def percent(self, level=DOMAIN):
        return 100.0 * self.count(level) / self.total if self.total else 0.0

    @property
    def uncovered(self):
        return [r for r in self.rows if not r.covered]

    def sections(self):
        """The coverage of each section, in the order of the specification (the clauses outside any section
        last, together)."""
        groups = {}
        for r in self.rows:
            groups.setdefault(r.section.uuid if r.section is not None else None, []).append(r)
        result = [SectionCoverage(rows[0].section, self.category, rows) for key, rows in groups.items()
                  if key is not None]
        if None in groups:
            result.append(SectionCoverage(None, self.category, groups[None]))
        return result


class SectionCoverage(Coverage):
    """The clauses of a category in a section (None: those outside any section)."""

    def __init__(self, section, category, rows):
        super().__init__(category, rows)
        self.section = section


def _chain(model, item):
    """The item, then the parts containing it (its parent, the parent of its parent…)."""
    chain, seen = [item], {item.uuid}
    parent = model.get(item.get("parent")) if item.get("parent") else None
    while parent is not None and parent.uuid not in seen:
        chain.append(parent)
        seen.add(parent.uuid)
        parent = model.get(parent.get("parent")) if parent.get("parent") else None
    return chain


def coverage(model, ordered, category):
    """The coverage of the clauses of a category; ordered: the SRS items in the order of the specification."""
    functions_of, derived_of = {}, {}
    for sf in model.of_kind("system_function"):
        for uuid in sf.get("sections") or []:
            functions_of.setdefault(uuid, []).append(sf)
    for d in model.of_kind("derived_requirement"):
        if d.get("parent"):
            derived_of.setdefault(d.get("parent"), []).append(d)
    rows, by_item = [], {}
    for item in ordered:
        if item.get("item_type") not in COUNTED_TYPES or category not in (item.get("category") or []):
            continue
        chain = _chain(model, item)
        row = CoverageRow(item, section=next((e for e in chain if e.get("item_type") == "Sezione"), None))
        row.parent = next((by_item[e.uuid] for e in chain[1:] if e.uuid in by_item), None)
        for part in chain:
            own = [(model.get(part.get("primary_domain")), True)] if part.get("primary_domain") else []
            own += [(model.get(u), False) for u in part.get("contributing_domains") or []]
            own = [(d, p) for d, p in own if d is not None]
            if own:
                row.domains, row.domains_from = own, (part if part is not item else None)
                break
        for part in chain:
            row.functions += [f for f in functions_of.get(part.uuid, []) if f not in row.functions]
            row.derived += [d for d in derived_of.get(part.uuid, []) if d not in row.derived]
        rows.append(row)
        by_item[item.uuid] = row
    return Coverage(category, rows)


def subset_coverage(reports):
    """The coverage of the subset at the level of the domains: (covered, total, percent) of all the reports."""
    covered = sum(r.count(DOMAIN) for r in reports)
    total = sum(r.total for r in reports)
    return covered, total, (100.0 * covered / total if total else 0.0)
