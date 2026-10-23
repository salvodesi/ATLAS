import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QMessageBox, QPushButton

import arcadia_tool.ui.srs_trace as srs_trace
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.srs_trace import CONTRIBUTES, PRINCIPAL, TraceSrsDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")

    def req(ident, item_type, parent=None, **values):
        return p.new_element("requirement", id=ident, item_type=item_type,
                             parent=parent.uuid if parent else None, **values)

    chapter = req("3.4", "Capitolo", title="Balise configuration")
    section = req("3.4.1", "Sezione", chapter, title="Balise groups")
    clause = req("3.4.1.3", "Requisito", section, text="A balise group shall consist of 1 to 8 balises.")
    item = req("3.4.1.3 a)", "Voce", clause, text="first")
    other = req("3.4.2", "Sezione", chapter, title="Linking")
    odometry = p.new_element("domain", name="Odometria")
    location = p.new_element("domain", name="Localizzazione")
    return p, dict(chapter=chapter, section=section, clause=clause, item=item, other=other,
                   odometry=odometry, location=location)


def test_trace_sections_and_clauses_from_the_domain(app, tmp_path):
    p, e = build(tmp_path)
    p.new_element("requirement", id="5.4.1", item_type="Sezione", title="Start of Mission")
    dialog = TraceSrsDialog(p, e["location"])
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["Capitolo 3", "Capitolo 5"]
    items = dialog._items  # chapter 3 only, loaded when its tab is shown
    assert set(items) == {e["section"].uuid, e["clause"].uuid, e["other"].uuid}  # not chapters, not list items
    chapter_item = items[e["section"].uuid].parent()
    assert chapter_item.isExpanded() and not items[e["section"].uuid].isExpanded()  # down to the sections
    dialog.click(items[e["section"].uuid], PRINCIPAL)
    dialog.click(items[e["clause"].uuid], CONTRIBUTES)
    dialog.click(items[e["other"].uuid], CONTRIBUTES)
    dialog.click(items[e["other"].uuid], PRINCIPAL)  # principal or contributing, not both
    assert dialog.state[e["other"].uuid] == PRINCIPAL
    assert dialog.tabs.tabText(0) == "Capitolo 3 · 3 tracciate"
    dialog.search.setText("8 balises")
    assert not items[e["clause"].uuid].isHidden() and items[e["other"].uuid].isHidden()
    assert dialog.tabs.tabText(1) == "Capitolo 5 · 0 trovate"
    dialog.accept()
    loc = e["location"].uuid
    assert e["section"].get("primary_domain") == loc and e["other"].get("primary_domain") == loc
    assert e["clause"].get("contributing_domains") == [loc]

    # Another domain cannot silently take a section that already has a principal domain.
    dialog = TraceSrsDialog(p, e["odometry"])
    section_item = dialog._items[e["section"].uuid]
    assert section_item.text(4) == p.model.label(e["location"])
    dialog.click(section_item, PRINCIPAL)
    assert section_item.text(4) == p.model.label(e["odometry"])  # shown before «Applica»
    dialog.click(section_item, PRINCIPAL)
    assert section_item.text(4) == p.model.label(e["location"])  # unchecked: back to the current one
    dialog.click(section_item, PRINCIPAL)
    dialog.accept()  # the question is answered No by the test fixture
    assert e["section"].get("primary_domain") == loc

    # Untracing from the domain.
    dialog = TraceSrsDialog(p, e["location"])
    dialog.click(dialog._items[e["clause"].uuid], CONTRIBUTES)
    dialog.accept()
    assert e["clause"].get("contributing_domains") in ([], None)
    p.close()


