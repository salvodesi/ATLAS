"""Indicators for the architectural review (computed, not errors: they ask for an evaluation) and checks against
the last published version."""
from collections import defaultdict

from arcadia_tool.checks import WARNING, check, issue
from arcadia_tool.checks.sa import chain_metrics


# --- IND: indicators ----------------------------------------------------------------------------------------

@check("IND-01", "Metriche delle functional chain (attraversamenti, rimbalzi, domini, cicli)", "I", "A5")
def ind_chain_metrics(ctx):
    for c in ctx.of("functional_chain"):
        if ctx.chain_steps(c):
            m = chain_metrics(ctx, c)
            yield issue(c, f"Attraversamenti {m['crossings']} · rimbalzi {m['bounces']} · domini coinvolti "
                           f"{m['domains']} · cicli {m['cycles']}.")


def component_dependencies(ctx):
    """Dependencies between components (Parte V): consumer → {producer: exchanges}, from the exchanges between
    logical functions allocated to different components and from the component exchanges."""
    depends = defaultdict(lambda: defaultdict(list))
    for fe in ctx.of("functional_exchange"):
        a, b = ctx.get(fe.get("source")), ctx.get(fe.get("target"))
        if a is None or b is None or a.kind != "logical_function" or b.kind != "logical_function":
            continue
        ca, cb = a.get("component"), b.get("component")
        if ca and cb and ca != cb:
            depends[cb][ca].append(fe)
    for ce in ctx.of("component_exchange"):
        if ce.get("source") and ce.get("target") and ce.get("source") != ce.get("target"):
            depends[ce.get("target")][ce.get("source")].append(ce)
    return depends


def _strongly_connected(nodes, edges):
    """Groups of nodes that depend on each other (Tarjan), only those of more than one node."""
    index, low, stack, on_stack, result, counter = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            group = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                group.append(w)
                if w == v:
                    break
            if len(group) > 1:
                result.append(group)

    for v in nodes:
        if v not in index:
            visit(v)
    return result


@check("IND-02", "Dipendenze cicliche tra componenti", "A", "Parte V (indicatori, grafo delle dipendenze)")
def ind_cycles(ctx):
    depends = component_dependencies(ctx)
    edges = {consumer: set(producers) for consumer, producers in depends.items()}
    nodes = set(edges) | {p for ps in edges.values() for p in ps}
    for group in _strongly_connected(sorted(nodes), edges):
        for c in group:
            others = [o for o in group if o != c]
            yield issue(c, f"Dipendenza ciclica con {ctx.labels(others)}: va valutata e motivata.", others)


@check("IND-03", "Fan-in o fan-out anomalo di funzioni e componenti", "I", "Parte V (indicatori)",
       needs="fan_threshold")
def ind_fan(ctx):
    threshold = ctx.param("fan_threshold")
    for f in ctx.of("system_function", "logical_function"):
        consumers = {fe.get("target") for fe in ctx.exchanges_from.get(f.uuid, [])} - {None}
        producers = {fe.get("source") for fe in ctx.exchanges_to.get(f.uuid, [])} - {None}
        if len(consumers) > threshold:
            yield issue(f, f"Fornisce informazioni a {len(consumers)} funzioni (soglia {threshold}).")
        if len(producers) > threshold:
            yield issue(f, f"Riceve informazioni da {len(producers)} funzioni (soglia {threshold}).")
    depends = component_dependencies(ctx)
    dependents = defaultdict(set)
    for consumer, producers in depends.items():
        for p in producers:
            dependents[p].add(consumer)
    for c in ctx.of("logical_component"):
        if len(dependents.get(c.uuid, ())) > threshold:
            yield issue(c, f"{len(dependents[c.uuid])} componenti dipendono da questo (soglia {threshold}).")
        if len(depends.get(c.uuid, ())) > threshold:
            yield issue(c, f"Dipende da {len(depends[c.uuid])} componenti (soglia {threshold}).")


@check("IND-04", "Scambi densi sul confine tra due componenti", "I", "Parte V (indicatori)")
def ind_coupling(ctx):
    internal, cross = defaultdict(int), defaultdict(list)
    for fe in ctx.of("functional_exchange"):
        a, b = ctx.get(fe.get("source")), ctx.get(fe.get("target"))
        if a is None or b is None or a.kind != "logical_function" or b.kind != "logical_function":
            continue
        ca, cb = a.get("component"), b.get("component")
        if not ca or not cb:
            continue
        if ca == cb:
            internal[ca] += 1
        else:
            cross[tuple(sorted((ca, cb)))].append(fe)
    minimum = ctx.param("min_exchanges")
    for (ca, cb), exchanges in cross.items():
        if len(exchanges) >= minimum and len(exchanges) > max(internal[ca], internal[cb]):
            yield issue(ca, f"{len(exchanges)} scambi con {ctx.label(cb)}, più di quelli interni a ciascuno dei due: "
                            "funzioni coese potrebbero essere separate da un confine.", [cb, *exchanges])


