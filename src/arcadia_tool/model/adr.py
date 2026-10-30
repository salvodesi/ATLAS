"""The types of architectural decision (X-1, see schema.ADR_TYPES): what a new ADR of a type already knows from
the element it is opened from (the domain, the section, the function in question)."""
from datetime import date

from arcadia_tool.model.element import Element
from arcadia_tool.model.schema import (ADR_DELETE_DOMAIN, ADR_DETAILS, ADR_DOMAIN_SCOPE, ADR_FUNCTION,
                                       ADR_EXCLUSION, ADR_IMPLEMENTATION, ADR_MERGE_DOMAINS, ADR_NEW_DOMAIN,
                                       ADR_OWNER,
                                       ADR_PRODUCT_OPTION,
                                       ADR_SECTION, ADR_SPLIT_DOMAIN, KINDS_BY_NAME)
from arcadia_tool.model.teams import person_key

PROPOSED, IN_REVIEW, REVIEWED, DECIDED = "Proposta", "In revisione DA", "Revisionato DA", "Decisa"
OPEN = (PROPOSED, IN_REVIEW, REVIEWED, None)  # not decided yet

IDENTIFICATION = ("id", "title", "adr_type", "status", "superseded_by", "proposer", "proposer_member",
                  "decision_date")


def srs_items_of(model, domains):
    """The SRS items of the domains (principal or contributing domain), in specification order."""
    from arcadia_tool.model.element import natural_key

    domains = set(domains)
    if not domains:
        return []
    items = [e for e in model.of_kind("requirement")
             if e.get("primary_domain") in domains or domains & set(e.get("contributing_domains") or [])]
    return [e.uuid for e in sorted(items, key=lambda e: natural_key(e.get("id") or ""))]


def merged_srs_items(model, adr):
    """The SRS items of the domains merged by an ADR: they are those of the resulting domain."""
    return srs_items_of(model, adr.get("merged_domains") or [])


def current_mission(model, adr):
    """The mission the domain of the ADR has now (read from its sheet)."""
    domain = model.get(adr.get("domain")) if adr.get("domain") else None
    return (domain.get("mission") or "") if domain is not None else ""


def realloc_items(model, adr):
    """The SRS items of the ADR: those to reallocate (one or more, of sections of the same domain), or the one
    leaving a choice to the implementation."""
    value = adr.get("realloc_item") or adr.get("impl_item") or []
    uuids = [value] if isinstance(value, str) else list(value)  # one item: written by earlier versions
    return [e for e in (model.get(u) for u in uuids) if e is not None]


def allocated_part(model, item):
    """The SRS item whose domains the item has (A4): the item itself if it has a principal or contributing domain,
    else the nearest section or clause containing it that has one (a clause takes them from its section)."""
    seen = set()
    while item is not None and item.uuid not in seen:
        seen.add(item.uuid)
        if item.get("primary_domain") or item.get("contributing_domains"):
            return item
        item = model.get(item.get("parent")) if item.get("parent") else None
    return None


def principal_of(model, item):
    """The principal domain an SRS item has now: its own, else of the nearest section or clause containing it that
    has one (A4; also when the item has contributing domains of its own)."""
    seen = set()
    while item is not None and item.uuid not in seen:
        seen.add(item.uuid)
        if item.get("primary_domain"):
            return item.get("primary_domain")
        item = model.get(item.get("parent")) if item.get("parent") else None
    return None


def item_primary(model, adr):
    """The principal domain the SRS items of the ADR have now (of the first that has one: they are of one section,
    see same_section)."""
    return next((d for d in (principal_of(model, e) for e in realloc_items(model, adr)) if d), None)


def item_contributors(model, adr):
    """The contributing domains the SRS items to reallocate have now (their own, or of the sections containing
    them), without repetitions."""
    result = []
    for item in realloc_items(model, adr):
        part = allocated_part(model, item)
        result += [d for d in (part.get("contributing_domains") or [] if part is not None else []) if d not in result]
    return result


def allocated_from(model, adr):
    """The sections or clauses the domains of the SRS items of the ADR come from, when not the items themselves."""
    result = []
    for item in realloc_items(model, adr):
        part, seen = item, set()  # where its principal domain comes from (see principal_of)
        while part is not None and part.uuid not in seen and not part.get("primary_domain"):
            seen.add(part.uuid)
            part = model.get(part.get("parent")) if part.get("parent") else None
        if part is not None and part is not item and part.get("primary_domain") and part not in result:
            result.append(part)
    return result


