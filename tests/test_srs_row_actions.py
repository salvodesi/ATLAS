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
    assert row_kind(e["chapter"]) is None  # chapters and sections: not derivable
    assert row_kind(e["item"]) == "item"  # list items: derivable, traced to the functions with their clause
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
    assert [name for name, _, _box in actions[1]] == ["analyzed", "actions"]
    opened, shown = [], []
    reader.open_element.connect(opened.append)
    original = reader.quick_menu

    def quick_menu(element, menu=None):  # «Azioni ▾» opens the menu under the mouse: «Mappa a funzione…» chosen
        menu = original(element, menu)
        shown.append([a.text() for a in menu.actions() if a.text()])
        menu.exec = lambda *a: next(a for a in menu.actions() if a.text() == "Mappa a funzione…").trigger()
        return menu
    monkeypatch.setattr(reader, "quick_menu", quick_menu)
    _click(reader.view, buttons["actions"].center())  # «Azioni ▾» of the clause row
    assert shown and shown[0][0] == "Mappa a funzione…"
    assert e["sf"].get("sections") == [e["clause"].uuid] and opened == []  # done; the item was not opened
    assert reader._links_text(e["clause"]).startswith("Funzioni: SF-DF01-01 · SF-DF01-02 (sezione)")
    badges = reader._link_badges(e["clause"])  # drawn as badges: code and name, the one of the section in grey
    assert [style for _t, style, *_tip in badges][:2] == ["function", "inherited"]
    assert badges[0][0] == f"SF-DF01-01 - {e['sf'].get('name')}"
    assert "direttamente alla clausola" in badges[0][2] and "sezione" in badges[1][2]  # the kind of mapping
    rect = reader.view.visualRect(index)
    text_box = reader.delegate._layout(e["clause"], rect)[-2][0]
    first = reader.delegate._badge_places(text_box, badges)[0][0]
    tip = reader.delegate.badge_tip(index, first.center())  # the mouse on the badge
    assert tip.startswith("SF-DF01-01") and "direttamente" in tip and "Clic per aprirla" in tip
    # A click on the badge of a function: its sheet (also of one inherited from the section), not the clause.
    places = reader.delegate._badge_places(text_box, badges)
    assert reader.delegate.link_at(index, places[0][0].center()) == e["sf"].uuid
    assert reader.delegate.link_at(index, places[1][0].center()) == e["sf2"].uuid
    sheets = []
    reader.open_element.connect(sheets.append)
    _click(reader.view, places[0][0].center())
    assert sheets == [e["sf"].uuid] and e["clause"].uuid not in opened  # the function opened, the clause not
    reader.open_element.disconnect(sheets.append)
    opened.clear()

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
    assert reader._links_text(e["section"]) == "Domini: DF01 - Protezione (principale) · DF02 - Velocità (contributo)"
    assert reader._domain_badges(e["section"]) == [("DF01 - Protezione", True), ("DF02 - Velocità", False)]
    assert not reader.grab().isNull()  # the row drawn with its badges
    assert window.project.is_modified
    window.close()


def test_everything_but_chapters_and_sections_is_derivable(app, tmp_path):
    from arcadia_tool.model.coverage import DERIVED, coverage, derivable
    from arcadia_tool.ui.srs_reader import ROW_ACTIONS, document_order

    p, e = build(tmp_path)
    sub = p.new_element("requirement", id="3.14.4.2.1", item_type="Requisito", parent=e["clause"].uuid,
                        category=["Bordo"], text="a sub-clause")
    assert not derivable(e["chapter"]) and not derivable(e["section"])  # e.g. 3.8.1
    assert all(derivable(x) for x in (e["clause"], sub, e["item"]))  # 3.8.1.1, its sub-clauses, list items
    assert [name for name, *_ in ROW_ACTIONS[row_kind(e["item"])]] == ["analyzed", "actions"]  # analysed on its own
    # Derived from a list item: «3.14.4.2 a)-D1», covering its clause at the level SA-4.
    created, _ = p.derive_requirements(e["item"], [("", "Rileva il primo movimento.")])
    assert [d.get("id") for d in created] == ["3.14.4.2 a)-D1"]
    rows = {r.item.uuid: r for r in coverage(p.model, document_order(p.model), "Bordo").rows}
    assert rows[e["clause"].uuid].at(DERIVED) and created[0] in rows[e["clause"].uuid].derived
    # The menu of the catalogue: «Deriva» on clauses and list items, not on sections and chapters.
    reader = SrsReader(p)
    texts = lambda x: [a.text() for a in reader.context_menu(x).actions()]
    assert not any(t.startswith("Deriva") for t in texts(e["section"]) + texts(e["chapter"]))
    assert "Deriva requisiti…" in texts(e["item"]) and "Mappa a funzione…" not in texts(e["item"])  # with the clause
    assert "Mappa a funzione…" in texts(sub)


