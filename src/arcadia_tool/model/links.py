"""Fields of different sheets kept in step: when a sheet is saved, the other sheets that record the same relation,
or that take a value from it, are updated (and reported, so that their open tabs show it).

Same relation recorded in two sheets, kept in step both ways:
- domain «Team assegnatario» ↔ team «Domini» (a domain has one team);
- derived requirement «Voce madre» ↔ SA-3 record of that item, «Derivati / dizionario».

Values a sheet takes from another one (the methodology fixes them; the checks report them as errors otherwise):
- the functions of an SA-3 record trace its item (unless they already do, directly or through its section);
- derived requirement «Dominio» ← domain of its logical function (SA4-07);
- functional exchange «Natura» ← nature of its exchange item (SA5-07);
- step of a realization in LA (LA-4) «Componente» ← allocation of its logical function (LA4-05).

The relations recorded once (e.g. the functions of a domain, the derived requirements of a logical function) are
only read from the other sheet and need nothing here.
"""


class _Changed:
    def __init__(self, element):
        self.origin = element
        self.elements = {}

    def add(self, element):
        if element.uuid != self.origin.uuid:
            self.elements[element.uuid] = element


def _set(element, field, value, changed):
    current = element.values.get(field)
    if (current or None) != (value or None):
        element.set(field, value)
        changed.add(element)
        return True
    return False


def keep_in_step(model, element, previous=None):
    """Update the sheets linked to `element` (just changed; previous: the element before the change, None if
    unknown or new). Returns the other elements changed.

    A relation recorded in both sheets follows the change: what was removed from a list (known from previous) is
    removed on the other side too; what the other side records but the list does not have is added to it."""
    changed = _Changed(element)
    for handler in _HANDLERS.get(element.kind, ()):
        handler(model, element, previous, changed)
    return list(changed.elements.values())


def _removed(element, previous, field):
    if previous is None:
        return set()
    return set(previous.values.get(field) or []) - set(element.values.get(field) or [])


# --- domain ↔ team ------------------------------------------------------------------------------------------

def _team_of_domain(model, domain, previous, changed):
    """The team assigned in the domain sheet lists the domain; the other teams no longer do."""
    for team in model.of_kind("team"):
        domains = list(team.get("domains") or [])
        if team.uuid == domain.get("team") and domain.uuid not in domains:
            _set(team, "domains", domains + [domain.uuid], changed)
        elif team.uuid != domain.get("team") and domain.uuid in domains:
            _set(team, "domains", [d for d in domains if d != domain.uuid], changed)


def _domains_of_team(model, team, previous, changed):
    """The domains listed in the team sheet have it as their team (taken from the team they had, which no longer
    lists them); the domains removed from the list no longer have a team; a domain that has this team but is not
    listed (never added here) is added to the list."""
    removed = _removed(team, previous, "domains")
    listed = list(team.get("domains") or [])
    for domain in model.of_kind("domain"):
        if domain.uuid in listed and domain.get("team") != team.uuid:
            _set(domain, "team", team.uuid, changed)
            for other in model.of_kind("team"):
                if other.uuid != team.uuid and domain.uuid in (other.get("domains") or []):
                    _set(other, "domains", [d for d in other.get("domains") if d != domain.uuid], changed)
        elif domain.uuid not in listed and domain.get("team") == team.uuid:
            if domain.uuid in removed:
                _set(domain, "team", None, changed)
            else:
                listed.append(domain.uuid)
    if listed != list(team.get("domains") or []):
        team.set("domains", listed)  # the sheet being saved: not reported as another one


# --- derived requirement ↔ SA-3 record --------------------------------------------------------------------

def _is_derived(model, uuid):
    e = model.get(uuid)
    return e is not None and e.kind == "derived_requirement"


def _derived_of_record(model, record, previous, changed):
    """The derived requirements listed in the record have its item as «Voce madre» (and leave the record they
    were listed in); those removed from the list no longer have a «Voce madre»; the other derived requirements of
    the item (never listed here) are added to the list."""
    item = record.get("requirement")
    removed = _removed(record, previous, "exchange_items")
    items = list(record.get("exchange_items") or [])
    for uuid in [u for u in items if _is_derived(model, u)]:
        derived = model.get(uuid)
        if item and derived.get("parent") != item:
            _set(derived, "parent", item, changed)
        for other in model.of_kind("trace_record"):
            if other.uuid != record.uuid and uuid in (other.get("exchange_items") or []) \
                    and other.get("requirement") != item:
                _set(other, "exchange_items", [u for u in other.get("exchange_items") if u != uuid], changed)
    if item:
        for derived in model.of_kind("derived_requirement"):
            if derived.get("parent") == item and derived.uuid not in items:
                if derived.uuid in removed:
                    _set(derived, "parent", None, changed)
                else:
                    items.append(derived.uuid)
    if items != list(record.get("exchange_items") or []):
        record.set("exchange_items", items)  # the sheet being saved