def section_of(model, item):
    """The section (item type «Sezione») an SRS item is, or belongs to; None for one outside any section."""
    seen = set()
    while item is not None and item.uuid not in seen:
        seen.add(item.uuid)
        if item.get("item_type") == "Sezione":
            return item
        item = model.get(item.get("parent")) if item.get("parent") else None
    return None


def same_section(model, items):
    """The SRS items of one ADR of reallocation: all of the same section (else: one ADR per section)."""
    return len({getattr(section_of(model, e), "uuid", None) for e in items}) <= 1


def function_domain(model, adr):
    """The domain the system function to move has now."""
    function = model.get(adr.get("function")) if adr.get("function") else None
    return function.get("domain") if function is not None else None


def item_producers(model, adr):
    """Who produces the information now: the producers of the exchanges that carry it."""
    uuid = adr.get("exchange_item")
    if not uuid:
        return []
    return list(dict.fromkeys(fe.get("source") for fe in model.of_kind("functional_exchange")
                              if fe.get("exchange_item") == uuid and fe.get("source")))


def excluded_items(adr):
    """The SRS items (uuids) an ADR of exclusion leaves out (one, as written by the first versions, or a list)."""
    value = adr.get("excluded_item") or []
    return [value] if isinstance(value, str) else list(value)


def excluded_within(model, adr):
    """The sections (or clauses) containing the excluded items of which the excluding domain is principal."""
    domain = adr.get("excluding_domain")
    found = []
    for uuid in excluded_items(adr):
        item = model.get(uuid)
        part = principal_container(model, item, domain) if item is not None and domain else None
        if part is not None and part.uuid not in found:
            found.append(part.uuid)
    return found


def principal_container(model, item, domain_uuid):
    """The section or clause containing the item (not the item itself) of which the domain is principal; None."""
    seen = set()
    part = model.get(item.get("parent")) if item.get("parent") else None
    while part is not None and part.uuid not in seen:
        seen.add(part.uuid)
        if part.get("primary_domain") == domain_uuid:
            return part
        part = model.get(part.get("parent")) if part.get("parent") else None
    return None


def exclusion_adr(model, item, domain):
    """The ADR of the exclusion of the item from the domain, if any (the latest one)."""
    found = [a for a in model.of_kind("adr") if a.get("adr_type") == ADR_EXCLUSION
             and item.uuid in excluded_items(a) and a.get("excluding_domain") == domain.uuid]
    return found[-1] if found else None


def exclusion_defaults(model, item, domain):
    """The values of the ADR of exclusion of an SRS item from a domain (its reason: written by the team; other
    items it leaves out: added in its sheet)."""
    return {"adr_type": ADR_EXCLUSION, "status": PROPOSED, "excluded_item": [item.uuid],
            "excluding_domain": domain.uuid,
            "concerns": [domain.uuid], "proposer": domain.get("team"),
            "title": f"Esclusione di {item.get('id') or ''} da {domain.get('id') or model.label(domain)}"}


# Fields computed from the others (see Field.computed).
COMPUTED = {"merged_srs_items": merged_srs_items, "current_mission": current_mission,
            "item_primary": item_primary, "item_contributors": item_contributors,
            "function_domain": function_domain, "item_producers": item_producers, "excluded_within": excluded_within}


def split_domain_items(model, adr):
    """(uuid, label) of the SRS items of the domain split by an ADR: those to share among the resulting domains."""
    items = srs_items_of(model, [adr.get("split_domain")] if adr.get("split_domain") else [])
    return [(uuid, model.label_of(uuid)) for uuid in items]


def split_destinations(model, adr):
    """(name, name) of the resulting domains written in the ADR of a split."""
    names = [" ".join((row.get("name") or "").split()) for row in adr.get("new_domains") or []]
    return [(name, name) for name in dict.fromkeys(n for n in names if n)]


# Lists to choose from in the cells of a table, computed from the element (see Column.choices).
CHOICES = {"split_domain_items": split_domain_items, "split_destinations": split_destinations}


def type_fields(adr_type):
    """The fields of the details of a type, in the order of the sheet."""
    return [f for f in KINDS_BY_NAME["adr"].fields if f.section == ADR_DETAILS and adr_type in f.when[1]]