def records_of(p, item):
    return [r for r in p.model.of_kind("trace_record") if r.get("requirement") == item.uuid]


def test_a_requirement_created_from_sa4_has_its_trace_record_too(app, tmp_path, monkeypatch):
    from arcadia_tool.ui.model_tree import ModelTree

    p, e = build(tmp_path)
    window = MainWindow()
    window._set_project(p)
    monkeypatch.setattr(ModelTree, "_ask_context", lambda self, kind: {"parent": e["clause"].uuid})
    window.tree.create("derived_requirement")  # SA-4 in the tree on the left
    records = records_of(p, e["clause"])
    derived = p.model.of_kind("derived_requirement")
    assert len(derived) == 1 and len(records) == 1
    assert records[0].get("outcome") == "Scomposta in requisiti derivati" and records[0].get("b5_question")
    assert derived[0].uuid in records[0].get("exchange_items")
    window.tree.create("derived_requirement", {"parent": e["clause"].uuid})  # «Deriva requisito da…» of the catalogue
    assert len(records_of(p, e["clause"])) == 1  # the same record, listing both
    assert len(records_of(p, e["clause"])[0].get("exchange_items")) == 2
    window._set_project(None)
    window.close()


@pytest.mark.parametrize("kind", ["system_function", "logical_function"])
def test_derive_from_a_clause_mapped_on_a_function(app, tmp_path, monkeypatch, kind):
    from PySide6.QtWidgets import QLabel, QListWidget

    p, e = build(tmp_path)
    if kind == "system_function":
        function = e["sf"]
        function.set("sections", [e["section"].uuid, e["clause"].uuid])
    else:
        function = p.new_element("logical_function", name="Rileva", refines=e["sf"].uuid)
        function.set("detail_requirements", [e["section"].uuid, e["clause"].uuid])
    p.update(function)
    window = MainWindow()
    window._set_project(p)
    window.tree.select(function.uuid)
    editor = window.editor
    allocated = editor.findChild(QListWidget, "srsAllocated")
    assert allocated is not None
    assert allocated.contextMenuPolicy() == Qt.CustomContextMenu

    menu = editor._allocated_menu(e["section"])  # a section: not derivable
    assert not menu.actions()[0].isEnabled() and "non sono derivabili" in menu.actions()[0].text()
    menu = editor._allocated_menu(e["clause"])
    assert menu.actions()[0].isEnabled() and menu.actions()[0].text() == "Deriva requisiti…"

    def run(dialog):
        assert "mappati sulla funzione" in " ".join(label.text() for label in dialog.findChildren(QLabel))
        dialog.set_obligation(0, "Rileva il movimento.")
        dialog._create()
        return True
    monkeypatch.setattr(row_actions.DeriveDialog, "exec", run)
    menu.actions()[0].trigger()
    derived = p.model.of_kind("derived_requirement")
    field = "system_function" if kind == "system_function" else "function"
    expected = [function.uuid] if field == "system_function" else function.uuid  # the system functions: a list
    assert len(derived) == 1 and derived[0].get(field) == expected and derived[0].get("parent") == e["clause"].uuid
    assert records_of(p, e["clause"])[0].get("outcome") == "Scomposta in requisiti derivati"
    name = "derivedMapped" if kind == "system_function" else "derivedAllocated"
    box = editor.findChild(QListWidget, name)  # the sheet rebuilt: the box of the derived requirements shows it
    assert box.item(0).data(Qt.UserRole) == derived[0].uuid
    assert "CLAUSOLE SRS MAPPATE" in [label.text() for label in editor.findChildren(QLabel)]  # the title of the card
    window._set_project(None)
    window.close()


