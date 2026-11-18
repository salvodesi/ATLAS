"""The types of architectural decision (X-1, see schema.ADR_TYPES): what a new ADR of a type already knows from
the element it is opened from (the domain, the section, the function in question)."""
from datetime import date

from arcadia_tool.model.chains import COMPUTED as CHAIN_COMPUTED
from arcadia_tool.model.element import Element
from arcadia_tool.model.schema import (ADR_ALLOCATION, ADR_DELETE_DOMAIN, ADR_DERIVED, ADR_DETAILS, ADR_DOMAIN_SCOPE, ADR_FUNCTION,
                                       ADR_EXCLUSION, ADR_IMPLEMENTATION, ADR_MERGE_DOMAINS, ADR_NEW_DOMAIN,
                                       ADR_OWNER,
                                       ADR_PRODUCT_OPTION,
                                       ADR_SECTION, ADR_SHARED, ADR_SPLIT_DOMAIN, ADR_UNMAPPED, KINDS_BY_NAME,
                                       REALLOC_TYPES, SCOPE_CLAUSES, SCOPE_SECTION)
from arcadia_tool.model.teams import person_key

PROPOSED, IN_REVIEW, REVIEWED, DECIDED = "Proposta", "In revisione DA", "Revisionato DA", "Decisa"
OPEN = (PROPOSED, IN_REVIEW, REVIEWED, None)  # not decided yet

# Not among the other fields of a type (see common_fields): its identification, and the ADR linked (chosen in the
# tool, not in the templates of the teams).
IDENTIFICATION = ("id", "title", "adr_type", "status", "superseded_by", "proposer", "proposer_member",
                  "decision_date", "deleted_domain_label", "linked_adrs")


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


def realloc_scope(model, adr):
    """What a reallocation moves (SCOPE_SECTION, SCOPE_CLAUSES): as written in the ADR, else (an ADR of an earlier
    version) read from its items: one or more sections, or clauses; None if it cannot be told (nothing chosen, or
    sections with clauses). Not a reallocation of a section or clause: None."""
    if adr.get("adr_type") != ADR_SECTION:
        return None
    if adr.get("realloc_scope"):
        return adr.get("realloc_scope")
    items = realloc_items(model, adr)
    sections = [e for e in items if e.get("item_type") == "Sezione"]
    if not items:
        return None
    if not sections:
        return SCOPE_CLAUSES
    if len(sections) == 1 and all(e is sections[0] or section_of(model, e) is sections[0] for e in items):
        return SCOPE_SECTION  # a section, maybe with some of its clauses: they follow it
    return None


def scope_of_item(item):
    """The scope a reallocation opened from an SRS item proposes: of the section, or of the clause."""
    return SCOPE_SECTION if item.get("item_type") == "Sezione" else SCOPE_CLAUSES


