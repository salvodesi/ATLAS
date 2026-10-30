"""The artefacts of the System Analysis (SA-1 … SA-7): each written as its template (no subject: the guide in grey
italics and an example row) or filled in from the model (a domain, a chain, or the rows of the whole sheet). The
fields are those of the sheets of ATLAS (model.schema), so that template, sheet and document stay the same."""
from dataclasses import dataclass, field as dataclass_field

from arcadia_tool.model.adr import outcome, principal_of, related_adrs, section_of
from arcadia_tool.model.schema import (B5_QUESTIONS, B6_SCHEMES, ETCS_MODES, KINDS_BY_NAME, NATURES, SHEET_STATES)
from arcadia_tool.documents.values import (by_id, domain_of, end_text, label, plain, short, shorts, table_rows,
                                           text_of)

BASELINE = "SUBSET-026 v3.6.0 (B3R2)"


@dataclass
class Doc:
    """What a document is written from: the model and the data of its header. filled False: a template."""
    model: object = None
    project: str = ""
    baseline: str = ""
    author: str = ""
    date: str = ""
    version: str = "1.1"
    domains: set = None  # the domains chosen (None: all)
    filled: bool = True
    cache: dict = dataclass_field(default_factory=dict)  # computed once per document (the SRS items in order…)

    def in_scope(self, domain):
        return self.domains is None or (domain is not None and domain.uuid in self.domains)

    def ordered(self):
        """The SRS items in the order of the specification."""
        if "ordered" not in self.cache:
            from arcadia_tool.ui.srs_reader import document_order
            self.cache["ordered"] = document_order(self.model)
        return self.cache["ordered"]

    def board_items(self, uuids):
        """How many items of category «Bordo» the sections and clauses contain (themselves included)."""
        if "board" not in self.cache:  # each board item with the items containing it
            board = {}
            for item in self.model.of_kind("requirement"):
                if "Bordo" not in (item.get("category") or []):
                    continue
                chain, part, seen = [], item, set()
                while part is not None and part.uuid not in seen:
                    seen.add(part.uuid)
                    chain.append(part.uuid)
                    part = self.model.get(part.get("parent")) if part.get("parent") else None
                board[item.uuid] = set(chain)
            self.cache["board"] = board
        traced = set(uuids or [])
        return sum(1 for chain in self.cache["board"].values() if chain & traced)


@dataclass
class Artifact:
    code: str
    title: str
    template: str  # its file in Templates/
    files: str  # the name of the generated file
    who: str  # «Chi compila … · Livello … · Ordine di compilazione …»
    purpose: str
    guide: str
    checklist: tuple
    widths: tuple
    unit: tuple  # (one, many): what a sheet or a row is
    per: str = ""  # "domain", "chain": a sheet per element; "": one sheet
    subjects: object = None  # doc → the elements of the sheets (per) or the rows (one sheet)
    write: object = None  # (writer, doc, subject or None)
    extra: dict = dataclass_field(default_factory=dict)


def header(doc, code, team="", status=""):
    """The data of the document: the values of the model, or the guides of the template."""
    if not doc.filled:
        return {"Template": (code, False), "Team / dominio": ("es. T5 · DF07, DF08", True),
                "Versione": ("es. 0.1", True), "Data": ("gg/mm/aaaa", True),
                "Stato": (" / ".join(SHEET_STATES), True), "Baseline SRS": ("SUBSET-026 v3.6.0", False)}
    return {"Template": (code, False), "Team / dominio": (team, False), "Autore": (doc.author, False),
            "Data": (doc.date, False), "Stato": (status, False), "Baseline SRS": (doc.baseline, False)}


def team_of(model, domain):
    team = model.get(domain.get("team")) if domain is not None and domain.get("team") else None
    ident = team.get("id") if team is not None else ""
    return " · ".join(t for t in (ident, domain.get("id") if domain is not None else "") if t)


def scope_text(doc):
    if doc.domains is None:
        return "Tutti i domini"
    return ", ".join(short(doc.model, u) for u in sorted(doc.domains, key=lambda u: short(doc.model, u)))


def _f(kind, name):
    return KINDS_BY_NAME[kind].field(name)


# --- SA-1 ----------------------------------------------------------------------------------------------------------

ADR_COLUMNS = [("Esito", 1, ()), ("ID", 1, ()), ("Titolo", 2, ()), ("Tipo", 1, ()), ("Stato", 1, ()),
               ("Decisione DA", 1, ())]


def adr_rows(model, element):
    return [[outcome(a), a.get("id") or "", a.get("title") or "", a.get("adr_type") or "", a.get("status") or "",
             a.get("da_decision") or ""] for a in related_adrs(model, element)]


