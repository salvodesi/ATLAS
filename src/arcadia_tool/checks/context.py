"""Indexes of the relations between the sheets, built once for a run of the checks."""
import re
from collections import defaultdict
from functools import cached_property

from arcadia_tool.model.element import Model, natural_key
from arcadia_tool.model.schema import B5_QUESTIONS, ETCS_MODES, enum_option, kind as kind_of

APPROVED = {"Approvato", "Approvata", "Decisa"}
AGREED = {"Concordato", "Approvato"}
NON_BOARD = {"Terra", "Definizione", "Informativa", "Altro"}
CLAUSE_TYPES = ("Titolo", "Requisito")  # traceable clauses (sections have three numbers, see srs_trace)
WAIT = "attesa"  # a row «Attesa: evento atteso» of a functional chain (SA-7)

_MODE = re.compile(r"\b(" + "|".join(ETCS_MODES) + r")\b")
_LEVEL = re.compile(r"\b(L[0-3]|NTC)\b|\b(livell[oi]|level)\s*[0-3]\b", re.IGNORECASE)
_PARAGRAPH = re.compile(r"\b\d+\.\d+(\.\d+)*\b")
_SENTENCE = re.compile(r"(?<=[.!?;])\s+")
INFINITIVE_ENDINGS = ("are", "ere", "ire", "rre")


def sentences(text):
    return [s for s in _SENTENCE.split((text or "").strip()) if s.strip(" .")]


def name_acronyms(name, modes=ETCS_MODES, levels=True, paragraphs=True):
    """Mode or level acronyms and paragraph numbers in a function name (rule D5)."""
    mode = _MODE if tuple(modes) == tuple(ETCS_MODES) else (
        re.compile(r"\b(" + "|".join(map(re.escape, modes)) + r")\b") if modes else None)
    found = [m.group(0) for m in mode.finditer(name or "")] if mode is not None else []
    if levels:
        found += [m.group(0) for m in _LEVEL.finditer(name or "")]
    if paragraphs:
        found += [m.group(0) for m in _PARAGRAPH.finditer(name or "")]
    return found


def starts_with_verb(name, endings=INFINITIVE_ENDINGS, allowed=()):
    words = re.findall(r"[^\W\d_]+", name or "")
    if not words:
        return False
    first = words[0].lower()
    return first in {a.lower() for a in allowed} or first.endswith(tuple(e.lower() for e in endings if e))


def without_variants(name):
    """Name without mode, level and version: two functions with the same result are duplicated by mode (D6)."""
    text = _LEVEL.sub(" ", _MODE.sub(" ", name or ""))
    text = re.sub(r"\b(versione|version|v)\s*[0-9]\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(in|nel|nei|per|di|del|con|e)\s*$", " ", " ".join(text.split()))
    return " ".join(text.lower().split())


def question_number(record):
    value = record.get("b5_question")
    if not value:
        return None
    option = enum_option(kind_of("trace_record").field("b5_question"), value)
    head = option.split(" ", 1)[0]
    return int(head) if head.isdigit() and 1 <= int(head) <= len(B5_QUESTIONS) else None


