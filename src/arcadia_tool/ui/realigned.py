"""The identifiers changed by the deletion of a domain (see model.identifiers.realign_domains), as shown to the user."""

ORDER = {"domain": 0, "system_function": 1, "logical_function": 2, "functional_exchange": 3}


def realigned_lines(changes):
    """«DF04 → DF03», one per line, the domains first. changes: [(kind, old, new)]."""
    rows = sorted(changes, key=lambda c: (ORDER.get(c[0], 9), c[1] or ""))
    return "\n".join(f"{old} → {new or '(senza ID finché non ha un dominio)'}" for _kind, old, new in rows)


def with_id(element, ident):
    """A copy of the element with another identifier (e.g. the one it had before being renumbered)."""
    copy = element.copy()
    copy.set("id", ident)
    return copy