def _domain_data(model, domain):
    """The data the domain produces (from the exchanges of its functions) and those it uses from other domains."""
    produced, used = [], []
    for fe in model.of_kind("functional_exchange"):
        item = label(model, fe.get("exchange_item")) or fe.get("name") or ""
        source, target = domain_of(model, fe.get("source")), domain_of(model, fe.get("target"))
        if source is domain and item and item not in produced:
            produced.append(item)
        if target is domain and source is not domain and item:
            used.append(f"{item} ({source.get('id') if source is not None else 'attore esterno'}, "
                        f"{fe.get('id') or fe.get('name') or ''})")
    return produced, used


def write_sa1(w, doc, domain):
    model = doc.model
    w.document(header(doc, "SA-1", team_of(model, domain) if domain else "", domain.get("status") if domain else ""))
    kind = KINDS_BY_NAME["domain"]
    w.heading("Identificazione")
    if domain is None:
        w.field("ID e nome", hint="es. DF06 Protezione dei movimenti e comando dei freni")
        w.field(kind.field("team").label, hint="es. T5 · Odometria")
        w.field(kind.field("referent").label, hint="Calcolato da ATLAS: il referente del team assegnatario")
        w.field("Stato del dominio", hint=" / ".join(SHEET_STATES), options=SHEET_STATES)
        w.heading("Descrizione")
        w.field(kind.field("mission").label, hint="Una frase: cosa garantisce il dominio", tall=True)
        w.heading("Tracciabilità verso le voci SRS (A4)")
        w.field("Sezioni SRS principali", hint="es. 3.11.6, 3.11.7")
        w.field("Sezioni e clausole SRS a cui contribuisce", hint="es. 3.6.3 (DF02)")
        w.heading("Relazioni")
        w.field("Funzioni di sistema", hint="Calcolato da ATLAS: SF-DFnn-01 … (catalogo SA-2)")
        w.field("Dati prodotti/posseduti dal dominio",
                hint="Calcolato da ATLAS dagli scambi (SA-5): i dati logici che solo questo dominio produce")
        w.field("Dati usati da altri domini", hint="Calcolato da ATLAS: dato (dominio produttore, scambio FE)")
        w.field(kind.field("planned_components").label, hint="LC-nn, …")
        w.table(ADR_COLUMNS, example=["Attiva", "ADR-nnn", "Titolo della decisione", "Tipo", "Proposta", ""],
                empty=2, label="Decisioni architetturali (ADR) · calcolato da ATLAS: le ADR che riguardano il dominio")
        return
    principal, contributes = [], []
    for item in doc.ordered():
        if item.get("primary_domain") == domain.uuid:
            principal.append(item.get("id") or "")
        elif domain.uuid in (item.get("contributing_domains") or []):
            owner = short(model, principal_of(model, item))
            contributes.append(f"{item.get('id')} ({owner})" if owner else item.get("id") or "")
    functions = by_id(f for f in model.of_kind("system_function") if f.get("domain") == domain.uuid)
    produced, used = _domain_data(model, domain)
    w.field("ID e nome", " ".join(t for t in (domain.get("id"), domain.get("name")) if t))
    w.field(kind.field("team").label, label(model, domain.get("team")))
    team = model.get(domain.get("team")) if domain.get("team") else None
    w.field(kind.field("referent").label, (team.get("referent") or "") if team is not None else "")
    w.field("Stato del dominio", domain.get("status") or "")
    w.heading("Descrizione")
    w.field(kind.field("mission").label, plain(domain.get("mission")))
    w.heading("Tracciabilità verso le voci SRS (A4)")
    w.field("Sezioni SRS principali", ", ".join(principal))
    w.field("Sezioni e clausole SRS a cui contribuisce", ", ".join(contributes))
    w.heading("Relazioni")
    w.field("Funzioni di sistema", "\n".join(f"{f.get('id') or ''} {f.get('name') or ''}".strip()
                                             for f in functions))
    w.field("Dati prodotti/posseduti dal dominio", ", ".join(produced))
    w.field("Dati usati da altri domini", "\n".join(used))
    w.field(kind.field("planned_components").label, shorts(model, domain.get("planned_components")))
    w.table(ADR_COLUMNS, adr_rows(model, domain), label="Decisioni architetturali (ADR)")


# --- SA-2 ----------------------------------------------------------------------------------------------------------

SA2_COLUMNS = [("ID", 1, ()), ("Nome (verbo + oggetto)", 1, ()), ("Descrizione", 1, ()), ("Sezioni SRS", 1, ()),
               ("Righe 4.5.2", 1, ()), ("Disponibilità nei modi (X / O)", 1, ()),
               ("Componente logico proposto", 1, ()), ("Voci di bordo tracciate", 1, ()),
               ("Funzione nuova", 1, ("Sì", "No")), ("Motivo", 1, ()), ("Note e decisioni", 1, ()),
               ("Decisioni architetturali (ADR)", 1, ()), ("Stato", 1, ("Proposta", "Rivista", "Approvata"))]
