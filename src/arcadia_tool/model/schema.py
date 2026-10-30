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


# Types of architectural decision (X-1): each a template with its own fields (see the ADR kind).
ADR_NEW_DOMAIN = "Nuovo dominio funzionale"
ADR_DELETE_DOMAIN = "Eliminazione di dominio"
ADR_MERGE_DOMAINS = "Fusione di domini"
ADR_SPLIT_DOMAIN = "Scissione di dominio"
ADR_DOMAIN_SCOPE = "Ridefinizione dello scopo del dominio"
ADR_SECTION = "Riallocazione di sezione o clausola"
ADR_EXCLUSION = "Esclusione di sezione o clausola"
ADR_FUNCTION = "Spostamento di una funzione tra domini"
ADR_OWNER = "Proprietà di un'informazione / confine tra domini"
ADR_IMPLEMENTATION = "Scelta lasciata all'implementazione"
ADR_PRODUCT_OPTION = "Opzione di prodotto"
ADR_LOGICAL = "Decisione di architettura logica"
ADR_WAIVER = "Deroga a una regola della metodologia"
ADR_OTHER = "Altro / decisione trasversale"
# (type, when it is used: shown when the type is chosen)
ADR_TYPES = (
    (ADR_NEW_DOMAIN, "Un'area della specifica non ha un dominio adatto: si propone un nuovo dominio (A2, A6)."),
    (ADR_DELETE_DOMAIN, "Il dominio non ha più uno scopo proprio: sezioni, funzioni e informazioni passano ad altri."),
    (ADR_MERGE_DOMAINS, "Due o più domini separati da un confine artificiale (catene che rimbalzano, scambi densi)."),
    (ADR_SPLIT_DOMAIN, "Lo scopo del dominio non sta in una frase o la dimensione è eccessiva: si divide."),
    (ADR_DOMAIN_SCOPE, "Il perimetro di un dominio cambia: estensione, riduzione o cambio totale di scopo."),
    (ADR_SECTION, "Dubbio sul dominio principale o sui contributori di una sezione o clausola (A4)."),
    (ADR_EXCLUSION, "Una sezione o clausola, contenuta in una sezione di cui il dominio è principale, è esclusa di "
                    "proposito dal dominio: perché non la traccia (A4)."),
    (ADR_FUNCTION, "Una funzione di sistema appartiene allo scopo di un altro dominio."),
    (ADR_OWNER, "Chi produce un'informazione non è evidente (B4, D10), o una catena rimbalza ma il confine resta "
                "(A5)."),
    (ADR_IMPLEMENTATION, "La voce SRS lascia una scelta all'implementazione (B5, domanda 1)."),
    (ADR_PRODUCT_OPTION, "Una funzione è opzionale in uno o più modi: decisione di prodotto."),
    (ADR_LOGICAL, "Architettura logica: allocazione di funzioni, scissione o fusione di componenti, interfacce."),
    (ADR_WAIVER, "Una regola della metodologia non viene rispettata, consapevolmente e con una motivazione."),
    (ADR_OTHER, "Una scelta non ovvia che vincola le altre fasi e non rientra nei tipi precedenti."),
)
ADR_TYPE_LABELS = tuple(name for name, _ in ADR_TYPES)
DOMAIN_ADR_TYPES = (ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE)
# Where the types apply: the phase of the method (SA, LA) or the whole of it.
ADR_AREAS = (
    ("Domini funzionali (SA)", DOMAIN_ADR_TYPES),
    ("Voci SRS, funzioni e scambi (SA)", (ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION,
                                          ADR_PRODUCT_OPTION, ADR_EXCLUSION)),
    ("Architettura logica (LA)", (ADR_LOGICAL,)),
    ("Generali", (ADR_WAIVER, ADR_OTHER)),
)


def adr_area(adr_type):
    """The area a type of ADR applies to («Domini funzionali (SA)»…), or "" (an ADR without a type)."""
    return next((area for area, types in ADR_AREAS if adr_type in types), "")
ADR_DETAILS = "Dettagli del tipo di decisione"
DA_DECISION = "Decisione della DA"
# «Commenti DA»: the DA asks the proposer for changes before deciding (the ADR stays active).
DA_DECISIONS = ("Commenti DA", "Accolta", "Accolta con modifiche", "Respinta")


