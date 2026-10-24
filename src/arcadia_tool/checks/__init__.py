"""Checks of the model against the ARCADIA methodology of the project (rules D1–D10, activities A1–A6 and
B1–B7, checklists of the templates) and of the relations between the fields of different sheets.

Every check has a stable code (SA2-07, LA3-05…), a group (the sheet it is about), a severity and the rule of
the methodology it comes from. A check reports a Finding for every sheet that violates it, with the other sheets
involved. Which checks are active, with their parameters, severity and scope, is chosen in the profiles of
checks.yaml (none by default, see config); the Design Authority can accept a finding as an exception.
"""
from dataclasses import dataclass, field, replace

ERROR, WARNING, INFO = "E", "A", "I"
WAIVED = "eccezioni"  # findings accepted as exceptions, counted apart
SEVERITY_LABELS = {ERROR: "Errore", WARNING: "Avviso", INFO: "Informazione"}

# Groups in the order of the methodology: SA, LA, then the cross-cutting sheets, the indicators and the
# comparison with the published version. Key: prefix of the codes of the group.
GROUPS = (
    ("GEN", "Controlli generali"),
    ("A4", "Voci SRS e matrice sezioni/domini (A4)"),
    ("SA1", "SA-1 Domini funzionali"),
    ("SA2", "SA-2 Funzioni di sistema"),
    ("SA3", "SA-3 Registro di tracciabilità (B5)"),
    ("SA4", "SA-4 Requisiti derivati"),
    ("SA5", "SA-5 Scambi funzionali (B4)"),
    ("SA6", "SA-6 Exchange Item"),
    ("SA7", "SA-7 Functional chain"),
    ("LA1", "LA-1 Componenti logici"),
    ("LA2", "LA-2 Funzioni logiche"),
    ("LA3", "LA-3 Component Exchange"),
    ("LA4", "LA-4 Realizzazione delle chain"),
    ("TX", "Team, ADR e CQ"),
    ("IND", "Indicatori di revisione"),
    ("VER", "Rispetto alla versione pubblicata"),
)
GROUP_LABELS = dict(GROUPS)
GROUP_ORDER = {key: i for i, (key, _) in enumerate(GROUPS)}
PREFIX_GROUP = {"EPBS": "TX", "X": "TX"}  # team, ADR and CQ checks share one group


@dataclass(frozen=True)
class Check:
    code: str
    title: str
    severity: str  # E, A, I or two of them («E/A»): the one of each finding is set by the check
    ref: str  # rule of the methodology
    function: object = field(compare=False, repr=False)
    needs: str = ""  # option the check needs to run (e.g. the coding domains), shown in the settings

    @property
    def group(self):
        prefix = self.code.rsplit("-", 1)[0]
        return PREFIX_GROUP.get(prefix, prefix)

    @property
    def default_severity(self):
        return self.severity[0]

    @property
    def field(self):
        """Field (or card, «@srs») of the sheet where the problem is, unless a finding says otherwise."""
        from arcadia_tool.checks.fields import CHECK_FIELDS
        return CHECK_FIELDS.get(self.code, "")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    element: str  # uuid of the sheet that violates the check (None: the whole project)
    message: str
    related: tuple = ()  # uuids of the other sheets involved
    field: str = ""  # field of the sheet with the problem («@srs»: its traceability card; "": the sheet)
    exception: dict = None  # the exception of the Design Authority that accepts it (then it is not counted)

    @property
    def waived(self):
        return self.exception is not None

    @property
    def group(self):
        return CHECKS_BY_CODE[self.code].group

    @property
    def elements(self):
        return tuple(u for u in (self.element, *self.related) if u)


CHECKS = []
CHECKS_BY_CODE = {}


def check(code, title, severity, ref, needs=""):
    """Register a check: a function(ctx) yielding issue(...) for every violation."""
    def register(function):
        c = Check(code, title, severity, ref, function, needs)
        CHECKS.append(c)
        CHECKS_BY_CODE[code] = c
        return function
    return register


def issue(element, message, related=(), severity=None, field=None):
    """A violation: the sheet (an Element, or None for the whole project), what is wrong, the other sheets
    involved (Elements or uuids), for the checks with two severities the one of this violation and, when it is
    not the one of the check (see fields.CHECK_FIELDS), the field of the sheet with the problem."""
    return element, message, tuple(related), severity, field


