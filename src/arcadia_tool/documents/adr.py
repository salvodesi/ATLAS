"""The sheet of an architectural decision (X-1): the template of its type (the fields of its sheet in ATLAS, the guide
in grey italics) or an ADR of the model filled in; and the register of the open ADR."""
from arcadia_tool.documents.layout import SheetWriter
from arcadia_tool.documents.values import table_rows, text_of
from arcadia_tool.model.adr import COMPUTED, common_fields, type_fields
from arcadia_tool.model.schema import (ADR_TYPES, DA_DECISION, ENUM, KINDS_BY_NAME, MULTIENUM, REF, REFS, TABLE,
                                       TEXT)

STATUSES = KINDS_BY_NAME["adr"].field("status").options
WIDTHS = (30, 22, 20, 26, 22, 34)
WHO = "Chi compila: chi propone la decisione (team o Design Authority) · Quando serve, in qualunque passo"

# What the tool computes from the model (see model.adr.COMPUTED): in the template, as it is when proposed.
COMPUTED_HINTS = {
    "merged_srs_items": "le voci SRS dei domini da fondere (principale o contributore)",
    "current_mission": "la missione scritta ora nella scheda del dominio (SA-1)",
    "item_primary": "il dominio principale della voce, suo o della sezione che la contiene (A4)",
    "item_contributors": "i domini contributori della voce, suoi o della sezione che la contiene (A4)",
    "function_domain": "il dominio della funzione, dal catalogo delle funzioni (SA-2)",
    "item_producers": "i produttori degli scambi che portano l'informazione (SA-5)",
}
# The choices of a column computed from the other fields (see model.adr.CHOICES).
CHOICE_HINTS = {
    "split_domain_items": "una voce SRS del dominio da scindere",
    "split_destinations": "uno dei domini risultanti scritti sopra",
}
# The guides of the general template, for the fields it has too.
FIELD_HINTS = {"context": "Il problema e perché va deciso ora",
               "consequences": "Cosa cambia nel modello, nei requisiti, nei test",
               "review_when": "Condizione che riapre la decisione, se esiste"}
EXAMPLES = {"domain": "DF07 · Odometria", "team": "T5 · Odometria", "requirement": "3.14.4.2",
            "system_function": "SF-DF07-03 · Stimare la velocità", "exchange_item": "EI-velocità_stimata",
            "functional_chain": "FC-frenatura_di_servizio", "logical_function": "LF-DF07-03-01",
            "logical_component": "LC-04", "adr": "ADR-nnn", "external_actor": "Conducente"}
SPANS = {1: (6,), 2: (3, 3), 3: (2, 2, 2), 4: (1, 2, 1, 2), 5: (1, 1, 1, 1, 2)}


def _examples(kinds):
    return " / ".join(f"es. {EXAMPLES[k]}" if k in EXAMPLES else KINDS_BY_NAME[k].label for k in kinds)


def hint(f):
    """The guide in grey italics in the cell of the field (to replace when the template is filled in)."""
    if f.name == "decision_date":
        return "gg/mm/aaaa · impostata da ATLAS quando la Design Authority decide"
    if f.computed:
        return f"Calcolato da ATLAS: {COMPUTED_HINTS.get(f.computed, 'dal modello')}"
    if f.by_tool:
        return "Scritto da ATLAS all'approvazione della Design Authority"
    if f.members_of:
        return "Uno dei membri del team proponente: es. Anna Bianchi"
    if f.type == ENUM:
        return " / ".join(f.options)
    if f.type == MULTIENUM:
        return "Uno o più tra: " + ", ".join(f.options)
    if f.type == REF:
        return _examples(f.ref_kinds)
    if f.type == REFS:
        if f.sections_only:
            return "Una o più sezioni (tre numeri, es. 3.4.1)"
        return "Uno o più: " + _examples(f.ref_kinds)
    return FIELD_HINTS.get(f.name, "")


def guide(adr_type):
    """«Come si compila»: where the ADR is opened in ATLAS and what the tool fills in by itself."""
    text = ("In ATLAS si crea con «Nuova ADR» e il tipo «" + str(adr_type or "") + "»: la scheda ha gli stessi "
            "campi di questo template.")
    computed = [f.label for f in type_fields(adr_type) if f.computed or f.by_tool]
    if len(computed) == 1:
        text += (f" Il campo «{computed[0]}» è compilato da ATLAS dal modello: qui si riporta com'è al momento "
                 "della proposta.")
    elif computed:
        text += (" I campi " + ", ".join(f"«{c}»" for c in computed) + " sono compilati da ATLAS dal modello: qui "
                 "si riportano come sono al momento della proposta.")
    return text + (" La data della decisione è quella in cui la Design Authority decide (la DA è sempre il decisore);"
                   " l'esito e le osservazioni della DA sono nella sezione «Decisione della DA».")


