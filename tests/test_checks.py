"""Checks of the methodology: a coherent model (the standstill supervision example of the guide, from SA to LA)
has no errors or warnings, and a targeted change of it makes each check report the sheet that violates it."""
from types import SimpleNamespace

import pytest

from arcadia_tool.checks import CHECKS, ERROR, INFO, WARNING, problems, run
from arcadia_tool.checks.config import ChecksConfig, Profile
from arcadia_tool.checks.fields import CHECK_FIELDS, SRS_CARD
from arcadia_tool.model.element import Element, Model
from arcadia_tool.model.schema import B5_QUESTIONS, B6_SCHEMES

Q = {n: B5_QUESTIONS[n - 1] for n in range(1, 7)}
ALL = {c.code for c in CHECKS}


def coherent():
    """DF02 determines the speed, DF06 supervises the standstill and commands the brakes (Applicazione, B4)."""
    m = Model()
    g = SimpleNamespace(model=m, params={}, published=None)  # params: code → {parameter: value}

    def add(kind, **values):
        e = Element(kind, values={k: v for k, v in values.items() if v is not None})
        m.add(e)
        return e
    g.add = add

    g.lc06 = add("logical_component", id="LC-06", name="Localizzazione", responsibility="Stima velocità e posizione.",
                 safety_constraints="SIL 4", owner="Team 2", status="Approvato")
    g.lc12 = add("logical_component", id="LC-12", name="Protezione movimenti", responsibility="Comanda i freni.",
                 safety_constraints="SIL 4", owner="Team 1", status="Approvato")
    g.df06 = add("domain", id="DF06", name="Protezione dei movimenti e comando dei freni",
                 mission="Impedire movimenti non autorizzati del treno.", planned_components=[g.lc12.uuid],
                 status="Approvato")
    g.df02 = add("domain", id="DF02", name="Determinazione di velocità e posizione",
                 mission="Stimare velocità e posizione del treno.", planned_components=[g.lc06.uuid], status="Approvato")
    g.t1 = add("team", id="T1", name="Supervisione", domains=[g.df06.uuid], components=[g.lc12.uuid],
               members=["Anna", "Bruno"], referent="Anna", independent_verifier="Carla", design_authority=True)
    g.t2 = add("team", id="T2", name="Localizzazione", domains=[g.df02.uuid], components=[g.lc06.uuid],
               members=["Dario"], referent="Dario", independent_verifier="Elena")
    g.df06.set("team", g.t1.uuid)
    g.df02.set("team", g.t2.uuid)

    g.sec314 = add("requirement", id="3.14.4", item_type="Sezione", primary_domain=g.df06.uuid,
                   contributing_domains=[g.df02.uuid])
    g.cl3142 = add("requirement", id="3.14.4.2", item_type="Requisito", parent=g.sec314.uuid, category=["Bordo"])
    g.cl3143 = add("requirement", id="3.14.4.3", item_type="Requisito", parent=g.sec314.uuid, category=["Bordo"])
    g.sec361 = add("requirement", id="3.6.1", item_type="Sezione", primary_domain=g.df02.uuid)
    g.cl3611 = add("requirement", id="3.6.1.1", item_type="Requisito", parent=g.sec361.uuid, category=["Bordo"])

    g.oe01 = add("external_actor", id="OE-01", name="Treno")
    g.sf06 = add("system_function", id="SF-DF06-01", name="Supervisionare lo standstill", domain=g.df06.uuid,
                 description="Impedisce il movimento del treno fermo.", sections=[g.sec314.uuid],
                 rows_452=["4.5.2-R49"], mode_availability={"SB": "X"}, proposed_component=g.lc12.uuid,
                 status="Approvata")
    g.sf02 = add("system_function", id="SF-DF02-01", name="Determinare la velocità del treno", domain=g.df02.uuid,
                 description="Stima la velocità.", sections=[g.sec361.uuid], rows_452=["4.5.2-R10"],
                 mode_availability={"FS": "X"}, proposed_component=g.lc06.uuid, status="Approvata")
    g.lf02 = add("logical_function", id="LF-DF02-01-01", name="Calcolare la velocità", refines=g.sf02.uuid,
                 component=g.lc06.uuid, description="Calcola la velocità.", detail_requirements=[g.cl3611.uuid],
                 status="Approvata")
    g.lf06a = add("logical_function", id="LF-DF06-01-01", name="Rilevare un movimento oltre la distanza",
                  refines=g.sf06.uuid, component=g.lc12.uuid, description="Rileva il movimento.",
                  detail_requirements=[g.cl3142.uuid], status="Approvata")
    g.lf06b = add("logical_function", id="LF-DF06-01-02", name="Richiedere la frenatura", refines=g.sf06.uuid,
                  component=g.lc12.uuid, description="Chiede la frenatura.", detail_requirements=[g.cl3143.uuid],
                  status="Approvata")

    def item(ident, name, nature):
        return add("exchange_item", id=ident, name=name, type="Dato logico", nature=nature, meaning=name,
                   srs_origin="3.14.4", status="Approvato")
    g.ei_speed = item("EI-Velocita", "Velocità misurata", "FLOW")
    g.ei_mov = item("EI-MovimentoDelTreno", "Movimento del treno", "FLOW")
    g.ei_detected = item("EI-MovimentoRilevato", "Movimento rilevato", "EVENT")
    g.ei_brake = item("EI-ComandoFreno", "Comando freno", "FLOW")

    def exchange(ident, name, source, target, ei, condition="Sempre", **values):
        values.setdefault("status", "Approvato")
        return add("functional_exchange", id=ident, name=name, source=source.uuid, target=target.uuid,
                   exchange_item=ei.uuid, nature=ei.get("nature"), production_condition=condition, **values)
    agreed = dict(status="Approvato", producer_agreement="Dario", consumer_agreement="Anna")
    g.fe1 = exchange("FE-OE-01-DF02-01", "Velocità", g.oe01, g.sf02, g.ei_speed, clauses=[g.cl3611.uuid])
    g.fe2 = exchange("FE-DF02-DF06-01", "Movimento del treno", g.sf02, g.sf06, g.ei_mov, clauses=[g.cl3142.uuid],
                     **agreed)
    g.fe3 = exchange("FE-DF06-OE-01-01", "Comando freno", g.sf06, g.oe01, g.ei_brake)
    g.fe_la = exchange("FE-DF02-DF06-02", "Movimento del treno", g.lf02, g.lf06a, g.ei_mov, **agreed)
    g.fe_internal = exchange("FE-DF06-DF06-01", "Movimento rilevato", g.lf06a, g.lf06b, g.ei_detected, "Su evento")
    g.fe_brake = exchange("FE-DF06-OE-01-02", "Comando freno", g.lf06b, g.oe01, g.ei_brake)
    g.ce = add("component_exchange", id="CE-LC06-LC12-01", source=g.lc06.uuid, target=g.lc12.uuid,
               realizes=[g.fe2.uuid, g.fe_la.uuid], exchange_item=g.ei_mov.uuid, periodicity="Ogni ciclo",
               cycle_rw="Scritto al passo 3, letto al passo 8", status="Approvato")

    def record(clause, function):
        return add("trace_record", requirement=clause.uuid, b5_question=Q[6], outcome="Tracciata a funzione",
                   primary_function=function.uuid, status="Approvato")
    g.rec3142 = record(g.cl3142, g.sf06)
    g.rec3143 = record(g.cl3143, g.sf06)
    g.rec3611 = record(g.cl3611, g.sf02)

    g.fc = add("functional_chain", id="FC-Standstill", title="Standstill", responsible_domain=g.df06.uuid,
               trigger="Il treno si muove da fermo", final_effect="Comando del freno", oracle="Freno applicato",
               integration_test="Movimento oltre la distanza", status="Approvato", steps=[
                   {"cycle": "C0", "function": g.sf02.uuid, "what": "Determina il movimento", "nature": "FLOW",
                    "exchange": g.fe2.uuid, "srs": "3.6.1.1", "component": g.lc06.uuid},
                   {"cycle": "C0", "function": g.sf06.uuid, "what": "Comanda il freno", "nature": "FLOW",
                    "exchange": g.fe3.uuid, "srs": "3.14.4.2", "component": g.lc12.uuid}])
    g.real = add("chain_realization", chain=g.fc.uuid, outcome="Eseguibile", status="Approvato", steps=[
        {"sa_step": "1", "cycle": "C0", "logical_function": g.lf02.uuid, "component": g.lc06.uuid,
         "out_exchange": g.ce.uuid},
        {"sa_step": "2", "cycle": "C0", "logical_function": g.lf06b.uuid, "component": g.lc12.uuid}])
    return g


