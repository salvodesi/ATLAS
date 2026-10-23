"""Metamodel: element kinds and their fields, derived from the ARCADIA templates.

Only fields that are entered by the user are stored. Fields that the templates show
but that can be computed from the model (e.g. SA-1 "Funzioni di sistema", SA-2
"Voci di bordo tracciate") are not part of the schema.
"""
from dataclasses import dataclass, field

STR = "str"
TEXT = "text"
INT = "int"
BOOL = "bool"
ENUM = "enum"
MULTIENUM = "multienum"
REF = "ref"
REFS = "refs"
STRLIST = "strlist"
MAP = "map"
TABLE = "table"
IMAGE = "image"  # project-relative path of an image file (e.g. a figure of the specification)

NATURES = ("FLOW", "EVENT", "OPERATION")
SHEET_STATES = ("Bozza", "In revisione", "Approvato")
ETCS_MODES = ("FS", "LS", "OS", "SR", "SH", "UN", "PS", "SL", "SB", "TR", "PT", "SF", "IS", "NL", "SN", "RV", "NP")
FUNCTIONS = ("system_function", "logical_function")
EXCHANGE_ENDS = ("system_function", "logical_function", "external_actor")


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    type: str = STR
    ref_kinds: tuple = ()
    options: tuple = ()


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    type: str = STR
    options: tuple = ()
    ref_kinds: tuple = ()
    columns: tuple = ()
    # A change to a significant field is highlighted in the diff (e.g. moving a
    # function to another domain requires an ADR).
    significant: bool = False
    # Kept by the tool, not shown in the editor (e.g. the position of an SRS item in the document).
    hidden: bool = False
    # Editor section, when not the one of its type (e.g. the team of a domain among its identification data).
    section: str = ""
    # A text chosen among the values of a list field of the same element (the referent among the members).
    choices_from: str = ""
    # Copied from a referenced element, not entered: (reference field, field of the referenced element).
    derived_from: tuple = ()
    # Analysis data, not imported: editable also on read-only SRS items (e.g. the allocation to domains).
    analysis: bool = False
    # False: shown (derived_from) but not saved, always read from the referenced element (the chapter 9
    # category of the SRS item of a trace record).
    stored: bool = True
    # REF chosen in a window with search and ticks (one element) instead of a drop-down list.
    picker: bool = False


