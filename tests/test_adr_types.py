"""Types of architectural decision (X-1): each a template with its own fields, chosen when the ADR is created."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from arcadia_tool.model.adr import adr_defaults, suggested_type, type_fields
from arcadia_tool.model.schema import (ADR_DETAILS, ADR_DOMAIN_SCOPE, ADR_FUNCTION, ADR_NEW_DOMAIN, ADR_OTHER,
                                       ADR_SECTION, ADR_TYPES, ADR_WAIVER, KINDS_BY_NAME)
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.adr_types import AdrTypeDialog
from arcadia_tool.ui.element_editor import ElementEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def captions(editor):
    return [l.text() for l in editor.widget().findChildren(QLabel) if l.objectName() == "sectionCaption"]


def shown_fields(editor):
    return {name for name in editor.widgets}


def test_every_type_has_its_own_fields_and_they_are_in_its_template():
    schema = KINDS_BY_NAME["adr"]
    assert [name for name, _ in ADR_TYPES][:5] == ["Nuovo dominio funzionale", "Eliminazione di dominio",
                                                   "Fusione di domini", "Scissione di dominio",
                                                   "Ridefinizione dello scopo del dominio"]
    for name, when in ADR_TYPES:
        assert when
        if name not in (ADR_OTHER, "Eliminazione di dominio"):  # those two: no details of their own
            assert type_fields(name), name
    scope = {f.name for f in type_fields(ADR_DOMAIN_SCOPE)}
    assert scope == {"domain", "scope_change", "mission_current", "mission_proposed", "scope_reason",
                     "sections_acquired", "sections_ceded"}
    assert schema.field("mission_current").computed and not schema.field("mission_current").stored
    assert schema.field("scope_change").options == ("Estensione", "Riduzione", "Cambio totale di scopo")
    new_domain = {f.name for f in type_fields(ADR_NEW_DOMAIN)}
    assert new_domain >= {"new_domain_name", "mission_proposed", "sections_allocated", "team_proposed"}
    assert "proposed_domain" not in new_domain  # the name only: the ID is given at the approval
    assert not new_domain & {"include_proposed", "exclude_proposed", "a2_criteria", "sections_moved",
                             "functions_moved", "main_data"}
    assert schema.field("sections_allocated").label == "Sezioni allocate al dominio"
    assert [f.name for f in type_fields(ADR_NEW_DOMAIN)][:4] == ["new_domain_name", "mission_proposed",
                                                                 "proposal_reason", "proposal_benefits"]
    assert schema.field("new_domain_name").label == "Nome del dominio proposto"
    assert "evidence_chains" not in new_domain and "main_data" not in new_domain
    assert schema.field("sections_allocated").sections_only
    assert all(f.section == ADR_DETAILS for name, _ in ADR_TYPES for f in type_fields(name))


def test_a_new_adr_knows_what_the_selected_element_says(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione", mission="Impedire i movimenti non autorizzati.")
    d2 = p.new_element("domain", name="Localizzazione")
    section = p.new_element("requirement", id="3.14.4", item_type="Sezione", primary_domain=d1.uuid,
                            contributing_domains=[d2.uuid])
    sf = p.new_element("system_function", name="Supervisionare lo standstill", domain=d1.uuid)
    assert suggested_type(d1) == ADR_DOMAIN_SCOPE and suggested_type(section) == ADR_SECTION
    assert adr_defaults(p.model, ADR_DOMAIN_SCOPE, d1) == {
        "adr_type": ADR_DOMAIN_SCOPE, "status": "Proposta", "domain": d1.uuid}  # its mission: read from it
    assert adr_defaults(p.model, ADR_SECTION, section) == {
        "adr_type": ADR_SECTION, "status": "Proposta", "realloc_item": section.uuid}  # its domains: read from it
    assert adr_defaults(p.model, ADR_FUNCTION, sf) == {"adr_type": ADR_FUNCTION, "status": "Proposta",
                                                       "function": sf.uuid}
    assert adr_defaults(p.model, ADR_WAIVER, d1) == {"adr_type": ADR_WAIVER, "status": "Proposta"}
    p.close()


def test_the_window_of_the_types_shows_the_template_before_creating(app):
    from arcadia_tool.model.schema import ADR_AREAS, adr_area
    dialog = AdrTypeDialog(preselect=ADR_DOMAIN_SCOPE)
    assert len(dialog.type_rows()) == len(ADR_TYPES)  # the types, under the headers of their areas
    assert dialog.types.item(0).text() == "DOMINI FUNZIONALI (SA)" and not dialog.types.item(0).flags()
    headers = [dialog.types.item(r).text() for r in range(dialog.types.count()) if r not in dialog.type_rows()]
    assert headers == [area.upper() for area, _ in ADR_AREAS]
    assert sorted(t for _, types in ADR_AREAS for t in types) == sorted(n for n, _ in ADR_TYPES)
    assert adr_area(ADR_WAIVER) == "Generali" and adr_area(None) == ""
    text = dialog.preview.text()
    assert "Dettagli: Ridefinizione dello scopo del dominio" in text and "Natura della modifica" in text
    assert "Campi comuni" in text and "Motivazione" in text
    plain = AdrTypeDialog()  # no element selected: the first type, the list from the top
    plain.show()
    assert plain.types.currentRow() == plain.type_rows()[0] and plain.types.verticalScrollBar().value() == 0
    plain.close()
    dialog.types.setCurrentRow(dialog.type_rows()[-1])  # «Altro»
    assert "Nessun campo proprio" in dialog.preview.text()
    dialog._accept()
    assert dialog.adr_type == ADR_OTHER


def test_the_sheet_has_the_fields_of_its_type(app, tmp_path, monkeypatch):
    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione", mission="Impedire i movimenti.")
    adr = p.new_element("adr", title="Estendere DF01", **adr_defaults(p.model, ADR_DOMAIN_SCOPE, d1))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert "DETTAGLI: RIDEFINIZIONE DELLO SCOPO DEL DOMINIO" in [c.upper() for c in captions(editor)]
    order = [c.upper() for c in captions(editor)]
    assert order == ["IDENTIFICAZIONE", "DETTAGLI: RIDEFINIZIONE DELLO SCOPO DEL DOMINIO"]
    fields = shown_fields(editor)
    assert {"scope_change", "mission_current", "sections_acquired", "sections_ceded"} <= fields
    assert not {"merged_domains", "rule", "exchange_item"} & fields  # fields of other types: not there
    assert editor.widgets["mission_current"].markdown() == "Impedire i movimenti."  # read from the domain

    # Another type: the fields of the old one are emptied, after a confirmation.
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    combo = editor.widgets["adr_type"]
    combo.setCurrentIndex(combo.findData(ADR_WAIVER))
    assert asked and "Dominio interessato" in asked[0]
    assert "rule" in shown_fields(editor) and "mission_current" not in shown_fields(editor)
    editor.save_changes()
    assert adr.get("adr_type") == ADR_WAIVER and adr.get("mission_current") is None and adr.get("domain") is None

    # An ADR of the first versions, without a type: only the common fields.
    old = p.new_element("adr", title="Senza tipo")
    editor.edit(p, old)
    assert not any(c.startswith("Dettagli") for c in captions(editor))
    p.close()


def test_new_adr_from_the_tree_asks_the_type_and_fills_it(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.adr_types as adr_types
    from arcadia_tool.ui.model_tree import ModelTree

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione", mission="Impedire i movimenti.")
    tree = ModelTree()
    tree.set_project(p)
    tree.select(d1.uuid)
    offered = []

    def choose(dialog):
        offered.append(dialog.types.currentItem().data(0x0100))
        dialog._accept()  # the type offered: the redefinition of the scope of the selected domain
        return True
    monkeypatch.setattr(adr_types.AdrTypeDialog, "exec", choose)
    tree.create("adr")
    adr = p.model.of_kind("adr")[0]
    assert offered == [ADR_DOMAIN_SCOPE]
    assert (adr.get("adr_type"), adr.get("domain")) == (ADR_DOMAIN_SCOPE, d1.uuid)

    monkeypatch.setattr(adr_types.AdrTypeDialog, "exec", lambda dialog: False)
    tree.create("adr")  # cancelled: no ADR
    assert len(p.model.of_kind("adr")) == 1
    p.close()


def test_a_new_domain_has_only_its_identification_and_details(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.ui.element_editor import RefsWidget

    p = Project.create(tmp_path / "p", "Prova")
    section = p.new_element("requirement", id="3.16.2", item_type="Sezione", text="Ordini di emergenza")
    clause = p.new_element("requirement", id="3.16.2.1", item_type="Requisito", parent=section.uuid, text="…")
    adr = p.new_element("adr", title="Nuovo dominio della radio", **adr_defaults(p.model, ADR_NEW_DOMAIN))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    order = [c.upper() for c in captions(editor)]
    assert order == ["IDENTIFICAZIONE", "DETTAGLI: NUOVO DOMINIO FUNZIONALE"]  # no relations, description, options
    assert "superseded_by" in shown_fields(editor)  # in the identification
    assert not {"context", "srs_items", "options", "decision", "rationale"} & shown_fields(editor)

    # The sections are chosen with ticks, only the sections (three numbers)
    dialog = srs_trace.TraceSectionsDialog(p, adr.copy(), "sections_allocated")
    assert set(dialog.state) == {section.uuid}  # the clause cannot be chosen
    assert dialog.count_text() == "Nessuna sezione scelta"
    asked = []

    def choose(project, element, field, current, parent=None, sections_only=False):
        asked.append((field, sections_only))
        return [section.uuid]
    import arcadia_tool.ui.srs_trace
    monkeypatch.setattr(arcadia_tool.ui.srs_trace, "choose_items", choose)
    editor.edit(p, adr, editing=True)
    refs = next(w for w in editor.widget().findChildren(RefsWidget) if w is editor.widgets["sections_allocated"])
    refs._pick()  # «Seleziona»
    editor.save_changes()
    assert asked == [("sections_allocated", True)] and adr.get("sections_allocated") == [section.uuid]
    assert clause.uuid not in adr.get("sections_allocated")
    p.close()


def test_the_design_authority_approves_a_new_domain(app, tmp_path, monkeypatch):
    from datetime import date
    from arcadia_tool.model.adr import approval_problems, approve_new_domain, can_approve

    p = Project.create(tmp_path / "p", "Prova")
    df01 = p.new_element("domain", name="Dati di terra")
    team = p.new_element("team", name="Radio")
    s1 = p.new_element("requirement", id="3.5.3", item_type="Sezione", primary_domain=df01.uuid)
    s2 = p.new_element("requirement", id="3.5.4", item_type="Sezione", contributing_domains=[df01.uuid])
    adr = p.new_element("adr", title="Nuovo dominio della radio", **adr_defaults(p.model, ADR_NEW_DOMAIN))
    assert can_approve(adr)
    assert approval_problems(p.model, adr) == ["Manca il nome del dominio proposto.", "Manca la missione proposta."]
    adr.set("new_domain_name", "dati di  TERRA")
    assert "Esiste già un dominio" in approval_problems(p.model, adr)[0]
    adr.set("new_domain_name", "Gestione della sessione radio")
    adr.set("mission_proposed", "Stabilire e mantenere la sessione radio con l'RBC.")
    adr.set("sections_allocated", [s1.uuid, s2.uuid])
    adr.set("team_proposed", team.uuid)
    p.update(adr)
    domain, changed = approve_new_domain(p, adr, today=date(2026, 10, 27))
    assert domain.get("id") == "DF02" and domain.get("name") == "Gestione della sessione radio"  # ID by the tool
    assert domain.get("mission") == "Stabilire e mantenere la sessione radio con l'RBC."
    assert domain.get("team") == team.uuid and domain.uuid in team.get("domains")
    assert s1.get("primary_domain") == domain.uuid and s2.get("primary_domain") == domain.uuid
    assert s2.get("contributing_domains") == [df01.uuid]
    assert (adr.get("status"), adr.get("created_domain")) == ("Decisa", domain.uuid)
    assert adr.get("decision_date") == "27/10/2026"  # set by the tool; the decider is the DA
    assert not can_approve(adr) and {s1.uuid, s2.uuid} <= {e.uuid for e in changed}

    # In the sheet: the button only for the Design Authority, with a confirmation.
    other = p.new_element("adr", title="Un altro dominio", new_domain_name="Gestione dei guasti",
                          mission_proposed="Rilevare i guasti.", **adr_defaults(p.model, ADR_NEW_DOMAIN))
    editor = ElementEditor()
    editor.approver = lambda: None  # not a member of the DA
    editor.edit(p, other)
    assert not hasattr(editor, "approve_button") or editor.approve_button.parent() is None or         not editor.approve_button.isVisibleTo(editor)
    editor = ElementEditor()
    editor.approver = lambda: "Anna Bianchi"
    editor.edit(p, other)
    assert editor.approve_button.text() == "Approva e crea il dominio"
    asked, saved = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    editor.saved.connect(lambda: saved.append(True))
    editor.approve()
    assert "Gestione dei guasti" in asked[0] and saved == [True]
    created = p.model.get(other.get("created_domain"))
    assert created.get("id") == "DF03" and other.get("status") == "Decisa"
    assert not hasattr(editor, "approve_button") or not can_approve(other)
    p.close()


def test_the_deletion_of_a_domain_has_only_the_domain_the_motivation_and_the_observations(app, tmp_path):
    from arcadia_tool.model.adr import common_fields
    from arcadia_tool.model.schema import ADR_DELETE_DOMAIN

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Gestione dei guasti")
    assert adr_defaults(p.model, ADR_DELETE_DOMAIN, d1)["deleted_domain"] == d1.uuid
    assert type_fields(ADR_DELETE_DOMAIN) == []
    assert [f.label for f in common_fields(ADR_DELETE_DOMAIN)] == ["Dominio interessato", "Motivazione",
                                                                    "Osservazioni DA"]
    adr = p.new_element("adr", title="Eliminare DF01", **adr_defaults(p.model, ADR_DELETE_DOMAIN, d1))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DESCRIZIONE"]
    names = list(editor.widgets)
    assert names.index("deleted_domain") == names.index("adr_type") + 1  # right under the type of decision
    descr = [n for n in names if n in ("deleted_domain", "rationale", "da_notes", "context", "options",
                                       "srs_items", "decision")]
    assert descr == ["deleted_domain", "rationale", "da_notes"]
    assert editor.widgets["deleted_domain"].currentData() == d1.uuid
    p.close()


def test_the_date_of_the_decision_is_set_by_the_tool(app, tmp_path):
    from datetime import date
    from arcadia_tool.model.adr import decision_date_of
    from arcadia_tool.model.element import Element
    from arcadia_tool.model.serialization import dumps

    p = Project.create(tmp_path / "p", "Prova")
    adr = p.new_element("adr", title="Una scelta", status="Proposta")
    assert adr.get("decision_date") is None
    assert "date_decider" not in [f.name for f in KINDS_BY_NAME["adr"].fields]  # no decider: it is the DA
    adr.set("status", "Decisa")
    p.update(adr)
    assert adr.get("decision_date") == f"{date.today():%d/%m/%Y}"
    adr.set("status", "Superata")
    p.update(adr)
    assert adr.get("decision_date") == f"{date.today():%d/%m/%Y}"  # kept
    adr.set("status", "Proposta")
    p.update(adr)
    assert adr.get("decision_date") is None  # proposed again: not decided
    assert decision_date_of(Element("adr", values={"status": "Decisa"}), today=date(2026, 1, 2)) == "02/01/2026"

    # The sheet shows it read-only, only once the ADR is decided
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert "decision_date" not in editor.widgets
    adr.set("status", "Decisa")
    p.update(adr)
    editor.edit(p, adr, editing=True)
    assert not editor.widgets["decision_date"].isEnabled()

    # «Data e decisore» of the earlier versions: its date is kept
    p.save()
    p.close()
    old = Element("adr", values={"id": "ADR-009", "title": "Vecchia", "status": "Decisa",
                                 "date_decider": "5/9/2026 · Design Authority"})
    (tmp_path / "p" / "model" / "x" / "adr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "p" / "model" / "x" / "adr" / f"{old.uuid}.yaml").write_text(dumps(old), encoding="utf-8")
    again = Project.open(tmp_path / "p")
    migrated = again.model.get(old.uuid)
    assert migrated.get("decision_date") == "05/09/2026" and "date_decider" not in migrated.values
    again.close()


def test_the_merge_of_domains_shows_the_srs_items_of_the_domains_merged(app, tmp_path):
    from arcadia_tool.model.adr import common_fields, merged_srs_items
    from arcadia_tool.model.schema import ADR_MERGE_DOMAINS
    from arcadia_tool.ui.element_editor import RefsWidget

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Dati di terra")
    d2 = p.new_element("domain", name="Dati di bordo")
    d3 = p.new_element("domain", name="Altro")
    s1 = p.new_element("requirement", id="3.5.4", item_type="Sezione", primary_domain=d1.uuid)
    s2 = p.new_element("requirement", id="3.5.10", item_type="Sezione", primary_domain=d3.uuid,
                       contributing_domains=[d2.uuid])
    p.new_element("requirement", id="3.6.1", item_type="Sezione", primary_domain=d3.uuid)
    names = {f.name for f in type_fields(ADR_MERGE_DOMAINS)}
    assert {"merged_domains", "proposed_domain", "kept_domain", "mission_proposed", "merged_srs_items",
            "team_proposed"} == names
    assert KINDS_BY_NAME["adr"].field("proposed_domain").label == "Nome del dominio risultante"
    assert common_fields(ADR_MERGE_DOMAINS) == []  # no description, options or SRS items chosen by hand
    adr = p.new_element("adr", title="Fondere i dati", merged_domains=[d1.uuid, d2.uuid],
                        **adr_defaults(p.model, ADR_MERGE_DOMAINS))
    assert merged_srs_items(p.model, adr) == [s1.uuid, s2.uuid]  # principal or contributing, in order
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: FUSIONE DI DOMINI"]
    shown = editor.widgets["merged_srs_items"]
    assert isinstance(shown, RefsWidget) and shown.value() == [s1.uuid, s2.uuid]
    assert all(b.isHidden() for b in shown.findChildren(type(editor.widgets["merged_domains"].findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)[0])))
    editor.widgets["merged_domains"].set_value([d1.uuid])  # one domain less: the list follows
    editor.widgets["merged_domains"].changed.emit()
    editor.flush()
    assert shown.value() == [s1.uuid]
    editor.save_changes()
    assert "merged_srs_items" not in adr.values  # computed, not saved
    p.close()


def test_the_split_of_a_domain_is_the_dual_of_the_merge(app, tmp_path):
    from arcadia_tool.model.adr import CHOICES, common_fields
    from arcadia_tool.model.schema import ADR_SPLIT_DOMAIN

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Dati")
    d2 = p.new_element("domain", name="Altro")
    s1 = p.new_element("requirement", id="3.5.4", item_type="Sezione", primary_domain=d1.uuid)
    s2 = p.new_element("requirement", id="3.6.1", item_type="Sezione", primary_domain=d2.uuid,
                       contributing_domains=[d1.uuid])
    p.new_element("requirement", id="3.7.1", item_type="Sezione", primary_domain=d2.uuid)
    assert [f.name for f in type_fields(ADR_SPLIT_DOMAIN)] == ["split_domain", "new_domains", "split_allocation"]
    columns = [c.label for c in KINDS_BY_NAME["adr"].field("new_domains").columns]
    assert columns == ["Nome del dominio risultante", "Missione proposta", "Team proposto",
                       "Mantiene l'ID"]  # the names only: the IDs by the tool
    assert common_fields(ADR_SPLIT_DOMAIN) == []  # no description, options or SRS items chosen by hand
    values = adr_defaults(p.model, ADR_SPLIT_DOMAIN, d1)
    assert values["split_domain"] == d1.uuid
    adr = p.new_element("adr", title="Scindere i dati", **values)
    assert [u for u, _ in CHOICES["split_domain_items"](p.model, adr)] == [s1.uuid, s2.uuid]
    assert CHOICES["split_destinations"](p.model, adr) == []

    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: SCISSIONE DI DOMINIO"]
    domains = next(w for w in editor.widget().findChildren(type(editor)._make_widget.__globals__["TableWidget"])
                   if w.columns[0].name == "name")
    allocation = next(w for w in editor.widget().findChildren(type(editor)._make_widget.__globals__["TableWidget"])
                      if w.columns[0].name == "item")
    domains.set_value([{"name": "Dati del treno"}, {"name": "Dati nazionali"}])  # the resulting domains, above
    domains.changed.emit()
    allocation._add_clicked()
    editor.flush()  # the lists of the cells follow what is written above
    item_combo, destination_combo = allocation.table.cellWidget(0, 0), allocation.table.cellWidget(0, 1)
    assert [item_combo.itemData(i) for i in range(1, item_combo.count())] == [s1.uuid, s2.uuid]
    assert [destination_combo.itemText(i) for i in range(1, destination_combo.count())] == ["Dati del treno",
                                                                                           "Dati nazionali"]
    item_combo.setCurrentIndex(item_combo.findData(s2.uuid))
    destination_combo.setCurrentIndex(destination_combo.findData("Dati nazionali"))
    editor.save_changes()
    assert adr.get("split_allocation") == [{"item": s2.uuid, "destination": "Dati nazionali"}]
    p.close()


def test_the_reallocation_of_a_section_shows_its_domains_now_and_those_proposed(app, tmp_path):
    from arcadia_tool.model.adr import common_fields
    import arcadia_tool.ui.srs_trace as srs_trace

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    d2 = p.new_element("domain", name="Localizzazione")
    d3 = p.new_element("domain", name="Modi")
    section = p.new_element("requirement", id="3.14.4", item_type="Sezione", primary_domain=d1.uuid,
                            contributing_domains=[d2.uuid])
    assert [f.name for f in type_fields(ADR_SECTION)] == ["realloc_item", "primary_current", "contributors_current",
                                                          "primary_proposed", "contributors_proposed",
                                                          "realloc_reason"]
    assert common_fields(ADR_SECTION) == []  # no description, options, relations
    assert srs_trace.ITEM_DIALOGS["realloc_item"] is srs_trace.TraceReallocItemDialog  # chosen with ticks
    adr = p.new_element("adr", title="Spostare 3.14.4", **adr_defaults(p.model, ADR_SECTION, section))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: RIALLOCAZIONE DI SEZIONE O CLAUSOLA"]
    assert editor.widgets["primary_current"].text() == p.model.label(d1)  # read from the section
    assert editor.widgets["contributors_current"].value() == [d2.uuid]
    combo = editor.widgets["primary_proposed"]
    combo.setCurrentIndex(combo.findData(d3.uuid))
    editor.save_changes()
    assert adr.get("primary_proposed") == d3.uuid
    assert "primary_current" not in adr.values and "contributors_current" not in adr.values  # not saved
    section.set("primary_domain", d2.uuid)  # the section changes: the ADR shows it as it is
    p.update(section)
    editor.edit(p, adr)
    assert editor.widgets["primary_current"].text() == p.model.label(d2)
    p.close()


def test_the_move_of_a_function_shows_its_domain_now_and_the_one_proposed(app, tmp_path):
    from arcadia_tool.model.adr import common_fields

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    d2 = p.new_element("domain", name="Localizzazione")
    sf = p.new_element("system_function", name="Determinare la velocità", domain=d1.uuid)
    assert [f.name for f in type_fields(ADR_FUNCTION)] == ["function", "function_domain", "to_domain",
                                                           "move_reason"]
    assert common_fields(ADR_FUNCTION) == []
    adr = p.new_element("adr", title="Spostare la velocità", **adr_defaults(p.model, ADR_FUNCTION, sf))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE",
                                                     "DETTAGLI: SPOSTAMENTO DI UNA FUNZIONE TRA DOMINI"]
    assert editor.widgets["function_domain"].text() == p.model.label(d1)  # read from the function
    combo = editor.widgets["to_domain"]
    combo.setCurrentIndex(combo.findData(d2.uuid))
    editor.save_changes()
    assert adr.get("to_domain") == d2.uuid and "function_domain" not in adr.values
    p.close()


def test_the_owner_of_an_information_shows_who_produces_it_now(app, tmp_path):
    from arcadia_tool.model.adr import common_fields
    from arcadia_tool.model.schema import ADR_OWNER

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    sf1 = p.new_element("system_function", name="Determinare la velocità", domain=d1.uuid)
    sf2 = p.new_element("system_function", name="Supervisionare", domain=d1.uuid)
    ei = p.new_element("exchange_item", name="Velocità stimata")
    p.new_element("functional_exchange", name="v", source=sf1.uuid, target=sf2.uuid, exchange_item=ei.uuid)
    assert [f.name for f in type_fields(ADR_OWNER)] == ["exchange_item", "item_producers", "candidate_producers",
                                                        "chosen_producer", "evidence_chains", "owner_reason"]
    assert common_fields(ADR_OWNER) == []
    adr = p.new_element("adr", title="Chi produce la velocità", **adr_defaults(p.model, ADR_OWNER, ei))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE",
                                                     "DETTAGLI: PROPRIETÀ DI UN'INFORMAZIONE / CONFINE TRA DOMINI"]
    assert editor.widgets["item_producers"].value() == [sf1.uuid]  # read from the exchanges
    editor.save_changes()
    assert "item_producers" not in adr.values
    p.close()


def test_a_choice_left_to_the_implementation_has_its_item_the_choice_and_the_motivation(app, tmp_path):
    from arcadia_tool.model.adr import common_fields
    from arcadia_tool.model.schema import ADR_IMPLEMENTATION
    import arcadia_tool.ui.srs_trace as srs_trace

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    clause = p.new_element("requirement", id="3.13.9.2", item_type="Clausola", primary_domain=d1.uuid)
    assert [f.name for f in type_fields(ADR_IMPLEMENTATION)] == ["impl_item", "impl_domain", "open_choice",
                                                                 "adopted_choice", "test_case", "impl_reason"]
    assert common_fields(ADR_IMPLEMENTATION) == []
    assert srs_trace.ITEM_DIALOGS["impl_item"] is srs_trace.TraceImplItemDialog  # chosen with ticks
    values = adr_defaults(p.model, ADR_IMPLEMENTATION, clause)
    assert values == {"adr_type": ADR_IMPLEMENTATION, "status": "Proposta", "impl_item": clause.uuid}
    adr = p.new_element("adr", title="Frenatura", **values)
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE",
                                                     "DETTAGLI: SCELTA LASCIATA ALL'IMPLEMENTAZIONE"]
    assert editor.widgets["impl_domain"].text() == p.model.label(d1)  # read from the clause
    p.close()


def test_a_product_option_shows_the_domain_of_its_function(app, tmp_path):
    from arcadia_tool.model.adr import common_fields
    from arcadia_tool.model.schema import ADR_PRODUCT_OPTION

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    sf = p.new_element("system_function", name="Gestire il modo LS", domain=d1.uuid)
    assert [f.name for f in type_fields(ADR_PRODUCT_OPTION)] == ["function", "function_domain", "modes",
                                                                 "product_choice", "parameter", "option_reason"]
    assert common_fields(ADR_PRODUCT_OPTION) == []
    adr = p.new_element("adr", title="Modo LS", **adr_defaults(p.model, ADR_PRODUCT_OPTION, sf))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: OPZIONE DI PRODOTTO"]
    assert editor.widgets["function_domain"].text() == p.model.label(d1)
    p.close()