def _adr(field, *types):
    """A field of the given types of ADR, in the section of the details of the type."""
    return Field(**{**field.__dict__, "when": ("adr_type", types), "section": ADR_DETAILS})


def _adr_except(field, *types):
    """A common field of the ADR, but not of the given types (an ADR without a type has it)."""
    others = tuple(name for name in ADR_TYPE_LABELS if name not in types) + (None,)
    return Field(**{**field.__dict__, "when": ("adr_type", others)})


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    type: str = STR
    ref_kinds: tuple = ()
    options: tuple = ()
    # Chosen in a list computed from the element (the name of the function in model.adr.CHOICES): e.g. the SRS
    # items of the domain split by an ADR, or the resulting domains written above.
    choices: str = ""


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
    # A name chosen among the members of the team of a reference field of the same element (the member of the team
    # proposing an ADR).
    members_of: str = ""
    # Copied from a referenced element, not entered: (reference field, field of the referenced element).
    derived_from: tuple = ()
    # Analysis data, not imported: editable also on read-only SRS items (e.g. the allocation to domains).
    analysis: bool = False
    # False: shown (derived_from) but not saved, always read from the referenced element (the chapter 9
    # category of the SRS item of a trace record).
    stored: bool = True
    # REF chosen in a window with search and ticks (one element) instead of a drop-down list.
    picker: bool = False
    # REFS of SRS items: only the sections (three numbers) can be chosen in the window with ticks.
    sections_only: bool = False
    # Written by the tool (e.g. the domain created by the approval of an ADR): shown read-only, once it has a value.
    by_tool: bool = False
    # Computed from the other fields of the element, shown read-only and not saved: the name of the function in
    # model.adr.COMPUTED (e.g. the SRS items of the domains merged by an ADR).
    computed: str = ""
    # Shown only when another field of the element has one of these values: (field, (values…)), e.g. the fields
    # of a type of ADR.
    when: tuple = ()

    def applies(self, element):
        """The field belongs to the element as it is (see `when`)."""
        return not self.when or element.get(self.when[0]) in self.when[1]


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

