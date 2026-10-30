"""Sections and clauses excluded on purpose by a domain within its principal sections (A4): ticked «Esclusa» in
«Traccia sezioni e clausole SRS…» of its sheet, which opens at once the ADR «Esclusione di sezione o clausola» to
write the reason; the clause is excluded only when the ADR is saved. One ADR can exclude more clauses, added in its
sheet."""
import pytest
from PySide6.QtWidgets import QApplication, QListWidget

from arcadia_tool.storage.project import Project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    t1 = p.new_element("team", id="T1", name="Odometria")
    d1 = p.new_element("domain", id="DF01", name="Protezione", team=t1.uuid)
    d2 = p.new_element("domain", id="DF02", name="Localizzazione")
    s1 = p.new_element("requirement", id="3.11.6", item_type="Sezione", sequence=1, primary_domain=d1.uuid)
    c1 = p.new_element("requirement", id="3.11.6.3", item_type="Requisito", parent=s1.uuid, sequence=2,
                       category=["Bordo"], text="The speed restriction shall be valid.")
    c2 = p.new_element("requirement", id="3.11.6.4", item_type="Requisito", parent=s1.uuid, sequence=3,
                       category=["Bordo"])
    s2 = p.new_element("requirement", id="3.12.1", item_type="Sezione", sequence=4, primary_domain=d2.uuid)
    c3 = p.new_element("requirement", id="3.12.1.1", item_type="Requisito", parent=s2.uuid, sequence=5)
    p.save()
    return p, dict(t1=t1, d1=d1, d2=d2, s1=s1, c1=c1, c2=c2, s2=s2, c3=c3)


REASON = "La validità dei dati è del dominio dei dati di bordo."


def save_the_adr(window):
    """The ADR window: the reason written, «Salva»."""
    editor = window.editor
    editor.widgets["exclusion_reason"].set_markdown(REASON)
    editor._changed()  # as when typed
    editor.save_changes()


def row_of(srs_trace, element):
    row = srs_trace.QTreeWidgetItem([element.get("id")])
    row.setData(0, srs_trace.UUID_ROLE, element.uuid)
    return row


