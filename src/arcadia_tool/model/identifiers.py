"""Automatic identifiers, following the conventions of the ARCADIA templates.

DFnn · SF-DFnn-mm · LF-DFnn-mm-kk · FE-DFaa-DFbb-nn · EI-Nome · FC-Nome · LC-nn · CE-LCaa-LCbb-nn
<voce>-Dn · Tn · ADR-nnn · CQ-nn · OE-nn

An identifier is assigned once, as soon as the context it depends on is known (e.g. the domain of a
system function), and is not changed afterwards unless the user explicitly asks to renumber.
SRS items keep the clause number of the specification and are not numbered by the tool.
"""
import re
import unicodedata

# Fields that must be filled before the identifier can be computed.
REQUIRED_CONTEXT = {
    "system_function": ("domain",),
    "logical_function": ("refines",),
    "functional_exchange": ("source", "target"),
    "component_exchange": ("source", "target"),
    "derived_requirement": ("parent",),
    "exchange_item": ("name",),
    "functional_chain": ("title",),
}

# Kinds whose creation asks first for the element they belong to (field, label of the question).
CREATION_CONTEXT = {
    "system_function": "domain",
    "logical_function": "refines",
    "derived_requirement": "parent",
    "clarification": "recipient",  # the Design Authority or a team
}

MANUAL_ID_KINDS = {"requirement"}
NO_ID_KINDS = {"trace_record", "chain_realization", "message", "reading", "analysis"}


def is_automatic(kind):
    return kind not in MANUAL_ID_KINDS and kind not in NO_ID_KINDS


