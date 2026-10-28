"""The members of the teams, the Design Authority (the one team that integrates the branches of the model into
main), and who among the users of this PC belongs to them.

Every user has one ID, generated when their local account is created (shown in Utente › Modifica account). A
member of the Design Authority adds the users to the teams, each with that ID, which the person tells them: from
then on the account is recognized as that member of the project, also when the name is written differently.

The members were a list of names in the first versions: they are read as members without ID, recognized by name
and surname (case, accents, spaces and order do not matter) until the DA writes their ID.
"""
import unicodedata

DA_FIELD = "design_authority"
MEMBERS = "members"
ACCOUNT = "account"  # the ID of the local account of a member


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


# --- members ---------------------------------------------------------------------------------------------------

def member_rows(team):
    """The members of a team as rows {name, email, role, account} (a name of the first versions: a row with the
    name only)."""
    rows = []
    for m in team.get(MEMBERS) or []:
        if isinstance(m, dict):
            rows.append(m)
        elif str(m).strip():
            rows.append({"name": str(m).strip()})
    return rows


def member_names(team):
    return [r.get("name") for r in member_rows(team) if r.get("name")]


def normalize_account_id(text):
    """The ID of an account as stored (32 hexadecimal digits, without dashes, lower case), or "" if it is not one."""
    value = "".join(c for c in (text or "").strip().lower() if c not in "-{} ")
    return value if len(value) == 32 and all(c in "0123456789abcdef" for c in value) else ""


def _name_of(user):
    return user if isinstance(user, str) else getattr(user, "full_name", "")


def member_of(team, user):
    """The row of the team for the user (an account, or just a name and surname), or None: by the ID of the
    account; a member whose ID is not written yet (e.g. of the first versions), by name and surname."""
    rows = member_rows(team)
    account = normalize_account_id(getattr(user, "id", ""))
    if account:
        found = next((r for r in rows if normalize_account_id(r.get(ACCOUNT)) == account), None)
        if found is not None:
            return found
    key = person_key(_name_of(user))
    if not key:
        return None
    return next((r for r in rows if not r.get(ACCOUNT) and person_key(r.get("name")) == key), None)


def is_member(team, user):
    return member_of(team, user) is not None


def memberships(model, user):
    """(team, row) of every team the user belongs to."""
    return [(t, row) for t in model.of_kind("team") for row in [member_of(t, user)] if row is not None]


def is_da_member(model, user):
    """The user (an account, or a name and surname) is a member of the Design Authority team."""
    team = design_authority(model)
    return team is not None and is_member(team, user)


# --- who may change the teams ------------------------------------------------------------------------------------

DA_ONLY_KINDS = ("team",)  # sheets that only the members of the Design Authority create, change and delete
DA_ONLY_FIELDS = {"domain": ("team",)}  # fields of other sheets changed only by them (who works on a domain)


def edit_denied(model, user, kind, field=None):
    """Why the user may not create, change or delete a sheet of this kind (with field: change that field of it),
    or None if they may. The teams, and the team assigned to a domain, are changed only by the members of the
    Design Authority; while no DA team has members yet, by anyone (someone has to set it up)."""
    if kind not in DA_ONLY_KINDS and (field is None or field not in DA_ONLY_FIELDS.get(kind, ())):
        return None
    da = design_authority(model)
    if da is None or not member_rows(da):
        return None
    if user is not None and is_member(da, user):
        return None
    name = " ".join(str(v) for v in (da.get("id"), da.get("name")) if v)
    what = ("assegnare i domini ai team" if kind not in DA_ONLY_KINDS else
            "creare, modificare ed eliminare i team")
    return (f"Solo i membri della Design Authority ({name}) possono {what}. Se ne fai parte, comunica alla DA "
            "l'ID del tuo account (Utente › Modifica account), che lo indica nella tua riga del team.")


# --- who may open the project ------------------------------------------------------------------------------------

def member_accounts(model):
    """The IDs of the accounts written in the teams of the project."""
    return {a for t in model.of_kind("team") for r in member_rows(t) for a in [normalize_account_id(r.get(ACCOUNT))]
            if a}


def access_denied(model, user):
    """Why the user may not open the project, or None if they may: once the Design Authority has written the ID of
    an account in a team, only the users whose account ID is in a team open it. Before (a new project, or one of
    the first versions), anyone opens it, to set up the teams."""
    accounts = member_accounts(model)
    if not accounts:
        return None
    account = normalize_account_id(getattr(user, "id", "")) if user is not None else ""
    if account and account in accounts:
        return None
    da = design_authority(model)
    who = f"alla Design Authority ({' '.join(str(v) for v in (da.get('id'), da.get('name')) if v)})" if da else \
        "alla Design Authority del progetto"
    return (f"Il tuo account non è tra i membri dei team del progetto. Chiedi {who} di aggiungerti a un team con "
            "l'ID del tuo account, poi riapri il progetto.")


def locks_out(model, team, user):
    """The team (changed, not yet in the model) would leave the user outside the project: their ID would no longer
    be among the IDs of the accounts in the teams, while others are (e.g. the DA writing the IDs of the others
    before their own), or it would be removed from the teams (e.g. by mistake, by the DA themselves: removing the
    last ID would also open the project to anyone)."""
    if user is None:
        return False
    mine = normalize_account_id(getattr(user, "id", ""))
    accounts = {a for t in model.of_kind("team") if t.uuid != team.uuid for r in member_rows(t)
                for a in [normalize_account_id(r.get(ACCOUNT))] if a}
    accounts |= {a for r in member_rows(team) for a in [normalize_account_id(r.get(ACCOUNT))] if a}
    if mine and mine in member_accounts(model) and mine not in accounts:
        return True
    return bool(accounts) and mine not in accounts
