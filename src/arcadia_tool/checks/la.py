"""Checks of the Logical Architecture sheets (LA-1…LA-4) and of the cross-cutting ones (EPBS-1, X-1, X-2)."""
import re
from collections import defaultdict

from arcadia_tool.checks import ERROR, WARNING, check, issue
from arcadia_tool.checks.context import sentences
from arcadia_tool.checks.sa import _at_most, _name_checks
from arcadia_tool.model.element import natural_key


def _cycle(ctx, element, field):
    """The element is its own ancestor along `field` (e.g. a component that is its own macro-component)."""
    seen, current = set(), ctx.get(element.get(field))
    while current is not None and current.uuid not in seen:
        if current.uuid == element.uuid:
            return True
        seen.add(current.uuid)
        current = ctx.get(current.get(field))
    return False


# --- LA-1: logical components -------------------------------------------------------------------------------

@check("LA1-01", "Ciclo nei macro-componenti", "E", "LA-1")
def la1_cycle(ctx):
    for c in ctx.of("logical_component"):
        if _cycle(ctx, c, "parent"):
            yield issue(c, "Il componente risulta macro-componente di sé stesso.")


@check("LA1-02", "Dato scritto da più componenti", "E", "D10, checklist LA-1")
def la1_single_writer(ctx):
    for item in ctx.of("exchange_item"):
        writers = defaultdict(list)
        for fe in ctx.exchanges_of_item.get(item.uuid, []):
            source = ctx.get(fe.get("source"))
            if source is not None and source.kind == "logical_function" and source.get("component"):
                writers[source.get("component")].append(source)
        if len(writers) > 1:
            for component in writers:
                others = [c for c in writers if c != component]
                yield issue(component, f"Scrive {ctx.label(item)}, scritto anche da {ctx.labels(others)}: ogni dato "
                                       "ha un solo componente che lo scrive.", [item, *others, *writers[component]])


@check("LA1-03", "Componente senza funzioni logiche allocate", "A", "LA-1")
def la1_empty(ctx):
    for c in ctx.of("logical_component"):
        if not any(ctx.within(lf.get("component"), c.uuid) for lf in ctx.of("logical_function")):
            yield issue(c, "Nessuna funzione logica allocata al componente o ai suoi sottocomponenti.")


@check("LA1-04", "Funzioni allocate a un macro-componente che ha sottocomponenti", "A", "Parte V")
def la1_macro_allocation(ctx):
    for c in ctx.of("logical_component"):
        direct = ctx.lfs_of_component.get(c.uuid, [])
        if direct and ctx.lc_children.get(c.uuid):
            yield issue(c, f"Ha sottocomponenti ma anche funzioni allocate direttamente: {ctx.labels(direct)}.", direct)


@check("LA1-05", "Responsabilità vuota o più lunga di tre frasi", "A", "LA-1")
def la1_responsibility(ctx):
    limit = ctx.param("max_sentences")
    for c in ctx.of("logical_component"):
        n = len(sentences(c.get("responsibility")))
        if n == 0:
            yield issue(c, "Responsabilità non compilata.")
        elif n > limit:
            shown = "due o tre frasi" if limit == 3 else _at_most(limit)
            yield issue(c, f"Responsabilità di {n} frasi: va descritta in {shown}.")


@check("LA1-06", "Vincoli di sicurezza vuoti", "A", "LA-1")
def la1_safety(ctx):
    for c in ctx.of("logical_component"):
        if not c.get("safety_constraints"):
            yield issue(c, "Vincoli di sicurezza (SIL, barriere, dati safety-related) non compilati.")


@check("LA1-07", "Componente non assegnato a un team, o assegnato a più team", "A", "EPBS-1")
def la1_team(ctx):
    for c in ctx.of("logical_component"):
        teams = ctx.teams_of_component.get(c.uuid, [])
        if not teams:
            yield issue(c, "Componente non assegnato a nessun team.")
        elif len(teams) > 1:
            yield issue(c, f"Componente assegnato a più team: {ctx.labels(teams)}.", teams)


