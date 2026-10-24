"""Checks of the general rules, of the SRS items and matrix A4, and of the System Analysis sheets (SA-1…SA-7)."""
import re
from collections import Counter, defaultdict

from arcadia_tool.checks import ERROR, INFO, WARNING, check, issue
from arcadia_tool.checks.context import (AGREED, CLAUSE_TYPES, NON_BOARD, name_acronyms, question_number,
                                         sentences, starts_with_verb, without_variants)
from arcadia_tool.model.identifiers import NO_ID_KINDS, _domain_code
from arcadia_tool.checks.params import VERB_ENDINGS
from arcadia_tool.model.schema import ETCS_MODES, REF, REFS, TABLE

ID_FORMATS = {
    "domain": (r"DF\d{2}", "DFnn"),
    "system_function": (r"SF-DF\d{2}-\d{2}", "SF-DFnn-mm"),
    "logical_function": (r"LF-DF\d{2}-\d{2}-\d{2}", "LF-DFnn-mm-kk"),
    "functional_exchange": (r"FE-(DF\d{2}|OE-\d{2})-(DF\d{2}|OE-\d{2})-\d{2}", "FE-DFaa-DFbb-nn"),
    "exchange_item": (r"EI-[A-Za-z0-9][A-Za-z0-9-]*", "EI-nome"),
    "functional_chain": (r"FC-[A-Za-z0-9][A-Za-z0-9-]*", "FC-nome"),
    "logical_component": (r"LC-\d{2}", "LC-nn"),
    "component_exchange": (r"CE-LC\d{2}-LC\d{2}-\d{2}", "CE-LCaa-LCbb-nn"),
    "derived_requirement": (r".+-D\d+", "<voce>-Dn"),
    "team": (r"T\d+", "Tn"),
    "adr": (r"ADR-\d{3}", "ADR-nnn"),
    "clarification": (r"CQ-\d{2}", "CQ-nn"),
    "external_actor": (r"OE-\d{2}", "OE-nn"),
}
# Fields that an approved sheet should have (GEN-08).
MAIN_FIELDS = {
    "domain": ("mission", "team"),
    "system_function": ("domain", "description", "mode_availability"),
    "trace_record": ("requirement", "b5_question", "outcome"),
    "derived_requirement": ("parent", "obligation", "function", "domain", "b6_scheme"),
    "exchange_item": ("nature", "meaning", "srs_origin"),
    "functional_exchange": ("source", "target", "exchange_item", "nature", "production_condition"),
    "functional_chain": ("responsible_domain", "trigger", "final_effect", "steps"),
    "logical_function": ("refines", "description"),
    "logical_component": ("responsibility", "owner"),
    "component_exchange": ("source", "target", "realizes", "exchange_item"),
    "chain_realization": ("chain", "outcome", "steps"),
}
# Esito expected for each question B5 (SA-3).
OUTCOMES = {1: "Non tracciata", 2: "Ipotesi d'ambiente / dato atteso", 3: "Tracciata al dizionario",
            4: "Scomposta in requisiti derivati", 5: "Collegata alla voce nominale", 6: "Tracciata a funzione"}
CONDITIONS = {"FLOW": ("Sempre", "A ogni variazione"), "EVENT": ("Su evento",), "OPERATION": ("Su richiesta",)}
MATRIX_CHAPTERS = ("3", "4", "5", "A")
CODED_VARIABLE = re.compile(r"^[A-Z]{1,4}_[A-Z0-9_]+$")  # variables of chapter 7: M_MODE, NID_ENGINE, Q_DIR…


def _refs(element):
    """(field label, uuid) of every reference of an element, also in the cells of its tables."""
    for f in element.schema.fields:
        value = element.values.get(f.name)
        if not value:
            continue
        if f.type == REF:
            yield f, value
        elif f.type == REFS:
            for v in value:
                yield f, v
        elif f.type == TABLE:
            for row in value:
                for c in f.columns:
                    if c.type == REF and row.get(c.name):
                        yield f, row.get(c.name)


def _at_most(n, noun="frase", plural="frasi"):
    """«una frase», «una o due frasi», «al massimo 4 frasi»."""
    return {1: f"una {noun}", 2: f"una o due {plural}", 3: f"non più di tre {plural}"}.get(
        n, f"al massimo {n} {plural}")


def _name_field(element):
    return "title" if element.schema.field("title") and not element.schema.field("name") else "name"


# --- GEN: all the sheets -----------------------------------------------------------------------------------

@check("GEN-01", "ID mancante", "E", "Convenzioni di identificazione")
def gen_missing_id(ctx):
    for e in ctx.model:
        if e.kind not in NO_ID_KINDS and e.schema.field("id") and not e.get("id"):
            yield issue(e, f"{e.schema.label} senza identificativo.")


@check("GEN-02", "ID duplicato tra schede dello stesso tipo", "E", "Convenzioni di identificazione")
def gen_duplicate_id(ctx):
    for kind, elements in ctx.kinds.items():
        by_id = defaultdict(list)
        for e in elements:
            if e.get("id"):
                by_id[e.get("id")].append(e)
        for ident, same in by_id.items():
            if len(same) > 1:
                for e in same:
                    yield issue(e, f"L'ID «{ident}» è usato da {len(same)} schede «{e.schema.label}».",
                                [o for o in same if o is not e])


@check("GEN-03", "ID non conforme al formato del template", "A", "Convenzioni di identificazione")
def gen_id_format(ctx):
    for kind, pattern in (ctx.param("formats") or {}).items():
        if not pattern:
            continue
        default, shown = ID_FORMATS.get(kind, (None, None))
        shown = shown if pattern == default else f"«{pattern}»"
        for e in ctx.of(kind):
            if e.get("id") and not re.fullmatch(pattern, e.get("id")):
                yield issue(e, f"L'ID «{e.get('id')}» non segue il formato {shown}.")


@check("GEN-04", "Nome o titolo mancante", "A", "Template")
def gen_missing_name(ctx):
    for e in ctx.model:
        if e.kind in ("requirement", "derived_requirement", "trace_record", "chain_realization"):
            continue
        name = _name_field(e)
        if e.schema.field(name) and not e.get(name):
            yield issue(e, f"{e.schema.label} senza {e.schema.field(name).label.lower()}.", field=name)


@check("GEN-05", "Riferimento a un elemento che non esiste più", "E", "Integrità del modello")
def gen_dangling(ctx):
    for e in ctx.model:
        fields = [f for f, uuid in _refs(e) if ctx.get(uuid) is None]
        if fields:
            labels = sorted({f.label for f in fields})
            yield issue(e, f"Riferimenti a elementi eliminati in: {', '.join(labels)}.", field=fields[0].name)


@check("GEN-06", "Riferimento a un ADR «Superata»", "A", "X-1")
def gen_superseded_adr(ctx):
    for e in ctx.model:
        for f, uuid in _refs(e):
            adr = ctx.get(uuid)
            if adr is not None and adr.kind == "adr" and adr.get("status") == "Superata":
                by = ctx.get(adr.get("superseded_by"))
                hint = f": usare {ctx.label(by)}" if by is not None else ""
                yield issue(e, f"«{f.label}» cita {ctx.label(adr)}, superata{hint}.", [adr, by], field=f.name)


@check("GEN-07", "Scheda approvata che si appoggia su schede non approvate", "A", "Ordine di compilazione")
def gen_approved_on_draft(ctx):
    for e in ctx.model:
        if not ctx.approved(e):
            continue
        drafts, first = [], None
        for f, uuid in _refs(e):
            target = ctx.get(uuid)
            if target is not None and target.schema.field("status") and not ctx.approved(target) \
                    and target.kind != "adr" and target not in drafts:
                drafts.append(target)
                first = first or f.name
        if drafts:
            yield issue(e, f"Approvata, ma usa schede non approvate: {ctx.labels(drafts)}.", drafts, field=first)


@check("GEN-08", "Scheda approvata con campi principali vuoti", "A", "Checklist dei template")
def gen_approved_incomplete(ctx):
    for kind, names in (ctx.param("fields") or {}).items():
        for e in ctx.of(kind):
            if ctx.approved(e):
                empty = [n for n in names if e.schema.field(n) is not None and not e.get(n)]
                if empty:
                    yield issue(e, f"Approvata con campi vuoti: {', '.join(e.schema.field(n).label for n in empty)}.",
                                field=empty[0])