def config(codes, params=None, **profile):
    return ChecksConfig({"Predefinito": Profile(sorted(codes), dict(params or {}), **profile)})


def findings(g, codes=ALL):
    return run(g.model, config(codes, g.params), published=g.published)


def test_a_coherent_model_has_no_errors_or_warnings():
    g = coherent()
    problems = [f for f in findings(g) if f.severity in (ERROR, WARNING)]
    assert problems == [], "\n".join(f"{f.code} {g.model.label_of(f.element)}: {f.message}" for f in problems)
    assert {f.severity for f in findings(g)} <= {INFO}


def test_no_check_is_active_by_default():
    assert ChecksConfig().profile.enabled == []
    assert run(coherent().model, ChecksConfig()) == []


def test_settings_keep_checks_in_catalogue_order_and_only_what_differs():
    c = config(["SA2-07", "GEN-01"], {"IND-03": {"fan_threshold": 9}})
    data = c.to_data()
    assert data["profiles"]["Predefinito"] == {"enabled": ["GEN-01", "SA2-07"],
                                               "params": {"IND-03": {"fan_threshold": 9}}}
    assert ChecksConfig.from_data(data) == c
    assert c.profile.param("IND-03", "fan_threshold") == 9
    assert c.profile.param("A4-03", "max_domains") == 3  # the value of the methodology