def common_fields(adr_type):
    """The other fields an ADR of the type has (contesto, opzioni, decisione…), besides its identification:
    some types do without some of them (e.g. a new domain)."""
    probe = Element("adr", values={"adr_type": adr_type})
    return [f for f in KINDS_BY_NAME["adr"].fields
            if f.section != ADR_DETAILS and f.name not in IDENTIFICATION and f.applies(probe) and not f.hidden]


SUGGESTED = {"domain": ADR_DOMAIN_SCOPE, "requirement": ADR_SECTION, "system_function": ADR_FUNCTION,
             "exchange_item": ADR_OWNER}


def suggested_type(element):
    """The type most likely wanted from the element selected (e.g. a domain: the redefinition of its scope)."""
    return SUGGESTED.get(element.kind) if element is not None else None


def adr_defaults(model, adr_type, element=None):
    """The values of a new ADR of the type, from the element selected when it is created (None: just the type)."""
    values = {"adr_type": adr_type, "status": "Proposta"}
    if element is None:
        return values
    kind = element.kind
    if kind == "domain" and adr_type == ADR_DELETE_DOMAIN:
        values["deleted_domain"] = element.uuid
    elif kind == "domain" and adr_type == ADR_SPLIT_DOMAIN:
        values["split_domain"] = element.uuid
    elif kind == "domain" and adr_type == ADR_DOMAIN_SCOPE:
        values["domain"] = element.uuid
    elif kind == "domain" and adr_type == ADR_MERGE_DOMAINS:
        values["merged_domains"] = [element.uuid]  # the others: added in the sheet
    elif kind == "requirement" and adr_type == ADR_SECTION:
        values["realloc_item"] = [element.uuid]  # its domains now: read from it (see item_primary)
    elif kind == "requirement" and adr_type == ADR_EXCLUSION:
        values["excluded_item"] = [element.uuid]
    elif kind == "requirement" and adr_type == ADR_IMPLEMENTATION:
        values["impl_item"] = element.uuid  # its domain: read from it (see item_primary)
    elif kind == "system_function" and adr_type in (ADR_FUNCTION, ADR_PRODUCT_OPTION):
        values["function"] = element.uuid  # its domain now: read from it (see function_domain)
    elif kind == "exchange_item" and adr_type == ADR_OWNER:
        values["exchange_item"] = element.uuid
    return {k: v for k, v in values.items() if v}


# --- the ADR of a domain or of a system function -------------------------------------------------------------

ACTIVE, APPROVED, REJECTED, SUPERSEDED = "Attiva", "Approvata", "Respinta", "Superata"
OUTCOMES = (ACTIVE, APPROVED, REJECTED, SUPERSEDED)  # in the order of the table of a sheet


def outcome(adr):
    """Where an ADR stands: respinta (by the DA), superata, approvata (decided, or accepted by the DA), else
    attiva (proposed, under the review of the DA, or with its comments to address)."""
    if adr.get("da_decision") == "Respinta":
        return REJECTED
    if adr.get("status") == "Superata":
        return SUPERSEDED
    if adr.get("status") == DECIDED or adr.get("da_decision") in ("Accolta", "Accolta con modifiche"):
        return APPROVED
    return ACTIVE


def related_adrs(model, element):
    """The ADR about a domain or a system function: those that name it in a field (the domain to delete, the
    function to move, the domain proposed…, or «Riguarda», when created from its sheet), those that read it from
    the model (the domain of the clauses to reallocate, of the function to move), and those linked by hand in the
    sheet by earlier versions («Decisioni collegate»). In the order of the table: by outcome, then by ID."""
    from arcadia_tool.model.element import natural_key

    found = {u: model.get(u) for u in element.get("adrs") or []}
    for adr in model.of_kind("adr"):
        if adr.uuid in found:
            continue
        named = any(
            (f.type == "ref" and adr.values.get(f.name) == element.uuid) or
            (f.type == "refs" and element.uuid in (adr.values.get(f.name) or [])) or
            (f.type == "table" and any(element.uuid in row.values() for row in adr.values.get(f.name) or []
                                       if isinstance(row, dict)))
            for f in adr.schema.fields if f.stored and f.applies(adr) or f.name == "concerns")
        computed = any(element.uuid in ([v] if isinstance(v, str) else (v or []))
                       for f in adr.schema.fields if f.computed and f.applies(adr) and f.computed in COMPUTED
                       and f.type in ("ref", "refs") and element.kind in f.ref_kinds
                       for v in [COMPUTED[f.computed](model, adr)])
        if named or computed:
            found[adr.uuid] = adr
    adrs = [a for a in found.values() if a is not None and a.kind == "adr"]
    return sorted(adrs, key=lambda a: (OUTCOMES.index(outcome(a)), natural_key(a.get("id") or "")))