# --- A4: SRS items and matrix sections × domains ----------------------------------------------------------

def _sections(ctx):
    return [r for r in ctx.of("requirement") if r.get("item_type") == "Sezione"]


@check("A4-01", "Sezione dei capitoli 3, 4, 5 o dell'Appendice A senza dominio principale", "E", "A4, Parte VI")
def a4_section_without_domain(ctx):
    chapters = {str(c).strip() for c in ctx.param("chapters") or []}
    for s in _sections(ctx):
        if (s.get("id") or "").split(".")[0] in chapters and not s.get("primary_domain"):
            yield issue(s, "Sezione senza dominio principale: lacuna nella proposta dei domini.")


@check("A4-02", "Stesso dominio principale e contributore", "E", "A4")
def a4_primary_contributing(ctx):
    for r in ctx.of("requirement"):
        if r.get("primary_domain") and r.get("primary_domain") in (r.get("contributing_domains") or []):
            d = ctx.get(r.get("primary_domain"))
            yield issue(r, f"{ctx.label(d)} è sia dominio principale sia contributore.", [d])


@check("A4-03", "Sezione con più di tre domini non analizzata a livello di clausola", "A", "A4")
def a4_too_many_domains(ctx):
    limit = ctx.param("max_domains")
    for s in _sections(ctx):
        domains = ctx.own_domains(s)
        if len(domains) > limit and not any(ctx.own_domains(c) for c in ctx.descendants(s)):
            yield issue(s, f"La sezione coinvolge {len(domains)} domini: va analizzata a livello di clausola.",
                        [ctx.get(d) for d in domains])


@check("A4-04", "Clausola allocata a un dominio estraneo alla sua sezione", "A", "A4, B5")
def a4_clause_outside_section(ctx):
    for r in ctx.of("requirement"):
        if r.get("item_type") not in CLAUSE_TYPES or not r.get("primary_domain"):
            continue
        section = ctx.section_of(r)
        if section is not None and section.get("primary_domain") and \
                r.get("primary_domain") not in ctx.own_domains(section):
            d = ctx.get(r.get("primary_domain"))
            yield issue(r, f"Dominio principale {ctx.label(d)}, che non è né principale né contributore della "
                           f"sezione {section.get('id')}.", [d, section])


@check("A4-05", "Voce Definizione, Informativa o Altro allocata come principale", "A", "B5 domanda 1")
def a4_non_board_primary(ctx):
    for r in ctx.of("requirement"):
        cats = ctx.categories(r)
        if cats and not cats & {"Bordo", "Terra"} and r.get("primary_domain"):
            yield issue(r, f"Voce di categoria {', '.join(sorted(cats))} con un dominio principale: non si "
                           "traccia a funzioni.", [r.get("primary_domain")])


@check("A4-06", "Categorie del cap. 9 combinate non ammesse", "E", "Cap. 9")
def a4_combined_categories(ctx):
    for r in ctx.of("requirement"):
        cats = ctx.categories(r)
        if len(cats) > 1 and not cats <= {"Bordo", "Terra"}:
            yield issue(r, f"Categorie {', '.join(sorted(cats))}: si possono combinare solo Bordo e Terra.")


@check("A4-07", "Riga di tabella con categoria diversa dalla tabella", "A", "Nota al cap. 9")
def a4_table_row_category(ctx):
    for r in ctx.of("requirement"):
        parent = ctx.get(r.get("parent"))
        if parent is None or not (r.get("id") or "").startswith(f"{parent.get('id')}-"):
            continue
        if ctx.categories(r) and ctx.categories(parent) and ctx.categories(r) != ctx.categories(parent):
            yield issue(r, f"La riga ha categoria {', '.join(sorted(ctx.categories(r)))}, la tabella "
                           f"{parent.get('id')} {', '.join(sorted(ctx.categories(parent)))}: ogni riga eredita la "
                           "classificazione della tabella.", [parent])


@check("A4-08", "Voce senza categoria del cap. 9 (e senza CQ)", "A", "X-2")
def a4_no_category(ctx):
    with_cq = {c.get("clause") for c in ctx.of("clarification")}
    for r in ctx.of("requirement"):
        if r.get("item_type") == "Requisito" and not ctx.categories(r) and r.uuid not in with_cq:
            yield issue(r, "Voce senza categoria del capitolo 9: va aperta una richiesta di chiarimento (CQ).")


@check("A4-09", "Voce del capitolo 6 senza voce nominale sostituita", "A", "B5 domanda 5")
def a4_chapter6_nominal(ctx):
    for r in ctx.of("requirement"):
        if (r.get("id") or "").startswith("6.") and r.get("item_type") == "Requisito" and ctx.is_board(r) \
                and not r.get("replaces"):
            yield issue(r, "Voce del capitolo 6 (versione di sistema 1) senza la voce nominale che sostituisce.")


# --- SA-1: functional domains -------------------------------------------------------------------------------

@check("SA1-01", "Missione assente o più lunga di una o due frasi", "A", "D1, A2")
def sa1_mission(ctx):
    limit = ctx.param("max_sentences")
    for d in ctx.of("domain"):
        n = len(sentences(d.get("mission")))
        if n == 0:
            yield issue(d, "Missione non compilata: lo scopo del dominio va espresso in una frase.")
        elif n > limit:
            yield issue(d, f"Missione di {n} frasi: lo scopo del dominio va espresso in {_at_most(limit)}.")


@check("SA1-02", "Team assegnatario e «Domini» del team discordanti", "E", "EPBS-1")
def sa1_team_mismatch(ctx):
    for d in ctx.of("domain"):
        team = ctx.get(d.get("team"))
        if team is not None and d.uuid not in (team.get("domains") or []):
            yield issue(d, f"Il team assegnatario {ctx.label(team)} non ha il dominio tra i suoi domini.", [team])
        for t in ctx.teams_of_domain.get(d.uuid, []):
            if t.uuid != d.get("team"):
                yield issue(d, f"{ctx.label(t)} elenca il dominio ma non ne è il team assegnatario.", [t])


@check("SA1-03", "Dominio senza team o elencato da più team", "A", "EPBS-1")
def sa1_team_count(ctx):
    for d in ctx.of("domain"):
        teams = ctx.teams_of_domain.get(d.uuid, [])
        if not d.get("team") and not teams:
            yield issue(d, "Dominio non assegnato a nessun team.")
        elif len(teams) > 1:
            yield issue(d, f"Dominio elencato da più team: {ctx.labels(teams)}.", teams)


@check("SA1-04", "Team assegnatario senza referente", "A", "A3")
def sa1_no_referent(ctx):
    for d in ctx.of("domain"):
        team = ctx.get(d.get("team"))
        if team is not None and not team.get("referent"):
            yield issue(d, f"Il team assegnatario {ctx.label(team)} non ha un referente.", [team])


@check("SA1-05", "Dominio senza sezioni di cui è principale", "I", "A4, SA-1")
def sa1_no_sections(ctx):
    primary = {r.get("primary_domain") for r in ctx.of("requirement")}
    for d in ctx.of("domain"):
        if d.uuid not in primary:
            yield issue(d, "Il dominio non è principale per nessuna sezione o clausola SRS.")


@check("SA1-06", "Sezioni principali tutte in un solo capitolo", "I", "D3, errori tipici")
def sa1_one_chapter(ctx):
    for d in ctx.of("domain"):
        sections = [r for r in ctx.of("requirement") if r.get("primary_domain") == d.uuid]
        chapters = {(r.get("id") or "").split(".")[0] for r in sections}
        if len(sections) >= 2 and len(chapters) == 1:
            yield issue(d, f"Tutte le voci di cui è principale sono nel capitolo {chapters.pop()}: un dominio "
                           "attinge di norma da più parti della specifica.")


@check("SA1-07", "Dominio con lo stesso nome di un componente logico", "A", "D1")
def sa1_named_as_component(ctx):
    components = {(c.get("name") or "").casefold(): c for c in ctx.of("logical_component") if c.get("name")}
    for d in ctx.of("domain"):
        c = components.get((d.get("name") or "").casefold())
        if c is not None:
            yield issue(d, f"Ha lo stesso nome del componente {ctx.label(c)}: un dominio non è un componente.", [c])


