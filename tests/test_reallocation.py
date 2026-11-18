"""The approval of a reallocation (X-1): the section or the clause passes to the proposed domain, also a clause whose
section the domain does not have (an exception, known to the check A4-04 and shown in the sheets of the domains)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QMessageBox

from arcadia_tool.checks import run
from arcadia_tool.checks.config import ChecksConfig, Profile
from arcadia_tool.model.adr import (approve_reallocation, can_approve, principal_of, reallocation_pending,
                                    reallocation_preview, reallocation_problems)
from arcadia_tool.model.schema import ADR_SECTION
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor
from arcadia_tool.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    df1, df4, df7 = (p.new_element("domain", name=n) for n in ("Uno", "Quattro", "Sette"))
    section = p.new_element("requirement", id="3.8.1", item_type="Sezione", primary_domain=df1.uuid,
                            contributing_domains=[df7.uuid])
    clause = p.new_element("requirement", id="3.8.1.4", item_type="Requisito", parent=section.uuid, text="Una clausola")
    item = p.new_element("requirement", id="3.8.1.4 a)", item_type="Voce", parent=clause.uuid, text="Un punto")
    other = p.new_element("requirement", id="3.8.1.5", item_type="Requisito", parent=section.uuid, text="Un'altra")
    return p, dict(df1=df1, df4=df4, df7=df7, section=section, clause=clause, item=item, other=other)


def adr(p, items, primary=None, **values):
    return p.new_element("adr", title="Spostamento", adr_type=ADR_SECTION, status="Proposta",
                         realloc_item=[i.uuid for i in items], primary_proposed=primary.uuid if primary else None,
                         **values)


def findings(p, code):
    config = ChecksConfig({"Predefinito": Profile([code], {})})
    return [f for f in run(p.model, config) if f.code == code]


def test_a_clause_passes_to_a_domain_without_its_section(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"], e["item"]], e["df4"])  # with its list item, which follows it
    assert can_approve(decision)
    changed = approve_reallocation(p, decision)
    assert [c.uuid for c in changed] == [e["clause"].uuid]
    assert e["clause"].get("primary_domain") == e["df4"].uuid and not e["item"].get("primary_domain")
    assert principal_of(p.model, e["item"]) == e["df4"].uuid
    assert e["section"].get("primary_domain") == e["df1"].uuid  # the section does not change
    assert principal_of(p.model, e["other"]) == e["df1"].uuid
    assert decision.get("status") == "Decisa" and decision.get("da_decision") == "Accolta"
    assert decision.get("decision_date") and not can_approve(decision)


def test_a_section_passes_with_its_clauses_but_not_with_the_exceptions(tmp_path):
    p, e = build(tmp_path)
    approve_reallocation(p, adr(p, [e["clause"]], e["df4"]))
    function = p.new_element("system_function", name="Vecchia", domain=e["df1"].uuid, sections=[e["other"].uuid])
    decision = adr(p, [e["section"]], e["df7"])
    moved, kept, functions = reallocation_preview(p.model, decision)
    assert moved == [(e["section"], e["df1"].uuid)] and kept == [e["clause"]] and functions == [function]
    approve_reallocation(p, decision)
    assert e["section"].get("primary_domain") == e["df7"].uuid
    assert not e["section"].get("contributing_domains")  # the new principal, and none proposed
    assert principal_of(p.model, e["other"]) == e["df7"].uuid
    assert e["clause"].get("primary_domain") == e["df4"].uuid  # the earlier decision stands


def test_every_clause_chosen_passes_also_one_inside_another(tmp_path):
    p, e = build(tmp_path)
    sub = p.new_element("requirement", id="3.8.1.4.1", item_type="Requisito", parent=e["clause"].uuid, text="Sotto")
    decision = adr(p, [e["clause"], sub, e["other"], e["item"]], e["df4"])
    moved, _kept, _functions = reallocation_preview(p.model, decision)
    assert [m.get("id") for m, _ in moved] == ["3.8.1.4", "3.8.1.4.1", "3.8.1.5"]  # the list item follows its clause
    approve_reallocation(p, decision)
    assert all(c.get("primary_domain") == e["df4"].uuid for c in (e["clause"], sub, e["other"]))
    assert not e["item"].get("primary_domain")
    from arcadia_tool.ui.srs_trace import received_items
    assert [c.get("id") for c in received_items(p.model, e["df4"])] == ["3.8.1.4", "3.8.1.4.1", "3.8.1.5"]


def test_the_clauses_chosen_with_their_section_follow_it(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["section"], e["clause"], e["other"]], e["df4"])
    approve_reallocation(p, decision)
    assert e["section"].get("primary_domain") == e["df4"].uuid
    assert not e["clause"].get("primary_domain") and not e["other"].get("primary_domain")
    assert principal_of(p.model, e["other"]) == e["df4"].uuid


def test_open_adrs_read_the_principal_domain_after_a_section_moves(tmp_path):
    from arcadia_tool.model.adr import item_primary, shared_primary, unmapped_section_domains
    from arcadia_tool.model.schema import ADR_SHARED, ADR_UNMAPPED

    p, e = build(tmp_path)
    realloc = adr(p, [e["clause"]], e["df7"])
    sharing = p.new_element("adr", adr_type=ADR_SHARED, status="Proposta", shared_items=[e["other"].uuid])
    unmapped = p.new_element("adr", adr_type=ADR_UNMAPPED, status="Proposta", unmapped_items=[e["other"].uuid])
    assert item_primary(p.model, realloc) == shared_primary(p.model, sharing) == e["df1"].uuid
    approve_reallocation(p, adr(p, [e["section"]], e["df4"]))  # the whole section to another domain
    assert item_primary(p.model, realloc) == shared_primary(p.model, sharing) == e["df4"].uuid
    assert unmapped_section_domains(p.model, unmapped) == [e["df4"].uuid]


def test_a_clause_of_a_domain_of_another_team_asks_if_the_choice_is_right(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import srs_trace

    p, e = build(tmp_path)
    own, other = p.new_element("team", name="RFI"), p.new_element("team", name="FBK")
    e["df1"].set("team", other.uuid)  # the section 3.8.1 is of DF01, of the other team
    e["df4"].set("team", own.uuid)
    mine = p.new_element("requirement", id="3.9.1", item_type="Sezione", primary_domain=e["df4"].uuid)
    asked = []
    answer = [QMessageBox.No]
    monkeypatch.setattr(srs_trace.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or answer[0])

    def row(item):
        entry = srs_trace.QTreeWidgetItem([item.get("id")])
        entry.setData(0, srs_trace.UUID_ROLE, item.uuid)
        return entry
    decision = adr(p, [], proposer=own.uuid)
    dialog = srs_trace.TraceReallocItemsDialog(p, decision.copy(), "realloc_item")
    dialog.click(row(e["clause"]), srs_trace.PARENT)  # answered no: not chosen
    assert dialog.selected == [] and len(asked) == 1
    assert "nella sezione 3.8.1" in asked[0] and "DF01" in asked[0] and "FBK:" in asked[0] and "RFI)" in asked[0]
    answer[0] = QMessageBox.Yes
    dialog.click(row(e["clause"]), srs_trace.PARENT)  # answered yes: chosen
    assert dialog.selected == [e["clause"].uuid] and len(asked) == 2
    dialog.click(row(e["clause"]), srs_trace.PARENT)  # untick: nothing asked
    assert dialog.selected == [] and len(asked) == 2
    dialog.click(row(mine), srs_trace.PARENT)  # of the team proposing: nothing asked
    assert dialog.selected == [mine.uuid] and len(asked) == 2
    unproposed = srs_trace.TraceReallocItemsDialog(p, adr(p, []).copy(), "realloc_item")
    unproposed.click(row(e["other"]), srs_trace.PARENT)  # no team proposing it: nothing to compare
    assert unproposed.selected == [e["other"].uuid] and len(asked) == 2


def test_the_proposed_contributors_are_written(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"]], e["df4"], contributors_proposed=[e["df7"].uuid, e["df4"].uuid])
    approve_reallocation(p, decision)
    assert e["clause"].get("contributing_domains") == [e["df7"].uuid]


def test_what_cannot_be_approved(tmp_path):
    p, e = build(tmp_path)
    assert any("dominio principale proposto" in t for t in reallocation_problems(p.model, adr(p, [e["clause"]])))
    assert not can_approve(adr(p, [e["clause"]], e["df4"], da_decision="Respinta"))
    excluded = e["other"]
    excluded.set("excluded_domains", [e["df4"].uuid])
    assert any("esclusa" in t for t in reallocation_problems(p.model, adr(p, [excluded], e["df4"])))


def test_the_check_knows_the_decided_exceptions(tmp_path):
    p, e = build(tmp_path)
    e["clause"].set("primary_domain", e["df4"].uuid)
    p.update(e["clause"])
    assert "Manca un'ADR" in findings(p, "A4-04")[0].message
    decision = adr(p, [e["clause"]], e["df4"], id="ADR-001")
    assert "ADR-001" in findings(p, "A4-04")[0].message  # still to decide
    approve_reallocation(p, decision)
    assert not findings(p, "A4-04")


def test_a_decision_not_applied_is_found_and_applied(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"]], e["df4"])
    decision.set("status", "Decisa")  # by hand, or by an earlier version
    p.update(decision)
    assert reallocation_pending(p.model, decision) == [e["clause"]] and findings(p, "A4-10")
    approve_reallocation(p, decision)
    assert not reallocation_pending(p.model, decision) and not findings(p, "A4-10")
    # Moved again by a later decision: the first one is not «not applied».
    approve_reallocation(p, adr(p, [e["clause"]], e["df7"]))
    assert not reallocation_pending(p.model, decision)


def test_the_sheets_show_the_approval_and_the_clauses_received_and_ceded(app, tmp_path, monkeypatch):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"]], e["df4"], id="ADR-001")
    editor = ElementEditor()
    editor.approver = lambda: "Anna"
    editor.edit(p, decision)
    assert editor.approve_button.text() == "Approva e sposta le voci"
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    editor.approve()
    assert "3.8.1.4 (da DF01)" in asked[0] and not e["clause"].get("primary_domain")  # shown, then cancelled
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    editor.approve()
    assert e["clause"].get("primary_domain") == e["df4"].uuid
    window = MainWindow()
    window._set_project(p)
    window.tree.select(e["df4"].uuid)
    received = window.editor.findChild(QListWidget, "srsReceived")
    assert received.item(0).data(Qt.UserRole) == e["clause"].uuid and "ADR-001" in received.item(0).text()
    assert window.editor.findChild(QListWidget, "srsPrincipal").count() == 1  # «Nessuna voce»: not the clause
    assert not window.editor.findChild(QListWidget, "srsPrincipal").isEnabled()
    every = window.editor.findChild(QListWidget, "srsAll")  # «Tutte le clausole»: the received one too
    texts = [every.item(i).text() for i in range(every.count())]
    assert texts == [f"{p.model.label(e['clause'])} · ricevuta per ADR-001"]
    opened = []
    window.editor.open_requested.connect(opened.append)
    received.itemClicked.emit(received.item(0))  # a clause with an ADR: a menu, the ADR or the SRS item
    actions = [a for a in window.editor.clause_menu.actions() if a.text()]
    assert actions[0].text().startswith("Apri l'ADR ADR-001") and actions[-1].text().startswith("Vai alla voce")
    actions[0].trigger()
    assert opened == [decision.uuid]
    actions[-1].trigger()  # the SRS list, at the clause
    window.editor.clause_menu.close()  # a popup: not left open for the next tests
    assert window.pages.currentWidget() is window.reader
    window.tree.select(e["df1"].uuid)
    every = window.editor.findChild(QListWidget, "srsAll")  # the ceded one: no longer among those of DF01
    ids = [every.item(i).data(Qt.UserRole) for i in range(every.count())]
    assert e["clause"].uuid not in ids and e["other"].uuid in ids
    ceded = window.editor.findChild(QListWidget, "srsCeded")
    assert ceded.item(0).data(Qt.UserRole) == e["clause"].uuid and "ADR-001" in ceded.item(0).text()
    window.save()
    window._set_project(None)
    window.close()


def test_an_approved_adr_stays_as_it_was(tmp_path):
    from arcadia_tool.model.adr import COMPUTED, impacted_domains, item_contributors, item_primary, related_adrs

    p, e = build(tmp_path)
    decision = adr(p, [e["section"]], e["df4"])
    title, items = decision.get("title"), list(decision.get("realloc_item"))
    assert item_primary(p.model, decision) == e["df1"].uuid
    approve_reallocation(p, decision)
    assert e["section"].get("primary_domain") == e["df4"].uuid  # the section moved, the ADR shows where from
    assert item_primary(p.model, decision) == e["df1"].uuid
    assert item_contributors(p.model, decision) == [e["df7"].uuid]
    assert decision.get("title") == title and decision.get("realloc_item") == items
    assert decision.get("primary_proposed") == e["df4"].uuid
    assert {d.uuid for d in impacted_domains(p.model, decision)} == {e["df1"].uuid, e["df4"].uuid, e["df7"].uuid}
    assert decision in related_adrs(p.model, e["df1"])  # still in the table of the domain of origin
    approve_reallocation(p, adr(p, [e["section"]], e["df7"]))  # moved again later: the first ADR does not follow
    assert COMPUTED["item_primary"](p.model, decision) == e["df1"].uuid
    assert not reallocation_pending(p.model, decision)
    p.save()
    p.close()
    p = Project.open(p.path)  # also when opened again
    assert item_primary(p.model, p.model.get(decision.uuid)) == e["df1"].uuid
    assert item_contributors(p.model, p.model.get(decision.uuid)) == [e["df7"].uuid]



def test_a_whole_section_or_clauses(app, tmp_path):
    from arcadia_tool.model.adr import adr_defaults, realloc_scope, scope_mismatch
    from arcadia_tool.model.schema import KINDS_BY_NAME, SCOPE_CLAUSES, SCOPE_SECTION
    from arcadia_tool.ui import srs_trace

    p, e = build(tmp_path)
    assert adr_defaults(p.model, ADR_SECTION, e["section"])["realloc_scope"] == SCOPE_SECTION
    assert adr_defaults(p.model, ADR_SECTION, e["clause"])["realloc_scope"] == SCOPE_CLAUSES
    # Of an earlier version, without the scope: read from the items.
    assert realloc_scope(p.model, adr(p, [e["section"]])) == SCOPE_SECTION
    assert realloc_scope(p.model, adr(p, [e["section"], e["clause"]])) == SCOPE_SECTION  # its clause follows it
    assert realloc_scope(p.model, adr(p, [e["clause"], e["other"]])) == SCOPE_CLAUSES
    field = KINDS_BY_NAME["adr"].field
    whole = adr(p, [e["section"]], e["df4"], realloc_scope=SCOPE_SECTION)
    assert field("realloc_item").label_for(whole) == "Sezione da riallocare (con le sue clausole)"
    assert field("realloc_reason").label_for(whole) == "Motivazione della riallocazione della sezione"
    clauses = adr(p, [e["clause"]], e["df4"], realloc_scope=SCOPE_CLAUSES)
    assert field("realloc_item").label_for(clauses) == "Clausole da riallocare"
    assert reallocation_problems(p.model, whole) == [] and reallocation_problems(p.model, clauses) == []
    wrong = adr(p, [e["section"]], e["df4"], realloc_scope=SCOPE_CLAUSES)
    assert scope_mismatch(p.model, wrong) == [e["section"]]
    assert any("Oggetto «Clausole»: 3.8.1 è una sezione" in t for t in reallocation_problems(p.model, wrong))
    wrong = adr(p, [e["clause"]], e["df4"], realloc_scope=SCOPE_SECTION)
    assert any("una sola sezione" in t for t in reallocation_problems(p.model, wrong))
    # The window: one section, or clauses and their points.
    dialog = srs_trace.TraceReallocItemsDialog(p, adr(p, [], realloc_scope=SCOPE_SECTION).copy(), "realloc_item")
    assert set(dialog.state) == {e["section"].uuid} and "una sola" in dialog.HINT
    dialog.reject()
    dialog = srs_trace.TraceReallocItemsDialog(p, adr(p, [], realloc_scope=SCOPE_CLAUSES).copy(), "realloc_item")
    assert e["section"].uuid not in dialog.state and {e["clause"].uuid, e["item"].uuid} <= set(dialog.state)
    dialog.reject()
    # The whole section approved: its clauses follow, those with a domain of their own stay.
    e["other"].set("primary_domain", e["df7"].uuid)
    approve_reallocation(p, whole)
    assert principal_of(p.model, e["clause"]) == e["df4"].uuid and principal_of(p.model, e["other"]) == e["df7"].uuid


# --- an approved reallocation reopened ------------------------------------------------------------------------------

def reopen(p, decision, status="In revisione DA"):
    previous = decision.copy()
    decision.set("status", status)
    return p.update(decision, previous)


def test_a_reopened_reallocation_gives_the_clause_back_to_its_section(tmp_path):
    from arcadia_tool.model.adr import outcome, reallocation_revert_preview

    p, e = build(tmp_path)
    decision = adr(p, [e["clause"]], e["df4"], contributors_proposed=[e["df1"].uuid])
    approve_reallocation(p, decision)
    assert e["clause"].get("primary_domain") == e["df4"].uuid
    assert reallocation_revert_preview(p.model, decision) == [(e["clause"], e["df1"].uuid, True)]
    changed = reopen(p, decision)
    assert e["clause"] in changed
    assert not e["clause"].get("primary_domain") and not e["clause"].get("contributing_domains")  # as before
    assert principal_of(p.model, e["clause"]) == e["df1"].uuid
    assert not decision.get("realloc_applied") and not decision.get("realloc_before")
    assert not decision.get("da_decision") and not decision.get("decision_date") and outcome(decision) != "Approvata"
    assert can_approve(decision)  # to approve again
    approve_reallocation(p, decision)
    assert e["clause"].get("primary_domain") == e["df4"].uuid


def test_a_reopened_section_gets_back_its_own_domains(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["section"]], e["df4"])
    approve_reallocation(p, decision)
    reopen(p, decision, "Proposta")
    assert e["section"].get("primary_domain") == e["df1"].uuid
    assert e["section"].get("contributing_domains") == [e["df7"].uuid]


def test_only_the_items_still_as_decided_go_back_and_only_when_reopened(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"], e["other"]], e["df4"])
    approve_reallocation(p, decision)
    later = adr(p, [e["other"]], e["df7"])
    approve_reallocation(p, later)  # another decision moved one of them since
    superseded = decision.copy()
    superseded.set("status", "Superata")
    from arcadia_tool.model.adr import reopened_reallocation
    assert not reopened_reallocation(decision, superseded)  # superseded: not reopened
    reopen(p, decision)
    assert not e["clause"].get("primary_domain")
    assert e["other"].get("primary_domain") == e["df7"].uuid  # left as the later decision set it


def test_an_adr_approved_before_the_domains_were_recorded_is_reverted_too(tmp_path):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"]], e["df4"])
    approve_reallocation(p, decision)
    decision.set("realloc_before", None)  # as approved by an earlier version
    reopen(p, decision)
    assert not e["clause"].get("primary_domain") and principal_of(p.model, e["clause"]) == e["df1"].uuid


def test_the_sheet_asks_before_reopening(app, tmp_path, monkeypatch):
    p, e = build(tmp_path)
    decision = adr(p, [e["clause"]], e["df4"])
    approve_reallocation(p, decision)
    editor = ElementEditor()
    editor.edit(p, decision)
    editor.start_editing()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    editor.draft.set("status", "In revisione DA")
    editor.dirty = True
    assert editor.save_changes() is False and e["clause"].get("primary_domain") == e["df4"].uuid
    assert "3.8.1.4 → DF01 Uno" in asked[0]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    editor.save_changes()
    assert decision.get("status") == "In revisione DA" and not e["clause"].get("primary_domain")
    editor.deleteLater()