@check("IND-05", "Coperture del modello", "I", "B5, LA")
def ind_coverage(ctx):
    def share(part, whole):
        return f"{part} su {whole} ({round(100 * part / whole)}%)" if whole else "nessuna"

    board = [r for r in ctx.of("requirement") if r.get("item_type") == "Requisito" and ctx.is_board(r)]
    with_outcome = [r for r in board if ctx.records_by_requirement.get(r.uuid)]
    sections = [s for s in ctx.of("requirement") if s.get("item_type") == "Sezione"]
    closed = [s for s in sections if all(ctx.records_by_requirement.get(c.uuid) for c in ctx.descendants(s)
                                         if c.get("item_type") == "Requisito")]
    sfs = ctx.of("system_function")
    refined = [sf for sf in sfs if ctx.lfs_refining.get(sf.uuid)]
    leaves = [lf for lf in ctx.of("logical_function") if ctx.is_leaf(lf)]
    allocated = [lf for lf in leaves if lf.get("component")]
    from arcadia_tool.checks.la import _cross_component
    crossing = [fe for fe in ctx.of("functional_exchange") if _cross_component(ctx, fe)]
    realized = [fe for fe in crossing if ctx.component_exchanges_realizing.get(fe.uuid)]
    chains = ctx.of("functional_chain")
    executable = [c for c in chains if any(r.get("outcome") == "Eseguibile"
                                           for r in ctx.realizations_of_chain.get(c.uuid, []))]
    for label, part, whole in (("Voci di bordo con esito nel registro", with_outcome, board),
                               ("Sezioni concluse", closed, sections),
                               ("Funzioni di sistema raffinate in LA", refined, sfs),
                               ("Funzioni logiche foglia allocate", allocated, leaves),
                               ("Scambi tra componenti realizzati da Component Exchange", realized, crossing),
                               ("Functional chain eseguibili in LA", executable, chains)):
        yield issue(None, f"{label}: {share(len(part), len(whole))}.")


# --- VER: changes since the last published version ----------------------------------------------------------

def _new_adrs(ctx):
    """ADR created or changed since the last published version."""
    published = ctx.published
    return [a for a in ctx.of("adr") if published.get(a.uuid) is None or published.get(a.uuid).values != a.values]


def _adr_mentions(ctx, element):
    """New ADR that refer to the element: in a reference field (e.g. its «Voci SRS interessate») or by its ID in
    the text of the other elements involved."""
    ident = element.get("id")
    references = lambda a: [u for v in a.values.values() for u in (v if isinstance(v, list) else [v])
                            if isinstance(u, str)]
    return [a for a in _new_adrs(ctx) if element.uuid in references(a)
            or (ident and ident in (a.get("affected") or ""))]


@check("VER-01", "Funzione spostata in un altro dominio senza una nuova ADR", "A", "Regole di coordinamento, A6")
def ver_function_moved(ctx):
    for sf in ctx.of("system_function"):
        old = ctx.published.get(sf.uuid)
        if old is None or not old.get("domain") or old.get("domain") == sf.get("domain"):
            continue
        new_adrs = set(sf.get("adrs") or []) - set(old.get("adrs") or [])
        if not new_adrs and not _adr_mentions(ctx, sf):
            yield issue(sf, f"Spostata dal dominio {ctx.label(old.get('domain'))} a {ctx.label(sf.get('domain'))} "
                            "senza una nuova ADR collegata.", [old.get("domain"), sf.get("domain")])


@check("VER-02", "Dominio principale di una voce cambiato senza ADR", "A", "A6")
def ver_section_moved(ctx):
    for item in ctx.of("requirement"):
        old = ctx.published.get(item.uuid)
        if old is None or not old.get("primary_domain") or old.get("primary_domain") == item.get("primary_domain"):
            continue
        if not _adr_mentions(ctx, item):
            yield issue(item, f"Dominio principale cambiato da {ctx.label(old.get('primary_domain'))} a "
                              f"{ctx.label(item.get('primary_domain')) if item.get('primary_domain') else 'nessuno'} "
                              "senza una nuova ADR che citi la voce (tra le sue voci SRS interessate).",
                        [old.get("primary_domain"), item.get("primary_domain")])


@check("VER-03", "Dominio aggiunto o eliminato dopo la baseline senza ADR", "A", "A6")
def ver_domains(ctx):
    published = [d for d in ctx.published if d.kind == "domain"]
    if not published:
        return
    current = {d.uuid for d in ctx.of("domain")}
    for d in ctx.of("domain"):
        if ctx.published.get(d.uuid) is None and not _adr_mentions(ctx, d):
            yield issue(d, "Dominio aggiunto dopo la baseline senza una nuova ADR.")
    for d in published:
        if d.uuid not in current and not any((d.get("id") or "") in (a.get("affected") or "") for a in _new_adrs(ctx)):
            yield issue(None, f"Dominio {ctx.published.label(d)} eliminato dopo la baseline senza una nuova ADR che lo "
                              "citi.")


@check("VER-04", "Allocazione di una funzione logica cambiata senza ADR", "A", "Parte IV (allocazione)")
def ver_allocation(ctx):
    for lf in ctx.of("logical_function"):
        old = ctx.published.get(lf.uuid)
        if old is None or not old.get("component") or old.get("component") == lf.get("component"):
            continue
        if not _adr_mentions(ctx, lf):
            yield issue(lf, f"Allocazione cambiata da {ctx.label(old.get('component'))} a "
                            f"{ctx.label(lf.get('component')) if lf.get('component') else 'nessun componente'} senza una "
                            "nuova ADR che citi la funzione.", [old.get("component"), lf.get("component")])


@check("VER-05", "Scheda approvata modificata senza tornare in revisione", "A", "Ordine di compilazione")
def ver_approved_changed(ctx):
    for e in ctx.model:
        old = ctx.published.get(e.uuid)
        if old is None or not ctx.approved(e) or not ctx.approved(old):
            continue
        names = [f.name for f in e.schema.fields if f.name != "status"
                 and e.values.get(f.name) != old.values.get(f.name)]
        if names:
            changed = ", ".join(e.schema.field(n).label for n in names)
            yield issue(e, f"Modificata dopo l'approvazione ({changed}) ma ancora «{e.get('status')}»: va riportata in "
                           "revisione.", (), WARNING, field=names[0])