def test_problems_of_the_settings():
    g = coherent()
    assert problems(ChecksConfig(), g.model) == ["Nessuna verifica selezionata: scegli i controlli da eseguire."]
    assert problems(config(["SA2-07"]), g.model) == []
    assert problems(None, g.model)  # checks.yaml not readable
    wrong = problems(config(["SA5-13", "SA7-15", "ZZ-1", "IND-03", "GEN-03"],
                            {"SA5-13": {"coding_domains": ["eliminato"]}, "IND-03": {"fan_threshold": "molti"},
                             "GEN-03": {"formats": {"team": "T(\\d+"}}}), g.model)
    assert len(wrong) == 5, wrong
    assert any("ZZ-1" in p for p in wrong) and any("SA5-13" in p and "domini" in p for p in wrong)
    assert any("SA7-15" in p and "Dominio delle procedure" in p for p in wrong)
    assert any("IND-03" in p and "numero intero" in p for p in wrong)
    assert any("GEN-03" in p and "espressione regolare" in p for p in wrong)


def published_copy(g):
    g.published = Model([e.copy() for e in g.model])


def derived(g, **values):
    base = dict(id="3.14.4.2-D1", parent=g.cl3142.uuid, obligation="Richiede la frenatura.",
                function=g.lf06b.uuid, domain=g.df06.uuid, b6_scheme=B6_SCHEMES[2], status="Proposto")
    base.update(values)
    return g.add("derived_requirement", **base)


def domain(g, ident):
    return g.add("domain", id=ident, name=f"Dominio {ident}", mission="Scopo.")


def step(g, n, **values):
    steps = [dict(s) for s in g.fc.get("steps")]
    steps[n - 1].update(values)
    g.fc.set("steps", steps)


def real_step(g, n, **values):
    steps = [dict(s) for s in g.real.get("steps")]
    steps[n - 1].update(values)
    g.real.set("steps", steps)


def ground_item(g):
    return g.add("requirement", id="3.14.4.9", item_type="Requisito", parent=g.sec314.uuid, category=["Terra"])


def _sa5_13(g):
    g.ei_mov.set("type", "Messaggio")
    g.params["SA5-13"] = {"coding_domains": [g.df02.uuid]}


def _sa7_15(g):
    g.params["SA7-15"] = {"procedure_domain": g.df06.uuid}


def _ver(change):
    def mutate(g):
        published_copy(g)
        change(g)
    return mutate


def _twins(g):
    for name in ("Supervisionare lo standstill in FS", "Supervisionare lo standstill in OS"):
        g.add("system_function", name=name, domain=g.df06.uuid, sections=[g.sec314.uuid])


def _overdecomposed(g):
    for n in (3, 4):
        lf = g.add("logical_function", id=f"LF-DF06-01-0{n}", name="Valutare il movimento", refines=g.sf06.uuid,
                   component=g.lc12.uuid)
        g.add("functional_exchange", source=g.lf02.uuid, target=lf.uuid, exchange_item=g.ei_speed.uuid)


def _coupling(g):
    for _ in range(2):
        g.add("functional_exchange", source=g.lf02.uuid, target=g.lf06b.uuid, exchange_item=g.ei_speed.uuid)