SA2_EXAMPLE = ["SF-DF06-04", "Supervisionare lo standstill", "Cosa fa la funzione", "3.14.4", "4.5.2-R49",
               "FS: X, SR: O", "LC-12", "Calcolato da ATLAS", "No", "", "", "Calcolato da ATLAS", "Proposta"]


def sa2_row(doc, f):
    model = doc.model
    modes = f.get("mode_availability") or {}
    return [f.get("id") or "", f.get("name") or "", plain(f.get("description")), shorts(model, f.get("sections")),
            ", ".join(f.get("rows_452") or []),
            ", ".join(f"{m}: {modes[m]}" for m in ETCS_MODES if modes.get(m)),
            label(model, f.get("proposed_component")), str(doc.board_items(f.get("sections"))),
            "Sì" if f.get("is_new") else "No", plain(f.get("new_reason")), plain(f.get("notes")),
            ", ".join(a.get("id") or "" for a in related_adrs(model, f)), f.get("status") or ""]


def write_sa2(w, doc, domain):
    model = doc.model
    w.document(header(doc, "SA-2", team_of(model, domain) if domain else "", domain.get("status") if domain else ""))
    if domain is None:
        w.field("Dominio", hint="es. DF06 Protezione dei movimenti e comando dei freni")
        w.row += 1
        w.table(SA2_COLUMNS, example=SA2_EXAMPLE, empty=15)
        return
    w.field("Dominio", " ".join(t for t in (domain.get("id"), domain.get("name")) if t))
    w.row += 1
    functions = by_id(f for f in model.of_kind("system_function") if f.get("domain") == domain.uuid)
    w.table(SA2_COLUMNS, [sa2_row(doc, f) for f in functions])


# --- SA-3 ----------------------------------------------------------------------------------------------------------

SA3_COLUMNS = [("Sezione SRS", 1, ()), ("Dominio principale", 1, ()), ("ID voce", 1, ()), ("Categoria cap. 9", 1, ()),
               ("Domanda B5 decisiva", 1, B5_QUESTIONS), ("Esito", 1, _f("trace_record", "outcome").options),
               ("Funzione primaria", 1, ()), ("Funzioni secondarie", 1, ()), ("Derivati / dizionario", 1, ()),
               ("Note", 1, ()), ("ADR", 1, ()), ("Stato", 1, _f("trace_record", "status").options)]
SA3_EXAMPLE = ["3.14.4", "DF06", "3.14.4.2", "Bordo", B5_QUESTIONS[5], "Tracciata a funzione", "SF-DF06-04",
               "SF-DF02-01, SF-DF13-02", "3.14.4.2-D1", "", "", "Proposto"]


def sa3_records(doc):
    model = doc.model
    order = {e.uuid: i for i, e in enumerate(doc.ordered())}
    records = []
    for r in model.of_kind("trace_record"):
        item = model.get(r.get("requirement")) if r.get("requirement") else None
        domain = model.get(principal_of(model, item) or "") if item is not None else None
        functions = [model.get(u) for u in [r.get("primary_function"), *(r.get("secondary_functions") or [])] if u]
        if doc.domains is not None and not doc.in_scope(domain) and not any(
                doc.in_scope(domain_of(model, f.uuid)) for f in functions if f is not None):
            continue
        records.append(r)
    return sorted(records, key=lambda r: order.get(r.get("requirement"), len(order)))


def write_sa3(w, doc, records):
    model = doc.model
    w.document(header(doc, "SA-3", scope_text(doc) if doc.filled else ""))
    if records is None:
        w.table(SA3_COLUMNS, example=SA3_EXAMPLE, empty=20)
        return
    rows = []
    for r in records:
        item = model.get(r.get("requirement")) if r.get("requirement") else None
        section = section_of(model, item) if item is not None else None
        rows.append([short(model, section.uuid) if section is not None else "",
                     short(model, principal_of(model, item)) if item is not None else "",
                     short(model, r.get("requirement")), ", ".join(item.get("category") or []) if item else "",
                     text_of(model, r, _f("trace_record", "b5_question")), r.get("outcome") or "",
                     short(model, r.get("primary_function")), shorts(model, r.get("secondary_functions")),
                     shorts(model, r.get("exchange_items")), plain(r.get("notes")), shorts(model, r.get("adrs")),
                     r.get("status") or ""])
    w.table(SA3_COLUMNS, rows)


# --- SA-4 ----------------------------------------------------------------------------------------------------------