class Context:
    def __init__(self, model, profile=None, published=None):
        from arcadia_tool.checks.config import Profile

        self.model = model
        self.profile = profile if profile is not None else Profile()
        self.code = None  # the check running: param() reads its parameters
        self._published = published
        self.kinds = defaultdict(list)
        for e in model:
            self.kinds[e.kind].append(e)
        for elements in self.kinds.values():
            elements.sort(key=lambda e: natural_key(model.label(e)))

    # --- generic -------------------------------------------------------------------------------------

    def of(self, *kinds):
        return [e for k in kinds for e in self.kinds.get(k, [])]

    def get(self, uuid):
        return self.model.get(uuid) if uuid else None

    def label(self, element_or_uuid):
        e = self.get(element_or_uuid) if isinstance(element_or_uuid, str) else element_or_uuid
        return self.model.label(e) if e is not None else "(elemento eliminato)"

    def labels(self, elements):
        return ", ".join(self.label(e) for e in elements)

    def sort_key(self, uuid):
        e = self.get(uuid)
        return natural_key(self.model.label(e)) if e is not None else []

    def param(self, name, code=None):
        """A parameter of the running check (or of `code`): the value of the profile, else of the methodology."""
        return self.profile.param(code or self.code, name)

    @staticmethod
    def approved(element):
        return element.get("status") in APPROVED

    def domains_of_element(self, element):
        """Domains a sheet belongs to, for the scope of a check: empty if it belongs to none in particular (then
        the scope by domain does not exclude it)."""
        k = element.kind
        if k == "domain":
            return {element.uuid}
        if k in ("system_function", "logical_function"):
            d = self.domain_of(element)
            return {d.uuid} if d is not None else set()
        if k == "requirement":
            return self.domains_of_item(element)
        if k == "derived_requirement":
            if element.get("domain"):
                return {element.get("domain")}
            d = self.domain_of(self.get(element.get("function")))
            return {d.uuid} if d is not None else set()
        if k == "trace_record":
            item = self.get(element.get("requirement"))
            return self.domains_of_item(item) if item is not None else set()
        if k == "functional_exchange":
            ends = (self.domain_of(self.get(element.get(f))) for f in ("source", "target"))
            return {d.uuid for d in ends if d is not None}
        if k == "exchange_item":
            return set().union(*(self.domains_of_element(fe) for fe in self.exchanges_of_item.get(element.uuid, [])))
        if k == "functional_chain":
            return {element.get("responsible_domain")} if element.get("responsible_domain") else set()
        if k == "chain_realization":
            chain = self.get(element.get("chain"))
            return self.domains_of_element(chain) if chain is not None else set()
        if k == "logical_component":
            return {d.uuid for lf in self.lfs_of_component.get(element.uuid, [])
                    for d in [self.domain_of(lf)] if d is not None}
        if k == "component_exchange":
            return set().union(*(self.domains_of_element(c) for c in
                                 (self.get(element.get("source")), self.get(element.get("target"))) if c is not None))
        if k == "team":
            return set(element.get("domains") or [])
        return set()

    @cached_property
    def published(self):
        value = self._published() if callable(self._published) else self._published
        return value if value is not None else Model()

    # --- SRS items -----------------------------------------------------------------------------------

    @cached_property
    def requirement_by_id(self):
        result = {}
        for r in self.of("requirement"):
            result.setdefault(r.get("id"), r)
        return result

    @cached_property
    def requirement_children(self):
        result = defaultdict(list)
        for r in self.of("requirement"):
            if r.get("parent"):
                result[r.get("parent")].append(r)
        return result

    @cached_property
    def _ancestors(self):
        return {}

    def ancestors(self, item):
        """uuids of the parents of an SRS item, nearest first."""
        cache = self._ancestors
        if item.uuid not in cache:
            chain, seen, parent = [], {item.uuid}, item.get("parent")
            while parent and parent not in seen and self.get(parent) is not None:
                chain.append(parent)
                seen.add(parent)
                parent = self.get(parent).get("parent")
            cache[item.uuid] = chain
        return cache[item.uuid]

    def section_of(self, item):
        for uuid in [item.uuid, *self.ancestors(item)]:
            e = self.get(uuid)
            if e is not None and e.get("item_type") == "Sezione":
                return e
        return None

    def descendants(self, item):
        result, stack = [], list(self.requirement_children.get(item.uuid, []))
        seen = set()
        while stack:
            e = stack.pop()
            if e.uuid in seen:
                continue
            seen.add(e.uuid)
            result.append(e)
            stack.extend(self.requirement_children.get(e.uuid, []))
        return result

    @staticmethod
    def categories(item):
        return set(item.get("category") or [])

    def is_board(self, item):
        return "Bordo" in self.categories(item)

    @staticmethod
    def own_domains(item):
        return {d for d in [item.get("primary_domain"), *(item.get("contributing_domains") or [])] if d}

    def domains_of_item(self, item):
        """Domains of an SRS item in the matrix A4: its own, else those of its nearest parent that has them."""
        for uuid in [item.uuid, *self.ancestors(item)]:
            e = self.get(uuid)
            if e is not None and self.own_domains(e):
                return self.own_domains(e)
        return set()

    def requirements_in_text(self, text):
        """SRS items cited in a free text (the «Voci SRS» column of a chain): their numbers, found in the model."""
        found = []
        for token in re.split(r"[\s,;]+", text or ""):
            token = token.strip("()[].")
            if token in self.requirement_by_id:
                found.append(self.requirement_by_id[token])
        return found

    # --- functions -----------------------------------------------------------------------------------

    @staticmethod
    def traced_field(function):
        return "sections" if function.kind == "system_function" else "detail_requirements"

    def traced(self, function):
        """SRS items (uuids) traced by a system or logical function."""
        return set(function.get(self.traced_field(function)) or [])

    def traces(self, function, item):
        """The function traces the item, directly or through one of its parents (a section)."""
        traced = self.traced(function)
        return item.uuid in traced or any(a in traced for a in self.ancestors(item))

    @cached_property
    def functions_tracing(self):
        """SRS item uuid → functions that trace it directly."""
        result = defaultdict(list)
        for f in self.of("system_function", "logical_function"):
            for uuid in self.traced(f):
                result[uuid].append(f)
        return result

    @cached_property
    def lf_children(self):
        result = defaultdict(list)
        for lf in self.of("logical_function"):
            if lf.get("parent"):
                result[lf.get("parent")].append(lf)
        return result

    def is_leaf(self, lf):
        return not self.lf_children.get(lf.uuid)

    def sf_of(self, function):
        """System function of a function: itself, the one a logical function refines (or its parent refines)."""
        seen = set()
        while function is not None and function.uuid not in seen:
            if function.kind == "system_function":
                return function
            if function.kind != "logical_function":
                return None
            seen.add(function.uuid)
            refined = self.get(function.get("refines"))
            if refined is not None:
                return refined
            function = self.get(function.get("parent"))
        return None

    def domain_of(self, function):
        sf = self.sf_of(function)
        return self.get(sf.get("domain")) if sf is not None else None

    @cached_property
    def lfs_refining(self):
        """system function uuid → logical functions that refine it (or contribute to it)."""
        result = defaultdict(list)
        for lf in self.of("logical_function"):
            sf = self.sf_of(lf)
            if sf is not None:
                result[sf.uuid].append(lf)
            for other in lf.get("contributes_to") or []:
                if sf is None or other != sf.uuid:
                    result[other].append(lf)
        return result

    def components_of(self, function):
        """Components a function is allocated to: a logical function's own, those of the logical functions
        refining a system function; None for an external actor."""
        if function is None or function.kind == "external_actor":
            return None
        if function.kind == "logical_function":
            return {function.get("component")} if function.get("component") else set()
        return {lf.get("component") for lf in self.lfs_refining.get(function.uuid, []) if lf.get("component")}

    @cached_property
    def derived_by_parent(self):
        result = defaultdict(list)
        for d in self.of("derived_requirement"):
            if d.get("parent"):
                result[d.get("parent")].append(d)
        return result

    @cached_property
    def derived_by_function(self):
        result = defaultdict(list)
        for d in self.of("derived_requirement"):
            if d.get("function"):
                result[d.get("function")].append(d)
        return result

    def derived_of_sf(self, sf):
        return [d for lf in self.lfs_refining.get(sf.uuid, []) for d in self.derived_by_function.get(lf.uuid, [])]

    @cached_property
    def records_by_requirement(self):
        result = defaultdict(list)
        for r in self.of("trace_record"):
            if r.get("requirement"):
                result[r.get("requirement")].append(r)
        return result

    # --- exchanges -----------------------------------------------------------------------------------

    @cached_property
    def exchanges_from(self):
        result = defaultdict(list)
        for fe in self.of("functional_exchange"):
            result[fe.get("source")].append(fe)
        return result

    @cached_property
    def exchanges_to(self):
        result = defaultdict(list)
        for fe in self.of("functional_exchange"):
            result[fe.get("target")].append(fe)
        return result

    @cached_property
    def exchanges_of_item(self):
        result = defaultdict(list)
        for fe in self.of("functional_exchange"):
            if fe.get("exchange_item"):
                result[fe.get("exchange_item")].append(fe)
        return result

    def nature(self, fe):
        item = self.get(fe.get("exchange_item"))
        return fe.get("nature") or (item.get("nature") if item is not None else None)

    def between_domains(self, fe):
        """Domains of the two ends of an exchange between functions of different domains, else None."""
        a, b = self.get(fe.get("source")), self.get(fe.get("target"))
        if a is None or b is None or "external_actor" in (a.kind, b.kind):
            return None
        da, db = self.domain_of(a), self.domain_of(b)
        return (da, db) if da is not None and db is not None and da.uuid != db.uuid else None

    # --- components ----------------------------------------------------------------------------------

    @cached_property
    def lc_children(self):
        result = defaultdict(list)
        for lc in self.of("logical_component"):
            if lc.get("parent"):
                result[lc.get("parent")].append(lc)
        return result

    def lc_ancestors(self, uuid):
        """The component and its macro-components, nearest first."""
        chain, seen = [], set()
        while uuid and uuid not in seen and self.get(uuid) is not None:
            chain.append(uuid)
            seen.add(uuid)
            uuid = self.get(uuid).get("parent")
        return chain

    def within(self, component, container):
        return bool(component) and container in self.lc_ancestors(component)

    @cached_property
    def lfs_of_component(self):
        result = defaultdict(list)
        for lf in self.of("logical_function"):
            if lf.get("component"):
                result[lf.get("component")].append(lf)
        return result

    @cached_property
    def component_exchanges_realizing(self):
        result = defaultdict(list)
        for ce in self.of("component_exchange"):
            for fe in ce.get("realizes") or []:
                result[fe].append(ce)
        return result

    # --- teams, ADR ----------------------------------------------------------------------------------

    @cached_property
    def teams_of_domain(self):
        result = defaultdict(list)
        for t in self.of("team"):
            for d in t.get("domains") or []:
                result[d].append(t)
        return result

    @cached_property
    def teams_of_component(self):
        result = defaultdict(list)
        for t in self.of("team"):
            for c in t.get("components") or []:
                result[c].append(t)
        return result

    # --- functional chains ---------------------------------------------------------------------------

    @staticmethod
    def is_wait(row):
        return (row.get("what") or "").strip().lower().startswith(WAIT)

    def chain_steps(self, chain):
        """(number of the step, row) of the steps of a chain that are not waiting rows; the number is the
        position among them, starting from 1, as in the column «# passo SA» of LA-4."""
        steps, n = [], 0
        for row in chain.get("steps") or []:
            if not self.is_wait(row):
                n += 1
                steps.append((n, row))
        return steps

    @cached_property
    def realizations_of_chain(self):
        result = defaultdict(list)
        for r in self.of("chain_realization"):
            if r.get("chain"):
                result[r.get("chain")].append(r)
        return result
