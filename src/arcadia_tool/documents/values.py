"""The values of the model as texts of a sheet: references by ID, lists, tables, the domain of an end of an
exchange."""
from arcadia_tool.model.element import natural_key
from arcadia_tool.model.schema import BOOL, ENUM, MAP, MULTIENUM, REF, REFS, STRLIST, TABLE, enum_option


def short(model, uuid):
    """An element by its ID (DF07, SF-DF07-03, 3.14.4.2), else by its label; "" if it does not exist."""
    element = model.get(uuid) if uuid else None
    if element is None:
        return ""
    return element.get("id") or model.label(element)


def shorts(model, uuids):
    return ", ".join(t for t in (short(model, u) for u in uuids or []) if t)


def label(model, uuid):
    element = model.get(uuid) if uuid else None
    return model.label(element) if element is not None else ""


def plain(text):
    """A text of a sheet (Markdown): without the marks of bold and italics."""
    return (text or "").replace("**", "").replace("__", "").strip()


def text_of(model, element, field, computed=None):
    """The value of a field as it is written in a cell. computed: the value of a computed field."""
    value = computed if field.computed else element.get(field.name)
    if value in (None, "", [], {}):
        return ""
    if field.type == REF:
        return label(model, value)
    if field.type == REFS:
        if field.ref_kinds == ("requirement",):
            return shorts(model, value)
        return "; ".join(t for t in (label(model, u) for u in value) if t)
    if field.type == ENUM:
        return enum_option(field, value)
    if field.type in (MULTIENUM, STRLIST):
        return ", ".join(map(str, value))
    if field.type == BOOL:
        return "Sì" if value else "No"
    if field.type == MAP:
        return ", ".join(f"{k}: {v}" for k, v in value.items() if v)
    if field.type == TABLE:
        return "\n".join(" · ".join(str(row.get(c.name) or "") for c in field.columns) for row in value)
    return plain(str(value))


def table_rows(model, element, field):
    """The rows of a table field as texts, one per column."""
    rows = []
    for row in element.get(field.name) or []:
        cells = []
        for column in field.columns:
            value = row.get(column.name)
            if column.type == REF:
                cells.append(label(model, value))
            elif column.choices:  # an SRS item, a domain written in the ADR
                cells.append(short(model, value) or str(value or ""))
            else:
                cells.append(str(value or ""))
        rows.append(cells)
    return rows


def domain_of(model, uuid):
    """The domain of an end of an exchange: of the system function, of the one a logical function refines; None
    for an external actor."""
    element, seen = (model.get(uuid) if uuid else None), set()
    while element is not None and element.uuid not in seen:
        seen.add(element.uuid)
        if element.kind == "system_function":
            return model.get(element.get("domain")) if element.get("domain") else None
        if element.kind == "logical_function":
            element = model.get(element.get("refines") or element.get("parent") or "")
            continue
        return None
    return None


def end_text(model, uuid):
    """An end of an exchange: the function and its domain («Supervisionare lo standstill (DF06)»)."""
    element = model.get(uuid) if uuid else None
    if element is None:
        return ""
    domain = domain_of(model, uuid)
    name = element.get("name") or model.label(element)
    return f"{name} ({domain.get('id')})" if domain is not None and domain.get("id") else name


def by_id(elements):
    return sorted(elements, key=lambda e: natural_key(e.get("id") or e.get("name") or e.get("title") or ""))