SA4_COLUMNS = [("ID derivato", 1, ()), ("Nome sintetico", 1, ()), ("Voce madre", 1, ()), ("Obbligo (una frase)", 1, ()),
               ("Funzione logica", 1, ()), ("Dominio", 1, ()), ("Motivazione della derivazione", 1, B6_SCHEMES),
               ("Stato", 1, _f("derived_requirement", "status").options)]
SA4_EXAMPLE = ["5.11.2.2-A030-D1", "Evento di report di posizione", "5.11.2.2-A030",
               "Il cambio di modo genera un evento di report di posizione", "LF-DF02-11-01", "DF02", B6_SCHEMES[1],
               "Proposto"]


def sa4_items(doc):
    model = doc.model
    return by_id(d for d in model.of_kind("derived_requirement")
                 if doc.in_scope(model.get(d.get("domain")) if d.get("domain") else None))


def write_sa4(w, doc, items):
    model = doc.model
    w.document(header(doc, "SA-4", scope_text(doc) if doc.filled else ""))
    if items is None:
        w.table(SA4_COLUMNS, example=SA4_EXAMPLE, empty=15)
        return
    w.table(SA4_COLUMNS, [[d.get("id") or "", d.get("name") or "", short(model, d.get("parent")),
                           plain(d.get("obligation")), short(model, d.get("function")), short(model, d.get("domain")),
                           text_of(model, d, _f("derived_requirement", "b6_scheme")), d.get("status") or ""]
                          for d in items])


# --- SA-5 ----------------------------------------------------------------------------------------------------------

SA5_COLUMNS = [("ID scambio", 1, ()), ("Nome", 1, ()), ("Produttore (funzione, dominio)", 1, ()),
               ("Utilizzatore (funzione, dominio)", 1, ()), ("Dato di interfaccia", 1, ()), ("Natura", 1, NATURES),
               ("Condizione di produzione", 1, _f("functional_exchange", "production_condition").options),
               ("Clausole", 1, ()), ("Chain che lo usano", 1, ()), ("Accordo del produttore", 1, ()),
               ("Accordo dell'utilizzatore", 1, ()), ("Stato", 1, _f("functional_exchange", "status").options)]
SA5_EXAMPLE = ["FE-DF02-DF06-01", "Movimento del treno", "Determinare velocità e standstill (DF02)",
               "Supervisionare lo standstill (DF06)", "EI-movimento_treno", "FLOW", "Sempre", "3.14.4.2",
               "Calcolato da ATLAS", "Referente DF02, data", "Referente DF06, data", "Proposto"]


def sa5_items(doc):
    model = doc.model
    return by_id(fe for fe in model.of_kind("functional_exchange")
                 if doc.domains is None or doc.in_scope(domain_of(model, fe.get("source")))
                 or doc.in_scope(domain_of(model, fe.get("target"))))


def write_sa5(w, doc, items):
    model = doc.model
    w.document(header(doc, "SA-5", scope_text(doc) if doc.filled else ""))
    if items is None:
        w.table(SA5_COLUMNS, example=SA5_EXAMPLE, empty=15)
        return
    chains = model.of_kind("functional_chain")
    rows = []
    for fe in items:
        using = [c.get("id") or c.get("title") or "" for c in chains
                 if any(s.get("exchange") == fe.uuid for s in c.get("steps") or [])]
        rows.append([fe.get("id") or "", fe.get("name") or "", end_text(model, fe.get("source")),
                     end_text(model, fe.get("target")), short(model, fe.get("exchange_item")), fe.get("nature") or "",
                     fe.get("production_condition") or "", shorts(model, fe.get("clauses")), ", ".join(using),
                     fe.get("producer_agreement") or "", fe.get("consumer_agreement") or "", fe.get("status") or ""])
    w.table(SA5_COLUMNS, rows)


# --- SA-6 ----------------------------------------------------------------------------------------------------------

SA6_COLUMNS = [("ID", 1, ()), ("Nome", 1, ()), ("Tipo", 1, _f("exchange_item", "type").options),
               ("Natura", 1, NATURES), ("Significato", 1, ()), ("Origine SRS", 1, ()),
               ("Elementi (variabili cap. 7): variabile · descrizione · unità · campo · risoluzione", 2, ()),
               ("Produttore", 1, ()), ("Utilizzatori", 1, ()), ("Note", 1, ()),
               ("Stato", 1, SHEET_STATES)]
SA6_EXAMPLE = ["EI-PositionReport", "Train Position Report", "Messaggio", "EVENT", "Cosa rappresenta il dato",
               "8.6.4 (messaggio 136)", "NID_ENGINE · identità del bordo · — · 0..16777215 · 1", "Calcolato da ATLAS",
               "Calcolato da ATLAS", "", "Bozza"]


def _ends(model, item):
    producers, users = [], []
    for fe in model.of_kind("functional_exchange"):
        if fe.get("exchange_item") == item.uuid:
            for name, bucket in ((fe.get("source"), producers), (fe.get("target"), users)):
                text = short(model, name)
                if text and text not in bucket:
                    bucket.append(text)
    return producers, users