def test_domain_sheet_shows_the_traced_items(app, tmp_path, monkeypatch):
    p, e = build(tmp_path)
    p.trace_srs(e["location"], {e["section"].uuid}, {e["clause"].uuid})
    window = MainWindow()
    window._set_project(p)
    window.tree.select(e["location"].uuid)
    editor = window.editor
    button = next(b for b in editor.findChildren(QPushButton) if b.text().startswith("Traccia"))
    assert button.isEnabled()
    principal = editor.findChild(QListWidget, "srsPrincipal")
    contributing = editor.findChild(QListWidget, "srsContributing")
    assert principal.item(0).data(Qt.UserRole) == e["section"].uuid
    assert contributing.item(0).data(Qt.UserRole) == e["clause"].uuid

    titles = [l.text() for l in editor.widget().findChildren(QLabel) if l.objectName() == "sectionCaption"]
    assert titles[titles.index("DESCRIZIONE") + 1].startswith("TRACCIABILITÀ")  # right after «Descrizione»

    contributing.itemDoubleClicked.emit(contributing.item(0))  # the clause opens in its own window
    assert editor.element is e["location"]  # the domain page stays as it is
    item_window = window.item_window
    assert item_window.isVisible() and item_window.editor.element is e["clause"]
    # The allocation stays editable on the read-only SRS item; the domain page follows the change.
    item_editor = item_window.editor
    assert not item_editor.editing  # opens read-only
    item_editor.start_editing()
    assert item_editor.read_only and item_editor.widgets["primary_domain"].isEnabled()
    combo = item_editor.widgets["primary_domain"]
    combo.setCurrentIndex(combo.findData(e["odometry"].uuid))
    assert item_editor.dirty and e["clause"].get("primary_domain") is None  # not applied yet
    item_editor.save_changes()
    item_window.close()
    assert e["clause"].get("primary_domain") == e["odometry"].uuid
    assert window.editor.findChild(QListWidget, "srsContributing").item(0).data(Qt.UserRole) == e["clause"].uuid
    window.save()
    window.close()


def test_system_function_allocated_to_sections_and_clauses_only(app, tmp_path):
    from arcadia_tool.ui.srs_trace import ALLOCATED, TraceFunctionDialog

    p, e = build(tmp_path)
    function = p.new_element("system_function", name="Calcola la posizione", domain=e["location"].uuid)
    derived = p.new_element("derived_requirement", parent=e["clause"].uuid, obligation="Conta le boe",
                            function=function.uuid)
    dialog = TraceFunctionDialog(p, function)
    assert dialog.tree.headerItem().text(2) == "Allocata"
    assert derived.uuid not in dialog._items and derived.uuid not in dialog.state  # SA-2: not shown
    assert dialog.tree.isColumnHidden(3) and not dialog.only_derived.isVisible()
    dialog.click(dialog._items[e["section"].uuid], ALLOCATED)
    dialog.click(dialog._items[e["clause"].uuid], ALLOCATED)
    assert dialog.count.text() == "2 sezioni e clausole"
    dialog.accept()
    assert function.get("sections") == [e["section"].uuid, e["clause"].uuid]
    assert derived.get("function") == function.uuid  # its own field, not changed from here

    dialog.show_item(e["clause"].uuid)  # double click: the full text, with the list items
    text = dialog.viewer.browser.toPlainText()
    assert "1 to 8 balises" in text and "a)" in text and "first" in text

    window = MainWindow()
    window._set_project(p)
    window.tree.select(function.uuid)
    allocated = window.editor.findChild(QListWidget, "srsAllocated")
    assert [allocated.item(i).data(Qt.UserRole) for i in range(allocated.count())] == [e["section"].uuid,
                                                                                       e["clause"].uuid]
    assert window.editor.findChild(QListWidget, "derivedAllocated") is None
    assert "sections" not in window.editor.getters  # shown in the card, not as a plain field
    window.save()
    window.close()


