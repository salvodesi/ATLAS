"""What a sheet must have to be saved: the mandatory fields of a functional domain and of a system function; at least a
field filled in the sheets of the System Analysis and in the ADR."""
from arcadia_tool.model.element import is_empty
from arcadia_tool.model.identifiers import CREATION_CONTEXT

EMPTY_SHEET = "La scheda è vuota: riempi almeno un campo prima di salvarla."
# Given by the tool, or by where the sheet is created: not what the user has written in it.
NOT_WRITTEN = ("id", "status", "adr_type", "proposer", "proposer_member", "concerns", "decision_date",
               "realloc_applied", "primary_at_approval", "contributors_at_approval", "realloc_before", "share_applied",
               "contributors_before_share", "deleted_domain_label")


def _empty(element, name):
    return not (element.get(name) or "").strip()


def missing_fields(model, element):
    """What is missing to complete and save the sheet (element: as it is being edited), in the order of the sheet."""
    missing = []
    if element.kind == "domain":
        missing = [element.schema.field(n).label for n in ("name", "mission") if _empty(element, n)]
        if not any(element.uuid in (r.get("primary_domain"), *(r.get("contributing_domains") or []))
                   for r in model.of_kind("requirement")):
            missing.append("Almeno una sezione SRS mappata")
    elif element.kind == "system_function":
        missing = [element.schema.field(n).label for n in ("name", "description") if _empty(element, n)]
        if not element.get("sections"):
            missing.append("Clausole SRS mappate")
    return missing


def must_not_be_empty(kind):
    """The sheets of the System Analysis (also SA-3 and SA-4, under «Requisiti») and the ADR."""
    return kind.name == "adr" or kind.group == "System Analysis" or (kind.template or "").startswith("SA-")


def is_blank(element, model=None):
    """Nothing written in the sheet: only what the tool gives (the title of an ADR as proposed by the tool too)."""
    context = CREATION_CONTEXT.get(element.kind)

    def written(f):
        value = element.values.get(f.name)
        if is_empty(value):
            return False
        if element.kind == "adr" and f.name == "title":
            from arcadia_tool.model.adr import proposed_title
            from arcadia_tool.model.element import Model
            return value != proposed_title(model if model is not None else Model(), element)
        return True
    return not any(written(f) for f in element.schema.fields
                   if f.stored and not f.computed and not f.by_tool and f.name not in NOT_WRITTEN and f.name != context)


def save_refusal(model, element, untouched=False):
    """Why the sheet may not be saved, to say to the user, or None. untouched: created and left as it was: what it has
    comes from where it was created."""
    missing = missing_fields(model, element)
    if missing:
        return "Per completare e salvare la scheda mancano:\n\n" + "\n".join(f"• {name}" for name in missing)
    return EMPTY_SHEET if must_not_be_empty(element.schema) and (untouched or is_blank(element, model)) else None