MUTATIONS = {
    "GEN-01": lambda g: g.lc12.set("id", None),
    "GEN-02": lambda g: g.lc06.set("id", "LC-12"),
    "GEN-03": lambda g: g.lc06.set("id", "LC6"),
    "GEN-04": lambda g: g.lc06.set("name", None),
    "GEN-05": lambda g: g.lf02.set("component", "eliminato"),
    "GEN-06": lambda g: g.sf06.set("adrs", [g.add("adr", id="ADR-001", title="X", status="Superata").uuid]),
    "GEN-07": lambda g: g.ei_mov.set("status", "Bozza"),
    "GEN-08": lambda g: g.sf06.set("description", None),
    "A4-01": lambda g: g.sec314.set("primary_domain", None),
    "A4-02": lambda g: g.sec314.set("contributing_domains", [g.df06.uuid]),
    "A4-03": lambda g: g.sec314.set("contributing_domains", [g.df02.uuid] + [domain(g, f"DF9{n}").uuid
                                                                              for n in range(2)]),
    "A4-04": lambda g: g.cl3142.set("primary_domain", domain(g, "DF09").uuid),
    "A4-05": lambda g: g.add("requirement", id="3.14.4.8", item_type="Requisito", parent=g.sec314.uuid,
                             category=["Informativa"], primary_domain=g.df06.uuid),
    "A4-06": lambda g: g.cl3142.set("category", ["Bordo", "Definizione"]),
    "A4-07": lambda g: g.add("requirement", id="3.14.4.2-R1", item_type="Voce", parent=g.cl3142.uuid,
                             category=["Terra"]),
    "A4-08": lambda g: g.add("requirement", id="3.14.4.7", item_type="Requisito", parent=g.sec314.uuid),
    "A4-09": lambda g: g.add("requirement", id="6.5.1.1", item_type="Requisito", category=["Bordo"]),
    "SA1-01": lambda g: g.df06.set("mission", None),
    "SA1-02": lambda g: g.t1.set("domains", []),
    "SA1-03": lambda g: (g.df06.set("team", None), g.t1.set("domains", [])),
    "SA1-04": lambda g: g.t1.set("referent", None),
    "SA1-05": lambda g: g.sec361.set("primary_domain", None),
    "SA1-06": lambda g: g.add("requirement", id="3.14.5", item_type="Sezione", primary_domain=g.df06.uuid),
    "SA1-07": lambda g: g.lc06.set("name", g.df02.get("name")),
    "SA1-08": lambda g: g.df06.set("planned_components", [g.lc06.uuid]),
    "SA1-09": lambda g: domain(g, "DF07"),
    "SA2-01": lambda g: g.sf06.set("domain", None),
    "SA2-02": lambda g: g.sf06.set("id", "SF-DF02-09"),
    "SA2-03": lambda g: g.sf06.set("name", "Supervisione dello standstill"),
    "SA2-04": lambda g: g.sf06.set("name", "Supervisionare lo standstill in SB"),
    "SA2-05": _twins,
    "SA2-06": lambda g: g.add("system_function", name="Supervisionare lo standstill", domain=g.df06.uuid),
    "SA2-07": lambda g: g.add("system_function", name="Gestire la manovra", domain=g.df06.uuid),
    "SA2-08": lambda g: g.sf06.set("sections", [g.sec314.uuid, ground_item(g).uuid]),
    "SA2-09": lambda g: g.sf02.set("sections", [g.sec361.uuid, g.add(
        "requirement", id="3.15.1", item_type="Sezione", primary_domain=g.df06.uuid).uuid]),
    "SA2-10": lambda g: g.sf06.set("is_new", True),
    "SA2-11": lambda g: (g.sf06.set("is_new", True), g.sf06.set("new_reason", "Non in tabella 4.5.2")),
    "SA2-12": lambda g: g.sf06.set("mode_availability", None),
    "SA2-13": lambda g: g.sf06.set("mode_availability", {"SB": "Z"}),
    "SA2-14": lambda g: g.sf06.set("mode_availability", {"SB": "O"}),
    "SA2-15": lambda g: g.sf02.set("rows_452", ["4.5.2-R49"]),
    "SA2-16": lambda g: g.add("system_function", name="Gestire la manovra", domain=g.df06.uuid,
                              sections=[g.sec314.uuid]),
    "SA2-17": lambda g: g.sf06.set("proposed_component", g.lc06.uuid),
    "SA2-18": lambda g: g.add("system_function", name="Gestire la manovra", domain=g.df06.uuid),
    "SA3-01": lambda g: g.add("trace_record", outcome="Non tracciata"),
    "SA3-02": lambda g: g.add("trace_record", requirement=g.cl3142.uuid, b5_question=Q[6],
                              outcome="Tracciata a funzione", primary_function=g.sf06.uuid),
    "SA3-03": lambda g: g.rec3142.set("outcome", "Non tracciata"),
    "SA3-04": lambda g: (g.rec3142.set("b5_question", Q[1]), g.rec3142.set("outcome", "Non tracciata"),
                         g.rec3142.set("primary_function", None)),
    "SA3-05": lambda g: g.rec3142.set("primary_function", None),
    "SA3-06": lambda g: g.rec3142.set("secondary_functions", [g.sf02.uuid, g.lf06a.uuid, g.lf06b.uuid]),
    "SA3-07": lambda g: (g.rec3142.set("b5_question", Q[4]), g.rec3142.set("outcome", "Scomposta in requisiti derivati"),
                         g.rec3142.set("primary_function", None)),
    "SA3-08": lambda g: (g.rec3142.set("b5_question", Q[3]), g.rec3142.set("outcome", "Tracciata al dizionario"),
                         g.rec3142.set("primary_function", None)),
    "SA3-09": lambda g: g.add("trace_record", requirement=ground_item(g).uuid, b5_question=Q[2],
                              outcome="Ipotesi d'ambiente / dato atteso"),
    "SA3-10": lambda g: (g.rec3142.set("b5_question", Q[5]), g.rec3142.set("outcome", "Collegata alla voce nominale")),
    "SA3-11": lambda g: g.rec3142.set("secondary_functions", [g.sf02.uuid]),
    "SA3-12": lambda g: g.rec3611.set("primary_function", g.sf06.uuid),
    "SA3-13": lambda g: g.rec3142.set("secondary_functions", [g.sf06.uuid]),
    "SA3-14": lambda g: g.rec3142.set("primary_function", g.lf06a.uuid),
    "SA3-15": lambda g: g.add("requirement", id="3.14.4.5", item_type="Requisito", parent=g.sec314.uuid,
                              category=["Bordo"]),
    "SA3-16": lambda g: g.add("requirement", id="3.14.4.5", item_type="Requisito", parent=g.sec314.uuid,
                              category=["Bordo"]),
    "SA4-01": lambda g: derived(g, parent=None),
    "SA4-02": lambda g: derived(g),
    "SA4-03": lambda g: derived(g, id="D-1"),
    "SA4-04": lambda g: derived(g, obligation="Rileva il movimento. Poi frena."),
    "SA4-05": lambda g: derived(g, domain=None),
    "SA4-06": lambda g: derived(g, function=None),
    "SA4-07": lambda g: derived(g, domain=g.df02.uuid),
    "SA4-08": lambda g: derived(g, b6_scheme=None),
    "SA4-09": lambda g: derived(g),
    "SA4-10": lambda g: derived(g, function=None),
    "SA5-01": lambda g: g.fe3.set("target", None),
    "SA5-02": lambda g: g.fe3.set("target", g.sf06.uuid),
    "SA5-03": lambda g: g.fe1.set("target", g.add("external_actor", id="OE-02", name="RBC").uuid),
    "SA5-04": lambda g: g.fe3.set("target", g.lf02.uuid),
    "SA5-05": lambda g: g.add("logical_function", id="LF-DF06-01-03", name="Misurare la distanza",
                              parent=g.lf06a.uuid, component=g.lc12.uuid),
    "SA5-06": lambda g: g.fe3.set("exchange_item", None),
    "SA5-07": lambda g: g.fe3.set("nature", "EVENT"),
    "SA5-08": lambda g: g.fe3.set("production_condition", "Su evento"),
    "SA5-09": lambda g: g.fe3.set("id", "FE-DF02-OE-01-01"),
    "SA5-10": lambda g: g.add("functional_exchange", **g.fe3.copy().values),
    "SA5-11": lambda g: g.fe2.set("status", "Proposto"),
    "SA5-12": lambda g: g.fe2.set("clauses", [g.add("requirement", id="3.15.1.1", item_type="Requisito",
                                                    category=["Bordo"]).uuid]),
    "SA5-13": _sa5_13,
    "SA6-01": lambda g: g.add("functional_exchange", source=g.sf06.uuid, target=g.oe01.uuid,
                              exchange_item=g.ei_mov.uuid),
    "SA6-02": lambda g: g.add("exchange_item", id="EI-Livello", name="Livello", nature="FLOW"),
    "SA6-03": lambda g: g.ei_mov.set("nature", None),
    "SA6-04": lambda g: g.ei_mov.set("type", "Messaggio"),
    "SA6-05": lambda g: g.ei_mov.set("elements", [{"variable": "V_TRAIN"}]),
    "SA6-06": lambda g: g.ei_mov.set("elements", [dict(variable="D_X", unit="m", range="0-100", resolution="1")] * 2),
    "SA6-07": lambda g: g.ei_mov.set("srs_origin", None),
    "SA6-08": lambda g: g.add("exchange_item", id="EI-Altro", name="Movimento del treno", nature="FLOW"),
    "SA7-01": lambda g: g.fc.set("steps", None),
    "SA7-02": lambda g: step(g, 2, function=None),
    "SA7-03": lambda g: step(g, 1, function=g.lf02.uuid),
    "SA7-04": lambda g: g.model.remove(g.fe1.uuid),
    "SA7-05": lambda g: g.fc.set("trigger", None),
    "SA7-06": lambda g: step(g, 1, exchange=g.fe3.uuid),
    "SA7-07": lambda g: step(g, 1, exchange=None),
    "SA7-08": lambda g: step(g, 1, nature="EVENT"),
    "SA7-09": lambda g: step(g, 1, srs=""),
    "SA7-10": lambda g: step(g, 1, srs="3.14.4.2"),
    "SA7-11": lambda g: step(g, 2, cycle="C1"),
    "SA7-12": lambda g: g.fc.set("steps", g.fc.get("steps") + [dict(g.fc.get("steps")[0])]),
    "SA7-13": lambda g: g.fc.set("responsible_domain", None),
    "SA7-14": lambda g: step(g, 1, component=g.lc12.uuid),
    "SA7-15": _sa7_15,
    "SA7-16": lambda g: g.fc.set("oracle", None),
    "SA7-17": lambda g: g.model.remove(g.real.uuid),
    "LA1-01": lambda g: (g.lc06.set("parent", g.lc12.uuid), g.lc12.set("parent", g.lc06.uuid)),
    "LA1-02": lambda g: g.add("functional_exchange", source=g.lf06b.uuid, target=g.oe01.uuid,
                              exchange_item=g.ei_mov.uuid),
    "LA1-03": lambda g: g.add("logical_component", id="LC-20", name="Vuoto"),
    "LA1-04": lambda g: g.add("logical_component", id="LC-13", name="Sotto", parent=g.lc12.uuid),
    "LA1-05": lambda g: g.lc12.set("responsibility", None),
    "LA1-06": lambda g: g.lc12.set("safety_constraints", None),
    "LA1-07": lambda g: g.t1.set("components", []),
    "LA1-08": lambda g: g.lc12.set("name", g.df06.get("name")),
    "LA2-01": lambda g: g.lf02.set("refines", None),
    "LA2-02": lambda g: g.lf02.set("component", None),
    "LA2-03": lambda g: g.add("logical_function", id="LF-DF06-01-03", name="Misurare la distanza",
                              parent=g.lf06a.uuid, component=g.lc12.uuid),
    "LA2-04": lambda g: (g.lf06a.set("parent", g.lf06b.uuid), g.lf06b.set("parent", g.lf06a.uuid)),
    "LA2-05": lambda g: g.lf06b.set("parent", g.lf02.uuid),
    "LA2-06": lambda g: g.lf02.set("id", "LF-DF06-01-09"),
    "LA2-07": lambda g: g.lf02.set("contributes_to", [g.sf02.uuid]),
    "LA2-08": lambda g: g.lf06b.set("detail_requirements", None),
    "LA2-09": lambda g: g.lf06b.set("detail_requirements", [g.cl3611.uuid]),
    "LA2-10": lambda g: (derived(g, function=g.lf06a.uuid), g.add(
        "logical_function", id="LF-DF06-01-03", name="Misurare la distanza", parent=g.lf06a.uuid)),
    "LA2-11": lambda g: g.lf02.set("component", g.lc12.uuid),
    "LA2-12": lambda g: g.lf02.set("name", "Calcolo della velocità"),
    "LA2-13": lambda g: g.model.remove(g.fe2.uuid),
    "LA2-14": lambda g: g.sf02.set("status", "Proposta"),
    "LA2-15": _overdecomposed,
    "LA3-01": lambda g: g.ce.set("target", g.lc06.uuid),
    "LA3-02": lambda g: (g.ce.set("source", g.lc12.uuid), g.ce.set("target", g.lc06.uuid)),
    "LA3-03": lambda g: g.ce.set("realizes", [g.fe2.uuid]),
    "LA3-04": lambda g: g.ce.set("realizes", [g.fe2.uuid, g.fe_la.uuid, g.fe_internal.uuid]),
    "LA3-05": lambda g: g.ce.set("realizes", None),
    "LA3-06": lambda g: g.ce.set("exchange_item", g.ei_brake.uuid),
    "LA3-07": lambda g: g.fe2.set("status", "Concordato"),
    "LA3-08": lambda g: g.ce.set("id", "CE-LC12-LC06-01"),
    "LA3-09": lambda g: g.add("component_exchange", **g.ce.copy().values),
    "LA3-10": lambda g: g.ce.set("cycle_rw", None),
    "LA4-01": lambda g: g.real.set("chain", None),
    "LA4-02": lambda g: real_step(g, 2, logical_function=None),
    "LA4-03": lambda g: g.real.set("steps", g.real.get("steps")[:1]),
    "LA4-04": lambda g: real_step(g, 1, logical_function=g.lf06a.uuid, component=g.lc12.uuid),
    "LA4-05": lambda g: real_step(g, 1, component=g.lc12.uuid),
    "LA4-06": lambda g: real_step(g, 1, out_exchange=g.add("component_exchange", id="CE-LC12-LC06-01",
                                                           source=g.lc12.uuid, target=g.lc06.uuid).uuid),
    "LA4-07": lambda g: real_step(g, 1, cycle="C1"),
    "LA4-08": lambda g: g.real.set("steps", g.real.get("steps") + [dict(g.real.get("steps")[0])]),
    "LA4-09": lambda g: g.real.set("outcome", "Non eseguibile"),
    "LA4-10": lambda g: g.fc.set("status", "Bozza"),
    "EPBS-01": lambda g: g.t2.set("domains", []),  # not the DA team, which may have no domains
    "EPBS-02": lambda g: g.t1.set("referent", "Zeno"),
    "EPBS-03": lambda g: g.t1.set("independent_verifier", "bruno"),
    "EPBS-04": lambda g: g.t2.set("domains", [g.df02.uuid, g.df06.uuid]),
    "EPBS-05": lambda g: g.t2.set("design_authority", True),
    "EPBS-06": lambda g: g.t1.set("design_authority", False),
    "X-01": lambda g: g.add("adr", id="ADR-001", title="X", status="Superata"),
    "X-02": lambda g: g.add("adr", id="ADR-001", title="X", status="Decisa", decision="Sì"),
    "X-03": lambda g: g.add("clarification", id="CQ-01", problem="?"),
    "X-04": lambda g: g.add("clarification", id="CQ-01", clause=g.cl3142.uuid, interim_position="Come da analisi",
                            status="Aperta"),
    "IND-01": lambda g: None,
    "IND-02": lambda g: g.add("component_exchange", id="CE-LC12-LC06-01", source=g.lc12.uuid, target=g.lc06.uuid),
    "IND-03": lambda g: g.params.update({"IND-03": {"fan_threshold": 0}}),
    "IND-04": _coupling,
    "IND-05": lambda g: None,
    "VER-01": _ver(lambda g: g.sf06.set("domain", g.df02.uuid)),
    "VER-02": _ver(lambda g: g.sec314.set("primary_domain", g.df02.uuid)),
    "VER-03": _ver(lambda g: domain(g, "DF16")),
    "VER-04": _ver(lambda g: g.lf02.set("component", g.lc12.uuid)),
    "VER-05": _ver(lambda g: g.sf06.set("description", "Altro testo.")),
}


