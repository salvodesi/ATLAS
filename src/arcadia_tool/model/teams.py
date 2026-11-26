"""The members of the teams, the Design Authority (the one team that integrates the branches of the model into
main), and who among the users of this PC belongs to them.

Every user has one ID, generated when their local account is created (shown in Utente › Modifica account). A
member of the Design Authority adds the users to the teams, each with that ID, which the person tells them: from
then on the account is recognized as that member of the project, also when the name is written differently.

The members were a list of names in the first versions: they are read as members without ID, recognized by name
and surname (case, accents, spaces and order do not matter) until the DA writes their ID.
"""
import re
import unicodedata

DA_FIELD = "design_authority"
MEMBERS = "members"
ACCOUNT = "account"  # the ID of the local account of a member: one, or a list (one per PC the person works on)
# A member who may send to the main branch (publish, send, integrate on it): ticked in the sheet of the team. While no
# member of any team is ticked, the members of the Design Authority may (see main_denied).
MAIN_PUSH = "main_push"


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


def account_ids(row):
    """The IDs of the accounts of a member (one per PC the person works on), valid and without repetitions."""
    value = (row or {}).get(ACCOUNT)
    texts = value if isinstance(value, (list, tuple)) else re.split(r"[\s,;]+", str(value or ""))
    return list(dict.fromkeys(a for a in (normalize_account_id(t) for t in texts if t) if a))


def accounts_value(ids):
    """The IDs as kept in the row of a member: one as a text (as written by the first versions), more as a list."""
    ids = list(dict.fromkeys(ids))
    return ids[0] if len(ids) == 1 else ids if ids else ""


def _name_of(user):
    return user if isinstance(user, str) else getattr(user, "full_name", "")


def member_of(team, user):
    """The row of the team for the user (an account, or just a name and surname), or None: by the ID of the
    account; a member whose ID is not written yet (e.g. of the first versions), by name and surname."""
    return row_of(member_rows(team), user)


def row_of(rows, user):
    """The row (of the members of a team, of the referents of a domain) of the user, or None (see member_of)."""
    account = normalize_account_id(getattr(user, "id", ""))
    if account:
        found = next((r for r in rows if account in account_ids(r)), None)
        if found is not None:
            return found
    key = person_key(_name_of(user))
    if not key:
        return None
    return next((r for r in rows if not account_ids(r) and person_key(r.get("name")) == key), None)


def default_referent(model, domain, previous=None):
    """A domain whose team is assigned (or changed), or without a referent: its referent, if not a member of that
    team, becomes the referent of the team (then chosen in the sheet among its members); no team, no referent."""
    team = model.get(domain.get("team")) if domain.get("team") else None
    if previous is not None and previous.get("team") == domain.get("team") and domain.get("referent"):
        return
    names = {person_key(n) for n in member_names(team)} if team is not None else set()
    if domain.get("referent") and person_key(domain.get("referent")) in names:
        return
    domain.set("referent", (team.get("referent") or None) if team is not None else None)


def referent_domains(model, user):
    """The uuids of the functional domains the user is the referent of (the member of the team assigned chosen in the
    sheet of the domain: recognized as a member of that team, by the ID of the account or by name)."""
    if user is None:
        return set()
    found = set()
    for d in model.of_kind("domain"):
        name = d.get("referent")
        if not name:
            continue
        team = model.get(d.get("team")) if d.get("team") else None
        rows = [r for r in member_rows(team) if person_key(r.get("name")) == person_key(name)] if team else []
        if row_of(rows or [{"name": name}], user) is not None:
            found.add(d.uuid)
    return found


def is_member(team, user):
    return member_of(team, user) is not None


def memberships(model, user):
    """(team, row) of every team the user belongs to."""
    return [(t, row) for t in model.of_kind("team") for row in [member_of(t, user)] if row is not None]


