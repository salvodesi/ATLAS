"""The Design Authority: the one team that integrates the branches of the model into main, and who belongs to it.

A user belongs to the Design Authority when their name and surname are among the members of the DA team. For now
the comparison is on the name (case, accents, spaces and order of name and surname do not matter); a stable
identifier of the account may be used later.
"""
import unicodedata

DA_FIELD = "design_authority"


def da_teams(model):
    """Teams marked as Design Authority (one at most in a coherent model, see check EPBS-05)."""
    return [t for t in model.of_kind("team") if t.get(DA_FIELD)]


def design_authority(model):
    teams = da_teams(model)
    return teams[0] if teams else None


def person_key(name):
    """Name and surname compared without case, accents, extra spaces or order: «De Simone  Salvatore» is the same
    person as «salvatore de simone»."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return tuple(sorted(text.casefold().split()))


def is_member(team, full_name):
    key = person_key(full_name)
    return bool(key) and any(person_key(m) == key for m in team.get("members") or [])


def is_da_member(model, full_name):
    """The user (their name and surname) is among the members of the Design Authority team."""
    team = design_authority(model)
    return team is not None and is_member(team, full_name)