def test_every_check_has_a_case():
    assert set(MUTATIONS) == ALL


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_check_reports_the_sheet_that_violates_it(code):
    g = coherent()
    MUTATIONS[code](g)
    reported = [f for f in findings(g, {code}) if f.code == code]
    assert reported, f"{code} non segnala la modifica"
    for f in reported:
        assert f.message
        assert all(g.model.get(u) is not None for u in f.related)  # the other sheets involved exist
        if f.element is not None:
            element = g.model.get(f.element)
            assert element is not None
            # the double click goes to a field of that sheet (or its traceability card, or its top)
            assert f.field in ("", SRS_CARD) or element.schema.field(f.field) is not None, (code, f.field)


def test_fields_of_the_checks_are_known():
    assert set(CHECK_FIELDS) <= ALL


def test_run_reports_its_progress():
    g = coherent()
    steps = []
    run(g.model, {"SA2-01", "LA2-02", "GEN-01"}, progress=lambda done, total, c: steps.append(
        (done, total, c.code if c else None)))
    assert steps == [(0, 3, "GEN-01"), (1, 3, "SA2-01"), (2, 3, "LA2-02"), (3, 3, None)]

    g.lc12.set("id", None)
    g.sf06.set("domain", None)
    steps.clear()
    found = run(g.model, {"SA2-01", "GEN-01"}, progress=lambda done, total, c: steps.append(done) or done < 1)
    assert {f.code for f in found} == {"GEN-01"}  # stopped before SA2-01
    assert steps == [0, 1, 1]  # the last call: 1 check run


