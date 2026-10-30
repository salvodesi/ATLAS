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
        "adr_type": ADR_SECTION, "status": "Proposta", "realloc_item": [section.uuid]}  # its domains: read from it
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
    assert order == ["IDENTIFICAZIONE", "DETTAGLI: RIDEFINIZIONE DELLO SCOPO DEL DOMINIO", "DECISIONE DELLA DA"]
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
    assert order == ["IDENTIFICAZIONE", "DETTAGLI: NUOVO DOMINIO FUNZIONALE", "DECISIONE DELLA DA"]  # no relations, description, options
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
                                                                    "Esito della decisione DA", "Osservazioni DA"]
    adr = p.new_element("adr", title="Eliminare DF01", **adr_defaults(p.model, ADR_DELETE_DOMAIN, d1))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DESCRIZIONE", "DECISIONE DELLA DA"]
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
    adr.set("status", "Decisa")
    p.update(adr)
    for state in ("In revisione DA", "Revisionato DA"):  # under the review of the DA, reviewed: not decided
        adr.set("status", "Decisa")
        p.update(adr)
        adr.set("status", state)
        p.update(adr)
        assert adr.get("decision_date") is None
    from arcadia_tool.model.adr import can_approve
    assert KINDS_BY_NAME["adr"].field("status").options == ("Proposta", "In revisione DA", "Revisionato DA", "Decisa",
                                                              "Superata")
    assert all(can_approve(Element("adr", values={"adr_type": ADR_NEW_DOMAIN, "status": s}))
               for s in ("In revisione DA", "Revisionato DA"))
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
    assert [f.name for f in common_fields(ADR_MERGE_DOMAINS)] == ["da_decision", "da_notes"]  # no description, options or SRS items chosen by hand
    adr = p.new_element("adr", title="Fondere i dati", merged_domains=[d1.uuid, d2.uuid],
                        **adr_defaults(p.model, ADR_MERGE_DOMAINS))
    assert merged_srs_items(p.model, adr) == [s1.uuid, s2.uuid]  # principal or contributing, in order
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: FUSIONE DI DOMINI", "DECISIONE DELLA DA"]
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
    assert [f.name for f in common_fields(ADR_SPLIT_DOMAIN)] == ["da_decision", "da_notes"]  # no description, options or SRS items chosen by hand
    values = adr_defaults(p.model, ADR_SPLIT_DOMAIN, d1)
    assert values["split_domain"] == d1.uuid
    adr = p.new_element("adr", title="Scindere i dati", **values)
    assert [u for u, _ in CHOICES["split_domain_items"](p.model, adr)] == [s1.uuid, s2.uuid]
    assert CHOICES["split_destinations"](p.model, adr) == []

    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: SCISSIONE DI DOMINIO", "DECISIONE DELLA DA"]
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
    # No description, options, relations: only the decision of the DA.
    assert [f.name for f in common_fields(ADR_SECTION)] == ["da_decision", "da_notes"]
    assert srs_trace.ITEMS_DIALOGS["realloc_item"] is srs_trace.TraceReallocItemsDialog  # chosen with ticks
    adr = p.new_element("adr", title="Spostare 3.14.4", **adr_defaults(p.model, ADR_SECTION, section))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: RIALLOCAZIONE DI SEZIONE O CLAUSOLA",
                                                     "DECISIONE DELLA DA"]
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