@check("LA1-08", "Componente ricalcato su un dominio", "I", "«Non creare un componente per dominio»")
def la1_named_as_domain(ctx):
    domains = {(d.get("name") or "").casefold(): d for d in ctx.of("domain") if d.get("name")}
    for c in ctx.of("logical_component"):
        d = domains.get((c.get("name") or "").casefold())
        if d is not None:
            yield issue(c, f"Stesso nome del dominio {ctx.label(d)}: i componenti emergono dalle responsabilità, "
                           "non dai domini.", [d])


# --- LA-2: logical functions --------------------------------------------------------------------------------

@check("LA2-01", "Funzione logica non riconducibile a una funzione di sistema", "E", "Parte II")
def la2_no_sf(ctx):
    for lf in ctx.of("logical_function"):
        if ctx.sf_of(lf) is None and not lf.get("contributes_to"):
            yield issue(lf, "Non raffina né contribuisce ad alcuna funzione di sistema (nemmeno tramite la funzione "
                            "padre).")


@check("LA2-02", "Funzione logica foglia senza componente", "E", "LA, checklist LA-2")
def la2_leaf_unallocated(ctx):
    for lf in ctx.of("logical_function"):
        if ctx.is_leaf(lf) and not lf.get("component"):
            yield issue(lf, "Funzione foglia non allocata a un componente logico.")


@check("LA2-03", "Funzione con sotto-funzioni allocata a un componente", "A", "Checklist LA-2")
def la2_parent_allocated(ctx):
    for lf in ctx.of("logical_function"):
        if not ctx.is_leaf(lf) and lf.get("component"):
            yield issue(lf, "Ha sotto-funzioni ma è allocata: l'allocazione va sulle funzioni foglia.",
                        [lf.get("component"), *ctx.lf_children[lf.uuid]])


@check("LA2-04", "Ciclo nella gerarchia delle funzioni logiche", "E", "LA-2")
def la2_cycle(ctx):
    for lf in ctx.of("logical_function"):
        if _cycle(ctx, lf, "parent"):
            yield issue(lf, "La funzione risulta padre di sé stessa.")


@check("LA2-05", "La funzione padre raffina una funzione di sistema diversa", "A", "LA-2")
def la2_parent_other_sf(ctx):
    for lf in ctx.of("logical_function"):
        parent = ctx.get(lf.get("parent"))
        if parent is not None and lf.get("refines") and ctx.sf_of(parent) is not None \
                and ctx.sf_of(parent).uuid != lf.get("refines"):
            yield issue(lf, f"Raffina {ctx.label(lf.get('refines'))}, la funzione padre {ctx.label(parent)} raffina "
                            f"{ctx.label(ctx.sf_of(parent))}.", [parent, lf.get("refines"), ctx.sf_of(parent)])


@check("LA2-06", "L'ID non corrisponde alla funzione di sistema raffinata", "A", "Convenzioni di identificazione")
def la2_id(ctx):
    for lf in ctx.of("logical_function"):
        sf = ctx.get(lf.get("refines"))
        ident, sf_id = lf.get("id") or "", (sf.get("id") or "") if sf is not None else ""
        if ident.startswith("LF-") and sf_id.startswith("SF-") and not ident.startswith(f"LF-{sf_id[3:]}-"):
            yield issue(lf, f"L'ID non corrisponde a {sf_id}: atteso LF-{sf_id[3:]}-kk (usare «Rinumera»).", [sf])


@check("LA2-07", "La funzione raffinata è ripetuta in «Contribuisce anche a»", "A", "LA-2")
def la2_contributes_twice(ctx):
    for lf in ctx.of("logical_function"):
        if lf.get("refines") and lf.get("refines") in (lf.get("contributes_to") or []):
            yield issue(lf, f"{ctx.label(lf.get('refines'))} è sia raffinata sia in «Contribuisce anche a».",
                        [lf.get("refines")])