def sa6_items(doc):
    model = doc.model
    items = by_id(model.of_kind("exchange_item"))
    if doc.domains is None:
        return items
    kept = []
    for item in items:
        ends = [domain_of(model, fe.get(k)) for fe in model.of_kind("functional_exchange")
                if fe.get("exchange_item") == item.uuid for k in ("source", "target")]
        if any(doc.in_scope(d) for d in ends):
            kept.append(item)
    return kept


def write_sa6(w, doc, items):
    model = doc.model
    w.document(header(doc, "SA-6", scope_text(doc) if doc.filled else ""))
    if items is None:
        w.table(SA6_COLUMNS, example=SA6_EXAMPLE, empty=15)
        return
    rows = []
    elements = KINDS_BY_NAME["exchange_item"].field("elements")
    for item in items:
        producers, users = _ends(model, item)
        rows.append([item.get("id") or "", item.get("name") or "", item.get("type") or "", item.get("nature") or "",
                     plain(item.get("meaning")), item.get("srs_origin") or "",
                     "\n".join(" · ".join(r) for r in table_rows(model, item, elements)), ", ".join(producers),
                     ", ".join(users), plain(item.get("notes")), item.get("status") or ""])
    w.table(SA6_COLUMNS, rows)


# --- SA-7 ----------------------------------------------------------------------------------------------------------

STEP_COLUMNS = [("#", 1, ()), ("Ciclo", 1, ()), ("Dominio", 1, ()), ("Funzione SF", 1, ()), ("Cosa fa", 1, ()),
                ("Dato prodotto", 1, ()), ("Natura", 1, NATURES), ("Scambio", 1, ()), ("Voci SRS", 1, ()),
                ("Componente logico", 1, ())]
USED_COLUMNS = [("ID scambio (SA-5)", 2, ()), ("Produttore", 2, ()), ("Utilizzatore", 2, ()),
                ("Dato e natura", 2, ()), ("Stato", 2, ())]
DERIVED_COLUMNS = [("ID derivato (SA-4)", 2, ()), ("Voce madre", 2, ()), ("Obbligo", 2, ()),
                   ("Funzione (dominio)", 2, ()), ("Motivazione", 2, ())]
METRIC_COLUMNS = [("Attraversamenti", 2, ()), ("Rimbalzi nello stesso ciclo", 2, ()), ("Domini coinvolti", 2, ()),
                  ("Cicli", 2, ()), ("Decisione (metriche)", 2, ())]
VARIANT_COLUMNS = [("Variante", 2, ()), ("Tipo", 2, ("Exchange Scenario", "Chain distinta")),
                   ("Differenza dal nominale", 3, ()), ("Voci SRS", 3, ())]


def sa7_items(doc):
    model = doc.model
    chains = by_id(model.of_kind("functional_chain"))
    if doc.domains is None:
        return chains
    return [c for c in chains if doc.in_scope(model.get(c.get("responsible_domain") or ""))
            or any(doc.in_scope(domain_of(model, s.get("function"))) for s in c.get("steps") or [])]