@check("SA1-08", "Componenti previsti diversi dall'allocazione delle funzioni del dominio", "A", "SA-1, LA-1")
def sa1_planned_components(ctx):
    for d in ctx.of("domain"):
        planned = set(d.get("planned_components") or [])
        used = {lf.get("component") for lf in ctx.of("logical_function")
                if ctx.get(lf.get("component")) is not None and ctx.domain_of(lf) is d}
        for c in planned - used:
            if ctx.get(c) is not None and used:
                yield issue(d, f"Componente previsto {ctx.label(c)} senza funzioni logiche del dominio.", [c])
        for c in used - planned:
            yield issue(d, f"Funzioni del dominio allocate a {ctx.label(c)}, non tra i componenti previsti.", [c])


@check("SA1-09", "Dominio senza funzioni di sistema", "A", "A3, B1")
def sa1_no_functions(ctx):
    with_functions = {sf.get("domain") for sf in ctx.of("system_function")}
    for d in ctx.of("domain"):
        if d.uuid not in with_functions:
            yield issue(d, "Il dominio non ha funzioni di sistema.")


# --- SA-2: system functions ---------------------------------------------------------------------------------

@check("SA2-01", "Funzione di sistema senza dominio", "E", "D2, Parte VI")
def sa2_no_domain(ctx):
    for sf in ctx.of("system_function"):
        if not sf.get("domain"):
            yield issue(sf, "Funzione senza dominio: ogni funzione appartiene a un solo dominio.")


@check("SA2-02", "L'ID indica un dominio diverso da quello assegnato", "E", "Convenzioni di identificazione")
def sa2_id_domain(ctx):
    for sf in ctx.of("system_function"):
        d = ctx.get(sf.get("domain"))
        parts = (sf.get("id") or "").split("-")
        if d is not None and d.get("id") and len(parts) >= 3 and parts[0] == "SF" and parts[1] != d.get("id"):
            yield issue(sf, f"L'ID indica {parts[1]} ma la funzione è nel dominio {d.get('id')}: usare «Rinumera».",
                        [d])


def _name_checks(ctx, elements):
    """Rule D5 on the names, with the parameters of the running check (those it does not have: the methodology)."""
    def param(name, default):
        value = ctx.param(name)
        return default if value is None else value

    endings, allowed = param("verb_endings", VERB_ENDINGS), param("allowed_first_words", [])
    modes, levels, paragraphs = param("modes", list(ETCS_MODES)), param("levels", True), param("paragraphs", True)
    for e in elements:
        name = e.get("name") or ""
        if not name:
            continue
        if not starts_with_verb(name, endings, allowed):
            yield e, "verb", f"Il nome «{name}» non inizia con un verbo all'infinito (verbo + oggetto)."
        acronyms = name_acronyms(name, modes, levels, paragraphs)
        if acronyms:
            yield e, "acronyms", f"Il nome contiene sigle di modo, livello o paragrafo: {', '.join(acronyms)}."


@check("SA2-03", "Nome non nella forma verbo + oggetto", "A", "D5")
def sa2_name_verb(ctx):
    for e, what, message in _name_checks(ctx, ctx.of("system_function")):
        if what == "verb":
            yield issue(e, message)


@check("SA2-04", "Nome con sigle di modo, livello o numeri di paragrafo", "A", "D5, Parte VI")
def sa2_name_acronyms(ctx):
    for e, what, message in _name_checks(ctx, ctx.of("system_function")):
        if what == "acronyms":
            yield issue(e, message)


def _same_names(functions, key):
    groups = defaultdict(list)
    for f in functions:
        if f.get("name") and key(f.get("name")):
            groups[key(f.get("name"))].append(f)
    return [g for g in groups.values() if len(g) > 1]


@check("SA2-05", "Funzioni duplicate per modo, livello o versione", "A", "D6")
def sa2_duplicated_by_mode(ctx):
    for group in _same_names(ctx.of("system_function"), without_variants):
        if len({f.get("name").casefold() for f in group}) > 1:  # different only by mode, level or version
            for f in group:
                yield issue(f, f"Stessa logica di {ctx.labels(o for o in group if o is not f)}, distinta solo per "
                               "modo, livello o versione: va una sola funzione con il modo come ingresso.",
                            [o for o in group if o is not f])


@check("SA2-06", "Funzioni con lo stesso nome", "A", "D9")
def sa2_same_name(ctx):
    for group in _same_names(ctx.of("system_function"), lambda n: " ".join(n.casefold().split())):
        for f in group:
            yield issue(f, f"Stesso nome di {ctx.labels(o for o in group if o is not f)}: uno stesso comportamento "
                           "va realizzato da una sola funzione.", [o for o in group if o is not f])


@check("SA2-07", "Funzione senza voci tracciate né requisiti derivati", "E", "D8, Parte VI")
def sa2_not_justified(ctx):
    for sf in ctx.of("system_function"):
        if not ctx.traced(sf) and not ctx.derived_of_sf(sf):
            yield issue(sf, "Nessuna voce SRS tracciata e nessun requisito derivato: funzionalità non richiesta.")


@check("SA2-08", "Voce tracciata di sola Terra, Definizione, Informativa o Altro", "E", "D7, B5 domande 1–2")
def sa2_non_board_traced(ctx):
    for sf in ctx.of("system_function"):
        for uuid in ctx.traced(sf):
            item = ctx.get(uuid)
            if item is not None and ctx.categories(item) and not ctx.is_board(item):
                yield issue(sf, f"Traccia {item.get('id')}, di categoria "
                                f"{', '.join(sorted(ctx.categories(item)))}: non si traccia a funzioni di bordo.",
                            [item])


@check("SA2-09", "Voce tracciata di un dominio diverso da quello della funzione", "A", "A4, B5")
def sa2_item_other_domain(ctx):
    for sf in ctx.of("system_function"):
        if not sf.get("domain"):
            continue
        for uuid in ctx.traced(sf):
            item = ctx.get(uuid)
            domains = ctx.domains_of_item(item) if item is not None else set()
            if domains and sf.get("domain") not in domains:
                yield issue(sf, f"Traccia {item.get('id')}, allocata nella matrice A4 a "
                                f"{ctx.labels(ctx.get(d) for d in domains)} e non al dominio della funzione.",
                            [item])


@check("SA2-10", "Funzione nuova senza motivo, o motivo su una funzione non nuova", "A", "SA-2")
def sa2_new_reason(ctx):
    for sf in ctx.of("system_function"):
        if sf.get("is_new") and not sf.get("new_reason"):
            yield issue(sf, "Funzione nuova senza motivo.")
        elif sf.get("new_reason") and not sf.get("is_new"):
            yield issue(sf, "Motivo compilato su una funzione non segnata come nuova.", field="is_new")


@check("SA2-11", "Funzione nuova approvata senza ADR collegata", "I", "SA-2")
def sa2_new_without_adr(ctx):
    for sf in ctx.of("system_function"):
        if sf.get("is_new") and ctx.approved(sf) and not sf.get("adrs"):
            yield issue(sf, "Funzione nuova approvata senza ADR: se la scelta non è ovvia va registrata.")


def _modes(sf):
    return {mode: str(value).strip().upper() for mode, value in (sf.get("mode_availability") or {}).items()
            if str(value).strip()}


@check("SA2-12", "Disponibilità nei modi non compilata", "A", "B2")
def sa2_no_modes(ctx):
    for sf in ctx.of("system_function"):
        if not _modes(sf):
            yield issue(sf, "Disponibilità nei modi non compilata (righe della tabella 4.5.2).")


@check("SA2-13", "Disponibilità nei modi con valori diversi da X, O o vuoto", "E", "B2")
def sa2_mode_values(ctx):
    for sf in ctx.of("system_function"):
        wrong = [f"{m}={v}" for m, v in _modes(sf).items() if v not in ("X", "O")]
        if wrong:
            yield issue(sf, f"Valori non ammessi nella disponibilità nei modi: {', '.join(wrong)} (solo X o O).")