@check("LA2-08", "Funzione foglia senza voci di dettaglio né requisiti derivati", "A", "D8, checklist LA-2")
def la2_not_justified(ctx):
    for lf in ctx.of("logical_function"):
        if ctx.is_leaf(lf) and not ctx.traced(lf) and not ctx.derived_by_function.get(lf.uuid):
            yield issue(lf, "Funzione foglia non giustificata da alcuna voce SRS o requisito derivato.")


@check("LA2-09", "Voce di dettaglio esterna alla funzione di sistema raffinata", "A", "B5")
def la2_detail_outside(ctx):
    for lf in ctx.of("logical_function"):
        sf = ctx.sf_of(lf)
        if sf is None or not ctx.traced(sf):
            continue
        contributes = [ctx.get(u) for u in lf.get("contributes_to") or [] if ctx.get(u) is not None]
        for uuid in ctx.traced(lf):
            item = ctx.get(uuid)
            if item is None:
                continue
            inside = any(ctx.traces(f, item) for f in [sf, *contributes]) or any(
                ctx.get(s) is not None and uuid in ctx.ancestors(ctx.get(s)) for s in ctx.traced(sf))
            if not inside:
                yield issue(lf, f"{item.get('id')} non appartiene alle sezioni o clausole di {ctx.label(sf)}.",
                            [item, sf])


@check("LA2-10", "Requisito derivato allocato a una funzione con sotto-funzioni", "E", "SA-4 ↔ LA-2")
def la2_derived_on_parent(ctx):
    for lf in ctx.of("logical_function"):
        derived = ctx.derived_by_function.get(lf.uuid, [])
        if derived and not ctx.is_leaf(lf):
            yield issue(lf, f"Ha sotto-funzioni ma le sono allocati i requisiti derivati {ctx.labels(derived)}: vanno "
                            "su una funzione foglia.", derived)


@check("LA2-11", "Componente non previsto dal dominio", "A", "SA-1 ↔ LA-2")
def la2_component_not_planned(ctx):
    for lf in ctx.of("logical_function"):
        domain, component = ctx.domain_of(lf), lf.get("component")
        planned = set(domain.get("planned_components") or []) if domain is not None else set()
        if component and planned and not any(component == p or ctx.within(component, p) for p in planned):
            yield issue(lf, f"Allocata a {ctx.label(component)}, non tra i componenti previsti dal dominio "
                            f"{ctx.label(domain)}.", [component, domain])


@check("LA2-12", "Nome non verbo + oggetto, o con sigle di modo, livello o paragrafo", "A", "D5")
def la2_name(ctx):
    for e, _, message in _name_checks(ctx, ctx.of("logical_function")):
        yield issue(e, message)


@check("LA2-13", "Scambio tra domini senza scambio corrispondente in SA", "A", "Parte II, checklist LA-2")
def la2_exchange_refines(ctx):
    sa_pairs = set()
    for fe in ctx.of("functional_exchange"):
        a, b = ctx.get(fe.get("source")), ctx.get(fe.get("target"))
        if a is not None and b is not None and a.kind == b.kind == "system_function":
            sa_pairs.add((a.uuid, b.uuid))
    for fe in ctx.of("functional_exchange"):
        a, b = ctx.get(fe.get("source")), ctx.get(fe.get("target"))
        if a is None or b is None or not (a.kind == b.kind == "logical_function") or ctx.between_domains(fe) is None:
            continue
        sa, sb = ctx.sf_of(a), ctx.sf_of(b)
        if sa is not None and sb is not None and (sa.uuid, sb.uuid) not in sa_pairs:
            yield issue(fe, f"Scambio tra domini senza uno scambio SA tra {ctx.label(sa)} e {ctx.label(sb)}.", [sa, sb])