def test_logical_function_traces_clauses_and_derived_requirements(app, tmp_path):
    from arcadia_tool.ui.srs_trace import ALLOCATED, TraceFunctionDialog

    p, e = build(tmp_path)
    system = p.new_element("system_function", name="Calcola la posizione", domain=e["location"].uuid)
    derived = p.new_element("derived_requirement", parent=e["clause"].uuid, obligation="Conta le boe")
    first = p.new_element("logical_function", name="Legge il telegramma", refines=system.uuid)
    second = p.new_element("logical_function", name="Conta le boe lette", refines=system.uuid)
    assert derived.schema.field("function").ref_kinds == ("logical_function",)  # not a system function

    dialog = TraceFunctionDialog(p, first)
    assert dialog.tree.headerItem().text(3) == "Funzione logica del requisito derivato"
    dialog.click(dialog._items[e["clause"].uuid], ALLOCATED)
    dialog.click(dialog._items[derived.uuid], ALLOCATED)
    dialog.accept()  # no question: the requirement had no logical function
    assert first.get("detail_requirements") == [e["clause"].uuid] and derived.get("function") == first.uuid

    dialog = TraceFunctionDialog(p, second)  # one logical function per derived requirement
    row = dialog._items[derived.uuid]
    assert row.text(3) == p.model.label(first)
    dialog.click(row, ALLOCATED)
    assert row.text(3) == p.model.label(second)  # before «Applica»
    dialog.accept()  # moving it is confirmed: answered No
    assert derived.get("function") == first.uuid
    QMessageBox.question = lambda *args: QMessageBox.Yes  # restored by the conftest fixture
    dialog.accept()
    assert derived.get("function") == second.uuid
    first, second = second, first  # the sheet below shows the function that has it now

    window = MainWindow()
    window._set_project(p)
    window.tree.select(first.uuid)
    assert window.editor.findChild(QListWidget, "derivedAllocated").item(0).text().startswith(derived.get("id"))
    window.tree.select(second.uuid)
    assert window.editor.findChild(QListWidget, "srsAllocated").item(0).data(Qt.UserRole) == e["clause"].uuid
    window.save()
    window.close()


def test_derived_requirement_short_name_parent_and_logical_function(app, tmp_path, monkeypatch):
    from arcadia_tool.ui.element_editor import ElementEditor
    from arcadia_tool.ui.srs_trace import PARENT, TickPickerDialog, TraceParentDialog

    p, e = build(tmp_path)
    derived = p.new_element("derived_requirement", parent=e["clause"].uuid, name="Conta le boe",
                            obligation="Il bordo conta le boe del gruppo")
    assert p.model.label(derived) == "3.4.1.3-D1"  # referred to by its ID only
    assert p.model.choice_label(derived) == "3.4.1.3-D1 – Conta le boe"  # where it is chosen

    dialog = TraceParentDialog(p, derived)  # «Voce madre»: one only, with ticks
    assert dialog.state[e["clause"].uuid] == PARENT
    dialog.click(dialog._items[e["section"].uuid], PARENT)
    assert dialog.chosen(PARENT) == {e["section"].uuid}  # the tick moved
    assert dialog.count.text().startswith("Voce madre: 3.4.1")
    dialog.search.setText("1 to 8")
    assert not dialog._items[e["clause"].uuid].isHidden() and dialog._items[e["other"].uuid].isHidden()
    dialog.accept()
    assert derived.get("parent") == e["section"].uuid

    creating = TraceParentDialog(p, None)  # new derived requirement from the model tree: only the choice
    creating.click(creating._items[e["clause"].uuid], PARENT)
    creating.accept()
    assert creating.parent == e["clause"].uuid and creating.changed == []

    system = p.new_element("system_function", name="Calcola la posizione", domain=e["location"].uuid)
    first = p.new_element("logical_function", name="Legge il telegramma", refines=system.uuid)
    second = p.new_element("logical_function", name="Conta le boe lette", refines=system.uuid)
    picker = TickPickerDialog(p, "Funzione logica", "", p.model.of_kind("logical_function"), single=True,
                              group_of=lambda f: p.model.get(f.get("refines")))
    group = picker.items[first.uuid].parent()
    assert group.text(0) == p.model.choice_label(system)  # grouped by the refined system function
    picker._clicked(picker.items[first.uuid], 1)
    picker._clicked(picker.items[second.uuid], 1)
    assert picker.selected == {second.uuid}  # one logical function per derived requirement
    picker.search.setText("telegramma")
    assert not picker.items[first.uuid].isHidden() and picker.items[second.uuid].isHidden()

    import arcadia_tool.ui.srs_trace as srs_trace
    monkeypatch.setattr(srs_trace, "choose_logical_function", lambda project, d, parent=None: second.uuid)
    editor = ElementEditor()
    editor.edit(p, derived, editing=True)
    assert "parent" not in editor.getters and "function" not in editor.getters  # chosen in the windows
    assert editor.widgets["parentItem"].text().startswith("3.4.1")
    editor._choose_function()
    assert editor.widgets["logicalFunction"].text() == p.model.choice_label(second)
    assert derived.get("function") is None and editor.dirty  # in the draft, until «Salva»
    editor.save_changes()
    assert derived.get("function") == second.uuid
    p.close()


