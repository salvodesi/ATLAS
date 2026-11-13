"""The deletion of a functional domain: from the model tree, from a view, or approving the ADR of its deletion (X-1).
What has it as its domain would be left orphan: the SRS sections and clauses of which it is principal, the system
functions, the derived requirements, the functional chains it answers for, the ADRs not yet decided that name it; the
user says, for each, whether it passes to another domain, stays without one, or (a function, a derived requirement
nothing else uses) is deleted. The references of second order are simply removed: the domain as a contributor or
excluded, among the domains of its team. The decided ADRs keep naming it, as their history. Then the following
domains move down (see identifiers.realign_domains)."""
from dataclasses import dataclass

from arcadia_tool.model.element import Model, natural_key
from arcadia_tool.model.schema import ADR_DELETE_DOMAIN, KINDS_BY_NAME, REF

KEEP, DELETE = "keep", "delete"  # the choices of an orphan, besides the uuid of a domain to pass to


@dataclass(frozen=True)
class OrphanGroup:
    kind: str
    field: str  # None: the domain fields of an ADR (adr_fields)
    title: str  # «Sezioni e clausole di cui è dominio principale»…
    keep: str  # what «keep» means for these elements
    deletable: bool  # its elements can be deleted (when nothing else uses them)


GROUPS = (
    OrphanGroup("requirement", "primary_domain", "Sezioni e clausole SRS di cui è dominio principale",
                "Senza dominio principale", False),
    OrphanGroup("system_function", "domain", "Funzioni di sistema", "Senza dominio", True),
    OrphanGroup("derived_requirement", "domain", "Requisiti derivati", "Senza dominio", True),
    OrphanGroup("functional_chain", "responsible_domain", "Functional chain di cui è responsabile",
                "Senza dominio responsabile", False),
    OrphanGroup("adr", None, "ADR non ancora decise che citano il dominio", "Lascia il riferimento (non più valido)",
                False),
)
# Fields of an ADR recording what was so at a moment: never changed by a deletion.
HISTORY_FIELDS = {"deleted_domain", "primary_at_approval", "contributors_at_approval", "contributors_before_share"}


def adr_fields():
    """The fields of an ADR naming domains, stored and not historical."""
    return [f for f in KINDS_BY_NAME["adr"].fields if f.ref_kinds and "domain" in f.ref_kinds and f.stored
            and f.name not in HISTORY_FIELDS]


def _names(adr, domain_uuid):
    for f in adr_fields():
        value = adr.get(f.name)
        if (value == domain_uuid) if f.type == REF else (domain_uuid in (value or [])):
            return True
    return False


def _members(model, group, domain_uuid):
    if group.kind == "adr":
        from arcadia_tool.model.adr import DECIDED
        return [e for e in model.of_kind("adr") if e.get("status") != DECIDED and _names(e, domain_uuid)]
    return [e for e in model.of_kind(group.kind) if e.get(group.field) == domain_uuid]


def decided_adrs(model, domain_uuid):
    """The decided ADRs naming the domain: they keep it, as the record of what was decided."""
    from arcadia_tool.model.adr import DECIDED
    return [e for e in model.of_kind("adr") if e.get("status") == DECIDED and _names(e, domain_uuid)]


def deleted_domain(model, adr):
    """The domain the ADR deletes, if it is still in the model."""
    uuid = adr.get("deleted_domain")
    domain = model.get(uuid) if uuid else None
    return domain if domain is not None and domain.kind == "domain" else None


def deletion_problems(model, adr):
    """What is missing to approve the deletion (empty list: it can be approved)."""
    if adr.get("adr_type") != ADR_DELETE_DOMAIN:
        return ["L'ADR non è di eliminazione di un dominio."]
    if not adr.get("deleted_domain"):
        return ["Manca il dominio da eliminare."]
    if deleted_domain(model, adr) is None:
        return ["Il dominio da eliminare non è più nel modello."]
    return []


def orphans(model, domain_uuid, skip=()):
    """The elements left without their domain if it is deleted: [(OrphanGroup, [elements])], the groups with some, the
    elements by their ID (or name). skip: uuids not to list (e.g. the ADR deleting it, deleted with it)."""
    result = []
    for group in GROUPS:
        found = sorted((e for e in _members(model, group, domain_uuid) if e.uuid not in skip),
                       key=lambda e: natural_key(e.get("id") or e.get("name") or ""))
        if found:
            result.append((group, found))
    return result


def second_references(model, domain_uuid):
    """The elements that only lose a mention of the domain (as a contributor, as excluded, among the domains of a
    team): the reference is removed."""
    return [e for e in model.of_kind("requirement", "team")
            if domain_uuid in (e.get("contributing_domains") or []) + (e.get("excluded_domains") or [])
            + (e.get("domains") or [])]