def _write(w, doc, adr, f):
    """A field of the ADR: its value (adr given) or the guide of the template."""
    model = doc.model
    if f.type == TABLE:
        sizes = SPANS[len(f.columns)]
        columns = [(c.label + (f" ({CHOICE_HINTS[c.choices]})" if not doc.filled and c.choices in CHOICE_HINTS
                               else ""), size, c.options) for c, size in zip(f.columns, sizes)]
        w.table(columns, table_rows(model, adr, f) if adr is not None else None, empty=5, label=f.label)
        return
    if adr is None:
        w.field(f.label, hint=hint(f), options=f.options if f.type == ENUM else (), tall=f.type == TEXT)
        return
    computed = COMPUTED[f.computed](model, adr) if f.computed in COMPUTED else None
    w.field(f.label, text_of(model, adr, f, computed), tall=f.type == TEXT)


def write_adr(ws, doc, adr_type, adr=None, line=""):
    """The sheet of an ADR of the type: the template (adr None) or the ADR filled in."""
    model = doc.model
    kind = KINDS_BY_NAME["adr"]
    w = SheetWriter(ws, WIDTHS)
    title = f"X-1 · Decisione architetturale (ADR) · {adr_type or 'senza tipo'}"
    if adr is not None:
        title += f" · {adr.get('id') or ''}"
    purpose = dict(ADR_TYPES).get(adr_type, "Registrare una scelta non ovvia, le alternative e le conseguenze.")
    w.intro(title, line, purpose, guide(adr_type))
    if adr is None:
        w.document({"Template": ("X-1", False), "Team / dominio": ("es. T5 · DF07, DF08", True),
                    "Versione": ("es. 0.1", True), "Data": ("gg/mm/aaaa", True),
                    "Stato": ("Bozza / In revisione / Approvato", True),
                    "Baseline SRS": ("SUBSET-026 v3.6.0", False)})
    else:
        team = model.get(adr.get("proposer")) if adr.get("proposer") else None
        w.document({"Template": ("X-1", False), "Team / dominio": ((team.get("id") or "") if team else "", False),
                    "Autore": (adr.get("proposer_member") or doc.author, False), "Data": (doc.date, False),
                    "Stato": (adr.get("status") or "", False), "Baseline SRS": (doc.baseline, False)})
    w.heading("Identificazione")
    if adr is None:
        w.field("ID e titolo", hint="ADR-nnn · titolo della decisione")
        w.field("Tipo di decisione", adr_type or "")
        w.field(kind.field("status").label, hint=" / ".join(STATUSES), options=STATUSES)
    else:
        w.field("ID e titolo", " · ".join(t for t in (adr.get("id"), adr.get("title")) if t))
        w.field("Tipo di decisione", adr_type or "")
        w.field(kind.field("status").label, adr.get("status") or "")
    for name in ("superseded_by", "proposer", "proposer_member", "decision_date"):
        _write(w, doc, adr, kind.field(name))
    common = common_fields(adr_type)
    for f in common:  # e.g. the domain of a deletion, right under the type (as in the sheet)
        if f.section == "Identificazione":
            _write(w, doc, adr, f)
    details = type_fields(adr_type)
    if details:
        w.heading(f"Dettagli: {adr_type}")
        for f in details:
            _write(w, doc, adr, f)
    described = [f for f in common if f.section not in ("Identificazione", DA_DECISION)]
    if described:
        w.heading("Descrizione")
        for f in described:
            _write(w, doc, adr, f)
    decided = [f for f in common if f.section == DA_DECISION]
    if decided:
        w.heading(DA_DECISION)
        for f in decided:
            _write(w, doc, adr, f)
    w.finish()
    return w


REGISTER_COLUMNS = [("ID dell'ADR", 1, ()), ("Breve descrizione", 3, ()), ("Team proponente", 1, ()),
                    ("Stato", 1, STATUSES)]


def write_register(ws, doc, line=""):
    """The register of the open ADR (not decided yet by the Design Authority), filled in from the model."""
    from arcadia_tool.storage.adr_register import open_adrs

    w = SheetWriter(ws, WIDTHS)
    w.intro("X-1 · Registro delle decisioni architetturali (ADR) aperte", line,
            "Tenere sotto controllo le ADR proposte e non ancora decise dalla Design Authority.",
            "Una riga per ADR aperta: l'ID e il titolo della sua scheda, il team che l'ha proposta e lo stato. Quando "
            "la Design Authority decide, l'ADR esce dal registro.")
    w.document({"Template": ("X-1", False), "Team / dominio": ("Tutti", False), "Autore": (doc.author, False),
                "Data": (doc.date, False), "Baseline SRS": (doc.baseline, False)})
    w.table(REGISTER_COLUMNS, [list(row) for row in open_adrs(doc.model)], label="ADR aperte")
    w.finish()
    return w