def test_the_tick_opens_the_adr_and_only_its_save_excludes_the_clause(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.model.adr import COMPUTED, impacted_domains
    from arcadia_tool.model.schema import ADR_EXCLUSION

    p, e = build(tmp_path)
    told = []
    monkeypatch.setattr(srs_trace.QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    assert [h for _, h in srs_trace.TraceSrsDialog.COLUMNS] == ["Principale", "Contribuisce"]  # tracing only
    dialog = srs_trace.TraceExclusionDialog(p, e["d1"])
    assert [h for _, h in dialog.COLUMNS] == ["Esclusa"]
    opened = []
    monkeypatch.setattr(srs_trace.TraceExclusionDialog, "open_window", lambda self, window: opened.append(window))
    # Only the principal sections of the domain and what they contain; only what they contain can be ticked.
    listed = {x.uuid for items in dialog.by_chapter.values() for x in items}
    assert {e["s1"].uuid, e["c1"].uuid, e["c2"].uuid} <= listed and not {e["s2"].uuid, e["c3"].uuid} & listed
    assert set(dialog.state) == {e["c1"].uuid, e["c2"].uuid}
    dialog.click(row_of(srs_trace, e["s1"]), srs_trace.EXCLUDED)  # the principal section itself: nothing
    assert e["s1"].uuid not in dialog.state and not opened and dialog._items[e["s1"].uuid].icon(2).isNull()
    # The tick opens the ADR at once; closed without saving: it goes away, the clause is not excluded.
    dialog.click(row_of(srs_trace, e["c1"]), srs_trace.EXCLUDED)
    [window] = opened
    adr = window.editor.element
    assert adr.get("adr_type") == ADR_EXCLUSION and adr.get("excluded_item") == [e["c1"].uuid]
    assert adr.get("excluding_domain") == e["d1"].uuid and adr.get("proposer") == e["t1"].uuid
    assert adr.get("title") == "Esclusione di 3.11.6.3 da DF01" and window.editor.editing
    assert dialog.state[e["c1"].uuid] is None and p.model.get(adr.uuid) is None and not e["c1"].get("excluded_domains")
    # Saved this time: ticked, the clause excluded, both on disk.
    monkeypatch.setattr(srs_trace.TraceExclusionDialog, "open_window", lambda self, window: save_the_adr(window))
    dialog.click(row_of(srs_trace, e["c1"]), srs_trace.EXCLUDED)
    adr = dialog.adrs_saved[0]
    assert dialog.state[e["c1"].uuid] == srs_trace.EXCLUDED and dialog.count.text() == "1 voce esclusa"
    assert e["c1"].get("excluded_domains") == [e["d1"].uuid] and adr.get("exclusion_reason") == REASON
    assert not {adr.uuid, e["c1"].uuid} & p.pending()
    assert COMPUTED["excluded_within"](p.model, adr) == [e["s1"].uuid]
    assert impacted_domains(p.model, adr) == [e["d1"]]
    dialog.accept()
    assert e["c1"].get("excluded_domains") == [e["d1"].uuid]
    # Opened again: excluded; ticked again (its ADR is there), no window.
    again = srs_trace.TraceExclusionDialog(p, e["d1"])
    assert again.state[e["c1"].uuid] == srs_trace.EXCLUDED
    again.set_state(e["c1"].uuid, None)
    monkeypatch.setattr(srs_trace.TraceExclusionDialog, "open_window", lambda self, window: opened.append(window))
    again.click(row_of(srs_trace, e["c1"]), srs_trace.EXCLUDED)
    assert again.state[e["c1"].uuid] == srs_trace.EXCLUDED and len(opened) == 1


def test_one_adr_excludes_more_clauses_set_in_its_sheet(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.model.adr import exclusion_defaults
    from arcadia_tool.ui.element_editor import ElementEditor

    p, e = build(tmp_path)
    values = exclusion_defaults(p.model, e["c1"], e["d1"])
    values["exclusion_reason"] = REASON
    adr = p.new_element("adr", **{k: v for k, v in values.items() if v})
    editor = ElementEditor()
    editor.edit(p, adr, editing=True)
    # The window of the clauses of the ADR: only those within the principal sections of the domain.
    warned = []
    monkeypatch.setattr(srs_trace.QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    choice = srs_trace.TraceExclusionItemsDialog(p, adr.copy(), "excluded_item")
    choice.click(row_of(srs_trace, e["c3"]), srs_trace.PARENT)
    choice.click(row_of(srs_trace, e["c2"]), srs_trace.PARENT)
    assert choice.selected == [e["c1"].uuid, e["c2"].uuid] and "sezioni principali del dominio" in warned[0]
    editor.widgets["excluded_item"].set_value(choice.selected)
    editor._changed()
    editor.save_changes()
    assert [e[k].get("excluded_domains") for k in ("c1", "c2", "c3")] == [[e["d1"].uuid], [e["d1"].uuid], None]
    # One of them no longer excluded from the domain sheet: out of the ADR, which stays for the other.
    asked = []
    monkeypatch.setattr(srs_trace.QMessageBox, "question",
                        lambda *a, **k: asked.append(a[1]) or srs_trace.QMessageBox.Yes)
    dialog = srs_trace.TraceExclusionDialog(p, e["d1"])
    dialog.set_state(e["c1"].uuid, None)
    dialog.accept()
    assert adr.get("excluded_item") == [e["c2"].uuid] and p.model.get(adr.uuid) is adr and not asked
    assert not e["c1"].get("excluded_domains") and e["c2"].get("excluded_domains") == [e["d1"].uuid]
    # The last one: the ADR, still proposed, deleted after asking.
    dialog = srs_trace.TraceExclusionDialog(p, e["d1"])
    dialog.set_state(e["c2"].uuid, None)
    dialog.accept()
    assert asked == ["Esclusioni tolte"] and p.model.get(adr.uuid) is None and not e["c2"].get("excluded_domains")
    # The principal section unticked (in the tracing window) while a clause of it is excluded: refused.
    told = []
    monkeypatch.setattr(srs_trace.QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    e["c2"].set("excluded_domains", [e["d1"].uuid])
    stranded = srs_trace.TraceSrsDialog(p, e["d1"])
    stranded.set_state(e["s1"].uuid, None)
    stranded.accept()
    assert told and "Escludi sezioni e clausole" in told[0] and e["s1"].get("primary_domain") == e["d1"].uuid


def test_an_adr_of_earlier_versions_with_one_clause_is_migrated_and_deleting_it_removes_the_exclusion(tmp_path):
    from arcadia_tool.model.adr import exclusion_defaults

    p, e = build(tmp_path)
    values = exclusion_defaults(p.model, e["c1"], e["d1"])
    adr = p.new_element("adr", **{k: v for k, v in values.items() if v})
    adr.values["excluded_item"] = e["c1"].uuid  # one item, as written by the first version
    p._migrate()
    assert adr.get("excluded_item") == [e["c1"].uuid]
    previous = adr.copy()
    p.update(adr, previous)  # saved
    p.save()
    assert e["c1"].get("excluded_domains") == [e["d1"].uuid]
    p.delete_element(adr.uuid)
    assert not e["c1"].get("excluded_domains") and e["c1"].uuid in p.pending()


def test_the_domain_sheet_lists_the_exclusions_one_after_the_other(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.checks.context import Context
    from arcadia_tool.checks.sa import sa1_exclusion_without_adr, sa1_exclusion_without_reason
    from arcadia_tool.model.coverage import DOMAIN, coverage
    from arcadia_tool.ui.main_window import MainWindow
    from arcadia_tool.ui.srs_reader import document_order

    p, e = build(tmp_path)
    window = MainWindow()
    window.resize(1300, 900)
    window.show()
    window._set_project(p)
    window._select(e["d1"])
    app.processEvents()
    domain_editor = window.editor
    principal, excluded_list = (domain_editor.widget().findChild(QListWidget, n)
                                for n in ("srsPrincipal", "srsExcluded"))
    assert excluded_list.mapTo(domain_editor.widget(), excluded_list.rect().topLeft()).y() > \
        principal.mapTo(domain_editor.widget(), principal.rect().topLeft()).y()

    from PySide6.QtWidgets import QPushButton
    buttons = {b.text(): b for b in domain_editor.widget().findChildren(QPushButton)}
    assert "Traccia sezioni e clausole SRS…" in buttons and "Escludi sezioni e clausole…" in buttons  # two buttons

    def excludes(dialog):
        dialog.click(row_of(srs_trace, e["c1"]), srs_trace.EXCLUDED)
        dialog.accept()
        return True
    monkeypatch.setattr(srs_trace.TraceExclusionDialog, "exec", excludes)
    monkeypatch.setattr(srs_trace.TraceExclusionDialog, "open_window", lambda self, window: save_the_adr(window))
    buttons["Escludi sezioni e clausole…"].click()
    app.processEvents()
    excluded_list = window.editors[e["d1"].uuid].widget().findChild(QListWidget, "srsExcluded")
    assert [excluded_list.item(i).text() for i in range(excluded_list.count())] == [p.model.label(e["c1"])]
    assert any(a.get("adr_type") for a in p.model.of_kind("adr"))
    ctx = Context(p.model)
    assert not list(sa1_exclusion_without_reason(ctx)) and not list(sa1_exclusion_without_adr(ctx))
    rows = {r.item.get("id"): r for r in coverage(p.model, document_order(p.model), "Bordo").rows}
    assert not rows["3.11.6.3"].at(DOMAIN) and rows["3.11.6.4"].at(DOMAIN)
    window._set_project(None)
    window.close()


def test_the_sa1_document_lists_the_exclusions_with_their_adr(tmp_path):
    import openpyxl
    from arcadia_tool.documents.generate import generate
    from arcadia_tool.model.adr import exclusion_defaults

    p, e = build(tmp_path)
    e["c1"].set("excluded_domains", [e["d1"].uuid])
    p.update(e["c1"])
    adr = p.new_element("adr", **{k: v for k, v in exclusion_defaults(p.model, e["c1"], e["d1"]).items() if v})
    [path] = generate(p, tmp_path / "out", ["SA-1"])
    ws = openpyxl.load_workbook(path)["DF01"]
    value = next(r[1] for r in ws.iter_rows(values_only=True) if r[0] == "Sezioni e clausole escluse")
    assert value == f"3.11.6.3 ({adr.get('id')})"