@check("LA2-14", "Raffina una funzione di sistema non approvata", "A", "Ordine di compilazione (gate SA)")
def la2_sf_not_approved(ctx):
    for lf in ctx.of("logical_function"):
        sf = ctx.get(lf.get("refines"))
        if sf is not None and not ctx.approved(sf):
            yield issue(lf, f"Raffina {ctx.label(sf)}, non ancora approvata: le funzioni logiche seguono il gate SA.",
                        [sf])


def _signature(ctx, lf):
    incoming = frozenset((fe.get("source"), fe.get("exchange_item")) for fe in ctx.exchanges_to.get(lf.uuid, []))
    outgoing = frozenset((fe.get("target"), fe.get("exchange_item")) for fe in ctx.exchanges_from.get(lf.uuid, []))
    return incoming, outgoing


@check("LA2-15", "Funzioni sorelle con gli stessi scambi e lo stesso componente", "I", "Parte V")
def la2_overdecomposed(ctx):
    groups = defaultdict(list)
    for lf in ctx.of("logical_function"):
        incoming, outgoing = _signature(ctx, lf)
        if incoming or outgoing:
            sibling = lf.get("parent") or lf.get("refines")
            groups[(sibling, lf.get("component"), incoming, outgoing)].append(lf)
    for same in groups.values():
        for lf in same:
            if len(same) > 1:
                yield issue(lf, f"Stessi ingressi, uscite e componente di {ctx.labels(o for o in same if o is not lf)}: "
                                "la separazione potrebbe essere sovra-descrittiva.", [o for o in same if o is not lf])


# --- LA-3: component exchanges ------------------------------------------------------------------------------

def _end_components(ctx, fe):
    return ctx.components_of(ctx.get(fe.get("source"))), ctx.components_of(ctx.get(fe.get("target")))


def _matches(ctx, components, ce_end):
    """The components of an end of a functional exchange are the end of the component exchange (or inside it)."""
    return components is None or not components or any(c == ce_end or ctx.within(c, ce_end) for c in components)


def _cross_component(ctx, fe):
    a, b = _end_components(ctx, fe)
    return bool(a) and bool(b) and not (a & b)


@check("LA3-01", "Componente di partenza o di arrivo mancante, o coincidenti", "E", "LA-3")
def la3_ends(ctx):
    for ce in ctx.of("component_exchange"):
        if not ce.get("source") or not ce.get("target"):
            yield issue(ce, "Component Exchange senza componente di partenza o di arrivo.")
        elif ce.get("source") == ce.get("target"):
            yield issue(ce, "Componente di partenza e di arrivo coincidono.", [ce.get("source")])


@check("LA3-02", "Lo scambio funzionale realizzato non collega i due componenti", "E", "Parte IV")
def la3_realizes_wrong(ctx):
    for ce in ctx.of("component_exchange"):
        for uuid in ce.get("realizes") or []:
            fe = ctx.get(uuid)
            if fe is None:
                continue
            a, b = _end_components(ctx, fe)
            if not _matches(ctx, a, ce.get("source")) or not _matches(ctx, b, ce.get("target")):
                yield issue(ce, f"Realizza {ctx.label(fe)}, le cui funzioni sono allocate a "
                                f"{ctx.labels(sorted(a or []))} → {ctx.labels(sorted(b or []))}, non a "
                                f"{ctx.label(ce.get('source'))} → {ctx.label(ce.get('target'))}.", [fe])


@check("LA3-03", "Scambio tra funzioni su componenti diversi non realizzato", "E", "Checklist LA-3")
def la3_not_realized(ctx):
    for fe in ctx.of("functional_exchange"):
        if _cross_component(ctx, fe) and not ctx.component_exchanges_realizing.get(fe.uuid):
            a, b = _end_components(ctx, fe)
            yield issue(fe, f"Attraversa il confine {ctx.labels(sorted(a))} → {ctx.labels(sorted(b))} ma nessun "
                            "Component Exchange lo realizza.", [*a, *b])