@check("SA2-14", "Modo opzionale («O») senza ADR collegata", "E", "B2")
def sa2_optional_without_adr(ctx):
    for sf in ctx.of("system_function"):
        optional = [m for m, v in _modes(sf).items() if v == "O"]
        if optional and not sf.get("adrs"):
            yield issue(sf, f"Funzione opzionale in {', '.join(optional)} senza ADR: è una decisione di prodotto.")


@check("SA2-15", "Riga 4.5.2 non nel formato 4.5.2-Rnn o assegnata a più funzioni", "A", "B1")
def sa2_rows_452(ctx):
    owners = defaultdict(list)
    for sf in ctx.of("system_function"):
        for row in sf.get("rows_452") or []:
            owners[row.strip()].append(sf)
            if not re.fullmatch(r"4\.5\.2-R\d{2}", row.strip()):
                yield issue(sf, f"Riga «{row}» non nel formato 4.5.2-Rnn.")
    for row, functions in owners.items():
        if len(functions) > 1:
            for sf in functions:
                yield issue(sf, f"La riga {row} è assegnata anche a {ctx.labels(o for o in functions if o is not sf)}.",
                            [o for o in functions if o is not sf])


@check("SA2-16", "Funzione non osservabile da un attore esterno", "A", "B1")
def sa2_not_observable(ctx):
    graph = defaultdict(set)  # system functions and actors connected by an exchange (of any level)
    for fe in ctx.of("functional_exchange"):
        ends = []
        for uuid in (fe.get("source"), fe.get("target")):
            e = ctx.get(uuid)
            node = e if e is not None and e.kind == "external_actor" else ctx.sf_of(e)
            if node is not None:
                ends.append(node.uuid)
        if len(ends) == 2:
            graph[ends[0]].add(ends[1])
            graph[ends[1]].add(ends[0])
    actors = {a.uuid for a in ctx.of("external_actor")}
    reaches = set()
    stack = [a for a in actors if a in graph]
    while stack:
        node = stack.pop()
        if node not in reaches:
            reaches.add(node)
            stack.extend(graph[node])
    for sf in ctx.of("system_function"):
        if sf.uuid not in reaches:
            yield issue(sf, "Nessun percorso di scambi la collega a un attore esterno: la funzione non è osservabile.")


@check("SA2-17", "Componente proposto diverso dall'allocazione delle funzioni logiche", "A", "SA-2")
def sa2_proposed_component(ctx):
    for sf in ctx.of("system_function"):
        proposed = sf.get("proposed_component")
        used = ctx.components_of(sf) or set()
        others = [c for c in used if c != proposed and not ctx.within(c, proposed)]
        if proposed and others:
            yield issue(sf, f"Componente proposto {ctx.label(proposed)}, ma le funzioni logiche sono allocate a "
                            f"{ctx.labels(others)}.", [proposed, *others])


@check("SA2-18", "Funzione non raffinata da nessuna funzione logica", "I", "B3")
def sa2_not_refined(ctx):
    if not ctx.of("logical_function"):
        return
    for sf in ctx.of("system_function"):
        if not ctx.lfs_refining.get(sf.uuid):
            yield issue(sf, "Nessuna funzione logica la raffina.")


# --- SA-3: traceability register (B5) -----------------------------------------------------------------------

def _record_functions(record, ctx):
    functions = [ctx.get(record.get("primary_function")), *(ctx.get(u) for u in record.get("secondary_functions") or [])]
    return list({f.uuid: f for f in functions if f is not None}.values())


@check("SA3-01", "Esito senza voce", "E", "SA-3")
def sa3_no_item(ctx):
    for r in ctx.of("trace_record"):
        if not r.get("requirement"):
            yield issue(r, "Esito di tracciatura senza ID voce.")


@check("SA3-02", "Più esiti per la stessa voce", "E", "B5")
def sa3_duplicate(ctx):
    for uuid, records in ctx.records_by_requirement.items():
        if len(records) > 1:
            for r in records[1:]:
                yield issue(r, f"La voce {ctx.get(uuid).get('id') if ctx.get(uuid) else '?'} ha {len(records)} "
                               "esiti nel registro.", [records[0], uuid])


@check("SA3-03", "Domanda B5 ed Esito incoerenti", "E", "B5")
def sa3_question_outcome(ctx):
    for r in ctx.of("trace_record"):
        q = question_number(r)
        if q and r.get("outcome") and r.get("outcome") != OUTCOMES[q]:
            yield issue(r, f"Domanda B5 n. {q}, ma esito «{r.get('outcome')}»: atteso «{OUTCOMES[q]}».")


@check("SA3-04", "Domanda B5 incoerente con la categoria del cap. 9, senza motivazione", "E", "B5, checklist SA-3")
def sa3_question_category(ctx):
    for r in ctx.of("trace_record"):
        item, q = ctx.get(r.get("requirement")), question_number(r)
        if item is None or not q or r.get("notes"):
            continue
        cats = ctx.categories(item)
        expected = None
        if cats and not cats & {"Bordo", "Terra"} and q != 1:
            expected = "1 (definizione, informativa o altro)"
        elif cats == {"Terra"} and q != 2:
            expected = "2 (solo terra)"
        elif "Bordo" in cats and q in (1, 2):
            expected = "da 3 a 6 (requisito di bordo)"
        if expected:
            yield issue(r, f"Voce di categoria {', '.join(sorted(cats))} alla domanda {q}: attesa la domanda "
                           f"{expected}. Lo scostamento va motivato nelle note.", [item])


@check("SA3-05", "«Tracciata a funzione» senza funzione primaria, o funzione con un altro esito", "E", "B5 domanda 6")
def sa3_primary_function(ctx):
    for r in ctx.of("trace_record"):
        outcome = r.get("outcome")
        if outcome == "Tracciata a funzione" and not r.get("primary_function"):
            yield issue(r, "Esito «Tracciata a funzione» senza funzione primaria.")
        elif r.get("primary_function") and outcome and outcome not in ("Tracciata a funzione",
                                                                       "Collegata alla voce nominale"):
            yield issue(r, f"Funzione primaria indicata con l'esito «{outcome}».", [r.get("primary_function")])


@check("SA3-06", "Più di tre funzioni tra primaria e secondarie", "A", "B5 domanda 6")
def sa3_too_many_functions(ctx):
    limit = ctx.param("max_functions")
    for r in ctx.of("trace_record"):
        functions = _record_functions(r, ctx)
        if len(functions) > limit:
            shown = "tre" if limit == 3 else str(limit)
            yield issue(r, f"{len(functions)} funzioni: con più di {shown} funzioni si torna alla domanda 4 "
                           "(requisiti derivati).", functions)


@check("SA3-07", "«Scomposta in requisiti derivati» senza derivati", "E", "B5 domanda 4, checklist SA-3")
def sa3_no_derived(ctx):
    for r in ctx.of("trace_record"):
        if r.get("outcome") == "Scomposta in requisiti derivati" and r.get("requirement") \
                and not ctx.derived_by_parent.get(r.get("requirement")):
            yield issue(r, "Nessun requisito derivato (SA-4) ha questa voce come voce madre.", [r.get("requirement")])


@check("SA3-08", "«Tracciata al dizionario» senza Exchange Item", "E", "B5 domanda 3")
def sa3_dictionary(ctx):
    for r in ctx.of("trace_record"):
        items = [ctx.get(u) for u in r.get("exchange_items") or []]
        if r.get("outcome") == "Tracciata al dizionario" and not any(
                i is not None and i.kind == "exchange_item" for i in items):
            yield issue(r, "Esito «Tracciata al dizionario» senza Exchange Item.")


@check("SA3-09", "«Ipotesi d'ambiente» senza dato atteso", "I", "D7, checklist SA-3")
def sa3_environment(ctx):
    for r in ctx.of("trace_record"):
        items = [ctx.get(u) for u in r.get("exchange_items") or []]
        if r.get("outcome") == OUTCOMES[2] and not any(i is not None and i.kind == "exchange_item" for i in items):
            yield issue(r, "Ipotesi d'ambiente senza dato atteso: se la voce descrive un'informazione inviata al "
                           "bordo, va registrato l'Exchange Item atteso in ingresso.")