def write_sa7(w, doc, chain):
    model = doc.model
    kind = KINDS_BY_NAME["functional_chain"]
    responsible = model.get(chain.get("responsible_domain") or "") if chain is not None else None
    w.document(header(doc, "SA-7", team_of(model, responsible) if responsible else "",
                      chain.get("status") if chain is not None else ""))
    hints = {"id": "FC-nome", "capability": "OCn", "responsible_domain": "DFnn", "adrs": "ADR-nnn",
             "trigger": "Attore esterno e scambio in ingresso",
             "final_effect": "Messaggio, comando o indicazione verso un attore esterno",
             "preconditions": "Modo, livello, sessione, dati validi", "out_of_scope": "Rami coperti da altre chain, con ID",
             "oracle": "Righe di tabella e condizioni che definiscono il risultato atteso",
             "integration_test": "Stimolo, sequenza attesa sugli attori esterni, criterio di superamento"}

    def field(name, tall=False):
        f = kind.field(name)
        value = text_of(model, chain, f) if chain is not None else ""
        if f.type == "ref" and value and chain is not None:
            value = short(model, chain.get(name)) + " " + (model.get(chain.get(name)).get("name") or "")
        w.field(f.label, value.strip(), hint=hints.get(name, ""), tall=tall)

    steps = list(chain.get("steps") or []) if chain is not None else []
    w.heading("1. Identificazione")
    for name in ("id", "title", "capability", "procedure", "responsible_domain"):
        field(name)
    domains = []
    for s in steps:
        d = domain_of(model, s.get("function"))
        if d is not None and d.get("id") and d.get("id") not in domains:
            domains.append(d.get("id"))
    w.field("Domini coinvolti", ", ".join(domains), hint="Calcolato da ATLAS dai passi del percorso")
    field("adrs")
    w.field("Stato della chain", (chain.get("status") or "") if chain is not None else "",
            hint=" / ".join(SHEET_STATES), options=SHEET_STATES)
    w.heading("2. Contesto")
    for name in ("trigger", "final_effect", "preconditions", "postconditions", "out_of_scope"):
        field(name)
    w.heading("3. Percorso")
    if chain is None:
        w.table(STEP_COLUMNS, example=["1", "C0", "DFnn", "SF-DFnn-mm", "", "…", "FLOW", "FE-… / Interno / attore",
                                       "3.x.y.z", "LC-nn"], empty=12)
    else:
        rows = []
        for i, s in enumerate(steps, 1):
            d = domain_of(model, s.get("function"))
            rows.append([str(i), s.get("cycle") or "", d.get("id") if d is not None else "",
                         short(model, s.get("function")), s.get("what") or "", s.get("data") or "",
                         s.get("nature") or "", short(model, s.get("exchange")) or "", s.get("srs") or "",
                         short(model, s.get("component"))])
        w.table(STEP_COLUMNS, rows)
    w.heading("4. Scambi usati")
    exchanges = [model.get(s.get("exchange")) for s in steps if s.get("exchange")]
    exchanges = list({fe.uuid: fe for fe in exchanges if fe is not None}.values())
    if chain is None:
        w.table(USED_COLUMNS, example=["Calcolato da ATLAS dai passi", "", "", "", ""], empty=2)
    else:
        w.table(USED_COLUMNS, [[fe.get("id") or "", end_text(model, fe.get("source")), end_text(model, fe.get("target")),
                                " ".join(t for t in (short(model, fe.get("exchange_item")), fe.get("nature")) if t),
                                fe.get("status") or ""] for fe in exchanges])
    w.heading("5. Requisiti derivati")
    cited = " ".join(s.get("srs") or "" for s in steps)
    derived = [d for d in by_id(model.of_kind("derived_requirement"))
               if short(model, d.get("parent")) and short(model, d.get("parent")) in cited] if chain is not None else []
    if chain is None:
        w.table(DERIVED_COLUMNS, example=["Calcolato da ATLAS: i derivati delle voci SRS dei passi", "", "", "", ""],
                empty=2)
    else:
        w.table(DERIVED_COLUMNS, [[d.get("id") or "", short(model, d.get("parent")), plain(d.get("obligation")),
                                   " ".join(t for t in (short(model, d.get("function")),
                                                        f"({short(model, d.get('domain'))})" if d.get("domain") else "")
                                            if t), text_of(model, d, _f("derived_requirement", "b6_scheme"))]
                                  for d in derived])
    w.heading("6. Metriche di validazione")
    if chain is None:
        w.table(METRIC_COLUMNS, example=["Calcolato da ATLAS", "Calcolato da ATLAS", "Calcolato da ATLAS",
                                         "Calcolato da ATLAS", "Accettata / rimbalzo motivato con ADR"], empty=0)
    else:
        from arcadia_tool.checks.context import Context
        from arcadia_tool.checks.sa import chain_metrics
        m = chain_metrics(Context(model), chain)
        w.table(METRIC_COLUMNS, [[str(m["crossings"]), str(m["bounces"]), str(m["domains"]), str(m["cycles"]),
                                  plain(chain.get("decision"))]])
    w.heading("7. Varianti, oracolo e test")
    if chain is None:
        w.table(VARIANT_COLUMNS, example=["", "Exchange Scenario", "", ""], empty=4)
    else:
        w.table(VARIANT_COLUMNS, table_rows(model, chain, kind.field("variants")))
    w.row += 1
    for name in ("oracle", "integration_test"):
        field(name, tall=True)


# --- the artefacts --------------------------------------------------------------------------------------------------

def _domains(doc):
    return by_id(d for d in doc.model.of_kind("domain") if doc.in_scope(d))


