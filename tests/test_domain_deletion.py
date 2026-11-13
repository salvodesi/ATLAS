"""The ADR of the deletion of a functional domain: approved by the Design Authority, the domain is removed from the
model; the elements left orphan are shown, and each passes to another domain, stays without, or is deleted, as the
Design Authority chooses."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMessageBox

from arcadia_tool.model.adr import can_approve
from arcadia_tool.model.domain_deletion import (DELETE, KEEP, approve_domain_deletion, deletable, deletion_problems,
                                                orphans, second_references)
from arcadia_tool.model.schema import ADR_DELETE_DOMAIN
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="RFI")
    gone, kept = (p.new_element("domain", name=n) for n in ("Radio", "Odometria"))
    for d in (gone, kept):
        previous = d.copy()
        d.set("team", team.uuid)
        p.update(d, previous)  # the team lists them
    section = p.new_element("requirement", id="3.5.1", item_type="Sezione", primary_domain=gone.uuid,
                            contributing_domains=[kept.uuid])
    clause = p.new_element("requirement", id="3.5.1.1", item_type="Requisito", parent=section.uuid)
    other = p.new_element("requirement", id="3.6.1", item_type="Sezione", primary_domain=kept.uuid,
                          contributing_domains=[gone.uuid], excluded_domains=[gone.uuid])
    free = p.new_element("system_function", name="Gestire la radio", domain=gone.uuid)
    used = p.new_element("system_function", name="Inviare messaggi", domain=gone.uuid)
    target = p.new_element("system_function", name="Ricevere messaggi", domain=kept.uuid)
    p.new_element("functional_exchange", name="Messaggio", source=used.uuid, target=target.uuid)
    derived = p.new_element("derived_requirement", id="3.5.1.1-D1", obligation="Una", domain=gone.uuid,
                            parent=clause.uuid)
    chain = p.new_element("functional_chain", name="Sessione radio", responsible_domain=gone.uuid)
    adr = p.new_element("adr", title="Eliminare la radio", adr_type=ADR_DELETE_DOMAIN, status="Proposta",
                        deleted_domain=gone.uuid)
    p.save()
    return p, dict(team=team, gone=gone, kept=kept, section=section, clause=clause, other=other, free=free,
                   used=used, derived=derived, chain=chain, adr=adr)


def test_the_orphans_and_what_can_be_deleted(tmp_path):
    p, e = build(tmp_path)
    groups = {g.kind: [x.uuid for x in elements] for g, elements in orphans(p.model, e["gone"].uuid)}
    assert groups == {"requirement": [e["section"].uuid], "system_function": [e["free"].uuid, e["used"].uuid],
                      "derived_requirement": [e["derived"].uuid], "functional_chain": [e["chain"].uuid]}
    assert deletable(p.model, e["free"], e["gone"].uuid) and deletable(p.model, e["derived"], e["gone"].uuid)
    assert not deletable(p.model, e["used"], e["gone"].uuid)  # an exchange uses it
    assert not deletable(p.model, e["section"], e["gone"].uuid)  # SRS items are never deleted
    assert {x.uuid for x in second_references(p.model, e["gone"].uuid)} == {e["other"].uuid, e["team"].uuid}
    assert can_approve(e["adr"]) and deletion_problems(p.model, e["adr"]) == []
    empty = p.new_element("adr", adr_type=ADR_DELETE_DOMAIN, status="Proposta")
    assert deletion_problems(p.model, empty) == ["Manca il dominio da eliminare."]


def test_the_approval_removes_the_domain_as_chosen(tmp_path):
    p, e = build(tmp_path)
    gone, kept = e["gone"].uuid, e["kept"].uuid
    choices = {e["section"].uuid: kept, e["free"].uuid: DELETE, e["used"].uuid: DELETE,  # not deletable: kept
               e["derived"].uuid: kept, e["chain"].uuid: KEEP}
    changed, deleted = approve_domain_deletion(p, e["adr"], choices)
    assert p.model.get(gone) is None and set(deleted) == {gone, e["free"].uuid}
    assert e["section"].get("primary_domain") == kept and not e["section"].get("contributing_domains")
    assert e["used"].get("domain") is None and p.model.get(e["used"].uuid) is not None
    assert e["derived"].get("domain") == kept and e["chain"].get("responsible_domain") is None
    assert not e["other"].get("contributing_domains") and not e["other"].get("excluded_domains")
    assert e["team"].get("domains") == [kept]
    adr = e["adr"]
    assert adr.get("status") == "Decisa" and adr.get("da_decision") == "Accolta" and adr.get("decision_date")
    assert adr.get("deleted_domain_label") == "DF01 Radio" and not can_approve(adr)
    assert {x.uuid for x in changed} >= {e["section"].uuid, e["used"].uuid, e["other"].uuid, e["team"].uuid}
    p.save()
    p.close()
    p = Project.open(p.path)  # also on disk
    assert p.model.get(gone) is None and p.model.get(e["free"].uuid) is None
    assert p.model.get(e["section"].uuid).get("primary_domain") == kept
    p.close()


def test_the_sheet_shows_the_orphans_and_approves_the_deletion(app, tmp_path, monkeypatch):
    from arcadia_tool.ui.domain_deletion import DomainDeletionDialog

    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.approver = lambda: "Anna"
    editor.edit(p, e["adr"])
    assert editor.approve_button.text() == "Approva ed elimina il dominio"
    frame = editor.findChild(QFrame, "domainOrphans")
    text = " ".join(label.text() for label in frame.findChildren(QLabel))
    assert "Funzioni di sistema (2)" in text and f"<a href='{e['section'].uuid}'>3.5.1</a>" in text
    assert "Functional chain di cui è responsabile (1)" in text

    seen = []

    def run(dialog):  # the section to Odometria for the whole group; the free function deleted
        seen.append(dialog)
        combo = dialog.combos[e["free"].uuid]
        combo.setCurrentIndex(combo.findData(DELETE))
        assert dialog.combos[e["used"].uuid].findData(DELETE) < 0  # used by an exchange: not to delete
        return True
    monkeypatch.setattr(DomainDeletionDialog, "exec", run)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.append(a[2]))
    editor.approve()
    assert p.model.get(e["gone"].uuid) is None and p.model.get(e["free"].uuid) is None
    assert e["section"].get("primary_domain") is None  # left without, as chosen at first
    assert "il dominio DF01 Radio è stato eliminato; eliminato anche 1 elemento orfano; 1 dominio successivo "            "rinumerato" in seen[-1]
    assert e["kept"].get("id") == "DF01"  # the following domain moved down
    editor = ElementEditor()
    editor.edit(p, e["adr"])  # decided: no more orphans to show, the name of the domain kept
    assert editor.findChild(QFrame, "domainOrphans") is None
    assert editor.widgets["deleted_domain_label"].text() == "DF01 Radio"
    p.close()


def test_the_choice_for_a_whole_group(app, tmp_path):
    from arcadia_tool.ui.domain_deletion import DomainDeletionDialog

    p, e = build(tmp_path)
    dialog = DomainDeletionDialog(p, e["gone"])
    assert set(dialog.choices) == {e[k].uuid for k in ("section", "free", "used", "derived", "chain")}
    assert set(dialog.choices.values()) == {None}  # each to be chosen
    assert not dialog.ok.isEnabled()
    top = dialog.tree.topLevelItem(1)  # the system functions
    assert top.text(0) == "Funzioni di sistema (2)"
    all_combo = dialog.tree.itemWidget(top, 1)
    all_combo.setCurrentIndex(all_combo.findData(DELETE))
    all_combo.activated.emit(all_combo.currentIndex())
    assert dialog.choices[e["free"].uuid] == DELETE and dialog.choices[e["used"].uuid] == KEEP
    all_combo.setCurrentIndex(all_combo.findData(e["kept"].uuid))
    all_combo.activated.emit(all_combo.currentIndex())
    assert dialog.choices[e["free"].uuid] == dialog.choices[e["used"].uuid] == e["kept"].uuid
    p.close()
