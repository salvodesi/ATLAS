"""Allocation from the rows of the SRS catalogue: domains of a section, system functions and derived requirements
of a clause."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import arcadia_tool.ui.srs_row_actions as row_actions
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.srs_reader import SrsReader, row_kind
from arcadia_tool.ui.theme import apply_theme


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    chapter = p.new_element("requirement", id="3.14", item_type="Capitolo", title="Brake")
    section = p.new_element("requirement", id="3.14.4", item_type="Sezione", parent=chapter.uuid, title="Standstill")
    clause = p.new_element("requirement", id="3.14.4.2", item_type="Requisito", parent=section.uuid,
                           category=["Bordo"], text="When a movement is detected")
    item = p.new_element("requirement", id="3.14.4.2 a)", item_type="Voce", parent=clause.uuid, text="first")
    d6 = p.new_element("domain", name="Protezione")
    d2 = p.new_element("domain", name="Velocità")
    sf = p.new_element("system_function", name="Supervisionare lo standstill", domain=d6.uuid)
    sf2 = p.new_element("system_function", name="Gestire i freni", domain=d6.uuid, sections=[section.uuid])
    return p, dict(chapter=chapter, section=section, clause=clause, item=item, d6=d6, d2=d2, sf=sf, sf2=sf2)


def test_rows_of_sections_and_clauses(tmp_path):
    _, e = build(tmp_path)
    assert row_kind(e["section"]) == "section" and row_kind(e["clause"]) == "clause"
    assert row_kind(e["chapter"]) is None and row_kind(e["item"]) is None  # list items: through their clause
    from arcadia_tool.model.element import Element
    assert row_kind(Element("requirement", values={"id": "5.4.3.2-S21", "item_type": "Requisito"})) == "clause"
    assert row_kind(Element("requirement", values={"id": "A.3.1.2", "item_type": "Requisito"})) == "clause"


def test_project_allocates_from_a_row(tmp_path):
    p, e = build(tmp_path)
    changed = p.allocate_item(e["section"], e["d6"].uuid, [e["d2"].uuid, e["d6"].uuid])
    assert e["section"] in changed
    assert e["section"].get("primary_domain") == e["d6"].uuid
    assert e["section"].get("contributing_domains") == [e["d2"].uuid]  # not both principal and contributing
    assert p.allocate_item(e["section"], e["d6"].uuid, [e["d2"].uuid]) == []  # nothing changed

    changed = p.trace_item_to_functions(e["clause"], {e["sf"].uuid})
    assert [c.uuid for c in changed] == [e["sf"].uuid] and e["sf"].get("sections") == [e["clause"].uuid]
    assert e["sf2"].get("sections") == [e["section"].uuid]  # traces the section: not changed
    p.trace_item_to_functions(e["clause"], set())
    assert not e["sf"].get("sections")

    created, changed = p.derive_requirements(e["clause"], [("Rileva", "Rileva il movimento."),
                                                           ("", "Richiede la frenatura."), ("", "  ")])
    assert [d.get("id") for d in created] == ["3.14.4.2-D1", "3.14.4.2-D2"]
    assert created[0].get("name") == "Rileva" and all(d.get("parent") == e["clause"].uuid for d in created)
    [record] = [r for r in p.model.of_kind("trace_record") if r.get("requirement") == e["clause"].uuid]
    assert record.get("outcome") == "Scomposta in requisiti derivati" and record.get("b5_question").startswith("4")
    assert record.get("exchange_items") == [d.uuid for d in created]  # the record lists them
    more, _ = p.derive_requirements(e["clause"], [("", "Un altro.")], decompose=False)
    assert more[0].get("id") == "3.14.4.2-D3" and record.get("exchange_items")[-1] == more[0].uuid


def test_windows_of_the_row_actions(app, tmp_path):
    p, e = build(tmp_path)
    dialog = row_actions.ItemDomainsDialog(p, e["section"])
    rows = dialog.rows
    dialog._clicked(rows[e["d6"].uuid], row_actions.PRINCIPAL)
    dialog._clicked(rows[e["d2"].uuid], row_actions.CONTRIBUTES)
    dialog._clicked(rows[e["d2"].uuid], row_actions.PRINCIPAL)  # now principal: no longer contributing
    assert dialog.chosen() == (e["d2"].uuid, [])

    p.new_element("derived_requirement", parent=e["clause"].uuid, obligation="Già derivato.")  # 3.14.4.2-D1
    derive = row_actions.DeriveDialog(p, e["clause"])
    ID, NAME = row_actions.ID_COLUMN, row_actions.NAME_COLUMN
    table = derive.table
    assert table.rowCount() == 1 and table.columnCount() == 2  # one row: ID and short name
    assert [table.horizontalHeaderItem(c).text() for c in (ID, NAME)] == ["ID", "Nome sintetico"]
    assert not table.item(0, ID).flags() & Qt.ItemIsEditable  # assigned by the tool
    assert table.item(0, ID).text() == "3.14.4.2-D2"  # at once, after the existing D1
    assert derive.text_label.text() == "Obbligo di 3.14.4.2-D2 (una frase)"
    derive._create()  # no obligation written: says which one, nothing created
    assert "3.14.4.2-D2" in derive.error.text() and not derive.created

    derive.text.editor.setPlainText("Rileva il movimento.")  # the box below the table: the obligation of the row
    derive.add_row()
    assert table.item(1, ID).text() == "3.14.4.2-D3" and derive.text.plain_text() == ""  # a new row, empty box
    table.item(1, NAME).setText("Freno")
    derive.text.editor.setPlainText("Richiede la frenatura.")
    derive.text.toggle_bold()  # with styles, as in the sheet: the word under the cursor in bold
    table.setCurrentCell(0, NAME)  # back to the first row: the box shows its obligation
    assert derive.text.plain_text() == "Rileva il movimento."
    derive.add_row()
    derive.remove_row()  # the third, empty row removed
    assert derive.ids() == ["3.14.4.2-D2", "3.14.4.2-D3"]
    derive._create()
    assert [d.get("id") for d in derive.created] == ["3.14.4.2-D2", "3.14.4.2-D3"]
    assert derive.created[0].get("obligation") == "Rileva il movimento."
    assert "**" in derive.created[1].get("obligation")  # the bold word, stored as Markdown
    assert derive.created[1].get("obligation").replace("**", "") == "Richiede la frenatura."
    assert [d.get("name") for d in derive.created] == [None, "Freno"] and derive.changed


def _click(view, point):
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        event = QMouseEvent(kind, QPointF(point), QPointF(view.viewport().mapToGlobal(point)), Qt.LeftButton,
                            Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(view.viewport(), event)


def test_buttons_of_a_row_run_the_actions(app, tmp_path, monkeypatch):
    p, e = build(tmp_path)
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window._set_project(p)
    window.open_srs_reader()
    reader = window.reader
    app.processEvents()
    assert "Funzioni: SF-DF01-02 (sezione)" in reader._links_text(e["clause"])
    assert reader._links_text(e["section"]) == "Nessun dominio allocato"

    monkeypatch.setattr(row_actions, "choose_functions", lambda project, item, parent=None: {e["sf"].uuid})
    rows = {el.uuid: i for i, el in enumerate(reader.model.elements)}
    index = reader.model.index(rows[e["clause"].uuid])
    rect = reader.view.visualRect(index)
    *_, actions, _ = reader.delegate._layout(e["clause"], rect)
    buttons = {name: box for name, _, box in actions[1]}
    assert set(buttons) == {"functions", "derive"}
    opened = []
    reader.open_element.connect(opened.append)
    _click(reader.view, buttons["functions"].center())  # «Funzioni…» of the clause row
    assert e["sf"].get("sections") == [e["clause"].uuid] and opened == []  # done; the item was not opened
    assert reader._links_text(e["clause"]).startswith("Funzioni: SF-DF01-01 · SF-DF01-02 (sezione)")

    class Domains:  # «Domini…» of the section row, answered
        def __init__(self, project, item, parent=None):
            pass

        def exec(self):
            return True

        def chosen(self):
            return e["d6"].uuid, [e["d2"].uuid]
    monkeypatch.setattr(row_actions, "ItemDomainsDialog", Domains)
    reader.run_action(e["section"].uuid, "domains")
    assert e["section"].get("primary_domain") == e["d6"].uuid
    assert reader._links_text(e["section"]) == "Domini: DF01 (principale) · DF02 (contributo)"
    assert window.project.is_modified
    window.close()