def camel(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", ascii_text))


def _ref_id(model, element, field):
    target = model.get(element.get(field))
    return target.get("id") if target else None


def _domain_code(model, element):
    """Domain (or external actor) an exchange end belongs to, as used in FE identifiers."""
    if element is None:
        return None
    if element.kind == "external_actor":
        return element.get("id")
    if element.kind == "system_function":
        return _ref_id(model, element, "domain")
    if element.kind == "logical_function":
        sf = model.get(element.get("refines"))
        return _ref_id(model, sf, "domain") if sf else None
    return None


def _numbered(prefix, width):
    return ("number", prefix, width)


def _named(prefix, text):
    return ("name", prefix, camel(text or ""))


def rule(element, model):
    """How the identifier of this element is built in its current context, or None if not yet possible."""
    k = element.kind
    if k == "domain":
        return _numbered("DF", 2)
    if k == "system_function":
        dom = _ref_id(model, element, "domain")
        return _numbered(f"SF-{dom}-", 2) if dom else None
    if k == "logical_function":
        sf = _ref_id(model, element, "refines")
        return _numbered(f"LF-{sf[3:]}-", 2) if sf and sf.startswith("SF-") else None
    if k == "functional_exchange":
        a = _domain_code(model, model.get(element.get("source")))
        b = _domain_code(model, model.get(element.get("target")))
        return _numbered(f"FE-{a}-{b}-", 2) if a and b else None
    if k == "component_exchange":
        a, b = _ref_id(model, element, "source"), _ref_id(model, element, "target")
        return _numbered(f"CE-{a.replace('-', '')}-{b.replace('-', '')}-", 2) if a and b else None
    if k == "derived_requirement":
        parent = _ref_id(model, element, "parent")
        return _numbered(f"{parent}-D", 1) if parent else None
    if k == "exchange_item":
        return _named("EI-", element.get("name")) if camel(element.get("name") or "") else None
    if k == "functional_chain":
        return _named("FC-", element.get("title")) if camel(element.get("title") or "") else None
    if k == "logical_component":
        return _numbered("LC-", 2)
    if k == "team":
        return _numbered("T", 1)
    if k == "adr":
        return _numbered("ADR-", 3)
    if k == "clarification":
        return _numbered("CQ-", 2)
    if k == "external_actor":
        return _numbered("OE-", 2)
    return None


def _taken(model, reserved, element):
    taken = {e.get("id") for e in model if e.uuid != element.uuid and e.get("id")}
    return taken | set(reserved)


def compute_id(element, model, reserved=()):
    """First free identifier for the element: the lowest number not used by the other elements of the model (a
    number left free by a deleted element is given again); `reserved`: identifiers not to give anyway."""
    r = rule(element, model)
    if r is None:
        return None
    taken = _taken(model, reserved, element)
    if r[0] == "number":
        _, prefix, width = r
        used = {int(i[len(prefix):]) for i in taken if i.startswith(prefix) and i[len(prefix):].isdigit()}
        n = next(n for n in range(1, len(used) + 2) if n not in used)
        return f"{prefix}{n:0{width}d}"
    _, prefix, name = r
    candidate, n = f"{prefix}{name}", 2
    while candidate in taken:
        candidate, n = f"{prefix}{name}-{n}", n + 1
    return candidate


DOMAIN_CODE = re.compile(r"\bDF\d+\b")
# The kinds whose identifier holds the code of a domain, in the order they are realigned (a logical function after
# its system function).
DOMAIN_DEPENDENT = ("system_function", "logical_function", "functional_exchange")


def realign_domains(model, deleted_code):
    """A domain deleted (its code, e.g. «DF03»): the domains after it move down so that the numbering has no gap
    (DF04 → DF03, DF05 → DF04…), and the identifiers holding their codes follow, each keeping its own number
    (SF-DF04-02 → SF-DF03-02, LF-DF04-02-01 → LF-DF03-02-01, FE-DF05-DF04-01 → FE-DF04-DF03-01). What still had the code
    of the deleted domain (passed to another domain, or left without one) gets a new identifier in its context, or
    none until it has one. The model is changed; returns [(element, old id, new id)], new id None if removed."""
    domains = sorted((d for d in model.of_kind("domain") if re.fullmatch(r"DF\d+", d.get("id") or "")),
                     key=lambda d: int(d.get("id")[2:]))
    mapping = {}
    for n, domain in enumerate(domains, start=1):
        code = f"DF{n:02d}"
        if domain.get("id") != code:
            mapping[domain.get("id")] = code
    changes = [(d, d.get("id"), mapping[d.get("id")]) for d in domains if d.get("id") in mapping]
    dependent = [e for kind in DOMAIN_DEPENDENT for e in model.of_kind(kind) if e.get("id")]
    stale = [e for e in dependent if deleted_code in DOMAIN_CODE.findall(e.get("id"))]
    stale_uuids = {e.uuid for e in stale}
    for e in dependent:
        if e.uuid in stale_uuids:
            continue
        new = DOMAIN_CODE.sub(lambda m: mapping.get(m.group(0), m.group(0)), e.get("id"))
        if new != e.get("id"):
            changes.append((e, e.get("id"), new))
    for element, _old, new in changes:  # all together: DF04 → DF03 while DF05 → DF04, without clashes in between
        element.set("id", new)
    for e in stale:  # in the order of DOMAIN_DEPENDENT: a function before what depends on it
        old = e.get("id")
        e.set("id", None)
        new = compute_id(e, model)
        e.set("id", new)
        changes.append((e, old, new))
    return changes


def matches_context(element, model):
    """True if the current identifier is consistent with the element's context (no renumbering needed)."""
    r = rule(element, model)
    ident = element.get("id")
    if r is None or not ident:
        return False
    if r[0] == "number":
        return ident.startswith(r[1]) and ident[len(r[1]):].isdigit()
    return ident == f"{r[1]}{r[2]}" or ident.startswith(f"{r[1]}{r[2]}-")


def missing_context(element, model):
    """Labels of the fields still needed to compute the identifier."""
    schema = element.schema
    return [schema.field(f).label for f in REQUIRED_CONTEXT.get(element.kind, ())
            if not element.get(f) or (schema.field(f).type == "ref" and model.get(element.get(f)) is None)]