@check("SA3-10", "«Collegata alla voce nominale» incompleta o su funzioni diverse", "E", "B5 domanda 5")
def sa3_nominal(ctx):
    for r in ctx.of("trace_record"):
        item = ctx.get(r.get("requirement"))
        if r.get("outcome") != OUTCOMES[5] or item is None:
            continue
        nominal = ctx.get(item.get("replaces"))
        if nominal is None:
            yield issue(r, "La voce non indica la voce nominale che sostituisce.", [item])
            continue
        nominal_functions = {f.uuid for f in ctx.functions_tracing.get(nominal.uuid, [])}
        nominal_functions |= {x.get("primary_function") for x in ctx.records_by_requirement.get(nominal.uuid, [])}
        nominal_functions.discard(None)
        if r.get("primary_function") and nominal_functions and r.get("primary_function") not in nominal_functions:
            yield issue(r, f"Tracciata a {ctx.label(r.get('primary_function'))}, la voce nominale "
                           f"{nominal.get('id')} a {ctx.labels(ctx.get(u) for u in nominal_functions)}: va tracciata "
                           "alla stessa funzione.", [nominal, r.get("primary_function")])


@check("SA3-11", "Registro e tracciatura delle funzioni discordanti", "A", "SA-2 ↔ SA-3")
def sa3_register_vs_functions(ctx):
    for r in ctx.of("trace_record"):
        item = ctx.get(r.get("requirement"))
        if item is None:
            continue
        for f in _record_functions(r, ctx):
            if not ctx.traces(f, item):
                where = "primary_function" if f.uuid == r.get("primary_function") else "secondary_functions"
                yield issue(r, f"{ctx.label(f)} è nel registro ma non traccia la voce {item.get('id')} né la sua "
                               "sezione.", [f, item], field=where)
        listed = {f.uuid for f in _record_functions(r, ctx)}
        for f in ctx.functions_tracing.get(item.uuid, []):
            if f.kind == "system_function" and f.uuid not in listed:
                yield issue(r, f"{ctx.label(f)} traccia la voce {item.get('id')} ma non compare nel registro.",
                            [f, item])


@check("SA3-12", "Funzione primaria di un dominio estraneo alla voce", "A", "B5 (unità di lavoro)")
def sa3_primary_domain(ctx):
    for r in ctx.of("trace_record"):
        item, function = ctx.get(r.get("requirement")), ctx.get(r.get("primary_function"))
        if item is None or function is None:
            continue
        domain, domains = ctx.domain_of(function), ctx.domains_of_item(item)
        if domain is not None and domains and domain.uuid not in domains:
            yield issue(r, f"La funzione primaria è del dominio {ctx.label(domain)}, la voce {item.get('id')} è "
                           f"allocata a {ctx.labels(ctx.get(d) for d in domains)}.", [function, item, domain])


@check("SA3-13", "Funzione primaria ripetuta tra le secondarie", "A", "SA-3")
def sa3_primary_secondary(ctx):
    for r in ctx.of("trace_record"):
        if r.get("primary_function") and r.get("primary_function") in (r.get("secondary_functions") or []):
            yield issue(r, f"{ctx.label(r.get('primary_function'))} è sia primaria sia secondaria.",
                        [r.get("primary_function")])


@check("SA3-14", "Funzione primaria di tipo logico", "A", "SA-3")
def sa3_logical_primary(ctx):
    for r in ctx.of("trace_record"):
        f = ctx.get(r.get("primary_function"))
        if f is not None and f.kind == "logical_function":
            yield issue(r, f"La funzione primaria {ctx.label(f)} è una funzione logica: il registro SA-3 traccia "
                           "sulle funzioni di sistema.", [f])


@check("SA3-15", "Voce di bordo senza esito nel registro", "A", "Parte VI, checklist di revisione 7")
def sa3_board_without_record(ctx):
    for item in ctx.of("requirement"):
        if item.get("item_type") == "Requisito" and ctx.is_board(item) \
                and not ctx.records_by_requirement.get(item.uuid):
            yield issue(item, "Voce di bordo senza esito nel registro di tracciabilità.")


@check("SA3-16", "Sezione non conclusa: voci senza esito", "I", "B5 (unità di lavoro)")
def sa3_section_open(ctx):
    for s in _sections(ctx):
        clauses = [c for c in ctx.descendants(s) if c.get("item_type") == "Requisito"]
        open_ = [c for c in clauses if not ctx.records_by_requirement.get(c.uuid)]
        if clauses and open_ and len(open_) < len(clauses):
            yield issue(s, f"Sezione non conclusa: {len(open_)} voci su {len(clauses)} senza esito nel registro.")


# --- SA-4: derived requirements -----------------------------------------------------------------------------

@check("SA4-01", "Requisito derivato senza voce madre", "E", "SA-4")
def sa4_no_parent(ctx):
    for d in ctx.of("derived_requirement"):
        if not d.get("parent"):
            yield issue(d, "Requisito derivato senza voce madre.")


@check("SA4-02", "Voce madre senza esito «Scomposta» nel registro", "A", "SA-3 ↔ SA-4")
def sa4_parent_outcome(ctx):
    for d in ctx.of("derived_requirement"):
        parent = ctx.get(d.get("parent"))
        if parent is not None and not any(r.get("outcome") == OUTCOMES[4]
                                          for r in ctx.records_by_requirement.get(parent.uuid, [])):
            yield issue(d, f"La voce madre {parent.get('id')} non ha nel registro l'esito «{OUTCOMES[4]}».", [parent])


@check("SA4-03", "ID non nella forma «voce madre-Dn»", "A", "Convenzioni di identificazione")
def sa4_id(ctx):
    for d in ctx.of("derived_requirement"):
        parent = ctx.get(d.get("parent"))
        if parent is not None and d.get("id") and not re.fullmatch(re.escape(parent.get("id") or "") + r"-D\d+",
                                                                    d.get("id")):
            yield issue(d, f"L'ID non è nella forma {parent.get('id')}-Dn.", [parent])


@check("SA4-04", "Obbligo vuoto o con più frasi", "A", "Checklist SA-4")
def sa4_obligation(ctx):
    limit = ctx.param("max_sentences")
    for d in ctx.of("derived_requirement"):
        n = len(sentences(d.get("obligation")))
        if n == 0:
            yield issue(d, "Obbligo non compilato.")
        elif n > limit:
            shown = "un requisito derivato ha un solo obbligo" if limit == 1 else f"al massimo {limit} frasi"
            yield issue(d, f"Obbligo di {n} frasi: {shown}.")


@check("SA4-05", "Requisito derivato senza dominio", "E", "Checklist SA-4")
def sa4_no_domain(ctx):
    for d in ctx.of("derived_requirement"):
        if not d.get("domain"):
            yield issue(d, "Requisito derivato senza dominio.")


@check("SA4-06", "Requisito derivato senza funzione logica", "A", "SA-4")
def sa4_no_function(ctx):
    for d in ctx.of("derived_requirement"):
        if not d.get("function"):
            yield issue(d, "Requisito derivato non allocato a una funzione logica.")


@check("SA4-07", "Dominio diverso da quello della funzione logica", "E", "Checklist SA-4")
def sa4_domain_function(ctx):
    for d in ctx.of("derived_requirement"):
        lf = ctx.get(d.get("function"))
        domain = ctx.domain_of(lf) if lf is not None else None
        if domain is not None and d.get("domain") and domain.uuid != d.get("domain"):
            yield issue(d, f"Dominio {ctx.label(d.get('domain'))}, ma la funzione logica {ctx.label(lf)} è del "
                           f"dominio {ctx.label(domain)}.", [lf, domain, d.get("domain")])


@check("SA4-08", "Motivazione della derivazione mancante", "A", "B6")
def sa4_no_scheme(ctx):
    for d in ctx.of("derived_requirement"):
        if not d.get("b6_scheme"):
            yield issue(d, "Motivazione della derivazione (schema B6) non indicata.")


