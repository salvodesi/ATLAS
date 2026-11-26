"""Links between SRS items: «Richiama», «Include», «Dipende da». Including covers the clause by the tracing of the
included one (SA-3 outcome «Coperta dalla clausola inclusa», coverage, functions traced); the others are said only."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QListWidget

from arcadia_tool.model.links import record_functions, record_summary, traced_functions
from arcadia_tool.model.srs_links import (COVERED_BY_INCLUDED, DEPENDS, INCLUDES, REFERS, included, includes_loop,
                                          incoming, link_rows, links_of)
from arcadia_tool.storage.project import Project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    df3 = p.new_element("domain", id="DF03", name="Movimento")
    df7 = p.new_element("domain", id="DF07", name="Protezione")
    s1 = p.new_element("requirement", id="3.8.4", item_type="Sezione", primary_domain=df3.uuid)
    s2 = p.new_element("requirement", id="3.12.2", item_type="Sezione", primary_domain=df7.uuid)
    a = p.new_element("requirement", id="3.8.4.1", item_type="Requisito", parent=s1.uuid, category=["Bordo"],
                      text="Si applicano le condizioni di 3.12.2.3")
    b = p.new_element("requirement", id="3.12.2.3", item_type="Requisito", parent=s2.uuid, category=["Bordo"],
                      text="Le condizioni")
    c = p.new_element("requirement", id="3.12.2.4", item_type="Requisito", parent=s2.uuid, category=["Bordo"])
    f7 = p.new_element("system_function", id="SF-DF07-01", name="Proteggere", domain=df7.uuid, sections=[b.uuid])
    return p, dict(df3=df3, df7=df7, a=a, b=b, c=c, f7=f7)


def test_the_links_and_the_other_way(tmp_path):
    p, e = build(tmp_path)
    e["a"].set("links", link_rows([(INCLUDES, e["b"].uuid), (REFERS, e["c"].uuid), (INCLUDES, e["b"].uuid)]))
    assert links_of(e["a"]) == [(INCLUDES, e["b"].uuid), (REFERS, e["c"].uuid)]  # each once
    assert incoming(p.model, e["b"].uuid) == [(INCLUDES, e["a"])]
    e["b"].set("links", link_rows([(INCLUDES, e["c"].uuid)]))
    assert included(p.model, e["a"].uuid) == [e["b"].uuid, e["c"].uuid]  # through the included ones
    assert not includes_loop(p.model, e["a"].uuid)
    e["c"].set("links", link_rows([(INCLUDES, e["a"].uuid)]))
    assert includes_loop(p.model, e["a"].uuid) and included(p.model, e["a"].uuid) == [e["b"].uuid, e["c"].uuid]
    p.close()


def test_including_covers_the_clause_and_the_others_say_only(tmp_path):
    from arcadia_tool.model.coverage import FUNCTION, coverage
    from arcadia_tool.ui.srs_reader import document_order

    p, e = build(tmp_path)

    def covered(uuid):
        rows = {r.item.uuid: r for r in coverage(p.model, document_order(p.model), "Bordo").rows}
        return rows[uuid].at(FUNCTION)
    assert not covered(e["a"].uuid) and traced_functions(p.model, e["a"].uuid) == []
    e["a"].set("links", link_rows([(REFERS, e["b"].uuid), (DEPENDS, e["c"].uuid)]))  # said only
    assert incoming(p.model, e["c"].uuid) == [(DEPENDS, e["a"])]
    assert not covered(e["a"].uuid) and traced_functions(p.model, e["a"].uuid) == []
    e["a"].set("links", link_rows([(INCLUDES, e["b"].uuid)]))  # covered by the tracing of 3.12.2.3
    assert covered(e["a"].uuid) and traced_functions(p.model, e["a"].uuid) == [e["f7"].uuid]
    record = p.new_element("trace_record", requirement=e["a"].uuid, outcome=COVERED_BY_INCLUDED)
    assert record_functions(p.model, record) == ([e["f7"].uuid], [])
    assert record_summary(p.model, record) == "Dalle clausole incluse: 3.12.2.3"
    e["a"].set("links", [])
    assert record_functions(p.model, record) == ([], []) and "non include nessuna clausola" in record_summary(
        p.model, record)
    p.close()


def test_the_window_of_the_links_and_the_catalogue(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import srs_trace
    from arcadia_tool.ui.srs_links import LinksDialog
    from arcadia_tool.ui.srs_reader import SrsReader

    p, e = build(tmp_path)
    reader = SrsReader(p)
    reader.resize(1000, 600)
    reader.show()
    app.processEvents()

    def run(dialog):  # «Include» 3.12.2.3 and 3.12.2.4 (not the clause itself), then one becomes «Richiama»
        monkeypatch.setattr(srs_trace, "pick_srs_items", lambda *a, **k: [e["b"].uuid, e["c"].uuid, e["a"].uuid])
        dialog.add(INCLUDES)
        assert dialog.links == [(INCLUDES, e["b"].uuid), (INCLUDES, e["c"].uuid)]
        dialog.table.cellWidget(1, 0).setCurrentText(REFERS)
        return True
    monkeypatch.setattr(LinksDialog, "exec", run)
    reader.run_action(e["a"].uuid, "links")
    assert links_of(e["a"]) == [(INCLUDES, e["b"].uuid), (REFERS, e["c"].uuid)]
    badges = [(text, style) for text, style, *_tip in reader._link_badges(e["a"])]
    assert ("→ 3.12.2.3", "link") in badges and ("→ 3.12.2.4", "link") in badges
    assert ("← 3.8.4.1", "link") in [(t, s) for t, s, *_tip in reader._link_badges(e["b"])]
    # Removed in the window: no longer linked.
    monkeypatch.setattr(LinksDialog, "exec", lambda d: d.table.removeRow(0) or True)
    reader.run_action(e["a"].uuid, "links")
    assert links_of(e["a"]) == [(REFERS, e["c"].uuid)]
    reader.close()
    reader.deleteLater()
    app.processEvents()
    p.close()


def test_the_sheet_shows_them(app, tmp_path):
    from arcadia_tool.ui.element_editor import ElementEditor

    p, e = build(tmp_path)
    e["a"].set("links", link_rows([(INCLUDES, e["b"].uuid)]))
    editor = ElementEditor()
    editor.edit(p, e["b"])
    shown = editor.findChild(QListWidget, "srsLinks")
    assert [shown.item(i).text() for i in range(shown.count())] == [f"Inclusa in {p.model.label(e['a'])}"]
    editor = ElementEditor()
    editor.edit(p, e["a"])
    shown = editor.findChild(QListWidget, "srsLinks")
    assert shown.item(0).text().startswith("Include 3.12.2.3")
    # The record of a clause covered by those it includes: its functions read-only, from them.
    record = p.new_element("trace_record", requirement=e["a"].uuid, outcome=COVERED_BY_INCLUDED)
    editor = ElementEditor()
    editor.edit(p, record, editing=True)
    assert editor.widgets["primary_functions"].value() == [e["f7"].uuid]
    assert "clausole che la voce include" in editor.widgets["primary_functions"].list.toolTip()
    p.close()


def test_a_dependence_on_a_clause_of_another_domain_is_said(tmp_path):
    from arcadia_tool.checks import run
    from arcadia_tool.checks.config import ChecksConfig, Profile

    p, e = build(tmp_path)
    e["a"].set("links", link_rows([(DEPENDS, e["b"].uuid)]))  # 3.8.4.1 (DF03) depends on 3.12.2.3 (DF07)
    found = [f for f in run(p.model, ChecksConfig({"Predefinito": Profile(["A4-11"], {})})) if f.code == "A4-11"]
    assert [f.message.split(",")[0] for f in found] == ["Dipende da 3.12.2.3"]
    p.close()


def test_the_meaning_of_the_types_is_said_before_choosing(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel
    from arcadia_tool.ui import srs_links, srs_trace

    p, e = build(tmp_path)
    dialog = srs_links.LinksDialog(p, e["a"])
    legend = next(w for w in dialog.findChildren(QLabel) if w.accessibleName() == "linkLegend").text()
    assert "Es.:" not in legend and "Aggiungi collegamento" in legend  # the meanings: only where the type is chosen
    explained = " ".join(w.text() for w in srs_links.LinkTypeDialog("3.8.4.1").findChildren(QLabel))
    assert explained.count("Es.:") == 3 and "3.8.4.4.3" in explained
    choice = srs_links.LinkTypeDialog("3.8.4.1")
    labels = [b.text() for b in choice.buttons.values()]
    assert labels == ["3.8.4.1 richiama l'altra voce", "3.8.4.1 include l'altra voce",
                      "3.8.4.1 dipende dall'altra voce"]
    assert not choice.ok.isEnabled()  # no type proposed: one is chosen knowing what it means
    choice.buttons[DEPENDS].setChecked(True)
    assert choice.ok.isEnabled() and choice.chosen == DEPENDS
    # «Aggiungi collegamento…»: the type first, then the items.
    asked = []
    monkeypatch.setattr(srs_links.LinkTypeDialog, "exec", lambda d: asked.append(1) or d.buttons[DEPENDS].setChecked(True) or True)
    monkeypatch.setattr(srs_trace, "pick_srs_items", lambda *a, **k: [e["b"].uuid])
    dialog.add_button.click()
    assert asked and dialog.links == [(DEPENDS, e["b"].uuid)]
    p.close()


def test_collega_from_the_right_click_of_the_catalogue_and_of_the_tree(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.srs_links import LinksDialog

    p, e = build(tmp_path)
    window = mw.MainWindow()
    window._set_project(p)
    window.open_srs_reader()
    reader = window.reader
    assert "Collega…" in [a.text() for a in reader.context_menu(e["a"]).actions()]  # the catalogue
    tree = window.tree

    def menu_of(uuid):
        return [x.text() for x in tree.context_menu_for(tree._items[uuid]).actions()]
    assert "Collega…" in menu_of(e["a"].uuid)  # the model tree, on an SRS item
    assert "Collega…" not in menu_of(e["f7"].uuid)  # not on a function
    # From the tree: the same window; the catalogue shows the new link.
    monkeypatch.setattr(LinksDialog, "exec", lambda d: d._row(INCLUDES, e["b"].uuid) or True)
    tree.links_requested.emit(e["a"].uuid)
    assert links_of(e["a"]) == [(INCLUDES, e["b"].uuid)]
    assert ("← 3.8.4.1", "link") in [(t, s) for t, s, *_tip in reader._link_badges(e["b"])]
    window._set_project(None)
    window.close()