def test_derived_requirements_listed_by_a_logical_function_are_migrated(tmp_path):
    from arcadia_tool.model.serialization import dumps

    p, e = build(tmp_path)
    logical = p.new_element("logical_function", name="Conta le boe lette")
    derived = p.new_element("derived_requirement", parent=e["clause"].uuid, obligation="Conta le boe")
    logical.values["derived_requirements"] = [derived.uuid]  # as written by the previous version
    p.update(logical)
    p.save()
    p.close()
    p = Project.open(tmp_path / "p")
    logical, derived = p.model.get(logical.uuid), p.model.get(derived.uuid)
    assert derived.get("function") == logical.uuid
    assert "derived_requirements" not in dumps(logical) and p.is_modified  # written at the next save
    p.close()


def test_derive_from_the_allocation_window(app, tmp_path):
    from arcadia_tool.ui.srs_trace import ALLOCATED, TraceFunctionDialog

    p, e = build(tmp_path)
    system = p.new_element("system_function", name="Calcola la posizione", domain=e["location"].uuid)
    function = p.new_element("logical_function", name="Conta le boe lette", refines=system.uuid)
    orphan = p.new_element("derived_requirement", obligation="Senza voce madre")
    dialog = TraceFunctionDialog(p, function)
    dialog.show_item(orphan.uuid)  # double click: the full text, also of a derived requirement
    assert "Senza voce madre" in dialog.viewer.browser.toPlainText()
    tabs = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert tabs == ["Capitolo 3", "Requisiti derivati senza voce madre"]  # not lost
    derived = dialog.derive(e["clause"], "Conta le boe del gruppo")
    assert derived.get("id") == "3.4.1.3-D1" and dialog.state[derived.uuid] == ALLOCATED
    row = dialog._items[derived.uuid]
    assert not row.isHidden() and row.parent().isExpanded() and row.parent().parent().isExpanded()
    assert dialog.tabs.tabText(0) == "Capitolo 3 · 1 tracciate · 1 derivati"
    dialog.only_derived.setChecked(True)
    assert dialog._items[e["section"].uuid].isHidden() is False  # its parent, to show it
    assert dialog._items[e["other"].uuid].isHidden()
    dialog.reject()  # «Annulla»: the requirement created here is removed
    assert p.model.get(derived.uuid) is None and p.model.get(orphan.uuid) is not None

    dialog = TraceFunctionDialog(p, function)
    derived = dialog.derive(e["clause"], "Conta le boe del gruppo")
    dialog.accept()
    assert derived.get("function") == function.uuid and dialog.created == [derived]
    p.close()


def test_viewer_of_the_trace_window_has_the_theme_background(app, tmp_path):
    """Regression: under the element page (a scroll area) the viewer had a transparent, black background."""
    from arcadia_tool.ui.element_editor import ElementEditor
    from arcadia_tool.ui.theme import BG, apply_theme

    apply_theme(app)
    p, e = build(tmp_path)
    editor = ElementEditor()
    editor.edit(p, e["location"])
    dialog = TraceSrsDialog(p, e["location"], editor)
    dialog.show_item(e["clause"].uuid)
    assert dialog.viewer.grab().toImage().pixelColor(4, 200).name() == BG.lower()
    dialog.viewer.close()
    p.close()


def test_trace_rows_are_coloured(app, tmp_path):
    p, e = build(tmp_path)
    dialog = TraceSrsDialog(p, e["location"])
    row = dialog._items[e["section"].uuid]
    assert row.background(0).style() == Qt.NoBrush
    dialog.click(row, PRINCIPAL)
    principal = row.background(0).color().name()
    dialog.click(row, CONTRIBUTES)
    assert row.background(0).color().name() != principal  # two colours
    dialog.click(row, CONTRIBUTES)
    assert row.background(0).style() == Qt.NoBrush
    p.close()


def test_trace_button_disabled_without_srs_items(app, tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    domain = p.new_element("domain", name="Odometria")
    window = MainWindow()
    window._set_project(p)
    window.tree.select(domain.uuid)
    button = next(b for b in window.editor.findChildren(QPushButton) if b.text().startswith("Traccia"))
    assert not button.isEnabled()
    window.save()
    window.close()