def problems(config, model):
    """What prevents a run of the active profile of the checks: no check chosen, or settings that are not correct
    (unknown checks, parameters with a wrong value, a value a check needs not given, domains no longer in the
    model)."""
    from arcadia_tool.checks.params import params_of

    if config is None:
        return ["Le impostazioni delle verifiche del progetto non sono leggibili: salvale di nuovo."]
    profile = config.profile
    found = []
    known = [c for c in profile.enabled if c in CHECKS_BY_CODE]
    unknown = [c for c in profile.enabled if c not in CHECKS_BY_CODE]
    if not known:
        found.append("Nessuna verifica selezionata: scegli i controlli da eseguire.")
    if unknown:
        found.append(f"Controlli sconosciuti nelle impostazioni: {', '.join(map(str, unknown))}.")
    domains = {e.uuid for e in model if e.kind == "domain"}
    for code in known:
        for p in params_of(code):
            problem = p.problem(profile.param(code, p.name), model)
            if problem:
                found.append(f"{code}: {problem}")
        if profile.severity.get(code) not in (None, ERROR, WARNING, INFO):
            found.append(f"{code}: gravità non valida.")
        scope = profile.scope.get(code) or {}
        if any(d not in domains for d in scope.get("domains") or []):
            found.append(f"{code}: l'ambito indica domini che non esistono più.")
    return found


def checks_of_group(group):
    return [c for c in CHECKS if c.group == group]


def run(model, config, published=None, progress=None):
    """Findings of the checks of the active profile of `config` (a ChecksConfig, or just the codes of the checks
    to run) on the model, sorted by group,
    code and sheet, with the severity, the scope and the exceptions of the profile and of the project.
    published: the last published Model, or a function returning it (read only if a check needs it), for the VER
    checks. progress(done, total, check): called before each check, and with check None at the end; returning
    False it stops the run (the findings are those of the checks already run)."""
    from arcadia_tool.checks.config import ChecksConfig, Profile, fingerprint, in_status_scope
    from arcadia_tool.checks.context import Context

    if not isinstance(config, ChecksConfig):  # just the codes of the checks, with the values of the methodology
        config = ChecksConfig({"": Profile(sorted(config))})
    profile = config.profile
    ctx = Context(model, profile, published)
    findings = []
    active = [c for c in CHECKS if c.code in set(profile.enabled)]
    total = len(active)
    for done, c in enumerate(active):
        if progress is not None and progress(done, total, c) is False:
            active = active[:done]
            break
        ctx.code = c.code  # the parameters read by the check are its own
        scope = profile.scope.get(c.code) or {}
        status_scope, domain_scope = scope.get("status") or "all", set(scope.get("domains") or [])
        for element, message, related, severity, field in c.function(ctx) or ():
            uuid = element if isinstance(element, str) or element is None else element.uuid
            sheet = model.get(uuid) if uuid else None
            if sheet is not None and status_scope != "all" and sheet.schema.field("status") is not None \
                    and not in_status_scope(sheet.get("status"), status_scope):
                continue  # out of the scope of the check: a sheet not yet in review or approved
            if sheet is not None and domain_scope:
                domains = ctx.domains_of_element(sheet)
                if domains and not domains & domain_scope:
                    continue  # out of the scope of the check: a sheet of other domains
            finding = Finding(c.code, profile.severity.get(c.code) or severity or c.default_severity, uuid, message,
                              tuple(dict.fromkeys(r if isinstance(r, str) else r.uuid for r in related
                                                  if r is not None and (r if isinstance(r, str) else r.uuid)
                                                  != uuid)),
                              field if field is not None else c.field)
            exception = config.exception_of(finding)
            if exception is not None and exception.get("fingerprint") == fingerprint(sheet):
                finding = replace(finding, exception=exception)  # accepted, as long as the sheet does not change
            findings.append(finding)
    if progress is not None:
        progress(len(active), total, None)  # checks run (fewer than total if stopped), checks active
    order = {c.code: i for i, c in enumerate(CHECKS)}
    findings.sort(key=lambda f: (GROUP_ORDER[f.group], order[f.code], ctx.sort_key(f.element)))
    return findings


def count(findings):
    """{E: n, A: n, I: n, «eccezioni»: n}: the findings accepted as exceptions are counted apart."""
    result = {ERROR: 0, WARNING: 0, INFO: 0, WAIVED: 0}
    for f in findings:
        result[WAIVED if f.waived else f.severity] += 1
    return result


# The checks register themselves when their modules are imported, in the order of the groups.
from arcadia_tool.checks import sa, la, review  # noqa: E402,F401