@check("LA3-04", "Component Exchange che realizza uno scambio interno a un componente", "A", "Parte IV")
def la3_internal(ctx):
    for ce in ctx.of("component_exchange"):
        for uuid in ce.get("realizes") or []:
            fe = ctx.get(uuid)
            a, b = _end_components(ctx, fe) if fe is not None else (None, None)
            if a and b and a == b and len(a) == 1:
                yield issue(ce, f"{ctx.label(fe)} è interno a {ctx.labels(a)}: gli scambi interni non generano "
                                "interfacce.", [fe])


@check("LA3-05", "Component Exchange senza scambio funzionale realizzato", "A", "Parte IV")
def la3_no_fe(ctx):
    for ce in ctx.of("component_exchange"):
        if not ce.get("realizes"):
            yield issue(ce, "Non realizza alcuno scambio funzionale: interfaccia senza giustificazione funzionale.")


@check("LA3-06", "Exchange Item diverso da quello degli scambi realizzati", "A", "Checklist LA-3")
def la3_item(ctx):
    for ce in ctx.of("component_exchange"):
        items = {ctx.get(u).get("exchange_item") for u in ce.get("realizes") or [] if ctx.get(u) is not None} - {None}
        if ce.get("exchange_item") and items and ce.get("exchange_item") not in items:
            yield issue(ce, f"Exchange Item {ctx.label(ce.get('exchange_item'))}, gli scambi realizzati trasportano "
                            f"{ctx.labels(ctx.get(i) for i in items)}.", [ce.get("exchange_item"), *items])


@check("LA3-07", "Realizza uno scambio tra domini non ancora approvato", "A", "LA (interfacce già approvate)")
def la3_fe_not_approved(ctx):
    for ce in ctx.of("component_exchange"):
        for uuid in ce.get("realizes") or []:
            fe = ctx.get(uuid)
            if fe is not None and ctx.between_domains(fe) is not None and fe.get("status") != "Approvato":
                yield issue(ce, f"Realizza {ctx.label(fe)}, scambio tra domini non ancora approvato.", [fe])


@check("LA3-08", "L'ID CE-LCaa-LCbb non corrisponde ai componenti", "A", "Convenzioni di identificazione")
def la3_id(ctx):
    for ce in ctx.of("component_exchange"):
        a, b = ctx.get(ce.get("source")), ctx.get(ce.get("target"))
        if a is None or b is None or not a.get("id") or not b.get("id") or not ce.get("id"):
            continue
        prefix = f"CE-{a.get('id').replace('-', '')}-{b.get('id').replace('-', '')}-"
        if not ce.get("id").startswith(prefix):
            yield issue(ce, f"L'ID non corrisponde ai componenti: atteso {prefix}nn (usare «Rinumera»).", [a, b])


@check("LA3-09", "Component Exchange duplicato", "A", "LA-3")
def la3_duplicate(ctx):
    groups = defaultdict(list)
    for ce in ctx.of("component_exchange"):
        if ce.get("source") and ce.get("target") and ce.get("exchange_item"):
            groups[(ce.get("source"), ce.get("target"), ce.get("exchange_item"))].append(ce)
    for same in groups.values():
        for ce in same[1:]:
            yield issue(ce, f"Stessi componenti e dato di {ctx.label(same[0])}.", [same[0]])


@check("LA3-10", "Ciclo di produzione e lettura non compilato", "A", "Checklist LA-3")
def la3_cycle_rw(ctx):
    for ce in ctx.of("component_exchange"):
        if not ce.get("cycle_rw"):
            yield issue(ce, "Ciclo di produzione e lettura non compilato: il dato va letto dopo essere stato scritto, "
                            "oppure la lettura del ciclo precedente va motivata.")