def is_da_member(model, user):
    """The user (an account, or a name and surname) is a member of the Design Authority team."""
    team = design_authority(model)
    return team is not None and is_member(team, user)


def main_pushers(model):
    """The members (team, row) ticked in the sheets of the teams as those who may send to the main branch."""
    return [(t, r) for t in model.of_kind("team") for r in member_rows(t) if r.get(MAIN_PUSH)]


def main_denied(model, user, main):
    """Why the user may not change the main branch `main` (publish on it, send versions to it, merge into it with
    Rami › Integra or with Ricevi, bring it back to a version), or None: the members ticked in the sheets of the teams
    («Invia sul ramo principale», of any team, also of the DA); while none is ticked, the members of the Design
    Authority; while no DA team has members yet, anyone (as edit_denied)."""
    pushers = main_pushers(model)
    if pushers:
        if user is not None and row_of([r for _t, r in pushers], user) is not None:
            return None
        names = ", ".join(r.get("name") or "?" for _t, r in pushers)
        return (f"Solo i membri indicati nelle schede dei team modificano il ramo principale «{main}» (pubblica, invia, "
                f"integra): {names}. Chiedi a uno di loro di eseguire l'operazione, oppure lavora su un ramo tuo e "
                f"chiedi di integrarlo; puoi integrare «{main}» nel tuo ramo, per aggiornarlo.")
    da = design_authority(model)
    if da is None or not member_rows(da) or (user is not None and is_member(da, user)):
        return None
    names = ", ".join(member_names(da)) or "nessuno"
    return (f"Solo la Design Authority modifica il ramo principale «{main}» (pubblica, invia, integra): {names}. "
            f"Chiedi a uno di loro di eseguire l'operazione, oppure lavora su un ramo tuo e chiedi alla DA di "
            f"integrarlo; puoi integrare «{main}» nel tuo ramo, per aggiornarlo.")


# --- who may change the teams ------------------------------------------------------------------------------------

# Sheets that only the members of the Design Authority create, change and delete (what they do).
DA_ONLY_KINDS = {"team": "creare, modificare ed eliminare i team",
                 "requirement": "importare, modificare ed eliminare le voci SRS"}
# Fields of other sheets changed only by them: who works on a domain, the decision on an ADR. (what they do)
DA_ONLY_FIELDS = {"domain": ("team", "referent"), "adr": ("da_decision", "da_notes")}
DA_ONLY_WHAT = {"domain": "assegnare i domini ai team e sceglierne il referente",
                "adr": "decidere sulle ADR (esito e osservazioni)"}


def edit_denied(model, user, kind, field=None):
    """Why the user may not create, change or delete a sheet of this kind (with field: change that field of it),
    or None if they may. The teams, the SRS items and the team assigned to a domain are changed only by the members of
    the Design Authority; while no DA team has members yet, by anyone (someone has to set it up)."""
    if kind not in DA_ONLY_KINDS and (field is None or field not in DA_ONLY_FIELDS.get(kind, ())):
        return None
    da = design_authority(model)
    if da is None or not member_rows(da):
        return None
    if user is not None and is_member(da, user):
        return None
    name = " ".join(str(v) for v in (da.get("id"), da.get("name")) if v)
    what = DA_ONLY_KINDS.get(kind) or DA_ONLY_WHAT[kind]
    return (f"Solo i membri della Design Authority ({name}) possono {what}. Se ne fai parte, comunica alla DA "
            "l'ID del tuo account (Utente › Modifica account), che lo indica nella tua riga del team.")


# --- who may open the project ------------------------------------------------------------------------------------

def member_accounts(model):
    """The IDs of the accounts written in the teams of the project."""
    return {a for t in model.of_kind("team") for r in member_rows(t) for a in account_ids(r)}


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
                for a in account_ids(r)}
    accounts |= {a for r in member_rows(team) for a in account_ids(r)}
    if mine and mine in member_accounts(model) and mine not in accounts:
        return True
    return bool(accounts) and mine not in accounts
