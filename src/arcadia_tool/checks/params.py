"""Parameters of the checks: what a project can change in a check (a maximum, a list of chapters, the formats of
the IDs…). Each has a type, the value of the methodology (default) and its limits; a profile (see config) stores
only the values changed."""
import re
from dataclasses import dataclass, field

from arcadia_tool.model.schema import ETCS_MODES, KINDS_BY_NAME, NATURES

INT, BOOL, STRINGS, DOMAIN, DOMAINS, REGEX, MAP_STRINGS, MAP_REGEX = (
    "int", "bool", "strings", "domain", "domains", "regex", "map_strings", "map_regex")


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    type: str
    default: object = None
    minimum: int = None
    maximum: int = None
    hint: str = ""
    keys: tuple = field(default=())  # the keys of a map (e.g. the kinds of sheet, the natures)
    required: bool = False  # the check cannot run without a value (e.g. the coding domains)

    def problem(self, value, model):
        """What is wrong in a value, or None."""
        if value is None or value == "" or value == [] or value == {}:
            return f"«{self.label}» non indicato." if self.required else None
        if self.type == INT:
            if not isinstance(value, int) or isinstance(value, bool):
                return f"«{self.label}» deve essere un numero intero."
            if self.minimum is not None and value < self.minimum:
                return f"«{self.label}» deve essere almeno {self.minimum}."
            if self.maximum is not None and value > self.maximum:
                return f"«{self.label}» deve essere al massimo {self.maximum}."
        elif self.type == BOOL and not isinstance(value, bool):
            return f"«{self.label}» deve essere sì o no."
        elif self.type == STRINGS and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            return f"«{self.label}» deve essere un elenco di testi."
        elif self.type in (DOMAIN, DOMAINS):
            uuids = [value] if self.type == DOMAIN else value
            domains = {e.uuid for e in model if e.kind == "domain"}
            if not isinstance(uuids, list) or any(u not in domains for u in uuids):
                return f"«{self.label}»: indica domini che esistono nel modello."
        elif self.type == REGEX:
            return _regex_problem(self.label, value)
        elif self.type in (MAP_STRINGS, MAP_REGEX):
            if not isinstance(value, dict):
                return f"«{self.label}» non è leggibile."
            for key, item in value.items():
                if self.type == MAP_REGEX:
                    problem = _regex_problem(f"{self.label} ({key})", item)
                    if problem:
                        return problem
                elif not (isinstance(item, list) and all(isinstance(v, str) for v in item)):
                    return f"«{self.label}» ({key}) deve essere un elenco di testi."
        return None


def _regex_problem(label, value):
    if not isinstance(value, str):
        return f"«{label}» deve essere un'espressione regolare."
    try:
        re.compile(value)
    except re.error as exc:
        return f"«{label}» non è un'espressione regolare valida: {exc}."
    return None


ID_FORMATS = {
    "domain": r"DF\d{2}",
    "system_function": r"SF-DF\d{2}-\d{2}",
    "logical_function": r"LF-DF\d{2}-\d{2}-\d{2}",
    "functional_exchange": r"FE-(DF\d{2}|OE-\d{2})-(DF\d{2}|OE-\d{2})-\d{2}",
    "exchange_item": r"EI-[A-Za-z0-9][A-Za-z0-9-]*",
    "functional_chain": r"FC-[A-Za-z0-9][A-Za-z0-9-]*",
    "logical_component": r"LC-\d{2}",
    "component_exchange": r"CE-LC\d{2}-LC\d{2}-\d{2}",
    "derived_requirement": r".+-D\d+",
    "team": r"T\d+",
    "adr": r"ADR-\d{3}",
    "clarification": r"CQ-\d{2}",
    "external_actor": r"OE-\d{2}",
}
MAIN_FIELDS = {
    "domain": ["mission", "team"],
    "system_function": ["domain", "description", "mode_availability"],
    "trace_record": ["requirement", "b5_question", "outcome"],
    "derived_requirement": ["parent", "obligation", "function", "domain", "b6_scheme"],
    "exchange_item": ["nature", "meaning", "srs_origin"],
    "functional_exchange": ["source", "target", "exchange_item", "nature", "production_condition"],
    "functional_chain": ["responsible_domain", "trigger", "final_effect", "steps"],
    "logical_function": ["refines", "description"],
    "logical_component": ["responsibility", "owner"],
    "component_exchange": ["source", "target", "realizes", "exchange_item"],
    "chain_realization": ["chain", "outcome", "steps"],
}
CONDITIONS = {"FLOW": ["Sempre", "A ogni variazione"], "EVENT": ["Su evento"], "OPERATION": ["Su richiesta"]}
VERB_ENDINGS = ["are", "ere", "ire", "rre"]
CODED_VARIABLE = r"^[A-Z]{1,4}_[A-Z0-9_]+$"  # variables of chapter 7: M_MODE, NID_ENGINE, Q_DIR…