# --- LA-4: realization of the chains ------------------------------------------------------------------------

def _sa_steps(ctx, realization):
    chain = ctx.get(realization.get("chain"))
    return dict(ctx.chain_steps(chain)) if chain is not None else {}


def _step_numbers(row):
    return [int(n) for n in re.findall(r"\d+", row.get("sa_step") or "")]


def _step_problems(ctx, realization):
    """(row number, message, related, severity) of the steps of a realization that are not coherent."""
    sa_steps = _sa_steps(ctx, realization)
    rows = realization.get("steps") or []
    for i, row in enumerate(rows, 1):
        lf, component = ctx.get(row.get("logical_function")), row.get("component")
        if lf is None or not component:
            yield i, "LA4-02", "senza funzione logica o componente", [], ERROR
            continue
        for n in _step_numbers(row):
            sa_row = sa_steps.get(n)
            sf = ctx.get(sa_row.get("function")) if sa_row else None
            if sf is not None and ctx.sf_of(lf) is not sf and sf.uuid not in (lf.get("contributes_to") or []):
                yield i, "LA4-04", (f"{ctx.label(lf)} non raffina {ctx.label(sf)} del passo SA {n}"), [lf, sf], ERROR
        if ctx.get(lf.get("component")) is not None and not (lf.get("component") == component
                                                             or ctx.within(lf.get("component"), component)):
            yield i, "LA4-05", (f"componente {ctx.label(component)}, ma {ctx.label(lf)} è allocata a "
                                f"{ctx.label(lf.get('component'))}"), [component, lf, lf.get("component")], ERROR


@check("LA4-01", "Realizzazione senza chain, o più realizzazioni della stessa chain", "E/A", "LA-4")
def la4_chain(ctx):
    for r in ctx.of("chain_realization"):
        if not r.get("chain"):
            yield issue(r, "Realizzazione senza functional chain.", (), ERROR)
    for chain, realizations in ctx.realizations_of_chain.items():
        for r in realizations[1:]:
            yield issue(r, f"La chain {ctx.label(chain)} ha {len(realizations)} realizzazioni.", [chain, realizations[0]],
                        WARNING)


def _problems_of(ctx, code):
    for r in ctx.of("chain_realization"):
        for i, problem_code, message, related, severity in _step_problems(ctx, r):
            if problem_code == code:
                yield issue(r, f"Passo {i}: {message}.", related, severity)


@check("LA4-02", "Passo senza funzione logica o componente", "E", "Checklist LA-4")
def la4_step_incomplete(ctx):
    yield from _problems_of(ctx, "LA4-02")


@check("LA4-03", "Passi della chain SA non coperti", "A", "LA-4")
def la4_coverage(ctx):
    for r in ctx.of("chain_realization"):
        sa_steps = _sa_steps(ctx, r)
        covered = {n for row in r.get("steps") or [] for n in _step_numbers(row)}
        missing = sorted(set(sa_steps) - covered)
        if sa_steps and missing:
            yield issue(r, f"Passi della chain SA non coperti: {', '.join(map(str, missing))}.", [r.get("chain")])


@check("LA4-04", "La funzione logica del passo non raffina la funzione del passo SA", "E", "SA-7 ↔ LA-4")
def la4_refines(ctx):
    yield from _problems_of(ctx, "LA4-04")


@check("LA4-05", "Componente del passo diverso dall'allocazione della funzione logica", "E", "LA-2 ↔ LA-4")
def la4_component(ctx):
    yield from _problems_of(ctx, "LA4-05")


