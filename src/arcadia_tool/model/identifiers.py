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
}

MANUAL_ID_KINDS = {"requirement"}
NO_ID_KINDS = {"trace_record", "chain_realization"}


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
    """Next free identifier for the element; `reserved` holds ids of published elements (never reused)."""
    r = rule(element, model)
    if r is None:
        return None
    taken = _taken(model, reserved, element)
    if r[0] == "number":
        _, prefix, width = r
        used = [int(i[len(prefix):]) for i in taken if i.startswith(prefix) and i[len(prefix):].isdigit()]
        return f"{prefix}{max(used, default=0) + 1:0{width}d}"
    _, prefix, name = r
    candidate, n = f"{prefix}{name}", 2
    while candidate in taken:
        candidate, n = f"{prefix}{name}-{n}", n + 1
    return candidate


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