@check("SA4-09", "Voce madre scomposta in un solo derivato o in derivati dello stesso dominio", "A", "B5 domanda 4")
def sa4_scomposition(ctx):
    for parent, derived in ctx.derived_by_parent.items():
        if len(derived) == 1:
            yield issue(derived[0], "Unico derivato della voce madre: la scomposizione serve a separare obblighi di "
                                    "domini diversi.", [parent])
            continue
        by_domain = defaultdict(list)
        for d in derived:
            if d.get("domain"):
                by_domain[d.get("domain")].append(d)
        for domain, same in by_domain.items():
            for d in same[1:]:
                yield issue(d, f"Stesso dominio {ctx.label(domain)} di {ctx.labels(same[:1])}, derivato della stessa "
                               "voce madre.", [same[0], parent])


@check("SA4-10", "Voce madre non ancora coperta da tutti i derivati", "I", "B5 domanda 4")
def sa4_parent_covered(ctx):
    for parent, derived in ctx.derived_by_parent.items():
        missing = [d for d in derived if not (ctx.get(d.get("function")) and ctx.get(d.get("function")).get("component"))]
        if missing and ctx.get(parent) is not None:
            yield issue(parent, f"Voce madre non ancora coperta: {ctx.labels(missing)} senza funzione logica "
                                "allocata a un componente.", missing)


# --- SA-5: functional exchanges -----------------------------------------------------------------------------

def _ends(ctx, fe):
    return ctx.get(fe.get("source")), ctx.get(fe.get("target"))


@check("SA5-01", "Produttore o utilizzatore mancante", "E", "B4")
def sa5_missing_end(ctx):
    for fe in ctx.of("functional_exchange"):
        a, b = _ends(ctx, fe)
        missing = [label for label, e in (("produttore", a), ("utilizzatore", b)) if e is None]
        if missing:
            yield issue(fe, f"Scambio senza {' e '.join(missing)}.", field="source" if a is None else "target")


@check("SA5-02", "Produttore e utilizzatore coincidono", "E", "B4")
def sa5_same_end(ctx):
    for fe in ctx.of("functional_exchange"):
        if fe.get("source") and fe.get("source") == fe.get("target"):
            yield issue(fe, "Produttore e utilizzatore coincidono.", [fe.get("source")])


@check("SA5-03", "Scambio tra due attori esterni", "E", "B4")
def sa5_two_actors(ctx):
    for fe in ctx.of("functional_exchange"):
        a, b = _ends(ctx, fe)
        if a is not None and b is not None and a.kind == b.kind == "external_actor":
            yield issue(fe, "Scambio tra due attori esterni: non descrive un comportamento del bordo.", [a, b])


@check("SA5-04", "Estremi di livelli diversi (funzione di sistema e funzione logica)", "E", "Parte II")
def sa5_levels(ctx):
    for fe in ctx.of("functional_exchange"):
        a, b = _ends(ctx, fe)
        if a is not None and b is not None and {a.kind, b.kind} == {"system_function", "logical_function"}:
            yield issue(fe, "Collega una funzione di sistema e una funzione logica: gli scambi SA collegano funzioni "
                            "di sistema, quelli LA funzioni logiche.", [a, b])


@check("SA5-05", "Estremo che è una funzione logica con sotto-funzioni", "A", "Parte VI")
def sa5_not_leaf(ctx):
    for fe in ctx.of("functional_exchange"):
        for e in _ends(ctx, fe):
            if e is not None and e.kind == "logical_function" and not ctx.is_leaf(e):
                yield issue(fe, f"{ctx.label(e)} ha sotto-funzioni: solo le funzioni foglia ricevono scambi.", [e])


@check("SA5-06", "Scambio senza dato di interfaccia", "E", "Checklist SA-5")
def sa5_no_item(ctx):
    for fe in ctx.of("functional_exchange"):
        if not fe.get("exchange_item"):
            yield issue(fe, "Scambio senza dato di interfaccia (Exchange Item del dizionario SA-6).")


@check("SA5-07", "Natura dello scambio diversa da quella dell'Exchange Item", "E", "B4")
def sa5_nature(ctx):
    for fe in ctx.of("functional_exchange"):
        item = ctx.get(fe.get("exchange_item"))
        if item is not None and fe.get("nature") and item.get("nature") and fe.get("nature") != item.get("nature"):
            yield issue(fe, f"Natura {fe.get('nature')}, ma {ctx.label(item)} è {item.get('nature')}.", [item])


@check("SA5-08", "Condizione di produzione incoerente con la natura", "A", "B4")
def sa5_condition(ctx):
    conditions = {n: c for n, c in (ctx.param("conditions") or {}).items() if c}
    for fe in ctx.of("functional_exchange"):
        nature, condition = ctx.nature(fe), fe.get("production_condition")
        if nature in conditions and condition and condition not in conditions[nature]:
            yield issue(fe, f"Condizione «{condition}» per un dato {nature}: attesa "
                            f"{' o '.join(f'«{c}»' for c in conditions[nature])}.")


@check("SA5-09", "L'ID FE-DFaa-DFbb non corrisponde ai domini degli estremi", "A", "Convenzioni di identificazione")
def sa5_id(ctx):
    for fe in ctx.of("functional_exchange"):
        a, b = _ends(ctx, fe)
        codes = (_domain_code(ctx.model, a), _domain_code(ctx.model, b))
        ident = fe.get("id") or ""
        if ident and all(codes) and not ident.startswith(f"FE-{codes[0]}-{codes[1]}-"):
            yield issue(fe, f"L'ID non corrisponde agli estremi: atteso FE-{codes[0]}-{codes[1]}-nn (usare «Rinumera»).")


@check("SA5-10", "Scambio duplicato", "A", "SA-5")
def sa5_duplicate(ctx):
    groups = defaultdict(list)
    for fe in ctx.of("functional_exchange"):
        if fe.get("source") and fe.get("target") and fe.get("exchange_item"):
            groups[(fe.get("source"), fe.get("target"), fe.get("exchange_item"))].append(fe)
    for same in groups.values():
        for fe in same[1:]:
            yield issue(fe, f"Stesso produttore, utilizzatore e dato di {ctx.label(same[0])}: uno scambio si registra "
                            "una volta e si riusa.", [same[0]])


@check("SA5-11", "Scambio tra domini non concordato, o concordato senza accordo", "A/E", "B4, checklist di revisione 6")
def sa5_agreement(ctx):
    for fe in ctx.of("functional_exchange"):
        domains = ctx.between_domains(fe)
        if domains is None:
            continue
        if fe.get("status") not in AGREED:
            yield issue(fe, f"Scambio tra {ctx.label(domains[0])} e {ctx.label(domains[1])} non ancora concordato.",
                        domains, WARNING)
        else:
            missing = [(name, label) for name, label in (("producer_agreement", "del produttore"),
                                                         ("consumer_agreement", "dell'utilizzatore"))
                       if not fe.get(name)]
            if missing:
                yield issue(fe, f"Stato «{fe.get('status')}» senza l'accordo {' e '.join(m[1] for m in missing)}.",
                            domains, ERROR, field=missing[0][0])


@check("SA5-12", "Clausole dello scambio non tracciate dagli estremi", "A", "B4")
def sa5_clauses(ctx):
    for fe in ctx.of("functional_exchange"):
        ends = [e for e in _ends(ctx, fe) if e is not None and e.kind != "external_actor"]
        if not ends:
            continue
        for uuid in fe.get("clauses") or []:
            item = ctx.get(uuid)
            if item is not None and not any(ctx.traces(e, item) for e in ends):
                yield issue(fe, f"La clausola {item.get('id')} non è tracciata né dal produttore né dall'utilizzatore.",
                            [item, *ends])


def _coded(item, types, variable):
    return item is not None and (item.get("type") in types or any(
        variable.match((row.get("variable") or "").strip()) for row in item.get("elements") or []))


@check("SA5-13", "Codifica esterna usata fuori dai domini di codifica", "A", "B4, SA-6", needs="coding_domains")
def sa5_coded(ctx):
    coding = set(ctx.param("coding_domains") or [])
    if not coding:
        return
    types = set(ctx.param("coded_types") or [])
    variable = re.compile(ctx.param("coded_variable") or CODED_VARIABLE.pattern)
    for fe in ctx.of("functional_exchange"):
        item = ctx.get(fe.get("exchange_item"))
        if not _coded(item, types, variable):
            continue
        for e in _ends(ctx, fe):
            if e is None or e.kind == "external_actor":
                continue
            domain = ctx.domain_of(e)
            if domain is not None and domain.uuid not in coding:
                yield issue(fe, f"{ctx.label(item)} contiene la codifica dei capitoli 7–8 ma arriva a {ctx.label(e)} "
                                f"({ctx.label(domain)}): fuori dai domini di codifica si usano dati logici.",
                            [item, e, domain])