def _names(params):
    return (Param("verb_endings", "Finali del verbo all'infinito", STRINGS, VERB_ENDINGS,
                  hint="La prima parola del nome deve finire così (verbo + oggetto)."),
            Param("allowed_first_words", "Prime parole sempre ammesse", STRINGS, [],
                  hint="Ad esempio verbi in inglese (Determine, Manage…) se i nomi sono in inglese."),
            *params)


NAME_ACRONYMS = (Param("modes", "Sigle di modo vietate", STRINGS, list(ETCS_MODES)),
                 Param("levels", "Vietare le sigle di livello (L0–L3, NTC)", BOOL, True),
                 Param("paragraphs", "Vietare i numeri di paragrafo (es. 3.14.4)", BOOL, True))

PARAMS = {
    "GEN-03": (Param("formats", "Formato dell'ID per tipo di scheda", MAP_REGEX, ID_FORMATS,
                     keys=tuple(ID_FORMATS), hint="Espressioni regolari; un tipo senza formato non è controllato."),),
    "GEN-08": (Param("fields", "Campi obbligatori di una scheda approvata", MAP_STRINGS, MAIN_FIELDS,
                     keys=tuple(MAIN_FIELDS), hint="Nomi dei campi dello schema, separati da virgola."),),
    "A4-01": (Param("chapters", "Capitoli considerati", STRINGS, ["3", "4", "5", "A"],
                    hint="Le sezioni di questi capitoli devono avere un dominio principale."),),
    "A4-03": (Param("max_domains", "Domini massimi di una sezione", INT, 3, minimum=1, maximum=20),),
    "SA1-01": (Param("max_sentences", "Frasi massime della missione", INT, 2, minimum=1, maximum=10),),
    "SA2-03": _names(()),
    "SA2-04": NAME_ACRONYMS,
    "SA3-06": (Param("max_functions", "Funzioni massime di un esito", INT, 3, minimum=1, maximum=20,
                     hint="Oltre, si torna alla domanda B5 n. 4 (requisiti derivati)."),),
    "SA4-04": (Param("max_sentences", "Frasi massime dell'obbligo", INT, 1, minimum=1, maximum=10),),
    "SA5-08": (Param("conditions", "Condizioni di produzione ammesse per natura", MAP_STRINGS, CONDITIONS,
                     keys=NATURES),),
    "SA5-13": (Param("coding_domains", "Domini di codifica", DOMAINS, [], required=True,
                     hint="Gli unici domini che trattano le variabili codificate dei capitoli 7–8 (nella guida "
                          "DF01 e DF09)."),
               Param("coded_variable", "Variabile codificata (espressione regolare)", REGEX, CODED_VARIABLE),
               Param("coded_types", "Tipi di Exchange Item codificati", STRINGS, ["Messaggio", "Pacchetto"])),
    "SA6-04": (Param("types", "Tipi di Exchange Item che devono avere elementi", STRINGS,
                     ["Messaggio", "Pacchetto"]),),
    "SA7-15": (Param("procedure_domain", "Dominio delle procedure", DOMAIN, None, required=True,
                     hint="Il proprietario del flusso delle procedure del capitolo 5 (nella guida DF08)."),),
    "LA1-05": (Param("max_sentences", "Frasi massime della responsabilità", INT, 3, minimum=1, maximum=10),),
    "LA2-12": _names(NAME_ACRONYMS),
    "IND-03": (Param("fan_threshold", "Soglia di fan-in e fan-out", INT, 6, minimum=1, maximum=99),),
    "IND-04": (Param("min_exchanges", "Scambi minimi sul confine", INT, 3, minimum=1, maximum=99,
                     hint="Segnalato quando gli scambi tra due componenti sono almeno questi e più di quelli "
                          "interni."),),
}


def params_of(code):
    return PARAMS.get(code, ())


def key_label(param, key):
    """How a key of a map is shown: the label of a kind of sheet, a nature as it is."""
    kind = KINDS_BY_NAME.get(key)
    return kind.label if kind is not None else key