@dataclass(frozen=True)
class Kind:
    name: str
    label: str
    plural: str
    folder: str
    group: str
    template: str
    id_format: str
    fields: tuple = field(default_factory=tuple)

    def field(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        return None


GROUPS = ("Requisiti", "System Analysis", "Logical Architecture", "Trasversali")


# Decision questions of activity B5 and schemes of B6, worded as in the templates (SA-3 and SA-4). Projects
# created before stored only the number: the editor shows the option that starts with it.
B5_QUESTIONS = (
    "1 – Definizione, informativa o altro nel cap. 9: non si traccia",
    "2 – Solo terra: ipotesi d'ambiente o dato atteso",
    "3 – Formato di dati: dizionario",
    "4 – Obblighi di domini diversi: requisiti derivati",
    "5 – Solo versione di sistema 1: collegamento alla voce nominale",
    "6 – Altrimenti: funzioni che realizzano l'obbligo",
)
# Why a requirement is derived: the three B6 schemes, worded without naming a specific domain.
B6_SCHEMES = (
    "1 – Più eventi, anche da domini diversi, portano a un'unica decisione",
    "2 – Una procedura chiede un'azione al dominio che ne è responsabile",
    "3 – Più richieste, anche da domini diversi, sono decise da un solo dominio",
)


def enum_option(field, value):
    """The option of an ENUM field for a stored value, also when stored by earlier versions with the bare
    number or with another wording of the same numbered option («2 – La procedura (DF08)…»)."""
    if not value or value in field.options:
        return value
    number = value.split(" ", 1)[0]
    return next((o for o in field.options if o.split(" ", 1)[0] == number), value)


TRACE_SECTION = "Esito di tracciatura (SA-3)"


def derived_value(model, element, field):
    """Value of a field copied from a referenced element (field.derived_from), None without a reference."""
    ref, source = field.derived_from
    target = model.get(element.get(ref)) if element.get(ref) else None
    return target.get(source) if target is not None else None


def _common_status(options=SHEET_STATES):
    return Field("status", "Stato", ENUM, options, significant=True)


KINDS = (
    Kind("requirement", "Voce SRS", "Voci SRS", "requirements", "Requisiti", "", "3.14.4.2", (
        Field("id", "Clausola / voce"),
        Field("title", "Titolo"),
        Field("text", "Testo", TEXT),
        Field("item_type", "Tipo", ENUM, ("Capitolo", "Sezione", "Titolo", "Requisito", "Voce")),
        Field("parent", "Padre", REF, ref_kinds=("requirement",)),
        Field("category", "Categoria cap. 9", MULTIENUM,
              ("Bordo", "Terra", "Definizione", "Informativa", "Altro"), significant=True),
        Field("category_note", "Nota sulla categoria", TEXT),
        Field("replaces", "Voce nominale sostituita (cap. 6)", REF, ref_kinds=("requirement",)),
        Field("primary_domain", "Dominio principale (A4)", REF, ref_kinds=("domain",), significant=True,
              analysis=True),
        Field("contributing_domains", "Domini che contribuiscono (A4)", REFS, ref_kinds=("domain",), analysis=True),
        Field("srs_refs", "Riferimenti SRS (righe di tabella)", STRLIST),
        Field("figure", "Figura / formula", IMAGE),
        Field("baseline", "Baseline"),
        Field("page", "Pagina", INT),
        Field("import_note", "Note di import", TEXT),
        Field("sequence", "Posizione nel documento", INT, hidden=True),
    )),
    # Columns of the SA-3 register, in its order, in one card of the sheet.
    Kind("trace_record", "Esito di tracciatura", "Registro di tracciabilità", "sa/trace", "Requisiti", "SA-3", "", (
        Field("requirement", "ID voce", REF, ref_kinds=("requirement",), section=TRACE_SECTION, picker=True),
        Field("category", "Categoria cap. 9", STRLIST, derived_from=("requirement", "category"), stored=False,
              section=TRACE_SECTION),
        Field("primary_function", "Funzione primaria", REF, ref_kinds=FUNCTIONS, significant=True,
              section=TRACE_SECTION, picker=True),
        Field("secondary_functions", "Funzioni secondarie", REFS, ref_kinds=FUNCTIONS, section=TRACE_SECTION),
        # Name kept from the first version (it held only Exchange Items): saved projects stay valid.
        Field("exchange_items", "Derivati / dizionario", REFS, ref_kinds=("derived_requirement", "exchange_item"),
              section=TRACE_SECTION),
        Field("b5_question", "Domanda B5 decisiva", ENUM, B5_QUESTIONS, significant=True, section=TRACE_SECTION),
        Field("outcome", "Esito", ENUM, (
            "Non tracciata", "Ipotesi d'ambiente / dato atteso", "Tracciata al dizionario",
            "Scomposta in requisiti derivati", "Collegata alla voce nominale", "Tracciata a funzione"),
            significant=True, section=TRACE_SECTION),
        Field("notes", "Note", TEXT, section=TRACE_SECTION),
        Field("adrs", "ADR", REFS, ref_kinds=("adr",), section=TRACE_SECTION),
        _common_status(("Da analizzare", "Proposto", "Rivisto", "Approvato")),
    )),
    Kind("derived_requirement", "Requisito derivato", "Requisiti derivati", "sa/derived", "Requisiti", "SA-4",
         "<voce>-Dn", (
        Field("id", "ID derivato"),
        Field("name", "Nome sintetico"),  # shown with the ID where it is chosen; referred to by ID only
        # Voce madre and Funzione logica are chosen with their windows (search and ticks) from the sheet's card.
        Field("parent", "Voce madre", REF, ref_kinds=("requirement",), hidden=True),
        Field("obligation", "Obbligo (una frase)", TEXT),
        # Allocated to one logical function (LA-2), not to a system function.
        Field("function", "Funzione logica", REF, ref_kinds=("logical_function",), significant=True, hidden=True),
        Field("domain", "Dominio", REF, ref_kinds=("domain",), significant=True),
        Field("b6_scheme", "Motivazione della derivazione", ENUM, B6_SCHEMES),
        _common_status(("Proposto", "Rivisto", "Approvato")),
    )),
    Kind("domain", "Dominio funzionale", "Domini funzionali", "sa/domains", "System Analysis", "SA-1", "DFnn", (
        Field("id", "ID"),
        Field("name", "Nome"),
        Field("mission", "Missione", TEXT),
        # «Include» and «Esclude» were removed: values saved by earlier versions are kept in the files.
        Field("team", "Team assegnatario", REF, ref_kinds=("team",), section="Identificazione"),
        Field("referent", "Referente", derived_from=("team", "referent")),
        Field("planned_components", "Componenti logici previsti", REFS, ref_kinds=("logical_component",)),
        Field("adrs", "Decisioni collegate", REFS, ref_kinds=("adr",)),
        _common_status(),
    )),
    Kind("system_function", "Funzione di sistema", "Funzioni di sistema", "sa/functions", "System Analysis", "SA-2",
         "SF-DFnn-mm", (
        Field("id", "ID"),
        Field("name", "Nome (verbo + oggetto)"),
        Field("domain", "Dominio", REF, ref_kinds=("domain",), significant=True),
        Field("description", "Descrizione", TEXT),
        # Shown and edited in the traceability card of the sheet, with the derived requirements of the function.
        Field("sections", "Sezioni SRS", REFS, ref_kinds=("requirement",), hidden=True),
        Field("rows_452", "Righe 4.5.2", STRLIST),
        Field("mode_availability", "Disponibilità nei modi (X / O)", MAP, options=ETCS_MODES),
        Field("proposed_component", "Componente logico proposto", REF, ref_kinds=("logical_component",)),
        Field("is_new", "Funzione nuova", BOOL),
        Field("new_reason", "Motivo", TEXT),
        Field("notes", "Note e decisioni", TEXT),
        Field("adrs", "ADR", REFS, ref_kinds=("adr",)),
        _common_status(("Proposta", "Rivista", "Approvata")),
    )),
    Kind("external_actor", "Attore esterno", "Attori esterni", "sa/actors", "System Analysis", "", "", (
        Field("id", "ID"),
        Field("name", "Nome"),
        Field("description", "Descrizione", TEXT),
    )),
    Kind("exchange_item", "Exchange Item", "Exchange Item", "sa/exchange-items", "System Analysis", "SA-6",
         "EI-nome", (
        Field("id", "ID"),
        Field("name", "Nome"),
        Field("type", "Tipo", ENUM, ("Messaggio", "Pacchetto", "Variabile", "Dato logico")),
        Field("nature", "Natura", ENUM, NATURES, significant=True),
        Field("meaning", "Significato", TEXT),
        Field("srs_origin", "Origine SRS"),
        Field("elements", "Elementi (variabili cap. 7)", TABLE, columns=(
            Column("variable", "Variabile"), Column("description", "Descrizione"),
            Column("unit", "Unità"), Column("range", "Campo"), Column("resolution", "Risoluzione"))),
        Field("notes", "Note", TEXT),
        _common_status(),
    )),
    Kind("functional_exchange", "Scambio funzionale", "Scambi funzionali", "sa/exchanges", "System Analysis", "SA-5",
         "FE-DFaa-DFbb-nn", (
        Field("id", "ID scambio"),
        Field("name", "Nome"),
        Field("source", "Produttore", REF, ref_kinds=EXCHANGE_ENDS, significant=True),
        Field("target", "Utilizzatore", REF, ref_kinds=EXCHANGE_ENDS, significant=True),
        Field("exchange_item", "Dato di interfaccia", REF, ref_kinds=("exchange_item",), significant=True),
        Field("nature", "Natura", ENUM, NATURES),
        Field("production_condition", "Condizione di produzione", ENUM,
              ("Sempre", "A ogni variazione", "Su evento", "Su richiesta")),
        Field("clauses", "Clausole", REFS, ref_kinds=("requirement",)),
        Field("producer_agreement", "Accordo del produttore"),
        Field("consumer_agreement", "Accordo dell'utilizzatore"),
        _common_status(("Proposto", "Concordato", "Approvato")),
    )),
    Kind("functional_chain", "Functional chain", "Functional chain", "sa/chains", "System Analysis", "SA-7",
         "FC-nome", (
        Field("id", "ID"),
        Field("title", "Titolo"),
        Field("capability", "Capability operativa"),
        Field("procedure", "Procedura o sezione SRS"),
        Field("responsible_domain", "Dominio responsabile", REF, ref_kinds=("domain",)),
        Field("adrs", "Decisioni collegate", REFS, ref_kinds=("adr",)),
        Field("trigger", "Trigger", TEXT),
        Field("final_effect", "Effetto osservabile finale", TEXT),
        Field("preconditions", "Precondizioni", TEXT),
        Field("postconditions", "Postcondizioni", TEXT),
        Field("out_of_scope", "Fuori ambito", TEXT),
        Field("steps", "Percorso", TABLE, columns=(
            Column("cycle", "Ciclo"),
            Column("function", "Funzione SF", REF, ref_kinds=FUNCTIONS),
            Column("what", "Cosa fa"),
            Column("data", "Dato prodotto"),
            Column("nature", "Natura", ENUM, options=NATURES),
            Column("exchange", "Scambio", REF, ref_kinds=("functional_exchange",)),
            Column("srs", "Voci SRS"),
            Column("component", "Componente logico", REF, ref_kinds=("logical_component",)))),
        Field("variants", "Varianti", TABLE, columns=(
            Column("variant", "Variante"),
            Column("type", "Tipo", ENUM, options=("Exchange Scenario", "Chain distinta")),
            Column("difference", "Differenza dal nominale"), Column("srs", "Voci SRS"))),
        Field("decision", "Decisione (metriche)", TEXT),
        Field("oracle", "Oracolo", TEXT),
        Field("integration_test", "Caso di test di integrazione", TEXT),
        _common_status(),
    )),
    Kind("logical_function", "Funzione logica", "Funzioni logiche", "la/functions", "Logical Architecture", "LA-2",
         "LF-DFnn-mm-kk", (
        Field("id", "ID"),
        Field("name", "Nome"),
        Field("refines", "Funzione di sistema raffinata", REF, ref_kinds=("system_function",), significant=True),
        Field("contributes_to", "Contribuisce anche a", REFS, ref_kinds=("system_function",)),
        Field("parent", "Funzione logica padre", REF, ref_kinds=("logical_function",), picker=True),
        Field("component", "Componente LC (allocazione)", REF, ref_kinds=("logical_component",), significant=True,
              picker=True),
        Field("description", "Descrizione", TEXT),
        # Shown and edited in the traceability card of the sheet, like the sections of a system function.
        # The derived requirements of the function are those whose «Funzione logica» is this one (SA-4).
        Field("detail_requirements", "Voci SRS di dettaglio", REFS, ref_kinds=("requirement",), hidden=True),
        Field("notes", "Note", TEXT),
        _common_status(("Proposta", "Rivista", "Approvata")),
    )),
    Kind("logical_component", "Componente logico", "Componenti logici", "la/components", "Logical Architecture",
         "LA-1", "LC-nn", (
        Field("id", "ID"),
        Field("name", "Nome"),
        Field("parent", "Macro-componente", REF, ref_kinds=("logical_component",), significant=True),
        Field("responsibility", "Responsabilità", TEXT),
        Field("cycle_position", "Posizione nel ciclo"),
        Field("safety_constraints", "Vincoli di sicurezza", TEXT),
        Field("owner", "Owner"),
        _common_status(),
    )),
    Kind("component_exchange", "Component Exchange", "Component Exchange", "la/exchanges", "Logical Architecture",
         "LA-3", "CE-LCaa-LCbb-nn", (
        Field("id", "ID"),
        Field("source", "Da LC", REF, ref_kinds=("logical_component",), significant=True),
        Field("target", "A LC", REF, ref_kinds=("logical_component",), significant=True),
        Field("realizes", "FE o scambio interno realizzato", REFS, ref_kinds=("functional_exchange",)),
        Field("exchange_item", "Exchange Item", REF, ref_kinds=("exchange_item",)),
        Field("periodicity", "Periodicità / evento"),
        Field("cycle_rw", "Ciclo di produzione e lettura"),
        _common_status(("Proposto", "Concordato", "Approvato")),
    )),
    Kind("chain_realization", "Realizzazione chain in LA", "Realizzazioni chain in LA", "la/chains",
         "Logical Architecture", "LA-4", "", (
        Field("chain", "Functional chain", REF, ref_kinds=("functional_chain",)),
        Field("outcome", "Esito", ENUM, ("Eseguibile", "Non eseguibile"), significant=True),
        Field("outcome_reason", "Motivo", TEXT),
        Field("steps", "Passi", TABLE, columns=(
            Column("sa_step", "# passo SA"), Column("cycle", "Ciclo"),
            Column("logical_function", "Funzione logica", REF, ref_kinds=("logical_function",)),
            Column("component", "Componente", REF, ref_kinds=("logical_component",)),
            Column("out_exchange", "Component Exchange in uscita", REF, ref_kinds=("component_exchange",)),
            Column("cycle_step", "Passo del ciclo applicativo"), Column("notes", "Note"))),
        _common_status(),
    )),
    Kind("team", "Team", "Team (EPBS-1)", "x/teams", "Trasversali", "EPBS-1", "Tn", (
        Field("id", "ID"),
        Field("name", "Nome"),
        Field("domains", "Domini", REFS, ref_kinds=("domain",), significant=True),
        Field("components", "Componenti LC", REFS, ref_kinds=("logical_component",), significant=True),
        Field("members", "Membri del team", STRLIST),
        Field("referent", "Referente", choices_from="members"),
        Field("independent_verifier", "Verificatore indipendente"),
        Field("notes", "Note", TEXT),
    )),
    Kind("adr", "Decisione architetturale", "Decisioni architetturali (ADR)", "x/adr", "Trasversali", "X-1",
         "ADR-nnn", (
        Field("id", "ID"),
        Field("title", "Titolo"),
        Field("status", "Stato", ENUM, ("Proposta", "Decisa", "Superata"), significant=True),
        Field("superseded_by", "Superata da", REF, ref_kinds=("adr",)),
        Field("date_decider", "Data e decisore"),
        Field("context", "Contesto", TEXT),
        Field("affected", "Voci SRS ed elementi interessati", TEXT),
        Field("options", "Opzioni", TABLE, columns=(
            Column("option", "Opzione"), Column("description", "Descrizione"),
            Column("pros", "Vantaggi"), Column("cons", "Svantaggi e rischi"))),
        Field("decision", "Decisione", TEXT),
        Field("rationale", "Motivazione", TEXT),
        Field("consequences", "Conseguenze", TEXT),
        Field("review_when", "Da rivedere quando", TEXT),
    )),
    Kind("clarification", "Richiesta di chiarimento", "Richieste di chiarimento (CQ)", "x/cq", "Trasversali", "X-2",
         "CQ-nn", (
        Field("id", "ID"),
        Field("clause", "Clausola", REF, ref_kinds=("requirement",)),
        Field("problem", "Problema", TEXT),
        Field("interim_position", "Posizione adottata nel frattempo", TEXT),
        Field("model_impact", "Impatto sul modello", TEXT),
        Field("recipient", "Destinatario"),
        Field("status", "Stato", ENUM, ("Aperta", "Chiusa"), significant=True),
    )),
)

KINDS_BY_NAME = {k.name: k for k in KINDS}
KINDS_BY_FOLDER = {k.folder: k for k in KINDS}


def kind(name):
    return KINDS_BY_NAME[name]