# --- SA-6: exchange items -----------------------------------------------------------------------------------

def _producers(ctx, item, level):
    """Distinct producers of an exchange item among the exchanges of one level (SF and actors, or LF and actors)."""
    kinds = {"sa": ("system_function", "external_actor"), "la": ("logical_function", "external_actor")}[level]
    result = []
    for fe in ctx.exchanges_of_item.get(item.uuid, []):
        source = ctx.get(fe.get("source"))
        if source is not None and source.kind in kinds and source not in result:
            result.append(source)
    return result


@check("SA6-01", "Exchange Item con più funzioni produttrici", "E", "D10, Parte VI")
def sa6_producers(ctx):
    for item in ctx.of("exchange_item"):
        for level in ("sa", "la"):
            producers = _producers(ctx, item, level)
            if len(producers) > 1:
                yield issue(item, f"Prodotto da {len(producers)} funzioni ({ctx.labels(producers)}): ogni informazione "
                                  "ha una sola funzione produttrice.", producers)


@check("SA6-02", "Exchange Item senza produttore o senza utilizzatori", "A", "Checklist SA-6, B4")
def sa6_unused(ctx):
    for item in ctx.of("exchange_item"):
        if not ctx.exchanges_of_item.get(item.uuid):
            yield issue(item, "Nessuno scambio funzionale trasporta il dato: manca il produttore o l'utilizzatore.")


@check("SA6-03", "Exchange Item senza natura", "A", "B4")
def sa6_nature(ctx):
    for item in ctx.of("exchange_item"):
        if not item.get("nature"):
            yield issue(item, "Natura (FLOW, EVENT, OPERATION) non indicata.")


@check("SA6-04", "Messaggio o Pacchetto senza elementi", "A", "SA-6")
def sa6_no_elements(ctx):
    types = set(ctx.param("types") or [])
    for item in ctx.of("exchange_item"):
        if item.get("type") in types and not item.get("elements"):
            yield issue(item, f"{item.get('type')} senza elementi (variabili del capitolo 7).")


@check("SA6-05", "Elemento senza variabile del cap. 7, unità, campo o risoluzione", "A", "Checklist SA-6")
def sa6_element_fields(ctx):
    for item in ctx.of("exchange_item"):
        for n, row in enumerate(item.get("elements") or [], 1):
            missing = [label for name, label in (("variable", "variabile"), ("unit", "unità"), ("range", "campo"),
                                                 ("resolution", "risoluzione")) if not (row.get(name) or "").strip()]
            if missing:
                yield issue(item, f"Elemento {n} ({row.get('variable') or 'senza nome'}) senza {', '.join(missing)}.")


@check("SA6-06", "Variabile ripetuta nello stesso Exchange Item", "A", "SA-6")
def sa6_repeated_variable(ctx):
    for item in ctx.of("exchange_item"):
        counts = Counter((row.get("variable") or "").strip() for row in item.get("elements") or [])
        repeated = [v for v, n in counts.items() if v and n > 1]
        if repeated:
            yield issue(item, f"Variabili ripetute: {', '.join(repeated)}.")


@check("SA6-07", "Origine SRS vuota", "A", "SA-6")
def sa6_origin(ctx):
    for item in ctx.of("exchange_item"):
        if not item.get("srs_origin"):
            yield issue(item, "Origine SRS non indicata.")


@check("SA6-08", "Exchange Item con lo stesso nome", "A", "B4")
def sa6_same_name(ctx):
    groups = defaultdict(list)
    for item in ctx.of("exchange_item"):
        if item.get("name"):
            groups[" ".join(item.get("name").casefold().split())].append(item)
    for same in groups.values():
        for item in same:
            if len(same) > 1:
                yield issue(item, f"Stesso nome di {ctx.labels(o for o in same if o is not item)}: un dato si definisce "
                                  "una sola volta nel dizionario.", [o for o in same if o is not item])


# --- SA-7: functional chains --------------------------------------------------------------------------------

def _row_domain(ctx, row):
    f = ctx.get(row.get("function"))
    d = ctx.domain_of(f) if f is not None else None
    return d.uuid if d is not None else None


def chain_metrics(ctx, chain):
    """Crossings (changes of domain between steps), bounces (back to a domain already crossed in the same cycle),
    domains involved and cycles of a chain (A5)."""
    crossings = bounces = 0
    domains, cycles = set(), set()
    previous, cycle, seen = None, None, set()
    for _, row in ctx.chain_steps(chain):
        domain = _row_domain(ctx, row)
        if row.get("cycle") != cycle:
            cycle, seen, previous = row.get("cycle"), set(), None
        cycles.add(row.get("cycle"))
        if domain is None:
            continue
        domains.add(domain)
        if previous is not None and domain != previous:
            crossings += 1
            if domain in seen:
                bounces += 1
        seen.add(domain)
        previous = domain
    return {"crossings": crossings, "bounces": bounces, "domains": len(domains), "cycles": len(cycles)}


@check("SA7-01", "Percorso vuoto", "E", "SA-7")
def sa7_empty(ctx):
    for c in ctx.of("functional_chain"):
        if not ctx.chain_steps(c):
            yield issue(c, "La chain non ha passi.")


@check("SA7-02", "Passo senza funzione", "E", "Checklist SA-7")
def sa7_step_function(ctx):
    for c in ctx.of("functional_chain"):
        for n, row in ctx.chain_steps(c):
            if not row.get("function"):
                yield issue(c, f"Passo {n} senza funzione.")


@check("SA7-03", "Passo con una funzione logica", "A", "SA-7")
def sa7_logical_step(ctx):
    for c in ctx.of("functional_chain"):
        for n, row in ctx.chain_steps(c):
            f = ctx.get(row.get("function"))
            if f is not None and f.kind == "logical_function":
                yield issue(c, f"Passo {n}: {ctx.label(f)} è una funzione logica; SA-7 usa le funzioni di sistema.", [f])


@check("SA7-04", "Inizio o fine non su un attore esterno", "E", "Checklist SA-7")
def sa7_actor_ends(ctx):
    """The «Scambio» of a step is the one that carries the data it produces: the chain starts on an actor when the
    function of the first step receives an exchange from an actor, and ends on one when the last exchange goes to
    an actor."""
    for c in ctx.of("functional_chain"):
        steps = ctx.chain_steps(c)
        if not steps:
            continue
        first = ctx.get(steps[0][1].get("function"))
        if first is not None:
            receivers = [first, *ctx.lfs_refining.get(first.uuid, [])]
            senders = [ctx.get(fe.get("source")) for f in receivers for fe in ctx.exchanges_to.get(f.uuid, [])]
            if not any(s is not None and s.kind == "external_actor" for s in senders):
                yield issue(c, f"La chain non inizia su un attore esterno: {ctx.label(first)}, al primo passo, non "
                               "riceve scambi da un attore.", [first])
        exchanges = [ctx.get(row.get("exchange")) for _, row in steps if ctx.get(row.get("exchange"))]
        last = ctx.get(exchanges[-1].get("target")) if exchanges else None
        if last is None or last.kind != "external_actor":
            yield issue(c, "La chain non finisce su un attore esterno: l'ultimo scambio "
                           f"{'(' + ctx.label(exchanges[-1]) + ') ' if exchanges else ''}non arriva a un attore.",
                        exchanges[-1:])


@check("SA7-05", "Trigger o effetto osservabile finale vuoti", "A", "SA-7")
def sa7_context(ctx):
    for c in ctx.of("functional_chain"):
        missing = [(name, label) for name, label in (("trigger", "trigger"),
                                                     ("final_effect", "effetto osservabile finale"))
                   if not c.get(name)]
        if missing:
            yield issue(c, f"Non compilati: {', '.join(m[1] for m in missing)}.", field=missing[0][0])


def _same_function(ctx, a, b):
    """The end of an exchange is the function of a step (or refines it)."""
    if a is None or b is None:
        return False
    return a.uuid == b.uuid or ctx.sf_of(a) is b or ctx.sf_of(b) is a


