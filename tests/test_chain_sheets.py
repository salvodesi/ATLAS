"""The sheets of a functional chain (SA-7) and of an Exchange Item (SA-6), as those of the proposal in Excel of the
increments: a chain up to the exchanges used (identification without the related questions, context, path, exchanges
used); an Exchange Item with the columns of the dictionary (ID … Utilizzatori, Note, Stato). Domain, name of the
function, number of the step, domains involved, exchanges used, producer and users are computed by the tool."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from arcadia_tool.model.chains import (STEP_COMPUTED, involved_domains, item_producer, item_users,
                                       used_exchange_rows)
from arcadia_tool.model.schema import EI_EXTERNAL_IN, KINDS_BY_NAME
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def shown(kind):
    return [f.label for f in KINDS_BY_NAME[kind].fields if not f.hidden]


def test_a_chain_has_the_fields_of_its_sheet_up_to_the_exchanges_used():
    assert shown("functional_chain") == [
        "ID", "Titolo", "Domini coinvolti", "Avviabilità", "Trigger", "Effetto osservabile finale", "Precondizioni",
        "Postcondizioni", "Fuori ambito", "Percorso", "Scambi usati", "Stato"]
    kind = KINDS_BY_NAME["functional_chain"]
    assert [c.label for c in kind.field("steps").columns] == [
        "#", "Ciclo", "Dominio", "Funzione SF", "Nome funzione", "Cosa fa", "Ingresso", "Dato prodotto", "Natura",
        "Scambio in uscita", "Voci SRS"]
    assert [c.label for c in kind.field("used_exchanges").columns] == [
        "ID scambio", "Produttore", "Utilizzatore", "Dato", "Natura", "Tipo", "Stato"]
    assert not kind.field("used_exchanges").stored


def test_an_exchange_item_has_the_columns_of_the_dictionary():
    assert shown("exchange_item") == ["ID", "Nome", "Natura", "Tipo", "Elementi", "Origine o specifica",
                                      "Produttore", "Utilizzatori", "Note", "Stato"]
    assert KINDS_BY_NAME["exchange_item"].field("type").options == (
        "Dato di interfaccia esterna (ingresso)", "Dato di interfaccia esterna (uscita)", "Dato logico")


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    e = {"df08": p.new_element("domain", id="DF08", name="Modi"),
         "df07": p.new_element("domain", id="DF07", name="Freni"),
         "pwr": p.new_element("external_actor", id="PWR", name="Alimentazione")}
    e["sf08"] = p.new_element("system_function", id="SF-DF08-01", name="Gestire l'avvio", domain=e["df08"].uuid)
    e["sf07"] = p.new_element("system_function", id="SF-DF07-01", name="Provare i freni", domain=e["df07"].uuid)
    e["ei_on"] = p.new_element("exchange_item", id="EI-EventoAccensione", name="Evento di accensione",
                               nature="EVENT", type=EI_EXTERNAL_IN)
    e["ei_test"] = p.new_element("exchange_item", id="EI-RichiestaTest", name="Richiesta di test", nature="OPERATION")
    e["ei_done"] = p.new_element("exchange_item", id="EI-EsitoTest", name="Esito del test", nature="EVENT")
    e["fe_on"] = p.new_element("functional_exchange", id="FE-PWR-DF08-01", source=e["pwr"].uuid,
                               target=e["sf08"].uuid, exchange_item=e["ei_on"].uuid, status="Proposto")
    e["fe_req"] = p.new_element("functional_exchange", id="FE-DF08-DF07-01", source=e["sf08"].uuid,
                                target=e["sf07"].uuid, exchange_item=e["ei_test"].uuid, nature="OPERATION")
    e["fe_done"] = p.new_element("functional_exchange", id="FE-DF07-DF08-01", source=e["sf07"].uuid,
                                 target=e["sf08"].uuid, exchange_item=e["ei_done"].uuid)
    e["fc"] = p.new_element("functional_chain", id="FC-TestAvvio", title="Test di avvio",
                            startable="Bloccata", steps=[
                                {"cycle": "C0", "function": e["sf08"].uuid, "what": "Chiede il test",
                                 "input": e["fe_on"].uuid, "data": "EI-RichiestaTest", "nature": "OPERATION",
                                 "exchange": e["fe_req"].uuid, "srs": "4.6.3"},
                                {"cycle": "—", "what": "Attesa: esecuzione del test"},
                                {"cycle": "C1", "function": e["sf07"].uuid, "what": "Prova i freni",
                                 "input": e["fe_req"].uuid, "data": "EI-EsitoTest", "nature": "EVENT",
                                 "exchange": e["fe_done"].uuid},
                                {"cycle": "C2", "function": e["sf08"].uuid, "what": "Valuta l'esito",
                                 "input": e["fe_done"].uuid, "data": "Esito dell'avvio", "nature": "Interno"}])
    p.save()
    return p, e


def test_the_tool_computes_what_the_sheets_read_from_the_model(tmp_path):
    p, e = build(tmp_path)
    model, rows = p.model, e["fc"].get("steps")
    assert [STEP_COMPUTED["step_number"](model, rows, i) for i in range(4)] == ["1", "", "2", "3"]
    assert [STEP_COMPUTED["step_domain"](model, rows, i) for i in range(4)] == ["DF08", "", "DF07", "DF08"]
    assert STEP_COMPUTED["function_name"](model, rows, 2) == "Provare i freni"
    assert involved_domains(model, e["fc"]) == [e["df08"].uuid, e["df07"].uuid]
    # Each exchange once, as it first appears (received, then sent), with its type and the nature of its data.
    assert [(r["exchange"], r["source"], r["target"], r["data"], r["nature"], r["type"], r["status"])
            for r in used_exchange_rows(model, e["fc"])] == [
        ("FE-PWR-DF08-01", "PWR", "SF-DF08-01", "EI-EventoAccensione", "EVENT", "Con attore esterno", "Proposto"),
        ("FE-DF08-DF07-01", "SF-DF08-01", "SF-DF07-01", "EI-RichiestaTest", "OPERATION", "Tra domini", ""),
        ("FE-DF07-DF08-01", "SF-DF07-01", "SF-DF08-01", "EI-EsitoTest", "EVENT", "Tra domini", "")]
    assert item_producer(model, e["ei_on"]) == [e["pwr"].uuid]
    assert item_users(model, e["ei_test"]) == [e["sf07"].uuid]


def test_the_sheet_of_a_chain_shows_the_computed_columns_and_the_exchanges_used(app, tmp_path):
    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.edit(p, e["fc"], editing=True)
    steps = editor.getters["steps"].__self__  # the table of the path
    table, labels = steps.table, [c.label for c in steps.columns]
    column = labels.index
    assert [table.item(r, column("#")).text() for r in range(4)] == ["1", "", "2", "3"]
    assert table.item(2, column("Dominio")).text() == "DF07"
    assert table.item(2, column("Nome funzione")).text() == "Provare i freni"
    assert not table.item(0, column("Dominio")).flags() & Qt.ItemIsEditable  # computed: not typed
    # Not saved: the rows keep only what is entered.
    assert "domain" not in steps.value()[0] and "number" not in steps.value()[0]
    # Another function in a step: its domain and name follow.
    combo = table.cellWidget(2, column("Funzione SF"))
    combo.setCurrentIndex(combo.findData(e["sf08"].uuid))
    assert table.item(2, column("Dominio")).text() == "DF08"
    assert table.item(2, column("Nome funzione")).text() == "Gestire l'avvio"

    assert "used_exchanges" not in editor.getters  # computed: not saved
    used = editor.widgets["used_exchanges"].findChild(type(steps))
    assert used.table.rowCount() == 3 and used.read_only
    assert used.table.item(0, 5).text() == "Con attore esterno"
    involved = editor.widgets["domains"]
    assert involved.value() == [e["df08"].uuid, e["df07"].uuid]  # of the functions of the steps
    for label in ("Decisioni collegate", "Capability operativa", "Varianti", "Oracolo", "Incremento",
                  "Procedura o sezione SRS", "Dominio responsabile"):
        assert label not in [w.text() for w in editor.field_labels.values()]


def test_the_sheet_of_an_exchange_item_reads_producer_and_users_from_the_exchanges(app, tmp_path):
    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.edit(p, e["ei_test"])
    assert editor.widgets["producer"].value() == [e["sf08"].uuid]
    assert editor.widgets["users"].value() == [e["sf07"].uuid]
    assert [w.text() for w in editor.field_labels.values()] == [
        "ID", "Nome", "Natura", "Tipo", "Elementi", "Origine o specifica", "Produttore", "Utilizzatori", "Note"]


@pytest.mark.parametrize("kind, field, typed, expected", [
    ("exchange_item", "name", "Evento di accensione", "EI-EventoAccensione"),
    ("functional_chain", "title", "Isolamento dell'EVC", "FC-IsolamentoEVC")])
def test_a_new_sheet_shows_its_identifier_as_the_name_is_typed(app, tmp_path, kind, field, typed, expected):
    p = Project.create(tmp_path / "p", "Prova")
    element = p.new_element(kind)
    assert element.get("id") is None  # no name yet
    editor = ElementEditor()
    editor.edit(p, element, editing=True)
    assert editor.id_edit.text() == "" and "Verrà assegnato" in editor.id_edit.placeholderText()
    editor.widgets[field].setText(typed)
    editor.flush()
    assert editor.id_edit.text() == expected  # before saving
    editor.widgets[field].setText(typed + " bis")
    editor.flush()
    assert editor.id_edit.text() == expected + "Bis"  # it follows the name until saved
    editor.save_changes()
    assert p.model.get(element.uuid).get("id") == expected + "Bis"
    editor.widgets[field].setText("Altro")
    editor.flush()
    assert editor.id_edit.text() == expected + "Bis"  # once saved, it no longer changes by itself


@pytest.mark.parametrize("kind, field, typed, expected", [
    ("exchange_item", "name", "Evento di accensione", "EI-EventoAccensione"),
    ("functional_chain", "title", "Isolamento dell'EVC", "FC-IsolamentoEVC")])
def test_the_tree_and_the_tab_follow_the_name_as_it_is_typed(app, tmp_path, kind, field, typed, expected):
    from arcadia_tool.ui.main_window import MainWindow

    p = Project.create(tmp_path / "p", "Prova")
    window = MainWindow()
    window._set_project(p)
    window.tree.create(kind)
    element = p.model.of_kind(kind)[0]
    editor = window.editors[element.uuid]
    editor.widgets[field].setText(typed)
    editor.flush()
    # Named by the ID only (made of the name): not «EI-EventoAccensione Evento di accensione».
    assert window.tree._items[element.uuid].text(0) == expected
    assert window.pages.tabText(window.pages.indexOf(editor)) == f"● {expected}"
    assert editor.title.text() == expected
    editor.save_changes()
    assert window.tree._items[element.uuid].text(0) == expected and p.model.label_of(element.uuid) == expected
    window._set_project(None)
    window.close()


def test_an_exchange_has_no_agreements_of_producer_and_user():
    labels = shown("functional_exchange")
    assert "Accordo del produttore" not in labels and "Accordo dell'utilizzatore" not in labels
    assert "Stato" in labels  # whether it is agreed


def test_the_domains_involved_are_those_of_the_steps_and_those_ticked(app, tmp_path, monkeypatch):
    from arcadia_tool.ui.element_editor import RefPicker

    p, e = build(tmp_path)
    assert e["fc"].get("domains") == [e["df08"].uuid, e["df07"].uuid]  # from the steps, when saved
    other = p.new_element("domain", id="DF15", name="JRU")
    editor = ElementEditor()
    editor.edit(p, e["fc"], editing=True)
    area = editor.widgets["domains"]
    seen = []

    def tick(dialog):  # the window with a box per domain: DF15 ticked, DF07 (of a step) unticked
        seen.append({dialog.list.item(i).text(): dialog.list.item(i).checkState() == Qt.Checked
                     for i in range(dialog.list.count())})
        for i in range(dialog.list.count()):
            item = dialog.list.item(i)
            item.setCheckState(Qt.Checked if item.text() != "DF07 Freni" else Qt.Unchecked)
        return True
    monkeypatch.setattr(RefPicker, "exec", tick)
    area._pick()
    editor.flush()
    assert seen == [{"DF08 Modi": True, "DF07 Freni": True, "DF15 JRU": False}]
    # DF07 stays: a function of the path is in it.
    assert area.value() == [e["df08"].uuid, e["df07"].uuid, other.uuid]
    editor.save_changes()
    assert p.model.get(e["fc"].uuid).get("domains") == [e["df08"].uuid, e["df07"].uuid, other.uuid]


def test_the_type_of_an_exchange_is_the_nature_of_its_exchange_item(app, tmp_path):
    p, e = build(tmp_path)
    fe = p.model.get(e["fe_done"].uuid)
    assert KINDS_BY_NAME["functional_exchange"].field("nature").label == "Tipo"
    assert fe.get("nature") == "EVENT"  # from EI-EsitoTest
    item = p.model.get(e["ei_done"].uuid)
    item.set("nature", "FLOW")
    p.update(item)
    assert fe.get("nature") == "FLOW"  # kept in step
    editor = ElementEditor()
    editor.edit(p, fe, editing=True)
    shown_type = editor.widgets["nature"]
    assert shown_type.isReadOnly() and shown_type.text() == "FLOW"


def test_the_type_of_an_exchange_item_is_chosen_in_a_window_that_explains_it(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QComboBox
    from arcadia_tool.ui.element_editor import ChoiceDialog, ValuePicker

    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.edit(p, e["ei_test"], editing=True)
    assert not editor.findChildren(QComboBox)  # no drop-down list in the sheet
    picker = editor.widgets["type"]
    assert isinstance(picker, ValuePicker)
    guides = [w.text() for w in editor.findChildren(type(editor.field_labels["type"])) if w.objectName() == "fieldGuide"]
    assert guides == []  # not in the sheet: only in the window to choose it
    seen = []

    def choose(dialog):
        seen.append([w.text() for w in dialog.findChildren(type(editor.field_labels["type"]))])
        values = [dialog.list.item(i).text() for i in range(dialog.list.count())]
        if "Dato di interfaccia esterna (uscita)" in values:
            dialog.list.setCurrentRow(values.index("Dato di interfaccia esterna (uscita)"))
        return True
    monkeypatch.setattr(ChoiceDialog, "exec", choose)
    picker.choose()
    assert any("forma esterna" in t for t in seen[0])  # the guide in the window
    editor.widgets["nature"].choose()  # the nature too: its own guide
    assert any("come si comporta il dato" in t for t in seen[1])
    editor.save_changes()
    assert p.model.get(e["ei_test"].uuid).get("type") == "Dato di interfaccia esterna (uscita)"


def test_the_fields_of_an_exchange_have_a_question_mark_with_what_they_mean(app, tmp_path):
    from PySide6.QtWidgets import QToolButton

    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.edit(p, e["fe_req"], editing=True)
    helps = {b.toolTip().split("</b>")[0].split("<b>")[1]: b.toolTip()
             for b in editor.findChildren(QToolButton) if b.objectName() == "fieldHelp"}
    assert set(helps) == {"ID scambio", "Nome", "Produttore", "Utilizzatore", "Dato di interfaccia", "Tipo",
                          "Condizione di produzione", "Clausole", "Stato"}
    assert "FE-DFaa-DFbb-nn" in helps["ID scambio"] and "Su richiesta" in helps["Condizione di produzione"]


@pytest.mark.parametrize("key, labels", [
    ("ei_test", {"ID", "Nome", "Natura", "Tipo", "Elementi", "Origine o specifica", "Produttore", "Utilizzatori",
                 "Note", "Stato"}),
    ("fc", {"ID", "Titolo", "Domini coinvolti", "Avviabilità", "Trigger", "Effetto osservabile finale",
            "Precondizioni", "Postcondizioni", "Fuori ambito", "Percorso", "Scambi usati", "Stato"})])
def test_the_fields_of_an_exchange_item_and_of_a_chain_have_the_question_mark(app, tmp_path, key, labels):
    from PySide6.QtWidgets import QToolButton

    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.edit(p, e[key], editing=True)
    helps = {b.toolTip().split("</b>")[0].split("<b>")[1]
             for b in editor.findChildren(QToolButton) if b.objectName() == "fieldHelp"}
    assert helps == labels  # every field, the tables (on the left of their title) and the state


def test_the_sheets_sa1_sa2_sa3_have_the_question_mark_on_every_field(app, tmp_path):
    from PySide6.QtWidgets import QToolButton

    p = Project.create(tmp_path / "p", "Prova")
    domain = p.new_element("domain", name="Odometria", mission="Stima velocità e posizione.")
    section = p.new_element("requirement", id="3.6.1", item_type="Sezione", primary_domain=domain.uuid)
    clause = p.new_element("requirement", id="3.6.1.1", item_type="Requisito", parent=section.uuid,
                           category=["Bordo"])
    function = p.new_element("system_function", name="Stimare la velocità", domain=domain.uuid, description="Stima.",
                             sections=[section.uuid])
    record = p.new_element("trace_record", requirement=clause.uuid, primary_functions=[function.uuid])
    for element in (domain, function, record):
        editor = ElementEditor()
        editor.edit(p, element, editing=True)
        helps = {b.toolTip().split("</b>")[0].split("<b>")[1]
                 for b in editor.findChildren(QToolButton) if b.objectName() == "fieldHelp"}
        expected = {f.label for f in element.schema.fields if not f.hidden and f.applies(element)
                    and not (element.kind == "domain" and f.name == "related_adrs")}  # a domain: its ADR in a tab
        assert helps == expected, element.kind  # every field shown, and the state
    from PySide6.QtWidgets import QTabWidget
    editor = ElementEditor()
    editor.edit(p, domain, editing=True)
    tabs = editor.findChild(QTabWidget, "srsTabs")  # the help of the ADR of the domain: on its tab
    assert tabs.tabToolTip(tabs.count() - 1) == domain.schema.field("related_adrs").guide


def test_the_views_of_a_chain_show_its_sheet(app, tmp_path):
    """Chain and scenario views as the path of the sheet: the steps numbered as «#», the waiting rows not drawn,
    the exchange received from an actor, the internal data on its lifeline, the data by the ID of the EI."""
    from arcadia_tool.model import diagrams as dg
    from arcadia_tool.model.schema import DIAGRAM_CHAIN, DIAGRAM_SCENARIO

    p, e = build(tmp_path)

    def view(kind):
        return p.new_element("diagram", name="Vista", diagram_type=kind, chain=e["fc"].uuid,
                             layout=dg.new_view_layout(p.model, kind, e["fc"].uuid))
    chain = view(DIAGRAM_CHAIN)
    rows = e["fc"].get("steps")
    assert set(dg.positions(chain)) == {dg.step_key(rows[i]) for i in (0, 2, 3)}  # no waiting row
    steps = dg.shown_steps(p.model, chain)
    assert [(s.number, s.domain_ident, s.input is not None) for s in steps] == [
        ("1", "DF08", True), ("2", "DF07", True), ("3", "DF08", True)]
    assert dg.missing(p.model, chain) == []  # the keys of the rows stay valid
    sc = dg.scenario(p.model, view(DIAGRAM_SCENARIO))
    assert [(m.label, m.ident) for m in sc.messages] == [
        ("EI-EventoAccensione", "FE-PWR-DF08-01"),  # the trigger: «Ingresso» of the first step, from PWR
        ("EI-RichiestaTest", "FE-DF08-DF07-01"), ("EI-EsitoTest", "FE-DF07-DF08-01"),
        ("Esito dell'avvio", "")]  # internal: it stays on the lifeline of DF08
    assert sc.lifelines[0].actor and sc.messages[-1].source == sc.messages[-1].target == e["df08"].uuid