def _record_of_derived(model, derived, previous, changed):
    """The SA-3 record of the «Voce madre» lists the derived requirement; the other records no longer do."""
    for record in model.of_kind("trace_record"):
        items = list(record.get("exchange_items") or [])
        if record.get("requirement") == derived.get("parent") and derived.get("parent"):
            if derived.uuid not in items:
                _set(record, "exchange_items", items + [derived.uuid], changed)
        elif derived.uuid in items:
            _set(record, "exchange_items", [u for u in items if u != derived.uuid], changed)


# --- SA-3 record → functions ----------------------------------------------------------------------------

def _ancestors(model, item):
    result, seen, parent = [], {item.uuid}, item.get("parent")
    while parent and parent not in seen and model.get(parent) is not None:
        result.append(parent)
        seen.add(parent)
        parent = model.get(parent).get("parent")
    return result


TRACED_FIELD = {"system_function": "sections", "logical_function": "detail_requirements"}


def _functions_trace_record_item(model, record, previous, changed):
    """The functions of the record trace its item: added to their SRS items unless they already trace it,
    directly or through one of its parents."""
    item = model.get(record.get("requirement"))
    if item is None:
        return
    for uuid in [record.get("primary_function"), *(record.get("secondary_functions") or [])]:
        function = model.get(uuid)
        if function is None or function.kind not in TRACED_FIELD:
            continue
        field = TRACED_FIELD[function.kind]
        traced = list(function.get(field) or [])
        if item.uuid not in traced and not any(a in traced for a in _ancestors(model, item)):
            _set(function, field, traced + [item.uuid], changed)


# --- values taken from another sheet -------------------------------------------------------------------

def _domain_of_function(model, function):
    seen = set()
    while function is not None and function.uuid not in seen:
        seen.add(function.uuid)
        if function.kind == "system_function":
            return function.get("domain")
        refined = model.get(function.get("refines"))
        function = refined if refined is not None else model.get(function.get("parent"))
    return None


def _domain_of_derived(model, derived, previous, changed):
    """«Dominio» of a derived requirement: the one of its logical function (when that is known)."""
    domain = _domain_of_function(model, model.get(derived.get("function")))
    if domain:
        _set(derived, "domain", domain, changed)


def _derived_of_logical_function(model, function, previous, changed, seen=None):
    seen = seen if seen is not None else set()
    if function.uuid in seen:
        return
    seen.add(function.uuid)
    for derived in model.of_kind("derived_requirement"):
        if derived.get("function") == function.uuid:
            _domain_of_derived(model, derived, None, changed)
    for child in model.of_kind("logical_function"):  # the domain of a child follows its parent
        if child.get("parent") == function.uuid and not child.get("refines"):
            _derived_of_logical_function(model, child, None, changed, seen)


def _derived_of_system_function(model, function, previous, changed):
    for lf in model.of_kind("logical_function"):
        if lf.get("refines") == function.uuid:
            _derived_of_logical_function(model, lf, None, changed)


def _nature_of_exchange(model, exchange, previous, changed):
    """«Natura» of a functional exchange: the one of its exchange item."""
    item = model.get(exchange.get("exchange_item"))
    if item is not None and item.get("nature"):
        _set(exchange, "nature", item.get("nature"), changed)


def _exchanges_of_item(model, item, previous, changed):
    for exchange in model.of_kind("functional_exchange"):
        if exchange.get("exchange_item") == item.uuid:
            _nature_of_exchange(model, exchange, None, changed)


def _components_of_realization(model, realization, previous, changed):
    """«Componente» of each step of a realization in LA: the allocation of its logical function."""
    steps = [dict(row) for row in realization.get("steps") or []]
    updated = False
    for row in steps:
        function = model.get(row.get("logical_function"))
        component = function.get("component") if function is not None else None
        if component and row.get("component") != component:
            row["component"] = component
            updated = True
    if updated:
        _set(realization, "steps", steps, changed)


def _realizations_of_logical_function(model, function, previous, changed):
    for realization in model.of_kind("chain_realization"):
        if any(row.get("logical_function") == function.uuid for row in realization.get("steps") or []):
            _components_of_realization(model, realization, None, changed)


_HANDLERS = {
    "domain": (_team_of_domain,),
    "team": (_domains_of_team,),
    "trace_record": (_derived_of_record, _functions_trace_record_item),
    "derived_requirement": (_record_of_derived, _domain_of_derived),
    "logical_function": (_derived_of_logical_function, _realizations_of_logical_function),
    "system_function": (_derived_of_system_function,),
    "exchange_item": (_exchanges_of_item,),
    "functional_exchange": (_nature_of_exchange,),
    "chain_realization": (_components_of_realization,),
}