def test_a_finding_names_the_other_sheets_involved():
    g = coherent()
    g.add("functional_exchange", source=g.sf06.uuid, target=g.oe01.uuid, exchange_item=g.ei_mov.uuid)
    [f] = findings(g, {"SA6-01"})
    assert f.element == g.ei_mov.uuid and g.sf02.uuid in f.related and g.sf06.uuid in f.related


def test_checks_needing_an_option_are_silent_without_it():
    g = coherent()
    g.ei_mov.set("type", "Messaggio")
    assert findings(g, {"SA5-13"}) == []


# --- customization of the checks: parameters, severity, scope, exceptions ---------------------------------

def test_parameters_change_what_a_check_reports():
    g = coherent()
    g.df06.set("mission", "Prima frase. Seconda frase. Terza frase.")
    assert [f.element for f in findings(g, {"SA1-01"})] == [g.df06.uuid]
    g.params["SA1-01"] = {"max_sentences": 3}
    assert findings(g, {"SA1-01"}) == []

    g.sf06.set("name", "Determine the standstill")
    assert [f.element for f in findings(g, {"SA2-03"})] == [g.sf06.uuid]
    g.params["SA2-03"] = {"allowed_first_words": ["Determine"]}
    assert findings(g, {"SA2-03"}) == []

    g.sf02.set("name", "Determinare la velocità in SB")
    assert findings(g, {"SA2-04"})
    g.params["SA2-04"] = {"modes": ["FS", "OS"]}
    assert findings(g, {"SA2-04"}) == []

    assert findings(g, {"GEN-03"}) == []
    g.params["GEN-03"] = {"formats": {"team": r"TEAM-\d+"}}
    reported = findings(g, {"GEN-03"})
    assert {f.element for f in reported} == {g.t1.uuid, g.t2.uuid}
    assert "«TEAM-\\d+»" in reported[0].message  # a format of the project is shown as it is