@check("SA7-06", "Scambio del passo non continuo con i passi", "E", "Checklist SA-7 (continuità)")
def sa7_continuity(ctx):
    for c in ctx.of("functional_chain"):
        steps = ctx.chain_steps(c)
        for i, (n, row) in enumerate(steps):
            fe, function = ctx.get(row.get("exchange")), ctx.get(row.get("function"))
            if fe is None or function is None:
                continue
            source, target = ctx.get(fe.get("source")), ctx.get(fe.get("target"))
            nxt = ctx.get(steps[i + 1][1].get("function")) if i + 1 < len(steps) else None
            if not _same_function(ctx, source, function) and not (i == 0 and source is not None
                                                                   and source.kind == "external_actor"):
                yield issue(c, f"Passo {n}: lo scambio {ctx.label(fe)} non parte da {ctx.label(function)}.",
                            [fe, function])
            elif nxt is not None and not _same_function(ctx, target, nxt) and not _same_function(ctx, target, function):
                yield issue(c, f"Passo {n}: lo scambio {ctx.label(fe)} non arriva alla funzione del passo successivo "
                               f"({ctx.label(nxt)}).", [fe, nxt])


@check("SA7-07", "Cambio di dominio senza scambio concordato", "E/A", "Checklist SA-7")
def sa7_domain_change(ctx):
    for c in ctx.of("functional_chain"):
        steps = ctx.chain_steps(c)
        for (n, row), (_, nxt) in zip(steps, steps[1:]):
            a, b = _row_domain(ctx, row), _row_domain(ctx, nxt)
            if a is None or b is None or a == b:
                continue
            fe = ctx.get(row.get("exchange"))
            if fe is None:
                yield issue(c, f"Passo {n}: cambio di dominio ({ctx.label(a)} → {ctx.label(b)}) senza scambio "
                               "funzionale.", [a, b], ERROR)
            elif fe.get("status") not in AGREED:
                yield issue(c, f"Passo {n}: cambio di dominio con {ctx.label(fe)}, non ancora concordato.", [fe], WARNING)


@check("SA7-08", "Natura del passo diversa da quella dello scambio", "A", "B4")
def sa7_step_nature(ctx):
    for c in ctx.of("functional_chain"):
        for n, row in ctx.chain_steps(c):
            fe = ctx.get(row.get("exchange"))
            nature = ctx.nature(fe) if fe is not None else None
            if nature and row.get("nature") and row.get("nature") != nature:
                yield issue(c, f"Passo {n}: natura {row.get('nature')}, lo scambio {ctx.label(fe)} è {nature}.", [fe])


@check("SA7-09", "Passo senza voce SRS, o con una voce non di bordo", "A", "Checklist SA-7")
def sa7_step_items(ctx):
    for c in ctx.of("functional_chain"):
        for n, row in ctx.chain_steps(c):
            if not (row.get("srs") or "").strip():
                yield issue(c, f"Passo {n} senza voce SRS.")
                continue
            items = ctx.requirements_in_text(row.get("srs"))
            for item in items:
                if ctx.categories(item) and not ctx.is_board(item):
                    yield issue(c, f"Passo {n}: {item.get('id')} non è una voce di bordo.", [item])


@check("SA7-10", "Voce del passo non tracciata dalla funzione del passo", "A", "SA-3 ↔ SA-7")
def sa7_step_traced(ctx):
    for c in ctx.of("functional_chain"):
        for n, row in ctx.chain_steps(c):
            function = ctx.get(row.get("function"))
            if function is None:
                continue
            for item in ctx.requirements_in_text(row.get("srs")):
                if not ctx.traces(function, item):
                    yield issue(c, f"Passo {n}: {item.get('id')} non è tracciata da {ctx.label(function)}.",
                                [item, function])


@check("SA7-11", "Cambio di ciclo senza riga di attesa, o riga di attesa compilata", "A", "Checklist SA-7")
def sa7_cycles(ctx):
    for c in ctx.of("functional_chain"):
        rows, previous_cycle, previous_wait = c.get("steps") or [], None, False
        for i, row in enumerate(rows, 1):
            if ctx.is_wait(row):
                filled = [k for k in ("function", "data", "nature", "exchange", "srs", "component") if row.get(k)]
                if filled:
                    yield issue(c, f"Riga {i} di attesa con altre colonne compilate: vanno lasciate vuote.")
                previous_wait = True
                continue
            if previous_cycle is not None and row.get("cycle") != previous_cycle and not previous_wait:
                yield issue(c, f"Riga {i}: nuovo ciclo ({row.get('cycle')}) senza una riga di attesa prima.")
            previous_cycle, previous_wait = row.get("cycle"), False


@check("SA7-12", "Rimbalzo nello stesso ciclo senza ADR collegata", "A", "D4, A5")
def sa7_bounces(ctx):
    for c in ctx.of("functional_chain"):
        bounces = chain_metrics(ctx, c)["bounces"]
        if bounces and not c.get("adrs"):
            yield issue(c, f"{bounces} rimbalzi tra domini nello stesso ciclo senza ADR: il confine va riesaminato o "
                           "la scelta motivata.")


@check("SA7-13", "Dominio responsabile mancante o non coinvolto", "A", "SA-7")
def sa7_responsible(ctx):
    for c in ctx.of("functional_chain"):
        domain = c.get("responsible_domain")
        involved = {_row_domain(ctx, row) for _, row in ctx.chain_steps(c)} - {None}
        if not domain:
            yield issue(c, "Dominio responsabile non indicato.")
        elif involved and domain not in involved:
            yield issue(c, f"Il dominio responsabile {ctx.label(domain)} non compare nei passi.", [domain])


@check("SA7-14", "Componente del passo diverso dall'allocazione delle funzioni logiche", "A", "SA-7 ↔ LA-2")
def sa7_step_component(ctx):
    for c in ctx.of("functional_chain"):
        for n, row in ctx.chain_steps(c):
            function, component = ctx.get(row.get("function")), row.get("component")
            used = ctx.components_of(function) if function is not None else None
            if component and used and not any(u == component or ctx.within(u, component) for u in used):
                yield issue(c, f"Passo {n}: componente {ctx.label(component)}, ma {ctx.label(function)} è allocata a "
                               f"{ctx.labels(used)}.", [component, function, *used])


@check("SA7-15", "Chain di procedura: passo in un altro dominio senza requisito derivato", "A",
       "Checklist SA-7, B6 schema 2", needs="procedure_domain")
def sa7_procedure_derived(ctx):
    procedure = ctx.param("procedure_domain")
    if not procedure:
        return
    for c in ctx.of("functional_chain"):
        if c.get("responsible_domain") != procedure:
            continue
        items = {i.uuid for _, row in ctx.chain_steps(c) for i in ctx.requirements_in_text(row.get("srs"))}
        derived = [d for i in items for d in ctx.derived_by_parent.get(i, [])]
        for n, row in ctx.chain_steps(c):
            domain = _row_domain(ctx, row)
            if domain and domain != procedure and not any(d.get("domain") == domain for d in derived):
                yield issue(c, f"Passo {n} nel dominio {ctx.label(domain)} senza requisito derivato: le azioni della "
                               "procedura verso altri domini si scompongono in derivati.", [domain])


@check("SA7-16", "Varianti senza tipo, oppure oracolo o caso di test vuoti", "A", "Checklist SA-7")
def sa7_variants(ctx):
    for c in ctx.of("functional_chain"):
        for i, row in enumerate(c.get("variants") or [], 1):
            if not row.get("type"):
                yield issue(c, f"Variante {i} ({row.get('variant') or 'senza nome'}) senza tipo.")
        missing = [(name, label) for name, label in (("oracle", "oracolo"),
                                                     ("integration_test", "caso di test di integrazione"))
                   if not c.get(name)]
        if missing:
            yield issue(c, f"Non compilati: {', '.join(m[1] for m in missing)}.", field=missing[0][0])


@check("SA7-17", "Chain non realizzata in LA-4", "I", "LA-4")
def sa7_not_realized(ctx):
    for c in ctx.of("functional_chain"):
        if not ctx.realizations_of_chain.get(c.uuid):
            yield issue(c, "Nessuna realizzazione in LA-4.")