def test_deleting_a_derived_requirement_removes_its_trace(tmp_path):
    p, e = build(tmp_path)
    (first, second), _ = p.derive_requirements(e["clause"], [("", "Uno."), ("", "Due.")])
    record = records_of(p, e["clause"])[0]
    p.save()
    p.delete_element(first.uuid)  # another one left: the record stays, without it
    assert records_of(p, e["clause"]) == [record] and record.get("exchange_items") == [second.uuid]
    assert record.get("outcome") == "Scomposta in requisiti derivati"
    p.delete_element(second.uuid)  # the last one: the record goes, also from the disk
    assert not records_of(p, e["clause"])
    p.save()
    p.close()
    p = Project.open(p.path)
    assert not p.model.of_kind("trace_record") and not p.model.of_kind("derived_requirement")


def test_a_record_with_other_contents_stays_when_the_last_derived_is_deleted(tmp_path):
    p, e = build(tmp_path)
    (derived,), _ = p.derive_requirements(e["clause"], [("", "Uno.")])
    record = records_of(p, e["clause"])[0]
    record.set("notes", "Scritta dall'analista")
    p.update(record)
    p.delete_element(derived.uuid)
    assert records_of(p, e["clause"]) == [record] and record.get("notes") == "Scritta dall'analista"
    assert not record.get("exchange_items") and not record.get("outcome") and not record.get("b5_question")


def test_a_new_derived_requirement_cancelled_leaves_no_record(app, tmp_path):
    p, e = build(tmp_path)
    (derived,), _ = p.derive_requirements(e["clause"], [("", "Uno.")])  # «Nuovo», then «Annulla»: never saved
    assert p.discard_new(derived.uuid)
    assert not records_of(p, e["clause"]) and not p.model.of_kind("derived_requirement")


def test_an_adr_created_from_any_srs_item(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.adr_types as adr_types
    from arcadia_tool.model.schema import ADR_IMPLEMENTATION, ADR_SECTION, ADR_WAIVER, SCOPE_CLAUSES, SCOPE_SECTION

    p, e = build(tmp_path)
    reader = SrsReader(p)
    for key in ("section", "clause", "item"):  # «Crea ADR…» in the quick actions of every row
        assert "Crea ADR…" in [a.text() for a in reader.quick_menu(e[key]).actions()]
    window = MainWindow()
    window._set_project(p)
    window.open_srs_reader()
    chosen = []

    def exec_(dialog):
        chosen.append(dialog)
        dialog.adr_type = types.pop(0)
        return True
    monkeypatch.setattr(adr_types.AdrTypeDialog, "exec", exec_)
    types = [ADR_SECTION, ADR_SECTION, ADR_IMPLEMENTATION, ADR_WAIVER]
    for key in ("section", "clause", "clause", "item"):
        window.reader.run_action(e[key].uuid, "adr")
    adrs = sorted(p.model.of_kind("adr"), key=lambda a: a.get("id"))
    assert len(adrs) == 4 and window.editor.element is adrs[-1]  # each opened in its sheet
    assert adrs[0].get("realloc_item") == [e["section"].uuid] and adrs[0].get("realloc_scope") == SCOPE_SECTION
    assert adrs[1].get("realloc_item") == [e["clause"].uuid] and adrs[1].get("realloc_scope") == SCOPE_CLAUSES
    assert adrs[2].get("impl_item") == e["clause"].uuid
    assert adrs[3].get("srs_items") == [e["item"].uuid] and not adrs[3].get("concerns")  # «Voci SRS interessate»
    window._set_project(None)
    window.close()