def test_severity_of_a_check_can_be_changed():
    g = coherent()
    g.lc12.set("id", None)
    [f] = run(g.model, config({"GEN-01"}, severity={"GEN-01": INFO}))
    assert f.severity == INFO


def test_scope_by_status_and_domain():
    g = coherent()
    for sf in (g.sf06, g.sf02):
        sf.set("sections", None)
    assert {f.element for f in findings(g, {"SA2-07"})} == {g.sf06.uuid, g.sf02.uuid}
    only_df06 = config({"SA2-07"}, scope={"SA2-07": {"domains": [g.df06.uuid]}})
    assert {f.element for f in run(g.model, only_df06)} == {g.sf06.uuid}
    g.sf06.set("status", "Bozza")
    approved = config({"SA2-07"}, scope={"SA2-07": {"status": "approved"}})
    assert {f.element for f in run(g.model, approved)} == {g.sf02.uuid}


def test_an_exception_holds_while_its_sheet_does_not_change():
    g = coherent()
    g.lc12.set("id", None)
    c = config({"GEN-01"})
    [f] = run(g.model, c)
    c.add_exception(f, g.lc12, "Componente provvisorio", "Anna")
    [waived] = run(g.model, c)
    assert waived.waived and waived.exception["reason"] == "Componente provvisorio"
    from arcadia_tool.checks import WAIVED, count
    assert count([waived]) == {ERROR: 0, WARNING: 0, INFO: 0, WAIVED: 1}
    again = ChecksConfig.from_data(c.to_data())  # saved and read back
    assert run(g.model, again)[0].waived
    g.lc12.set("name", "Protezione dei movimenti")  # the sheet changed: the finding comes back
    assert not run(g.model, c)[0].waived
    c.remove_exception(f)
    assert c.exceptions == []