def test_the_reallocation_of_clauses_takes_their_domains_from_their_section_and_only_of_one_section(app, tmp_path,
                                                                                                    monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.model.adr import item_contributors, item_primary

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", id="DF01", name="Protezione")
    d2 = p.new_element("domain", id="DF02", name="Localizzazione")
    s1 = p.new_element("requirement", id="3.11.6", item_type="Sezione", sequence=1, primary_domain=d1.uuid,
                       contributing_domains=[d2.uuid])
    c1, c2 = (p.new_element("requirement", id=f"3.11.6.{n}", item_type="Requisito", parent=s1.uuid, sequence=n + 1)
              for n in (1, 2))
    # Another section, of the same domain: its clauses go in another ADR all the same.
    s2 = p.new_element("requirement", id="3.12.1", item_type="Sezione", sequence=10, primary_domain=d1.uuid)
    other = p.new_element("requirement", id="3.12.1.1", item_type="Requisito", parent=s2.uuid, sequence=11)
    # A clause without domains of its own: those of the section containing it (A4).
    adr = p.new_element("adr", title="Spostare 3.11.6.3", **adr_defaults(p.model, ADR_SECTION, c1))
    assert item_primary(p.model, adr) == d1.uuid and item_contributors(p.model, adr) == [d2.uuid]
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert editor.widgets["primary_current"].text() == f"{p.model.label(d1)}  (da 3.11.6)"
    assert editor.widgets["contributors_current"].value() == [d2.uuid]
    # More clauses: only of the same section.
    told = []
    monkeypatch.setattr(srs_trace.QMessageBox, "warning", lambda *a, **k: told.append(a[2]))
    dialog = srs_trace.TraceReallocItemsDialog(p, adr.copy(), "realloc_item")

    def row(item):  # the row of an item (of any chapter)
        entry = srs_trace.QTreeWidgetItem([item.get("id")])
        entry.setData(0, srs_trace.UUID_ROLE, item.uuid)
        return entry
    rows = {e.uuid: row(e) for e in (c1, c2, other)}
    dialog.click(rows[c2.uuid], srs_trace.PARENT)  # the same section: added
    dialog.click(rows[other.uuid], srs_trace.PARENT)  # of another section: refused, said why and what to do
    assert dialog.selected == [c1.uuid, c2.uuid]
    assert told and "3.12.1.1" in told[0] and "sezione 3.12.1" in told[0] and "sezione 3.11.6" in told[0]
    assert "ADR separate" in told[0]
    dialog.click(rows[c1.uuid], srs_trace.PARENT)
    dialog.click(rows[c2.uuid], srs_trace.PARENT)
    dialog.click(rows[other.uuid], srs_trace.PARENT)  # nothing chosen any more: any domain
    assert dialog.selected == [other.uuid] and len(told) == 1
    p.close()


def test_the_proposer_member_is_chosen_among_the_members_of_the_proposing_team(app, tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    t1 = p.new_element("team", id="T1", name="Odometria", members=[{"name": "Anna Bianchi"}, {"name": "Luca Neri"}])
    t2 = p.new_element("team", id="T2", name="Fondazione", members=[{"name": "Marta Verdi"}])
    adr = p.new_element("adr", title="Una decisione", adr_type=ADR_WAIVER, status="Proposta")
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    team, member = editor.widgets["proposer"], editor.widgets["proposer_member"]
    names = list(editor.widgets)
    assert names.index("proposer_member") == names.index("proposer") + 1
    assert [member.itemText(i) for i in range(member.count())] == [""]  # no team yet
    team.setCurrentIndex(team.findData(t1.uuid))
    assert [member.itemText(i) for i in range(member.count())] == ["", "Anna Bianchi", "Luca Neri"]
    member.setCurrentIndex(member.findData("Luca Neri"))
    editor.save_changes()
    assert adr.get("proposer") == t1.uuid and adr.get("proposer_member") == "Luca Neri"
    editor.edit(p, adr, editing=True)
    team, member = editor.widgets["proposer"], editor.widgets["proposer_member"]
    team.setCurrentIndex(team.findData(t2.uuid))  # another team: its members, the one chosen kept and flagged
    assert [member.itemText(i) for i in range(member.count())] == ["", "Marta Verdi",
                                                                   "Luca Neri (non è tra i membri del team)"]
    p.close()


def test_the_decision_of_the_da_is_changed_only_by_its_members(app, tmp_path):
    from arcadia_tool.model.teams import edit_denied

    p = Project.create(tmp_path / "p", "Prova")
    p.new_element("team", id="T0", name="Design Authority", design_authority=True,
                  members=[{"name": "Dora Rossi", "account": "0" * 32}])
    reason = edit_denied(p.model, None, "adr", "da_decision")
    assert reason and "decidere sulle ADR" in reason
    assert edit_denied(p.model, None, "adr", "da_notes") and edit_denied(p.model, None, "adr", "realloc_reason") is None
    p.close()


def test_the_sheets_of_domains_and_functions_list_their_adr_and_create_one(app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from arcadia_tool.checks.context import Context
    from arcadia_tool.checks.sa import sa2_new_without_adr
    from arcadia_tool.model.adr import outcome, related_adrs
    from arcadia_tool.model.schema import ADR_DELETE_DOMAIN
    import arcadia_tool.ui.adr_types as adr_types
    from arcadia_tool.ui.main_window import MainWindow

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", id="DF01", name="Protezione")
    d2 = p.new_element("domain", id="DF02", name="Localizzazione")
    sf = p.new_element("system_function", name="Proteggere dal Roll Away", domain=d1.uuid, is_new=True,
                       status="Approvata")
    section = p.new_element("requirement", id="3.11.6", item_type="Sezione", primary_domain=d1.uuid)
    clause = p.new_element("requirement", id="3.11.6.3", item_type="Requisito", parent=section.uuid)
    delete = p.new_element("adr", title="Eliminare DF01", adr_type=ADR_DELETE_DOMAIN, status="Proposta",
                           deleted_domain=d1.uuid)  # names the domain
    realloc = p.new_element("adr", title="Spostare 3.11.6.3", adr_type=ADR_SECTION, status="Decisa",
                            realloc_item=[clause.uuid], primary_proposed=d2.uuid)  # its domain read from the clause
    move = p.new_element("adr", title="Spostare la funzione", adr_type=ADR_FUNCTION, status="Revisionato DA",
                         function=sf.uuid, to_domain=d2.uuid, da_decision="Respinta")
    old = p.new_element("adr", title="Collegata a mano", adr_type=ADR_OTHER, status="Superata")
    d1.set("adrs", [old.uuid])  # «Decisioni collegate» of earlier versions
    p.update(d1)
    p.new_element("adr", title="Di un altro dominio", adr_type=ADR_DELETE_DOMAIN, status="Proposta",
                  deleted_domain=d2.uuid)
    # By outcome: attive, approvate, respinte, superate.
    assert [(a.get("title"), outcome(a)) for a in related_adrs(p.model, d1)] == [
        ("Eliminare DF01", "Attiva"), ("Spostare 3.11.6.3", "Approvata"), ("Spostare la funzione", "Respinta"),
        ("Collegata a mano", "Superata")]
    assert [a.uuid for a in related_adrs(p.model, sf)] == [move.uuid]
    from arcadia_tool.model.element import Element
    from arcadia_tool.model.schema import DA_DECISIONS
    from arcadia_tool.ui.theme import status_colors
    assert DA_DECISIONS[0] == "Commenti DA" and status_colors("Commenti DA")[0] == "#92400E"
    assert outcome(Element("adr", values={"status": "Revisionato DA", "da_decision": "Commenti DA"})) == "Attiva"
    assert {a.uuid for a in related_adrs(p.model, d2)} >= {realloc.uuid, move.uuid}  # the domain proposed
    assert not list(sa2_new_without_adr(Context(p.model)))  # the function has its ADR (the move)

    window = MainWindow()
    window._set_project(p)
    window._select(d1)
    editor = window.editor
    assert "adrs" not in editor.widgets and "related_adrs" in editor.widgets  # a table instead of the links
    table = editor.adrs_table
    assert [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())] == [
        "Esito", "ID", "Titolo", "Tipo", "Stato", "Decisione DA"]
    assert [table.item(r, 2).text() for r in range(table.rowCount())] == [
        "Eliminare DF01", "Spostare 3.11.6.3", "Spostare la funzione", "Collegata a mano"]
    assert table.item(2, 5).text() == "Respinta" and "1 attiva" in editor.adrs_empty.text()
    opened = []
    editor.open_requested.disconnect()
    editor.open_requested.connect(opened.append)
    table.cellDoubleClicked.emit(1, 0)
    assert opened == [realloc.uuid]

    def choose(dialog):  # the type of the new ADR: the one suggested for a domain first
        assert dialog.adr_type is None
        dialog.adr_type = ADR_OTHER
        return True
    monkeypatch.setattr(adr_types.AdrTypeDialog, "exec", choose)
    assert editor.adrs_new.isEnabled()
    editor.adrs_new.click()
    new = next(a for a in p.model.of_kind("adr") if a.get("title") is None and a.get("adr_type") == ADR_OTHER)
    assert new.get("concerns") == [d1.uuid] and window.editors[new.uuid].editing  # created about it, opened
    window._select(d1)
    assert new.uuid in [window.editor.adrs_table.item(r, 1).data(Qt.UserRole)
                        for r in range(window.editor.adrs_table.rowCount())]
    window._select(sf)
    assert [window.editor.adrs_table.item(r, 2).text() for r in range(window.editor.adrs_table.rowCount())] == [
        "Spostare la funzione"]
    window._set_project(None)
    window.close()


def test_an_adr_with_one_item_to_reallocate_is_migrated_to_a_list(tmp_path):
    from arcadia_tool.model.adr import item_primary

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    item = p.new_element("requirement", id="3.11.6.3", item_type="Requisito", primary_domain=d1.uuid)
    adr = p.new_element("adr", title="Spostare", adr_type=ADR_SECTION, status="Proposta")
    adr.values["realloc_item"] = item.uuid  # as written by earlier versions: one item
    assert item_primary(p.model, adr) == d1.uuid  # read also so
    p._migrate()
    assert adr.get("realloc_item") == [item.uuid] and adr.uuid in p.pending()  # saved with the next save
    p.close()


def test_the_move_of_a_function_shows_its_domain_now_and_the_one_proposed(app, tmp_path):
    from arcadia_tool.model.adr import common_fields

    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", name="Protezione")
    d2 = p.new_element("domain", name="Localizzazione")
    sf = p.new_element("system_function", name="Determinare la velocità", domain=d1.uuid)
    assert [f.name for f in type_fields(ADR_FUNCTION)] == ["function", "function_domain", "to_domain",
                                                           "move_reason"]
    assert [f.name for f in common_fields(ADR_FUNCTION)] == ["da_decision", "da_notes"]
    adr = p.new_element("adr", title="Spostare la velocità", **adr_defaults(p.model, ADR_FUNCTION, sf))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE",
                                                     "DETTAGLI: SPOSTAMENTO DI UNA FUNZIONE TRA DOMINI", "DECISIONE DELLA DA"]
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
    assert [f.name for f in common_fields(ADR_OWNER)] == ["da_decision", "da_notes"]
    adr = p.new_element("adr", title="Chi produce la velocità", **adr_defaults(p.model, ADR_OWNER, ei))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE",
                                                     "DETTAGLI: PROPRIETÀ DI UN'INFORMAZIONE / CONFINE TRA DOMINI", "DECISIONE DELLA DA"]
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
    assert [f.name for f in common_fields(ADR_IMPLEMENTATION)] == ["da_decision", "da_notes"]
    assert srs_trace.ITEM_DIALOGS["impl_item"] is srs_trace.TraceImplItemDialog  # chosen with ticks
    values = adr_defaults(p.model, ADR_IMPLEMENTATION, clause)
    assert values == {"adr_type": ADR_IMPLEMENTATION, "status": "Proposta", "impl_item": clause.uuid}
    adr = p.new_element("adr", title="Frenatura", **values)
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE",
                                                     "DETTAGLI: SCELTA LASCIATA ALL'IMPLEMENTAZIONE", "DECISIONE DELLA DA"]
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
    assert [f.name for f in common_fields(ADR_PRODUCT_OPTION)] == ["da_decision", "da_notes"]
    adr = p.new_element("adr", title="Modo LS", **adr_defaults(p.model, ADR_PRODUCT_OPTION, sf))
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    assert [c.upper() for c in captions(editor)] == ["IDENTIFICAZIONE", "DETTAGLI: OPZIONE DI PRODOTTO", "DECISIONE DELLA DA"]
    assert editor.widgets["function_domain"].text() == p.model.label(d1)
    p.close()
