"""The ADR «Assegnazione di requisito derivato»: derived requirements (SA-4) assigned to a functional domain; the Design
Authority approves it with a button that assigns them for good (their domain no longer follows their function)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from arcadia_tool.model.adr import (adr_defaults, approve_derived, can_approve, derived_domains_current,
                                    derived_problems, impacted_domains, proposed_title, suggested_type, type_fields)
from arcadia_tool.model.element import Element
from arcadia_tool.model.schema import ADR_AREAS, ADR_DERIVED, ADR_TYPE_LABELS
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    d1, d2 = p.new_element("domain", name="Odometria"), p.new_element("domain", name="Radio")
    clause = p.new_element("requirement", id="3.4.1.3", item_type="Requisito", text="Una clausola")
    sf = p.new_element("system_function", name="Stimare la velocità", domain=d1.uuid)
    derived = p.new_element("derived_requirement", parent=clause.uuid, obligation="Stima la velocità.",
                            system_function=[sf.uuid])
    other = p.new_element("derived_requirement", parent=clause.uuid, obligation="Segnala l'errore.")
    return p, dict(d1=d1, d2=d2, sf=sf, derived=derived, other=other)


def test_the_type_and_its_fields(tmp_path):
    assert ADR_DERIVED in ADR_TYPE_LABELS and ADR_DERIVED in dict(ADR_AREAS)["Voci SRS, funzioni e scambi (SA)"]
    assert [f.name for f in type_fields(ADR_DERIVED)] == ["derived_items", "derived_domains_current",
                                                         "derived_domain_proposed", "derived_reason"]
    p, e = build(tmp_path)
    assert e["derived"].get("domain") == e["d1"].uuid  # from its system function
    assert suggested_type(e["derived"]) == ADR_DERIVED
    values = adr_defaults(p.model, ADR_DERIVED, e["derived"])
    assert values["derived_items"] == [e["derived"].uuid]
    probe = Element("adr", values={**values, "derived_domain_proposed": e["d2"].uuid})
    d1, d2, ident = e["d1"].get("id"), e["d2"].get("id"), e["derived"].get("id")
    assert proposed_title(p.model, probe) == f"Assegnazione del requisito derivato {ident} a {d2}"
    assert derived_domains_current(p.model, probe) == [e["d1"].uuid]
    assert [d.uuid for d in impacted_domains(p.model, probe)] == [e["d1"].uuid, e["d2"].uuid]  # both told
    assert proposed_title(p.model, Element("adr", values={"adr_type": ADR_DERIVED})) == \
        "Assegnazione di requisiti derivati"
    assert d1


def test_the_design_authority_assigns_them_for_good(tmp_path):
    p, e = build(tmp_path)
    adr = p.new_element("adr", adr_type=ADR_DERIVED, status="Proposta", id="ADR-001",
                        derived_items=[e["derived"].uuid, e["other"].uuid])
    assert can_approve(adr)
    assert derived_problems(p.model, adr) == ["Manca il dominio proposto."]
    with pytest.raises(ValueError):
        approve_derived(p, adr)
    adr.set("derived_domain_proposed", e["d2"].uuid)
    changed = approve_derived(p, adr)
    assert {c.uuid for c in changed} >= {e["derived"].uuid, e["other"].uuid}
    assert e["derived"].get("domain") == e["d2"].uuid and e["other"].get("domain") == e["d2"].uuid
    assert e["derived"].get("domain_adr") == adr.uuid
    assert adr.get("status") == "Decisa" and adr.get("da_decision") == "Accolta" and adr.get("decision_date")
    assert not can_approve(adr)
    assert derived_domains_current(p.model, adr) == [e["d1"].uuid]  # as they were: the ADR does not change
    previous = e["sf"].copy()
    e["sf"].set("name", "Stimare la velocità del treno")  # its function changes: the domain assigned stays
    p.update(e["sf"], previous)
    assert e["derived"].get("domain") == e["d2"].uuid


def test_the_sheet_has_the_button_of_the_design_authority(app, tmp_path, monkeypatch):
    p, e = build(tmp_path)
    adr = p.new_element("adr", adr_type=ADR_DERIVED, status="Proposta", id="ADR-001",
                        derived_items=[e["derived"].uuid], derived_domain_proposed=e["d2"].uuid)
    editor = ElementEditor()
    editor.approver = lambda: True  # the Design Authority
    editor.edit(p, adr)
    assert editor.approve_button.text() == "Approva e assegna il dominio"
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    editor.approve_button.click()
    assert asked and f"{e['derived'].get('id')}: {e['d1'].get('id')} → {e['d2'].get('id')}" in asked[0]
    assert e["derived"].get("domain") == e["d2"].uuid and adr.get("status") == "Decisa"
    editor.deleteLater()


def test_the_current_domain_is_the_one_of_the_section_of_the_parent_item(tmp_path):
    p, e = build(tmp_path)
    d3 = p.new_element("domain", name="Freni")
    section = p.new_element("requirement", id="5.20.2", item_type="Sezione", primary_domain=e["d1"].uuid)
    clause = p.new_element("requirement", id="5.20.2.2", item_type="Requisito", parent=section.uuid, text="Clausola")
    sf = p.new_element("system_function", name="Frenare", domain=d3.uuid)
    derived = p.new_element("derived_requirement", parent=clause.uuid, obligation="Frena.", system_function=[sf.uuid])
    lone = p.new_element("derived_requirement", obligation="Senza voce madre.")  # no parent: none
    adr = p.new_element("adr", adr_type=ADR_DERIVED, status="Proposta", derived_items=[derived.uuid, lone.uuid],
                        derived_domain_proposed=e["d2"].uuid)
    assert derived.get("domain") == d3.uuid  # from its function
    assert derived_domains_current(p.model, adr) == [e["d1"].uuid]  # from the section of 5.20.2.2, not the function
    from arcadia_tool.model.adr import derived_preview
    assert derived_preview(p.model, adr) == [(derived, e["d1"].uuid), (lone, None)]
    clause.set("primary_domain", e["d2"].uuid)  # the clause reallocated on its own: its own domain
    p.update(clause)
    assert derived_domains_current(p.model, adr) == [e["d2"].uuid]


def test_the_tab_of_all_the_clauses_shows_also_the_derived_requirements(app, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QCheckBox, QListWidget

    p, e = build(tmp_path)
    section = p.new_element("requirement", id="3.4.2", item_type="Sezione", primary_domain=e["d1"].uuid)
    c1 = p.new_element("requirement", id="3.4.2.1", item_type="Requisito", parent=section.uuid, text="Uno")
    c2 = p.new_element("requirement", id="3.4.2.2", item_type="Requisito", parent=section.uuid, text="Due")
    point = p.new_element("requirement", id="3.4.2.1 a)", item_type="Voce", parent=c1.uuid, text="Punto")
    under = p.new_element("derived_requirement", parent=point.uuid, obligation="Dal punto.", domain=e["d1"].uuid)
    elsewhere = e["derived"]  # derived from 3.4.1.3, a clause of no section of DF01, of DF01 by its function
    ElementEditor.SHOW_DERIVED = False
    editor = ElementEditor()
    editor.edit(p, e["d1"])  # read-only: the tick still works
    view = editor.widget().findChild(QListWidget, "srsAll")
    box = editor.widget().findChild(QCheckBox, "showDerived")
    rows = lambda: [view.item(i).data(Qt.UserRole) for i in range(view.count())]
    assert rows() == [c1.uuid, c2.uuid] and not box.isChecked() and box.text().endswith("(2)")
    box.setChecked(True)
    assert rows() == [c1.uuid, under.uuid, c2.uuid, elsewhere.uuid]  # under its clause; the others at the end
    assert ElementEditor.SHOW_DERIVED  # remembered
    box.setChecked(False)
    assert rows() == [c1.uuid, c2.uuid]
    ElementEditor.SHOW_DERIVED = False
    editor.deleteLater()


def test_a_derived_requirement_belongs_to_the_domain_of_its_clause_unless_an_adr_assigned_it(app, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QCheckBox, QListWidget
    from arcadia_tool.model.adr import derived_owner_domain

    p, e = build(tmp_path)
    section = p.new_element("requirement", id="5.20.2", item_type="Sezione", primary_domain=e["d2"].uuid)
    clause = p.new_element("requirement", id="5.20.2.2", item_type="Requisito", parent=section.uuid, text="Clausola")
    d1_, d2_ = (p.new_element("derived_requirement", parent=clause.uuid, obligation=o) for o in ("Uno.", "Due."))
    assert not d1_.get("domain") and not d2_.get("domain")  # mapped on no function, assigned by no ADR
    assert derived_owner_domain(p.model, d1_) == e["d2"].uuid  # the domain of its clause

    def shown(domain):
        editor = ElementEditor()
        editor.edit(p, domain)
        box = editor.widget().findChild(QCheckBox, "showDerived")
        box.setChecked(True)
        view = editor.widget().findChild(QListWidget, "srsAll")
        rows = [view.item(i).data(Qt.UserRole) for i in range(view.count())]
        box.setChecked(False)
        editor.deleteLater()
        return box.text(), rows
    text, rows = shown(e["d2"])
    assert text.endswith("(2)") and rows == [clause.uuid, d1_.uuid, d2_.uuid]  # under their clause
    adr = p.new_element("adr", adr_type=ADR_DERIVED, status="Proposta", derived_items=[d2_.uuid],
                        derived_domain_proposed=e["d1"].uuid)
    approve_derived(p, adr)  # assigned to DF01 by the Design Authority
    assert derived_owner_domain(p.model, d2_) == e["d1"].uuid
    assert shown(e["d2"])[1] == [clause.uuid, d1_.uuid]
    assert d2_.uuid in shown(e["d1"])[1]