def scope_mismatch(model, adr, scope=None):
    """The items of the reallocation that its scope (or `scope`) does not admit: a whole section admits one section
    (its own clauses, if chosen too, follow it: admitted), clauses admit no section."""
    scope = scope or adr.get("realloc_scope")
    items = realloc_items(model, adr)
    if adr.get("adr_type") != ADR_SECTION or not scope:
        return []
    if scope == SCOPE_SECTION:
        sections = [e for e in items if e.get("item_type") == "Sezione"]
        first = sections[0] if sections else None
        return [e for e in items if e.get("item_type") != "Sezione" and (first is None or section_of(model, e)
                                                                          is not first)] + sections[1:]
    return [e for e in items if e.get("item_type") == "Sezione"]


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
    see same_section); once the reallocation is applied, the one they had then: the ADR does not change."""
    if adr.get("realloc_applied"):
        return adr.get("primary_at_approval")
    return next((d for d in (principal_of(model, e) for e in realloc_items(model, adr)) if d), None)


def item_contributors(model, adr):
    """The contributing domains the SRS items to reallocate have now (their own, or of the sections containing
    them), without repetitions; once the reallocation is applied, those they had then."""
    if adr.get("realloc_applied"):
        return list(adr.get("contributors_at_approval") or [])
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


# A point of a clause: a list item («3.6.2.2.2 a)»), a bullet («3.6.2.2.2 a) 1st bullet»), a table row, a figure. An
# ADR of reallocation, exclusion or sharing can be about one: it then has domains of its own, and its clause is mixed.
POINT = "Voce"


def own_domains_of_point(item):
    """The domains a point has of its own: (principal or None, contributors, excluded); all empty: those of its
    clause."""
    return (item.get("primary_domain"), list(item.get("contributing_domains") or []),
            list(item.get("excluded_domains") or []))


def clause_of_point(model, item):
    """The clause (or section) containing a point, above the points containing it (a bullet of a letter)."""
    seen, part = {item.uuid}, model.get(item.get("parent")) if item.get("parent") else None
    while part is not None and part.uuid not in seen and part.get("item_type") == POINT:
        seen.add(part.uuid)
        part = model.get(part.get("parent")) if part.get("parent") else None
    return part


def mixed_points(model):
    """{clause uuid: [its points with domains of their own]}: the clauses whose points are not all in their domains."""
    found = {}
    for item in model.of_kind("requirement"):
        if item.get("item_type") == POINT and any(own_domains_of_point(item)):
            clause = clause_of_point(model, item)
            if clause is not None:
                found.setdefault(clause.uuid, []).append(item)
    return found


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


# The fields of an ADR naming SRS sections or clauses it is about, opened by a team on its own sections: not those
# of the ADR on the domains (sections allocated, acquired, ceded), which are about sections of other domains.
TEAM_ITEM_FIELDS = ("srs_items", "realloc_item", "excluded_item", "shared_items", "unmapped_items", "impl_item")


def adr_srs_items(model, adr):
    """The SRS sections and clauses the ADR is about (see TEAM_ITEM_FIELDS), in the order written."""
    found = []
    for f in adr.schema.fields:
        if f.name in TEAM_ITEM_FIELDS and f.applies(adr):
            value = adr.get(f.name) or []
            for uuid in [value] if isinstance(value, str) else value:
                item = model.get(uuid)
                if item is not None and item not in found:
                    found.append(item)
    return found


def sections_not_held(model, adr):
    """The sections (three numbers, e.g. 3.4.1) of the SRS items of the ADR that the team proposing it does not hold:
    none of its functional domains is their principal domain (nor of the clause itself, passed to it by a
    reallocation). [(section, its principal domain or None)], each once; empty if no team proposes the ADR."""
    team = adr.get("proposer")
    if not team or adr.get("adr_type") == ADR_ALLOCATION:  # a request of allocation: of another team by its nature
        return []
    own = team_domains(model, team)
    found, seen = [], set()
    for item in adr_srs_items(model, adr):
        section = section_of(model, item)
        if section is None or section.uuid in seen or held(model, item, own):
            continue
        seen.add(section.uuid)
        found.append((section, principal_of(model, section)))
    return found


def allocation_warnings(model, adr):
    """What does not hold in a request of allocation (texts): the domain requested is not of the team proposing it, a
    clause requested is already held by the team (see held), or is not a clause (a section, a list item)."""
    if adr.get("adr_type") != ADR_ALLOCATION:
        return []
    team, warnings = adr.get("proposer"), []
    own = team_domains(model, team) if team else set()
    requested = model.get(adr.get("primary_proposed") or "")
    if team and requested is not None and requested.uuid not in own:
        warnings.append(f"Il dominio richiedente {model.label(requested)} non è un dominio del team proponente.")
    for item in realloc_items(model, adr):
        if item.get("item_type") not in ("Titolo", "Requisito", POINT):
            warnings.append(f"{item.get('id')} non è una clausola: si richiedono solo clausole (es. 3.4.1.5) o loro "
                            "punti (es. 3.4.1.5 a)).")
        elif team and held(model, item, own):
            warnings.append(f"{item.get('id')} è già in un dominio del team proponente: non serve richiederla.")
    return warnings


def item_domains(model, item):
    """The domains an SRS item belongs to now: its principal domain and its contributors (its own, or of the nearest
    section or clause containing it that has them), but those it is excluded from (by itself or by a container)."""
    found = set()
    principal = principal_of(model, item)
    if principal:
        found.add(principal)
    part = allocated_part(model, item)
    found.update(part.get("contributing_domains") or [] if part is not None else [])
    excluded, seen, current = set(), set(), item
    while current is not None and current.uuid not in seen:
        seen.add(current.uuid)
        excluded.update(current.get("excluded_domains") or [])
        current = model.get(current.get("parent")) if current.get("parent") else None
    return found - excluded


def team_domains(model, team_uuid):
    """The uuids of the functional domains assigned to the team."""
    return {d.uuid for d in model.of_kind("domain") if d.get("team") == team_uuid}


def held(model, item, own):
    """The SRS item is held by the domains (uuids): one of them is the principal domain of its section, or of the item
    itself (e.g. a clause passed to it by a reallocation). An item out of any section: by its own principal domain."""
    section = section_of(model, item)
    return (section is not None and principal_of(model, section) in own) or principal_of(model, item) in own


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


def proposer_defaults(model, user):
    """Who proposes a new ADR: the team of the user logged in, and the user as a member of it (of the first one, if
    more: it can be changed in the sheet); nothing if the user is in no team."""
    from arcadia_tool.model.teams import memberships

    found = memberships(model, user) if user is not None else []
    if not found:
        return {}
    team, row = found[0]
    return {"proposer": team.uuid, "proposer_member": row.get("name")}


def exclusion_defaults(model, item, domain):
    """The values of the ADR of exclusion of an SRS item from a domain (its reason: written by the team; other
    items it leaves out: added in its sheet)."""
    return {"adr_type": ADR_EXCLUSION, "status": PROPOSED, "excluded_item": [item.uuid],
            "excluding_domain": domain.uuid,
            "concerns": [domain.uuid], "proposer": domain.get("team"),
            "title": f"Esclusione di {item.get('id') or ''} da {domain.get('id') or model.label(domain)}"}


# --- clauses shared among domains, clauses mapped to no domain (declared by the teams) --------------------------------

CLAUSE_FIELDS = {ADR_SHARED: "shared_items", ADR_UNMAPPED: "unmapped_items"}
# The reason of a clause mapped to no domain, proposed from its category of chapter 9.
UNMAPPED_FROM_CATEGORY = (("Terra", "Requisito di terra"), ("Definizione", "Informativa o definizione"),
                          ("Informativa", "Informativa o definizione"))


def clauses_of(model, adr):
    """The SRS clauses an ADR of sharing or of a clause mapped to no domain is about."""
    uuids = adr.get(CLAUSE_FIELDS.get(adr.get("adr_type"), "")) or []
    return [e for e in (model.get(u) for u in uuids) if e is not None]


def shared_primary(model, adr):
    """The principal domain the clauses to share have (of the first that has one)."""
    return next((d for d in (principal_of(model, e) for e in clauses_of(model, adr)) if d), None)


def shared_contributors(model, adr):
    """The contributing domains the clauses to share have now; once the sharing is applied, those they had then."""
    if adr.get("share_applied"):
        return list(adr.get("contributors_before_share") or [])
    result = []
    for item in clauses_of(model, adr):
        part = allocated_part(model, item)
        result += [d for d in (part.get("contributing_domains") or [] if part is not None else []) if d not in result]
    return result


def unmapped_sections(model, adr):
    """The sections containing the clauses mapped to no domain."""
    found = []
    for item in clauses_of(model, adr):
        section = section_of(model, item)
        if section is not None and section.uuid not in found:
            found.append(section.uuid)
    return found


def unmapped_section_domains(model, adr):
    """The principal domains of the sections containing the clauses mapped to no domain."""
    found = []
    for uuid in unmapped_sections(model, adr):
        domain = principal_of(model, model.get(uuid))
        if domain and domain not in found:
            found.append(domain)
    return found


def _clause_title(what, items):
    ids = [e.get("id") or "" for e in items]
    if len(ids) == 1:
        return f"{what} della clausola {ids[0]}"
    return f"{what} delle clausole {', '.join(ids[:3])}" + (" …" if len(ids) > 3 else "")


def sharing_defaults(model, items, proposer=None):
    """A new ADR of sharing of the clauses (elements). The domains to share them with are not proposed: the user says
    them (proposer: the team proposing, kept for the callers)."""
    values = {"adr_type": ADR_SHARED, "status": PROPOSED, "shared_items": [e.uuid for e in items],
              "title": _clause_title("Condivisione", items)}
    return {k: v for k, v in values.items() if v}


def unmapped_defaults(model, items):
    """A new ADR of clauses mapped to no domain (elements): the reason proposed from their category of chapter 9."""
    categories = {c for e in items for c in e.get("category") or []}
    reason = next((r for c, r in UNMAPPED_FROM_CATEGORY if c in categories), None)
    values = {"adr_type": ADR_UNMAPPED, "status": PROPOSED, "unmapped_items": [e.uuid for e in items],
              "title": _clause_title("Non mappatura", items), "unmapped_reason": reason}
    return {k: v for k, v in values.items() if v}


def clause_decisions(model, adr_type):
    """(clause, ADR) of the ADR of the type (sharing, or clauses mapped to no domain), whatever their status: what the
    teams have declared, in the order of the clauses."""
    from arcadia_tool.model.element import natural_key

    rows = [(item, adr) for adr in model.of_kind("adr") if adr.get("adr_type") == adr_type
            for item in clauses_of(model, adr)]
    return sorted(rows, key=lambda r: (natural_key(r[0].get("id") or ""), natural_key(r[1].get("id") or "")))


def unmapped_by_decision(model):
    """The uuids of the clauses an approved ADR maps to no domain."""
    return {item.uuid for item, adr in clause_decisions(model, ADR_UNMAPPED) if outcome(adr) == APPROVED}


# Fields computed from the others (see Field.computed).
COMPUTED = {"merged_srs_items": merged_srs_items, "current_mission": current_mission,
            "item_primary": item_primary, "item_contributors": item_contributors,
            "function_domain": function_domain, "item_producers": item_producers, "excluded_within": excluded_within,
            "shared_primary": shared_primary, "shared_contributors": shared_contributors,
            "unmapped_sections": unmapped_sections, "unmapped_section_domains": unmapped_section_domains,
            **CHAIN_COMPUTED}  # of the chains and of the exchange items


def split_domain_items(model, adr):
    """(uuid, label) of the SRS items of the domain split by an ADR: those to share among the resulting domains."""
    items = srs_items_of(model, [adr.get("split_domain")] if adr.get("split_domain") else [])
    return [(uuid, model.label_of(uuid)) for uuid in items]


def split_destinations(model, adr):
    """(name, name) of the resulting domains written in the ADR of a split."""
    names = [" ".join((row.get("name") or "").split()) for row in adr.get("new_domains") or []]
    return [(name, name) for name in dict.fromkeys(n for n in names if n)]


def shared_derived(model, adr):
    """(uuid, label) of the derived requirements (SA-4) of the clauses to share, or of the items inside them: the
    sub-requirements the sharing is structured in."""
    clauses = {e.uuid for e in clauses_of(model, adr)}
    inside = model.descendants(clauses) if clauses else set()
    found = [d for d in model.of_kind("derived_requirement") if d.get("parent") in inside]
    return [(d.uuid, model.choice_label(d)) for d in found]


def split_domains(adr):
    """The domains of destination of the sub-requirements of a sharing, in their order."""
    return list(dict.fromkeys(row.get("domain") for row in adr.get("share_split") or []
                              if isinstance(row, dict) and row.get("domain")))


# Lists to choose from in the cells of a table, computed from the element (see Column.choices).
CHOICES = {"split_domain_items": split_domain_items, "split_destinations": split_destinations,
           "shared_derived": shared_derived}


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
             "exchange_item": ADR_OWNER, "derived_requirement": ADR_DERIVED}


def suggested_type(element):
    """The type most likely wanted from the element selected (e.g. a domain: the redefinition of its scope)."""
    return SUGGESTED.get(element.kind) if element is not None else None


def new_adr_values(model, adr_type, element):
    """The values of an ADR created from an element («Nuova ADR…» of a sheet, «Crea ADR…» of an SRS item): those of
    adr_defaults; the domain or function it is about («Riguarda»); an SRS item named by none of the fields of the
    type: among the «Voci SRS interessate», when the type has them."""
    values = adr_defaults(model, adr_type, element)
    if element.kind in ("domain", "system_function"):
        values["concerns"] = [element.uuid]
    elif element.kind == "requirement" and not any(values.get(f) for f in TEAM_ITEM_FIELDS):
        probe = Element("adr", values=dict(values))
        if probe.schema.field("srs_items").applies(probe):
            values["srs_items"] = [element.uuid]
    return values


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
    elif kind == "requirement" and adr_type in REALLOC_TYPES:
        values["realloc_item"] = [element.uuid]  # its domains now: read from it (see item_primary)
        if adr_type == ADR_SECTION:
            values["realloc_scope"] = scope_of_item(element)
    elif kind == "requirement" and adr_type == ADR_EXCLUSION:
        values["excluded_item"] = [element.uuid]
    elif kind == "requirement" and adr_type == ADR_SHARED:
        values["shared_items"] = [element.uuid]
    elif kind == "requirement" and adr_type == ADR_UNMAPPED:
        values["unmapped_items"] = [element.uuid]
    elif kind == "requirement" and adr_type == ADR_IMPLEMENTATION:
        values["impl_item"] = element.uuid  # its domain: read from it (see item_primary)
    elif kind == "system_function" and adr_type in (ADR_FUNCTION, ADR_PRODUCT_OPTION):
        values["function"] = element.uuid  # its domain now: read from it (see function_domain)
    elif kind == "exchange_item" and adr_type == ADR_OWNER:
        values["exchange_item"] = element.uuid
    elif kind == "derived_requirement" and adr_type == ADR_DERIVED:
        values["derived_items"] = [element.uuid]  # its domain now: read from it (see derived_domains_current)
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


# The states of an ADR not approved (approved: decided, or accepted by the DA, also with changes), as the SRS list
# shows them: its status while open, with the comments of the DA, rejected by the DA, superseded.
NOT_APPROVED_STATES = ("Proposta", "In revisione DA", "Revisionato DA", "Commenti DA", "Respinta", "Superata")


def adr_state(adr):
    """The state of an ADR not approved (one of NOT_APPROVED_STATES), None if it is approved."""
    if adr.get("da_decision") == "Respinta":
        return "Respinta"
    if adr.get("status") == "Superata":
        return "Superata"
    if outcome(adr) == APPROVED:
        return None
    if adr.get("da_decision") == "Commenti DA":
        return "Commenti DA"
    return adr.get("status") if adr.get("status") in NOT_APPROVED_STATES else "Proposta"


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
        if f.type == "table" and f.applies(adr):  # the domains in its rows (e.g. of the sub-requirements of a sharing)
            for column in f.columns:
                if column.type == "ref" and "domain" in column.ref_kinds:
                    for row in adr.values.get(f.name) or []:
                        domain = model.get(row.get(column.name)) if isinstance(row, dict) else None
                        if domain is not None and domain.kind == "domain":
                            found[domain.uuid] = domain
            continue
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
    """An ADR the Design Authority can approve with an action of the tool: a new domain, a reallocation, a sharing of
    clauses or clauses mapped to no domain, still proposed (or under its review), not rejected."""
    return adr.kind == "adr" and adr.get("adr_type") in (ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, *REALLOC_TYPES, ADR_SHARED,
                                                         ADR_UNMAPPED, ADR_DERIVED) and \
        adr.get("status") in OPEN and adr.get("da_decision") != "Respinta"


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
    if not any(model.get(u) is not None for u in adr.get("sections_allocated") or []):
        problems.append("Mancano le sezioni allocate al nuovo dominio.")  # a domain must have some: model.required
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


# --- the approval of a reallocation ---------------------------------------------------------------------------

def realloc_targets(model, adr):
    """The SRS items an approved reallocation writes on: those of the ADR, but those that follow another one of them
    with no domains of their own: the list items of a clause moved, the clauses of a section moved. A clause chosen
    with the clause containing it (e.g. 3.11.6.3 and 3.11.6.3.1) is written too: it was chosen, and the domain sheets
    list it among the clauses received."""
    items = realloc_items(model, adr)
    chosen = {e.uuid for e in items}

    def follows(item):
        seen, parent = {item.uuid}, item.get("parent")
        while parent and parent not in seen:
            container = model.get(parent)
            if parent in chosen:
                return item.get("item_type") == "Voce" or (container is not None
                                                           and container.get("item_type") in ("Capitolo", "Sezione"))
            seen.add(parent)
            parent = container.get("parent") if container is not None else None
        return False
    return [e for e in items if not follows(e) or e.get("primary_domain") or e.get("contributing_domains")]


def reallocation_problems(model, adr):
    """What is missing to apply the reallocation (empty list: it can be applied)."""
    problems = []
    primary = adr.get("primary_proposed")
    if not realloc_items(model, adr):
        problems.append("Mancano le sezioni o clausole da riallocare.")
    if not primary or model.get(primary) is None:
        problems.append("Manca il dominio principale proposto.")
    scope = realloc_scope(model, adr)
    if adr.get("adr_type") == ADR_SECTION and realloc_items(model, adr) and scope is None:
        problems.append("Indica l'«Oggetto»: un'intera sezione o delle clausole (le voci scelte sono di entrambi i "
                        "tipi).")
    wrong = scope_mismatch(model, adr, scope)
    if wrong and scope == SCOPE_SECTION:
        problems.append("Oggetto «Intera sezione»: va scelta una sola sezione (tre numeri, es. 3.4.1), le sue "
                        f"clausole la seguono; da togliere: {', '.join(e.get('id') or '?' for e in wrong)}.")
    elif wrong:
        problems.append(f"Oggetto «Clausole»: {', '.join(e.get('id') or '?' for e in wrong)} è una sezione; per "
                        "riallocarla intera scegli l'oggetto «Intera sezione».")
    for item in realloc_targets(model, adr):  # a point of a clause too (POINT): it gets a principal domain of its own
        if primary in (item.get("excluded_domains") or []):
            problems.append(f"{item.get('id')} è esclusa dal dominio proposto: togli prima l'ADR di esclusione.")
    return problems


def reallocation_preview(model, adr):
    """What approving the reallocation changes: (the items moved with the principal domain they have now; the clauses
    inside them that keep a principal domain of their own, by an earlier decision; the functions of other domains
    that trace them, which stay where they are)."""
    from arcadia_tool.model.links import TRACED_FIELD, _domain_of_function

    primary = adr.get("primary_proposed")
    targets = realloc_targets(model, adr)
    moved = [(item, principal_of(model, item)) for item in targets]
    inside = set(model.descendants([e.uuid for e in targets]))
    chosen = {e.uuid for e in targets}
    kept = [e for e in model.of_kind("requirement") if e.uuid in inside and e.uuid not in chosen
            and e.get("primary_domain") and e.get("primary_domain") != primary]
    functions = [f for kind, field in TRACED_FIELD.items() for f in model.of_kind(kind)
                 if inside & set(f.get(field) or []) and _domain_of_function(model, f) != primary]
    return moved, kept, functions


def approve_reallocation(project, adr, today=None):
    """The Design Authority approves the reallocation (or applies one decided earlier): the items pass to the proposed
    principal domain, with the proposed contributors; the clauses inside them with a principal domain of their own
    keep it. The ADR is decided. Returns the other elements changed."""
    problems = reallocation_problems(project.model, adr)
    if problems:
        raise ValueError(" ".join(problems))
    primary, changed = adr.get("primary_proposed"), []
    before = item_primary(project.model, adr), item_contributors(project.model, adr)  # as the ADR goes on showing them
    for item in realloc_targets(project.model, adr):
        previous = item.copy()
        item.set("primary_domain", primary)
        item.set("contributing_domains", [d for d in adr.get("contributors_proposed") or [] if d != primary])
        changed += [item, *(project.update(item, previous) or [])]
    previous = adr.copy()
    adr.set("realloc_applied", True)
    adr.set("primary_at_approval", before[0])
    adr.set("contributors_at_approval", before[1])
    adr.set("status", DECIDED)
    if adr.get("da_decision") not in ("Accolta", "Accolta con modifiche"):
        adr.set("da_decision", "Accolta")
    adr.set("decision_date", decision_date_of(adr, today=today))
    project.update(adr, previous)
    return list({e.uuid: e for e in changed}.values())


def decided_reallocations(model, item):
    """The reallocations decided by the Design Authority (not rejected) that name the SRS item."""
    return [a for a in model.of_kind("adr") if a.get("adr_type") in REALLOC_TYPES and a.get("status") == DECIDED
            and a.get("da_decision") != "Respinta" and item in realloc_items(model, a)]


def open_reallocations(model, item):
    """The reallocations of the SRS item still to decide."""
    return [a for a in model.of_kind("adr") if a.get("adr_type") in REALLOC_TYPES and a.get("status") in OPEN
            and a.get("da_decision") != "Respinta" and item in realloc_items(model, a)]


def reallocation_pending(model, adr):
    """The SRS items of a reallocation decided and not applied to the model (e.g. decided before ATLAS applied them,
    or setting the status by hand), unless a decided reallocation gave them the domain they have now."""
    if adr.kind != "adr" or adr.get("adr_type") not in REALLOC_TYPES or adr.get("status") != DECIDED \
            or adr.get("realloc_applied") or adr.get("da_decision") == "Respinta" \
            or reallocation_problems(model, adr):
        return []
    primary = adr.get("primary_proposed")
    return [item for item in realloc_targets(model, adr) if principal_of(model, item) != primary
            and not any(a.get("primary_proposed") == principal_of(model, item)
                        for a in decided_reallocations(model, item))]


# --- the approval of a sharing, of clauses mapped to no domain --------------------------------------------------------

def sharing_domains(model, adr):
    """The domains the clauses are shared with: those named, and those of destination of the sub-requirements."""
    return [d for d in dict.fromkeys([*(adr.get("shared_with") or []), *split_domains(adr)]) if model.get(d) is not None]


def sharing_problems(model, adr):
    """What is missing to approve the sharing (empty list: it can be approved)."""
    problems = []
    if not clauses_of(model, adr):
        problems.append("Mancano le clausole da condividere.")
    if not sharing_domains(model, adr):
        problems.append("Mancano i domini con cui condividerle (o i domini di destinazione dei sottorequisiti).")
    return problems


def derived_moves(model, adr):
    """The derived requirements of the ripartition that go to another domain: (derived, domain of destination)."""
    moves = []
    for row in adr.get("share_split") or []:
        derived = model.get(row.get("derived")) if isinstance(row, dict) and row.get("derived") else None
        if derived is not None and row.get("domain") and derived.get("domain") != row.get("domain") \
                and model.get(row.get("domain")) is not None:
            moves.append((derived, row.get("domain")))
    return moves


def sharing_preview(model, adr):
    """What approving the sharing changes: (clause, the domains it gains as contributors)."""
    result = []
    for item in clauses_of(model, adr):
        part = allocated_part(model, item)
        now = list(part.get("contributing_domains") or []) if part is not None else []
        primary = principal_of(model, item)
        result.append((item, [d for d in sharing_domains(model, adr) if d not in now and d != primary]))
    return result


def _decide(project, adr, previous, today):
    adr.set("status", DECIDED)
    if adr.get("da_decision") not in ("Accolta", "Accolta con modifiche"):
        adr.set("da_decision", "Accolta")
    adr.set("decision_date", decision_date_of(adr, today=today))
    project.update(adr, previous)


def approve_sharing(project, adr, today=None):
    """The Design Authority approves the sharing: the domains of the ADR (named, or of destination of the
    sub-requirements) become contributors of its clauses (those the clause had from its section stay); each derived
    requirement of the ripartition goes to its domain of destination; the ADR is decided. Returns the other elements
    changed."""
    model = project.model
    problems = sharing_problems(model, adr)
    if problems:
        raise ValueError(" ".join(problems))
    before, changed = shared_contributors(model, adr), []
    for item, added in sharing_preview(model, adr):
        if not added:
            continue
        part = allocated_part(model, item)
        previous = item.copy()
        item.set("contributing_domains", [*(part.get("contributing_domains") or [] if part is not None else []),
                                          *added])
        changed += [item, *(project.update(item, previous) or [])]
    for derived, domain in derived_moves(model, adr):
        previous = derived.copy()
        derived.set("domain", domain)
        changed += [derived, *(project.update(derived, previous) or [])]
    previous = adr.copy()
    adr.set("share_applied", True)
    adr.set("contributors_before_share", before)
    _decide(project, adr, previous, today)
    return list({e.uuid: e for e in changed}.values())


def approve_unmapped(project, adr, today=None):
    """The Design Authority approves that the clauses are mapped to no domain: the ADR is decided (the clauses are not
    changed: the decision is the ADR, see unmapped_by_decision)."""
    if not clauses_of(project.model, adr):
        raise ValueError("Mancano le clausole non mappate.")
    _decide(project, adr, adr.copy(), today)



# --- the title proposed for an ADR, from its type and its fields --------------------------------------------------

def _short_ids(items, most=3):
    ids = [e.get("id") or "?" for e in items]
    return ", ".join(ids[:most]) + (" …" if len(ids) > most else "")


def _items_said(items, one, many):
    """«della clausola 3.4.1.3» / «delle clausole 3.4.1.3, 3.4.1.5»: one, many are the words before the ids."""
    return f"{one if len(items) == 1 else many} {_short_ids(items)}"


def proposed_title(model, adr):
    """The title proposed for the ADR (every type has one): what it decides, from its type and the fields already
    written; the team may change it (see ElementEditor: it follows the fields until it is changed by hand)."""
    from arcadia_tool.model.schema import (ADR_LOGICAL, ADR_OTHER, ADR_WAIVER)

    kind = adr.get("adr_type")

    def element(field):
        uuid = adr.get(field)
        return model.get(uuid) if isinstance(uuid, str) and uuid else None

    def elements(field):
        value = adr.get(field) or []
        return [e for e in (model.get(u) for u in ([value] if isinstance(value, str) else value)) if e is not None]

    def ident(e):
        return (e.get("id") or model.label(e)) if e is not None else ""

    def domain(uuid):
        return ident(model.get(uuid)) if uuid else ""

    def joined(names):
        names = [n for n in names if n]
        return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} e {names[-1]}" if names else ""

    def tail(*parts):  # « da DF02 a DF05», only what is known
        return "".join(f" {word} {value}" for word, value in parts if value)

    if kind == ADR_NEW_DOMAIN:
        name = " ".join((adr.get("new_domain_name") or "").split())
        sections = elements("sections_allocated")
        return (f"Nuovo dominio «{name}»" if name else "Nuovo dominio funzionale") + \
            (f" per {_items_said(sections, 'la sezione', 'le sezioni')}" if sections else "")
    if kind == ADR_DELETE_DOMAIN:
        return f"Eliminazione di {domain(adr.get('deleted_domain'))}" if adr.get("deleted_domain") else \
            "Eliminazione di un dominio funzionale"
    if kind == ADR_MERGE_DOMAINS:
        merged = joined([domain(u) for u in adr.get("merged_domains") or []])
        name = " ".join((adr.get("proposed_domain") or "").split())
        return (f"Fusione di {merged}" if merged else "Fusione di domini funzionali") + (f" in «{name}»" if name else "")
    if kind == ADR_SPLIT_DOMAIN:
        rows = [r for r in adr.get("new_domains") or [] if isinstance(r, dict) and r.get("name")]
        return (f"Scissione di {domain(adr.get('split_domain'))}" if adr.get("split_domain") else
                "Scissione di un dominio funzionale") + (f" in {len(rows)} domini" if len(rows) > 1 else "")
    if kind == ADR_DOMAIN_SCOPE:
        change = adr.get("scope_change")
        what = {"Estensione": "Estensione dello scopo", "Riduzione": "Riduzione dello scopo",
                "Cambio totale di scopo": "Cambio totale di scopo"}.get(change, "Ridefinizione dello scopo")
        return f"{what} di {domain(adr.get('domain'))}" if adr.get("domain") else f"{what} di un dominio funzionale"
    if kind == ADR_SECTION:
        items = realloc_items(model, adr)
        scope = realloc_scope(model, adr)
        if items and scope == SCOPE_SECTION:
            what = f"della sezione {_short_ids(items)}"
        elif items:
            what = _items_said(items, "della clausola", "delle clausole")
        else:
            what = "di sezione o clausola"
        return f"Riallocazione {what}" + tail(("da", domain(item_primary(model, adr))),
                                              ("a", domain(adr.get("primary_proposed"))))
    if kind == ADR_ALLOCATION:
        items = realloc_items(model, adr)
        what = _items_said(items, "della clausola", "delle clausole") if items else "di clausole"
        return f"Richiesta {what}" + tail(("per", domain(adr.get("primary_proposed"))))
    if kind == ADR_EXCLUSION:
        items = elements("excluded_item")
        return f"Esclusione di {_short_ids(items) if items else 'sezioni o clausole'}" + \
            tail(("da", domain(adr.get("excluding_domain"))))
    if kind == ADR_SHARED:
        items = clauses_of(model, adr)
        title = _clause_title("Condivisione", items) if items else "Condivisione di clausole"
        return title + tail(("con", joined([domain(u) for u in adr.get("shared_with") or []])))
    if kind == ADR_UNMAPPED:
        items = clauses_of(model, adr)
        return _clause_title("Non mappatura", items) if items else "Non mappatura di clausole"
    if kind == ADR_DERIVED:
        items = elements("derived_items")
        what = _items_said(items, "del requisito derivato", "dei requisiti derivati") if items else \
            "di requisiti derivati"
        return f"Assegnazione {what}" + tail(("a", domain(adr.get("derived_domain_proposed"))))
    if kind == ADR_FUNCTION:
        function = element("function")
        return (f"Spostamento di {ident(function)}" if function else "Spostamento di una funzione di sistema") + \
            tail(("da", domain(function_domain(model, adr))), ("a", domain(adr.get("to_domain"))))
    if kind == ADR_OWNER:
        item = element("exchange_item")
        return f"Proprietà dell'informazione «{model.label(item)}»" if item else "Proprietà di un'informazione"
    if kind == ADR_IMPLEMENTATION:
        items = realloc_items(model, adr)
        return "Scelta lasciata all'implementazione" + (f" in {_short_ids(items)}" if items else "")
    if kind == ADR_PRODUCT_OPTION:
        function = element("function")
        choice = adr.get("product_choice")
        return "Opzione di prodotto" + (f": {ident(function)}" if function else "") + \
            (f" ({choice.lower()})" if choice else "")
    if kind == ADR_LOGICAL:
        involved = elements("la_elements")
        return (adr.get("la_operation") or "Decisione di architettura logica") + \
            (f": {joined([ident(e) for e in involved[:3]])}" if involved else "")
    if kind == ADR_WAIVER:
        rule = " ".join((adr.get("rule") or "").split())
        return f"Deroga a {rule}" if rule else "Deroga a una regola della metodologia"
    if kind == ADR_OTHER:
        items = elements("srs_items")
        concerned = [ident(e) for e in elements("concerns")]
        return "Decisione trasversale" + (f" su {_short_ids(items)}" if items else
                                          f" su {joined(concerned)}" if concerned else "")
    return kind or "Nuova decisione architetturale"


# --- the assignment of derived requirements (SA-4) to a domain --------------------------------------------------

def derived_items(model, adr):
    """The derived requirements an ADR of assignment is about."""
    return [e for e in (model.get(u) for u in adr.get("derived_items") or []) if e is not None]


def derived_current_domain(model, derived):
    """The domain a derived requirement belongs to now, for an ADR of assignment: the principal domain of the SRS item
    it is derived from (of the section containing it, or its own); without a parent item, its own domain."""
    parent = model.get(derived.get("parent")) if derived.get("parent") else None
    return (principal_of(model, parent) if parent is not None else None) or derived.get("domain")


def derived_domains_current(model, adr):
    """The domains the derived requirements belong to now (each once, see derived_current_domain); once the
    assignment is applied, those they had then: the ADR does not change."""
    if adr.get("derived_applied"):
        return list(adr.get("derived_domains_before") or [])
    return list(dict.fromkeys(d for d in (derived_current_domain(model, e) for e in derived_items(model, adr)) if d))


COMPUTED["derived_domains_current"] = derived_domains_current


def derived_problems(model, adr):
    """What is missing to approve the assignment (empty list: it can be approved)."""
    problems = []
    if not derived_items(model, adr):
        problems.append("Mancano i requisiti derivati da assegnare.")
    domain = adr.get("derived_domain_proposed")
    if not domain or model.get(domain) is None:
        problems.append("Manca il dominio proposto.")
    return problems


def derived_preview(model, adr):
    """What approving the assignment changes: [(derived requirement, the domain it belongs to now or None, see
    derived_current_domain)], those already assigned to the domain proposed left out."""
    target = adr.get("derived_domain_proposed")
    return [(d, derived_current_domain(model, d)) for d in derived_items(model, adr) if d.get("domain") != target]


def approve_derived(project, adr, today=None):
    """The Design Authority approves the assignment: each derived requirement passes to the proposed domain, which no
    longer follows its system function (see model.links: domain_adr); the ADR is decided. Returns the requirements
    changed."""
    model = project.model
    problems = derived_problems(model, adr)
    if problems:
        raise ValueError(" ".join(problems))
    target, before, changed = adr.get("derived_domain_proposed"), derived_domains_current(model, adr), []
    for derived in derived_items(model, adr):
        previous = derived.copy()
        derived.set("domain", target)
        derived.set("domain_adr", adr.uuid)
        changed += [derived, *(project.update(derived, previous) or [])]
    previous = adr.copy()
    adr.set("derived_applied", True)
    adr.set("derived_domains_before", before)
    _decide(project, adr, previous, today)
    return list({e.uuid: e for e in changed}.values())


def adrs_about(model, item):
    """The ADR naming an SRS item among those they are about (see adr_srs_items: to reallocate, excluded, shared…),
    whatever their status, by their ID."""
    from arcadia_tool.model.element import natural_key

    return sorted((a for a in model.of_kind("adr") if item in adr_srs_items(model, a)),
                  key=lambda a: natural_key(a.get("id") or ""))


def derived_owner_domain(model, derived):
    """The domain a derived requirement (SA-4) belongs to, as the domain sheets list it: the one assigned by an approved
    ADR of assignment (domain_adr); otherwise that of the SRS item it is derived from (see derived_current_domain)."""
    if derived.get("domain_adr") and model.get(derived.get("domain_adr")) is not None and derived.get("domain"):
        return derived.get("domain")
    return derived_current_domain(model, derived)