def test_profiles():
    c = config({"GEN-01"})
    c.add_profile("Gate SA")
    assert c.active == "Gate SA" and c.profile.enabled == ["GEN-01"]
    c.profile.enabled = ["SA2-01"]
    assert c.profiles["Predefinito"].enabled == ["GEN-01"]  # a copy
    c.rename_profile("Gate SA", "Gate LA")
    assert list(c.profiles) == ["Predefinito", "Gate LA"] and c.active == "Gate LA"
    c.remove_profile("Gate LA")
    assert c.active == "Predefinito"
    c.remove_profile("Predefinito")  # the last one stays
    assert list(c.profiles) == ["Predefinito"]


def test_settings_of_the_first_versions_are_migrated():
    old = {"checks": {"enabled": ["SA5-13", "IND-03"], "coding_domains": ["d1"], "procedure_domain": "d2",
                      "fan_threshold": 9}}
    c = ChecksConfig.from_project_settings(old)
    assert c.profile.enabled == ["SA5-13", "IND-03"]
    assert c.profile.params == {"SA5-13": {"coding_domains": ["d1"]}, "SA7-15": {"procedure_domain": "d2"},
                                "IND-03": {"fan_threshold": 9}}
    assert ChecksConfig.from_project_settings({}).profile.enabled == []