@check("LA4-06", "Component Exchange in uscita incoerente con i componenti dei passi", "A", "LA-3 ↔ LA-4")
def la4_out_exchange(ctx):
    for r in ctx.of("chain_realization"):
        rows = r.get("steps") or []
        for i, row in enumerate(rows, 1):
            ce = ctx.get(row.get("out_exchange"))
            if ce is None:
                continue
            component = row.get("component")
            nxt = rows[i].get("component") if i < len(rows) else None
            if component and ce.get("source") and not (ce.get("source") == component
                                                       or ctx.within(component, ce.get("source"))):
                yield issue(r, f"Passo {i}: {ctx.label(ce)} non parte da {ctx.label(component)}.", [ce, component])
            elif nxt and ce.get("target") and not (ce.get("target") == nxt or ctx.within(nxt, ce.get("target"))):
                yield issue(r, f"Passo {i}: {ctx.label(ce)} non arriva a {ctx.label(nxt)}, componente del passo "
                               "successivo.", [ce, nxt])


@check("LA4-07", "Cicli non in ordine, senza nota", "A", "Checklist LA-4")
def la4_cycle_order(ctx):
    for r in ctx.of("chain_realization"):
        previous = None
        for i, row in enumerate(r.get("steps") or [], 1):
            cycle = row.get("cycle")
            if cycle and previous and natural_key(cycle) < natural_key(previous) and not row.get("notes"):
                yield issue(r, f"Passo {i}: ciclo {cycle} dopo il ciclo {previous}, senza nota che lo motivi.")
            previous = cycle or previous


@check("LA4-08", "Componente attraversato due volte nello stesso ciclo, senza nota", "A", "Checklist LA-4")
def la4_component_twice(ctx):
    for r in ctx.of("chain_realization"):
        seen, previous = defaultdict(set), None
        for i, row in enumerate(r.get("steps") or [], 1):
            component, cycle = row.get("component"), row.get("cycle")
            if not component:
                continue
            if component in seen[cycle] and component != previous and not row.get("notes"):
                yield issue(r, f"Passo {i}: {ctx.label(component)} è attraversato due volte nel ciclo {cycle} senza "
                               "motivo indicato.", [component])
            seen[cycle].add(component)
            previous = component


@check("LA4-09", "Esito incoerente: «Non eseguibile» senza motivo o «Eseguibile» con passi in errore", "E", "LA-4")
def la4_outcome(ctx):
    for r in ctx.of("chain_realization"):
        if r.get("outcome") == "Non eseguibile" and not r.get("outcome_reason"):
            yield issue(r, "Esito «Non eseguibile» senza motivo.")
        elif r.get("outcome") == "Eseguibile":
            problems = list(_step_problems(ctx, r))
            if problems:
                steps = sorted({p[0] for p in problems})
                yield issue(r, f"Esito «Eseguibile» con passi incoerenti: {', '.join(map(str, steps))}.")


@check("LA4-10", "Realizzazione di una chain SA non approvata", "A", "Ordine di compilazione")
def la4_chain_not_approved(ctx):
    for r in ctx.of("chain_realization"):
        chain = ctx.get(r.get("chain"))
        if chain is not None and not ctx.approved(chain):
            yield issue(r, f"La chain {ctx.label(chain)} non è ancora approvata.", [chain])


# --- Team (EPBS-1), ADR (X-1), CQ (X-2) ---------------------------------------------------------------------

@check("EPBS-01", "Team senza domini (esclusa la Design Authority)", "A", "EPBS-1")
def epbs_no_domains(ctx):
    for t in ctx.of("team"):
        if not t.get("domains") and not t.get("design_authority"):
            yield issue(t, "Team senza domini: ogni team ha almeno un dominio.")


@check("EPBS-02", "Referente non tra i membri del team", "E", "EPBS-1")
def epbs_referent(ctx):
    for t in ctx.of("team"):
        if t.get("referent") and t.get("referent") not in (t.get("members") or []):
            yield issue(t, f"Il referente {t.get('referent')} non è tra i membri del team.")