def deletable(model, element, domain_uuid):
    """An orphan that can be deleted: of a kind that can, and used by no other element (but the domain itself and
    the ADR, which only name it)."""
    group = next(g for g in GROUPS if g.kind == element.kind)
    if not group.deletable:
        return False
    return not [e for e in model.referencing([element.uuid]) if e.uuid != domain_uuid and e.kind not in ("adr",)]


def _repoint(adr, domain_uuid, target):
    """An ADR naming the domain: the other domain in its place, in each of its fields."""
    for f in adr_fields():
        value = adr.get(f.name)
        if f.type == REF:
            if value == domain_uuid:
                adr.set(f.name, target)
        elif value and domain_uuid in value:
            adr.set(f.name, list(dict.fromkeys(target if v == domain_uuid else v for v in value)))


def apply_choices(model, domain, choices=None, delete=None, update=None, skip=()):
    """The orphans as chosen ({uuid: KEEP, DELETE or the uuid of another domain}; KEEP if not said), the mentions of
    second order removed. delete(uuid), update(element, previous): how the model is changed (a project records them;
    without, the model alone, e.g. for a preview). Returns (elements changed, uuids deleted)."""
    choices = choices or {}
    changed, deleted = {}, []

    def record(element, previous):
        for other in [element, *((update(element, previous) if update else None) or [])]:
            changed[other.uuid] = other

    for group, elements in orphans(model, domain.uuid, skip):
        for element in elements:
            choice = choices.get(element.uuid) or KEEP
            if choice == DELETE and deletable(model, element, domain.uuid):
                (delete or model.remove)(element.uuid)
                deleted.append(element.uuid)
                continue
            target = choice if choice not in (KEEP, DELETE) and model.get(choice) is not None else None
            previous = element.copy()
            if group.kind == "adr":
                if target is None:
                    continue  # left as it is: the reference no longer leads anywhere
                _repoint(element, domain.uuid, target)
            else:
                element.set(group.field, target)
            if group.kind == "requirement" and target:  # principal: no longer a contributor of it
                element.set("contributing_domains", [d for d in element.get("contributing_domains") or []
                                                     if d != target])
            record(element, previous)
    for element in second_references(model, domain.uuid):
        previous = element.copy()
        for name in ("contributing_domains", "excluded_domains", "domains"):
            if domain.uuid in (element.get(name) or []):
                element.set(name, [d for d in element.get(name) if d != domain.uuid])
        record(element, previous)
    return [e for u, e in changed.items() if model.get(u) is not None], deleted


def delete_domain(project, domain, choices=None, skip=()):
    """The domain deleted from the project: the orphans as chosen (see apply_choices), then the domain, and the
    following domains moved down with what depends on them (project.take_realigned tells what). Returns (elements
    changed, uuids deleted)."""
    changed, deleted = apply_choices(project.model, domain, choices, project.delete_element, project.update, skip)
    project.delete_element(domain.uuid)
    return changed, [*deleted, domain.uuid]


def unresolved(choices):
    """The orphans with no choice made yet: the user must say what to do with each."""
    return [u for u, choice in choices.items() if not choice]


def renumbering(model, domain, choices=None, skip=()):
    """What the deletion would renumber, with these choices: [(kind, old id, new id or None)]; the model unchanged."""
    from arcadia_tool.model.identifiers import realign_domains

    if not domain.get("id"):
        return []
    copy = Model([e.copy() for e in model])
    apply_choices(copy, copy.get(domain.uuid), choices, skip=skip)
    copy.remove(domain.uuid)
    return [(e.kind, old, new) for e, old, new in realign_domains(copy, domain.get("id")) if old != new]


def approve_domain_deletion(project, adr, choices=None, today=None):
    """The Design Authority approves the deletion: the ADR decided, with the name of the domain it deletes (its
    reference no longer leads anywhere), then the domain deleted as delete_domain does. Returns (elements changed,
    uuids deleted)."""
    from arcadia_tool.model.adr import DECIDED, decision_date_of

    problems = deletion_problems(project.model, adr)
    if problems:
        raise ValueError(" ".join(problems))
    domain = deleted_domain(project.model, adr)
    previous = adr.copy()
    adr.set("deleted_domain_label", project.model.label(domain))
    adr.set("status", DECIDED)
    if adr.get("da_decision") not in ("Accolta", "Accolta con modifiche"):
        adr.set("da_decision", "Accolta")
    adr.set("decision_date", decision_date_of(adr, today=today))
    project.update(adr, previous)
    return delete_domain(project, domain, choices)