def impacted_domains(model, adr):
    """The functional domains an ADR is about: those named in its fields of its type (the domain to delete, to
    merge, proposed…, «Riguarda»), and those read from the model (of the clauses to reallocate, of the function to
    move); in the order of their IDs."""
    from arcadia_tool.model.element import natural_key

    found = {}
    for f in adr.schema.fields:
        if "domain" not in f.ref_kinds or f.type not in ("ref", "refs") or not (f.applies(adr) or f.name == "concerns"):
            continue
        value = COMPUTED[f.computed](model, adr) if f.computed in COMPUTED else adr.values.get(f.name)
        for uuid in ([value] if isinstance(value, str) else value or []):
            domain = model.get(uuid)
            if domain is not None and domain.kind == "domain":
                found[domain.uuid] = domain
    return sorted(found.values(), key=lambda d: natural_key(d.get("id") or d.get("name") or ""))


def related_adrs_ids(model, element):
    return [a.uuid for a in related_adrs(model, element)]


COMPUTED["related_adrs"] = related_adrs_ids  # the table of the ADR of a domain or function sheet


# --- the approval of the Design Authority ---------------------------------------------------------------------

def can_approve(adr):
    """An ADR the Design Authority can approve with an action of the tool: a new domain still proposed (or under
    its review)."""
    return adr.kind == "adr" and adr.get("adr_type") == ADR_NEW_DOMAIN and adr.get("status") in OPEN


def approval_problems(model, adr):
    """What is missing to approve the ADR of a new domain (empty list: it can be approved)."""
    problems = []
    name = " ".join((adr.get("new_domain_name") or "").split())
    if not name:
        problems.append("Manca il nome del dominio proposto.")
    elif any(person_key(d.get("name")) == person_key(name) for d in model.of_kind("domain")):
        problems.append(f"Esiste già un dominio «{name}».")
    if not (adr.get("mission_proposed") or "").strip():
        problems.append("Manca la missione proposta.")
    return problems


def sections_taken(model, adr):
    """The sections allocated to the new domain that have another principal domain now: (section, domain)."""
    result = []
    for uuid in adr.get("sections_allocated") or []:
        section = model.get(uuid)
        if section is not None and section.get("primary_domain"):
            result.append((section, model.get(section.get("primary_domain"))))
    return result


def decision_date_of(adr, previous=None, today=None):
    """The date of the decision of an ADR as it should be: set (today) when it becomes «Decisa», kept while it is
    decided or superseded, removed if it goes back to «Proposta», «In revisione DA» or «Revisionato
    DA»."""
    status = adr.get("status")
    if status == DECIDED and not adr.get("decision_date"):
        return f"{(today or date.today()):%d/%m/%Y}"
    if status in OPEN:
        return None
    return adr.get("decision_date")


def approve_new_domain(project, adr, today=None):
    """The Design Authority approves the ADR of a new domain: the domain is created (its ID given by the tool),
    with the proposed mission and team, and is the principal domain of the allocated sections (their earlier
    principal domain no longer is); the ADR is decided, with the date (today) and the domain created.
    Returns (domain, the other elements changed)."""
    problems = approval_problems(project.model, adr)
    if problems:
        raise ValueError(" ".join(problems))
    domain = project.new_element("domain", name=" ".join(adr.get("new_domain_name").split()),
                                 mission=adr.get("mission_proposed"), status="Approvato")
    changed = []
    if adr.get("team_proposed") and project.model.get(adr.get("team_proposed")) is not None:
        previous = domain.copy()
        domain.set("team", adr.get("team_proposed"))
        changed += project.update(domain, previous) or []  # the team lists the domain (see model.links)
    for uuid in adr.get("sections_allocated") or []:
        section = project.model.get(uuid)
        if section is None:
            continue
        previous = section.copy()
        section.set("primary_domain", domain.uuid)
        section.set("contributing_domains", [d for d in section.get("contributing_domains") or []
                                             if d != domain.uuid])
        changed += [section, *(project.update(section, previous) or [])]
    previous = adr.copy()
    adr.set("status", DECIDED)
    adr.set("created_domain", domain.uuid)
    adr.set("decision_date", decision_date_of(adr, today=today))
    project.update(adr, previous)
    return domain, list({e.uuid: e for e in changed if e.uuid != domain.uuid}.values())