# Graphic views of the SA (the «diagram» kind), created by the users, as many as they need (the functional
# breakdown of the whole model, under SA-1 and SA-2, is computed and not stored).
DIAGRAM_BREAKDOWN = "Domini funzionali"  # SA-1: the domains, opened one by one
DIAGRAM_FUNCTIONS = "Funzioni per dominio"  # SA-2: the same drawing, the domains open on their functions
DIAGRAM_DATAFLOW = "Dataflow funzionale"
DIAGRAM_CHAIN = "Catena funzionale"
DIAGRAM_SCENARIO = "Scenario di scambio"
DIAGRAM_TYPES = (DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS, DIAGRAM_DATAFLOW, DIAGRAM_CHAIN, DIAGRAM_SCENARIO)
DIAGRAM_LEVELS = ("Per dominio", "Per funzione")


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
        # Left out on purpose by the domains principal of a section containing it (with an ADR of exclusion):
        # chosen with ticks from the sheet of the domain.
        Field("excluded_domains", "Esclusa dai domini (A4)", REFS, ref_kinds=("domain",), analysis=True,
              hidden=True),
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
        # Mapped on one system function (SA-2) and allocated to one logical function (LA-2), each chosen with its
        # window from the sheet's card (the system function also from the sheet of the function).
        Field("system_function", "Funzione di sistema", REF, ref_kinds=("system_function",), significant=True,
              hidden=True),
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
        # Linked by hand by earlier versions: now among the ADR about the domain (see related_adrs).
        Field("adrs", "Decisioni collegate", REFS, ref_kinds=("adr",), hidden=True),
        Field("related_adrs", "Decisioni architetturali (ADR)", REFS, ref_kinds=("adr",), stored=False,
              computed="related_adrs"),
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
        Field("proposed_component", "Componente logico proposto", REF, ref_kinds=("logical_component",)),
        Field("is_new", "Funzione nuova", BOOL),
        Field("new_reason", "Motivo", TEXT),
        Field("notes", "Note e decisioni", TEXT),
        # Linked by hand by earlier versions: now among the ADR about the function (see related_adrs).
        Field("adrs", "ADR", REFS, ref_kinds=("adr",), hidden=True),
        Field("related_adrs", "Decisioni architetturali (ADR)", REFS, ref_kinds=("adr",), stored=False,
              computed="related_adrs"),
        # Imported from the SA-2 catalogue in Excel: its ID there (a re-import deletes it if no longer there).
        Field("catalogue_id", "ID nel catalogo SA-2", hidden=True),
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
        # One team only is the Design Authority: it integrates the branches into main (see model.teams).
        Field("design_authority", "Design Authority (DA)", BOOL, significant=True),
        Field("domains", "Domini", REFS, ref_kinds=("domain",), significant=True),
        Field("components", "Componenti LC", REFS, ref_kinds=("logical_component",), significant=True),
        # Each member with the ID of their local account, written by the DA (see model.teams).
        Field("members", "Membri del team", TABLE, columns=(
            Column("name", "Nome e cognome"), Column("email", "E-mail"), Column("role", "Ruolo"),
            Column("account", "ID account"))),
        Field("referent", "Referente", choices_from="members"),
        Field("independent_verifier", "Verificatore indipendente"),
        Field("notes", "Note", TEXT),
    )),
    Kind("adr", "Decisione architetturale", "Decisioni architetturali (ADR)", "x/adr", "Trasversali", "X-1",
         "ADR-nnn", (
        Field("id", "ID"),
        Field("title", "Titolo"),
        # The type gives the template: the fields of its details (chosen when the ADR is created).
        Field("adr_type", "Tipo di decisione", ENUM, ADR_TYPE_LABELS, significant=True),
        # The deletion of a domain: the domain right under the type.
        Field("deleted_domain", "Dominio interessato", REF, ref_kinds=("domain",), section="Identificazione",
              when=("adr_type", (ADR_DELETE_DOMAIN,))),
        # «In revisione DA»: the Design Authority is examining it; «Revisionato DA»: it has examined it. Both still
        # open, not decided.
        Field("status", "Stato", ENUM, ("Proposta", "In revisione DA", "Revisionato DA", "Decisa", "Superata"),
              significant=True),
        # The ADR can be many: chosen in a window with search and ticks, not in a drop-down list.
        Field("superseded_by", "Superata da", REF, ref_kinds=("adr",), picker=True, section="Identificazione"),
        Field("proposer", "Proponente (team)", REF, ref_kinds=("team",), section="Identificazione"),
        Field("proposer_member", "Proponente (membro del team)", members_of="proposer", section="Identificazione"),
        # The domain or the system function whose sheet the ADR was created from (among its ADR, see related_adrs).
        Field("concerns", "Riguarda", REFS, ref_kinds=("domain", "system_function"), hidden=True),
        # Set by the tool when the ADR is decided (the decider is always the Design Authority).
        Field("decision_date", "Data della decisione", by_tool=True),
        # Description, relations and options: not in a new domain, whose details say it all (its sections); the
        # deletion of a domain has only the motivation and the observations of the DA (and its domain, above).
        _adr_except(Field("context", "Contesto", TEXT), ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        # The SRS sections and clauses the decision is about, chosen with ticks; the other elements in a text.
        _adr_except(Field("srs_items", "Voci SRS interessate", REFS, ref_kinds=("requirement",)), ADR_NEW_DOMAIN,
                    ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        _adr_except(Field("affected", "Altri elementi del modello interessati", TEXT), ADR_NEW_DOMAIN,
                    ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        _adr_except(Field("options", "Opzioni", TABLE, columns=(
            Column("option", "Opzione"), Column("description", "Descrizione"),
            Column("pros", "Vantaggi"), Column("cons", "Svantaggi e rischi"))), ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        _adr_except(Field("decision", "Decisione", TEXT), ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        _adr_except(Field("rationale", "Motivazione", TEXT), ADR_NEW_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        # The decision of the Design Authority on the proposal, in every ADR (changed only by its members, see
        # model.teams).
        Field("da_decision", "Esito della decisione DA", ENUM, DA_DECISIONS, section=DA_DECISION),
        Field("da_notes", "Osservazioni DA", TEXT, section=DA_DECISION),
        _adr_except(Field("consequences", "Conseguenze", TEXT), ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        _adr_except(Field("review_when", "Da rivedere quando", TEXT), ADR_NEW_DOMAIN, ADR_DELETE_DOMAIN, ADR_MERGE_DOMAINS, ADR_SPLIT_DOMAIN, ADR_DOMAIN_SCOPE, ADR_SECTION, ADR_FUNCTION, ADR_OWNER, ADR_IMPLEMENTATION, ADR_PRODUCT_OPTION, ADR_EXCLUSION),
        # --- details of the type (see ADR_TYPES) ---------------------------------------------------------
        _adr(Field("domain", "Dominio interessato", REF, ref_kinds=("domain",)), ADR_DOMAIN_SCOPE),
        _adr(Field("merged_domains", "Domini da fondere", REFS, ref_kinds=("domain",)), ADR_MERGE_DOMAINS),
        # The split is the dual of the merge: one domain, several resulting ones, its SRS items shared among them.
        _adr(Field("split_domain", "Dominio da scindere", REF, ref_kinds=("domain",)), ADR_SPLIT_DOMAIN),
        # The name only: the ID (DFnn) is given by the tool when the Design Authority approves the ADR.
        _adr(Field("new_domain_name", "Nome del dominio proposto"), ADR_NEW_DOMAIN),
        # The name only: the ID is the one of the domain that is kept, or given by the tool after the merge.
        _adr(Field("proposed_domain", "Nome del dominio risultante"), ADR_MERGE_DOMAINS),
        _adr(Field("kept_domain", "Dominio che resta (se è uno di quelli fusi)", REF, ref_kinds=("domain",)),
             ADR_MERGE_DOMAINS),
        _adr(Field("scope_change", "Natura della modifica", ENUM,
                   ("Estensione", "Riduzione", "Cambio totale di scopo")), ADR_DOMAIN_SCOPE),
        # Read from the sheet of the domain: always the mission it has now.
        _adr(Field("mission_current", "Missione attuale", TEXT, stored=False, computed="current_mission"),
             ADR_DOMAIN_SCOPE),
        _adr(Field("mission_proposed", "Missione proposta (una o due frasi)", TEXT), ADR_NEW_DOMAIN,
             ADR_MERGE_DOMAINS, ADR_DOMAIN_SCOPE),
        _adr(Field("proposal_reason", "Perché si propone il nuovo dominio", TEXT), ADR_NEW_DOMAIN),
        _adr(Field("proposal_benefits", "Vantaggi della proposta", TEXT), ADR_NEW_DOMAIN),
        _adr(Field("scope_reason", "Motivazione della modifica", TEXT), ADR_DOMAIN_SCOPE),
        # The sections the domain takes from other domains, or gives to them, chosen with ticks.
        _adr(Field("sections_acquired", "Sezioni acquisite dal dominio", REFS, ref_kinds=("requirement",),
                   sections_only=True), ADR_DOMAIN_SCOPE),
        _adr(Field("sections_ceded", "Sezioni cedute dal dominio", REFS, ref_kinds=("requirement",),
                   sections_only=True), ADR_DOMAIN_SCOPE),
        # The names only: the IDs are given by the tool, one of them keeps the ID of the domain split.
        _adr(Field("new_domains", "Domini risultanti", TABLE, columns=(
            Column("name", "Nome del dominio risultante"), Column("mission", "Missione proposta"),
            Column("team", "Team proposto", REF, ref_kinds=("team",)),
            Column("keeps_id", "Mantiene l'ID", ENUM, options=("Sì",)))), ADR_SPLIT_DOMAIN),
        # The SRS items of the domains merged (principal or contributing): those of the resulting domain.
        _adr(Field("merged_srs_items", "Voci SRS attribuite al dominio risultante", REFS, ref_kinds=("requirement",),
                   stored=False, computed="merged_srs_items"), ADR_MERGE_DOMAINS),
        # The sections (three numbers) of a new domain, chosen with ticks.
        _adr(Field("sections_allocated", "Sezioni allocate al dominio", REFS, ref_kinds=("requirement",),
                   sections_only=True), ADR_NEW_DOMAIN),
        # Each SRS item of the domain split, to one of the resulting domains written above.
        _adr(Field("split_allocation", "Ripartizione delle voci SRS tra i domini risultanti", TABLE, columns=(
            Column("item", "Voce SRS del dominio da scindere", choices="split_domain_items"),
            Column("destination", "Dominio risultante", choices="split_destinations"))), ADR_SPLIT_DOMAIN),
        # The reallocation of SRS items: the items (chosen with ticks, one or more, of sections of the same domain),
        # their domains now (read from them) and those proposed, with the motivation.
        _adr(Field("realloc_item", "Sezioni o clausole da riallocare", REFS, ref_kinds=("requirement",)),
             ADR_SECTION),
        _adr(Field("primary_current", "Dominio principale attuale", REF, ref_kinds=("domain",), stored=False,
                   computed="item_primary"), ADR_SECTION),
        _adr(Field("contributors_current", "Contributori attuali", REFS, ref_kinds=("domain",), stored=False,
                   computed="item_contributors"), ADR_SECTION),
        _adr(Field("primary_proposed", "Dominio principale proposto", REF, ref_kinds=("domain",)), ADR_SECTION),
        _adr(Field("contributors_proposed", "Contributori proposti", REFS, ref_kinds=("domain",)), ADR_SECTION),
        _adr(Field("realloc_reason", "Motivazione della riallocazione", TEXT), ADR_SECTION),
        # The exclusion of SRS items from a domain principal of the sections containing them: the items (one or more,
        # chosen with ticks), the domain, the sections they are excluded from (read from the model), why the domain
        # does not trace them, who traces them.
        _adr(Field("excluded_item", "Sezioni o clausole escluse", REFS, ref_kinds=("requirement",)), ADR_EXCLUSION),
        _adr(Field("excluding_domain", "Dominio che le esclude", REF, ref_kinds=("domain",)), ADR_EXCLUSION),
        _adr(Field("excluded_within", "Sezioni principali che le contengono", REFS, ref_kinds=("requirement",),
                   stored=False, computed="excluded_within"), ADR_EXCLUSION),
        _adr(Field("exclusion_reason", "Motivo della non tracciatura", TEXT), ADR_EXCLUSION),
        _adr(Field("traced_by", "Dominio che le traccia al suo posto (se c'è)", REF, ref_kinds=("domain",)),
             ADR_EXCLUSION),

        _adr(Field("function", "Funzione di sistema", REF, ref_kinds=("system_function",)), ADR_FUNCTION,
             ADR_PRODUCT_OPTION),
        # The move of a function: its domain now (read from it), the one proposed, the motivation.
        _adr(Field("function_domain", "Dominio attuale", REF, ref_kinds=("domain",), stored=False,
                   computed="function_domain"), ADR_FUNCTION, ADR_PRODUCT_OPTION),
        _adr(Field("to_domain", "Dominio proposto", REF, ref_kinds=("domain",)), ADR_FUNCTION),
        _adr(Field("move_reason", "Motivazione dello spostamento", TEXT), ADR_FUNCTION),
        # The owner of an information: who produces it now (read from the exchanges), the candidates, the one
        # chosen and why.
        _adr(Field("exchange_item", "Informazione (Exchange Item)", REF, ref_kinds=("exchange_item",)),
             ADR_OWNER),
        _adr(Field("item_producers", "Produttori attuali", REFS, ref_kinds=EXCHANGE_ENDS, stored=False,
                   computed="item_producers"), ADR_OWNER),
        _adr(Field("candidate_producers", "Produttori candidati", TABLE, columns=(
            Column("function", "Funzione", REF, ref_kinds=FUNCTIONS), Column("arguments", "Argomenti"))),
             ADR_OWNER),
        _adr(Field("chosen_producer", "Produttore scelto", REF, ref_kinds=FUNCTIONS), ADR_OWNER),
        _adr(Field("evidence_chains", "Catene funzionali usate come prova", REFS, ref_kinds=("functional_chain",)),
             ADR_OWNER),
        _adr(Field("owner_reason", "Motivazione della scelta", TEXT), ADR_OWNER),
        _adr(Field("team_proposed", "Team proposto o risultante", REF, ref_kinds=("team",)), ADR_NEW_DOMAIN,
             ADR_MERGE_DOMAINS),
        # Written by the approval of the Design Authority (see model.adr.approve_new_domain).
        _adr(Field("created_domain", "Dominio creato all'approvazione", REF, ref_kinds=("domain",), by_tool=True),
             ADR_NEW_DOMAIN),
        # A choice left to the implementation: the SRS item (chosen with ticks), its domain (read from it), the
        # choice left open, the one adopted and why.
        _adr(Field("impl_item", "Sezione o clausola", REF, ref_kinds=("requirement",), picker=True),
             ADR_IMPLEMENTATION),
        _adr(Field("impl_domain", "Dominio principale", REF, ref_kinds=("domain",), stored=False,
                   computed="item_primary"), ADR_IMPLEMENTATION),
        _adr(Field("open_choice", "Scelta lasciata all'implementazione", TEXT), ADR_IMPLEMENTATION),
        _adr(Field("adopted_choice", "Scelta adottata", TEXT), ADR_IMPLEMENTATION),
        _adr(Field("test_case", "Caso di prova (se la voce è un esempio)"), ADR_IMPLEMENTATION),
        _adr(Field("impl_reason", "Motivazione della scelta", TEXT), ADR_IMPLEMENTATION),
        _adr(Field("modes", "Modi interessati", MULTIENUM, ETCS_MODES), ADR_PRODUCT_OPTION),
        _adr(Field("product_choice", "Scelta", ENUM, ("Inclusa", "Esclusa", "Configurabile")),
             ADR_PRODUCT_OPTION),
        _adr(Field("parameter", "Parametro di configurazione (se configurabile)"), ADR_PRODUCT_OPTION),
        _adr(Field("option_reason", "Motivazione della scelta", TEXT), ADR_PRODUCT_OPTION),
        _adr(Field("la_operation", "Operazione", ENUM, ("Allocazione di funzioni", "Scissione di componente",
                                                       "Fusione di componenti", "Interfaccia tra componenti")),
             ADR_LOGICAL),
        _adr(Field("la_elements", "Elementi coinvolti", REFS, ref_kinds=("logical_function", "logical_component")),
             ADR_LOGICAL),
        _adr(Field("indicators", "Indicatori considerati (fan-in/out, scambi densi, dipendenze cicliche)", TEXT),
             ADR_LOGICAL),
        _adr(Field("rule", "Regola o controllo derogato (es. SA2-07)"), ADR_WAIVER),
    )),
    Kind("clarification", "Richiesta di chiarimento", "Richieste di chiarimento (CQ)", "x/cq", "Trasversali", "X-2",
         "CQ-nn", (
        Field("id", "ID"),
        # Chosen with ticks among the SRS items (chapters, search), as the other references to the specification.
        Field("clause", "Clausola", REF, ref_kinds=("requirement",), picker=True),
        Field("problem", "Problema", TEXT),
        Field("interim_position", "Posizione adottata nel frattempo", TEXT),
        Field("model_impact", "Impatto sul modello", TEXT),
        # The Design Authority or a team: asked when the request is created.
        Field("recipient", "Destinatario", REF, ref_kinds=("team",)),
        # A recipient written as text by earlier versions, that is not a team of the model (shown in the table).
        Field("recipient_text", "Destinatario (testo)", hidden=True),
        Field("status", "Stato", ENUM, ("Aperta", "Chiusa"), significant=True),
    )),
    # A graphic view of the SA, composed by the user with elements of the model (see model.diagrams): shown in the
    # model tree under the SA it belongs to, not as a kind of its own.
    Kind("diagram", "Vista grafica", "Viste grafiche", "sa/views", "System Analysis", "", "", (
        Field("name", "Nome"),
        Field("diagram_type", "Tipo di vista", ENUM, DIAGRAM_TYPES, significant=True),
        Field("description", "Descrizione", TEXT),
        # Catena funzionale and scenario: the chain whose steps are shown.
        Field("chain", "Functional chain", REF, ref_kinds=("functional_chain",)),
        Field("level", "Livello", ENUM, DIAGRAM_LEVELS),
        # What the view shows and where: {uuid of an element (or «step:n» of the chain): "x,y"}. A text and not a
        # pair of numbers: the three-way merge takes a position as a whole.
        Field("layout", "Elementi e posizioni", MAP, hidden=True),
        # Domini funzionali: the domains shown open, on their functions (uuids, not references: deleting a
        # domain does not warn about the views).
        Field("opened", "Domini aperti", STRLIST, hidden=True),
        # Dataflow: where the arrow of an exchange drawn with a connector leaves and reaches its elements, {uuid of
        # the exchange: "R500 L250"} (side and thousandths along it, see ui.diagrams.anchor_point).
        Field("anchors", "Punti di attacco", MAP, hidden=True),
    )),
)

KINDS_BY_NAME = {k.name: k for k in KINDS}
KINDS_BY_FOLDER = {k.folder: k for k in KINDS}


def kind(name):
    return KINDS_BY_NAME[name]