ARTIFACTS = (
    Artifact("SA-1", "Scheda di dominio funzionale", "Template_SA-1_Scheda_di_dominio_funzionale.xlsx",
             "Schede_di_dominio_funzionale", "Chi compila: referente del dominio · Livello: SA · Ordine di compilazione: 1",
             "Fissare missione, perimetro e interfacce di un dominio.",
             "Una scheda per dominio, compilata dal referente: in ATLAS è la scheda del dominio (SA-1). Le sezioni "
             "SRS principali sono quelle di cui il dominio è principale; quelle di altri domini a cui contribuisce "
             "sono indicate con il dominio principale. Funzioni, dati e ADR sono calcolati da ATLAS dal modello.",
             ("Lo scopo è una frase (D1)", "Nessun dato ha due produttori (D10)",
              "Ogni interfaccia verso altri domini è uno scambio FE registrato (SA-5)",
              "Le sezioni SRS del dominio compaiono nella matrice sezioni vs domini"),
             (30, 18, 18, 42, 26, 18, 18), ("dominio", "domini"), "domain", _domains, write_sa1),
    Artifact("SA-2", "Catalogo delle funzioni di sistema del singolo dominio funzionale",
             "Template_SA-2_Catalogo_funzioni_di_sistema.xlsx", "Catalogo_funzioni_di_sistema",
             "Chi compila: team del dominio · Livello: SA · Ordine di compilazione: 2",
             "Elencare le funzioni di sistema del dominio, unità di allocazione e di tracciabilità.",
             "Un foglio per dominio. Nome con verbo e oggetto, senza sigle di modo, livello o paragrafo (D5). La "
             "disponibilità per modo si prende dalle righe 4.5.2-R01–R77. Una funzione nuova va proposta qui con la "
             "motivazione. In ATLAS è la scheda della funzione di sistema (SA-2); voci di bordo e ADR sono calcolate.",
             ("Ogni funzione ha almeno una voce di bordo tracciata, oppure un riferimento alla specifica di "
              "interfaccia (SUBSET-034, -035, -041, cap. 7–8)",
              "Ogni funzione ha un solo dominio e un solo componente proposto",
              "Le funzioni nuove sono approvate dalla Design Authority"),
             (14, 30, 30, 16, 12, 16, 14, 10, 10, 22, 22, 14, 12), ("dominio", "domini"), "domain",
             lambda doc: [d for d in _domains(doc) if any(f.get("domain") == d.uuid
                                                         for f in doc.model.of_kind("system_function"))],
             write_sa2),
    Artifact("SA-3", "Registro di tracciabilità delle voci SRS sulle funzioni di sistema",
             "Template_SA-3_Registro_tracciabilita_voci_SRS.xlsx", "Registro_tracciabilita_voci_SRS",
             "Chi compila: team del dominio · Livello: SA · Ordine di compilazione: 3",
             "Registrare per ogni voce l'esito della tracciatura.",
             "Un'unica tabella con le voci di tutte le sezioni, una riga per voce, con la sezione e il suo dominio "
             "principale. Per ogni voce si applicano le domande B5 in ordine e ci si ferma alla prima risposta sì: "
             "1 definizione, informativa o altro nel cap. 9 → non si traccia; 2 solo terra → ipotesi d'ambiente o "
             "dato atteso; 3 formato di dati → dizionario; 4 obblighi di domini diversi → requisiti derivati (SA-4, "
             "nella colonna «Derivati / dizionario»); 5 solo versione di sistema 1 → collegamento alla voce "
             "nominale; 6 altrimenti → funzioni che realizzano l'obbligo.",
             ("Ogni voce della sezione ha un esito",
              "La categoria del cap. 9 coincide con la matrice; gli scostamenti sono spiegati nelle note",
              "Le voci solo di terra che descrivono dati inviati al bordo sono registrate come dati attesi (D7)",
              "Ogni voce con più obblighi ha i requisiti derivati in SA-4"),
             (12, 12, 14, 12, 26, 20, 14, 18, 18, 22, 12, 12), ("voce", "voci"), "", sa3_records, write_sa3),
    Artifact("SA-4", "Requisiti derivati", "Template_SA-4_Requisiti_derivati.xlsx", "Requisiti_derivati",
             "Chi compila: team del dominio · Livello: SA · Ordine di compilazione: 3 (insieme a SA-3)",
             "Scomporre una voce che assegna obblighi a domini diversi in requisiti atomici, uno per dominio (Fase "
             "B6).",
             "Schema 1: più eventi convergono su una decisione; schema 2: una procedura chiede un'azione al dominio "
             "che ne è responsabile; schema 3: più richieste arbitrate da un solo dominio. La voce madre è coperta "
             "quando lo sono tutti i derivati. In ATLAS è la scheda del requisito derivato (SA-4).",
             ("Ogni derivato ha un solo obbligo e un solo dominio",
              "Il dominio assegnato è il proprietario del dato o dell'azione",
              "Nessun derivato crea un secondo produttore per un dato esistente"),
             (18, 22, 16, 40, 16, 10, 30, 12), ("requisito derivato", "requisiti derivati"), "", sa4_items, write_sa4),
    Artifact("SA-5", "Accordo di scambio tra domini (Functional Exchanges)",
             "Template_SA-5_Accordo_di_scambio_tra_domini_FE.xlsx", "Accordo_di_scambio_tra_domini_FE",
             "Chi compila: responsabili dei team dei due/k domini · Livello: SA, LA · Ordine di compilazione: 4",
             "Concordare ogni scambio tra funzioni di domini diversi.",
             "Uno scambio si registra una volta e si riusa in tutte le chain. Natura: FLOW (valore sempre "
             "disponibile), EVENT (fatto accaduto), OPERATION (richiesta eseguita da un altro dominio). In ATLAS è la "
             "scheda dello scambio funzionale (SA-5); le chain che lo usano sono calcolate.",
             ("Il dato ha un solo produttore",
              "Il dato è nel dizionario (SA-6) o è un dato logico con nome e significato definiti",
              "I referenti dei due domini hanno concordato lo scambio"),
             (18, 20, 26, 26, 18, 10, 14, 14, 16, 18, 18, 12), ("scambio", "scambi"), "", sa5_items, write_sa5),
    Artifact("SA-6", "Dizionario degli Exchange Item", "Template_SA-6_Dizionario_Exchange_Item.xlsx",
             "Dizionario_Exchange_Item",
             "Chi compila: team del dominio o dei domini coinvolti · Livello: SA · Ordine di compilazione: 4",
             "Definire i dati scambiati con il terra e tra domini, derivati dal capitolo 7 (variabili) e dal "
             "capitolo 8 (pacchetti e messaggi).",
             "Una variabile SRS diventa un Exchange Item Element, un pacchetto o un messaggio un Exchange Item. Le "
             "variabili codificate (per esempio M_MODE) compaiono solo nelle funzioni di DF01 e DF09 che le "
             "interpretano o compongono. In ATLAS è la scheda dell'Exchange Item (SA-6); produttori e utilizzatori "
             "sono calcolati dagli scambi.",
             ("Ogni elemento cita la variabile del capitolo 7",
              "Unità, campo e risoluzione sono quelli del capitolo 7 o di A.3.11",
              "Ogni Exchange Item ha un produttore e almeno un utilizzatore"),
             (18, 20, 12, 10, 26, 16, 26, 20, 14, 16, 18, 12), ("Exchange Item", "Exchange Item"), "", sa6_items,
             write_sa6),
    Artifact("SA-7", "Functional chain", "Template_SA-7_Functional_chain.xlsx", "Functional_chain",
             "Chi compila: team del dominio · Ordine di compilazione: 5",
             "Descrivere un percorso eseguibile tra le funzioni, dal trigger di un attore esterno a un effetto "
             "osservabile.",
             "Un foglio per chain. Un passo è una funzione che riceve un dato, fa una cosa e ne produce un altro. I "
             "passi dello stesso ciclo applicativo stanno insieme; quando la chain aspetta un evento si inserisce "
             "una riga di attesa e si apre un nuovo ciclo. In ATLAS è la scheda della functional chain (SA-7); "
             "domini coinvolti, scambi usati, derivati e metriche sono calcolati.",
             ("Inizio e fine su un attore esterno", "Ogni passo usa una funzione del catalogo e cita una voce di bordo",
              "Ogni cambio di dominio usa un FE almeno concordato", "Nessun dominio ricalcola un dato di un altro (D10)",
              "Cicli separati da righe di attesa",
              "Nessun rimbalzo nello stesso ciclo, oppure rimbalzo motivato con un'ADR",
              "Passi di procedura verso altri domini con requisito derivato",
              "Varianti classificate; oracolo e test definiti"),
             (24, 8, 10, 14, 28, 20, 10, 16, 14, 14), ("chain", "chain"), "chain", sa7_items, write_sa7),
)
ARTIFACTS_BY_CODE = {a.code: a for a in ARTIFACTS}


def template_line(doc, artifact):
    """Row 2: the template and its version, or the project the document is generated from."""
    if not doc.filled:
        return (f"Template ARCADIA per i team di sviluppo · v{doc.version} · {doc.date} · Baseline delle specifiche: "
                f"{BASELINE} · {artifact.who}")
    return (f"Generato da ATLAS il {doc.date} dal progetto «{doc.project}» · Baseline delle specifiche: "
            f"{doc.baseline or BASELINE} · {artifact.who}")


def write_sheet(ws, doc, artifact, subject):
    """A sheet of the artefact: about a domain or a chain, or the rows of the whole sheet; None: the template."""
    from arcadia_tool.documents.layout import SheetWriter

    w = SheetWriter(ws, artifact.widths)
    title = f"{artifact.code} · {artifact.title}"
    if doc.filled and artifact.per and subject is not None:
        name = subject.get("id") or subject.get("title") or ""
        title += f" · {name}"
    w.intro(title, template_line(doc, artifact), artifact.purpose, artifact.guide)
    artifact.write(w, doc, subject)
    w.checklist(f"Checklist di compilazione di {artifact.code}", artifact.checklist)
    w.finish()
    return w