@check("EPBS-03", "Verificatore indipendente mancante o membro del team", "E", "EN 50716, EPBS-1")
def epbs_verifier(ctx):
    for t in ctx.of("team"):
        verifier = (t.get("independent_verifier") or "").strip()
        if not verifier:
            yield issue(t, "Verificatore indipendente non indicato.")
        elif verifier.casefold() in {m.casefold() for m in t.get("members") or []}:
            yield issue(t, f"Il verificatore indipendente {verifier} è membro del team: manca l'indipendenza.")


@check("EPBS-04", "Dominio assegnato a più team", "E", "EPBS-1")
def epbs_domain_twice(ctx):
    for d, teams in ctx.teams_of_domain.items():
        for t in teams[1:]:
            yield issue(t, f"Il dominio {ctx.label(d)} è assegnato anche a {ctx.labels(teams[:1])}.", [d, teams[0]])


@check("EPBS-05", "Più team indicati come Design Authority", "E", "Governance dei rami (una sola DA)")
def epbs_many_da(ctx):
    teams = [t for t in ctx.of("team") if t.get("design_authority")]
    if len(teams) > 1:
        for t in teams:
            yield issue(t, f"Anche {ctx.labels(o for o in teams if o is not t)} è indicato come Design Authority: "
                           "può essercene una sola.", [o for o in teams if o is not t])


@check("EPBS-06", "Nessun team indicato come Design Authority, o DA senza membri", "A",
       "Governance dei rami (integrazione in main)")
def epbs_no_da(ctx):
    teams = ctx.of("team")
    da = [t for t in teams if t.get("design_authority")]
    if teams and not da:
        yield issue(None, "Nessun team è indicato come Design Authority: nessuno può integrare i rami in main.")
    for t in da:
        if not t.get("members"):
            yield issue(t, "Il team della Design Authority non ha membri: nessun utente è riconosciuto come DA.")


@check("X-01", "ADR «Superata» senza «Superata da», o sostituzioni circolari", "E", "X-1")
def x_superseded(ctx):
    for a in ctx.of("adr"):
        if a.get("status") == "Superata" and not a.get("superseded_by"):
            yield issue(a, "ADR superata senza l'ADR che la sostituisce.")
        if a.get("superseded_by") and _cycle(ctx, a, "superseded_by"):
            yield issue(a, "Catena di sostituzioni circolare.")


@check("X-02", "ADR «Decisa» senza decisione o motivazione", "E", "X-1")
def x_decided(ctx):
    for a in ctx.of("adr"):
        missing = [(name, label) for name, label in (("decision", "decisione"), ("rationale", "motivazione"))
                   if not a.get(name)]
        if a.get("status") == "Decisa" and missing:
            yield issue(a, f"ADR decisa senza {' e '.join(m[1] for m in missing)}.", field=missing[0][0])


@check("X-03", "CQ senza clausola, o aperta senza posizione adottata nel frattempo", "E/A", "X-2")
def x_clarification(ctx):
    for q in ctx.of("clarification"):
        if not q.get("clause"):
            yield issue(q, "Richiesta di chiarimento senza clausola.", (), ERROR)
        if q.get("status", "Aperta") == "Aperta" and not q.get("interim_position"):
            yield issue(q, "Richiesta aperta senza la posizione adottata nel frattempo.", (), WARNING,
                        field="interim_position")


@check("X-04", "CQ aperta su una clausola tracciata da schede approvate", "A", "X-2")
def x_open_on_approved(ctx):
    for q in ctx.of("clarification"):
        item = ctx.get(q.get("clause"))
        if item is None or q.get("status", "Aperta") != "Aperta":
            continue
        approved = [f for f in ctx.of("system_function", "logical_function") if ctx.approved(f) and ctx.traces(f, item)]
        approved += [r for r in ctx.records_by_requirement.get(item.uuid, []) if ctx.approved(r)]
        if approved:
            yield issue(q, f"La clausola {item.get('id')} ha un chiarimento aperto ma è tracciata da schede approvate: "
                           f"{ctx.labels(approved)}.", [item, *approved])
