import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox

import arcadia_tool.ui.model_tree as model_tree
import arcadia_tool.ui.srs_reader as srs_reader
from arcadia_tool.ui.element_editor import ElementEditor
from arcadia_tool.ui.srs_edit_mode import SrsEditMode
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.srs_reader import SrsReader, document_order
from arcadia_tool.ui.theme import apply_theme


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def confirm_yes(monkeypatch):
    monkeypatch.setattr(srs_reader.QMessageBox, "exec", lambda self: QMessageBox.Yes)
    infos = []
    monkeypatch.setattr(model_tree.QMessageBox, "information", lambda *args: infos.append(args[2]))
    return infos


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")

    def req(ident, item_type, parent=None, category=None, text="", title=""):
        return p.new_element("requirement", id=ident, item_type=item_type, parent=parent.uuid if parent else None,
                             category=category, text=text, title=title)

    ch3 = req("3.14", "Capitolo", title="Brake")
    sec = req("3.14.4", "Sezione", ch3, ["Informativa"], title="Standstill supervision")
    r10 = req("3.14.4.10", "Requisito", sec, ["Bordo"], text="Tenth")
    r2 = req("3.14.4.2", "Requisito", sec, ["Bordo"], text="When a movement is detected")
    a = req("3.14.4.2 a)", "Voce", r2, ["Bordo"], text="first item")
    d = req("3.14.4.3", "Requisito", sec, ["Definizione"], text="A definition")
    t = req("3.14.4.4", "Requisito", sec, ["Terra"], text="Trackside only")
    ch7 = req("7.5", "Capitolo", title="Variables")
    var = req("7.5.1.72", "Requisito", ch7, ["Bordo", "Terra"], title="M_MODE", text="Name Onboard mode")
    derived = p.new_element("derived_requirement", parent=r2.uuid, obligation="derived")
    trace = p.new_element("trace_record", requirement=r2.uuid)
    return p, dict(ch3=ch3, sec=sec, r2=r2, r10=r10, a=a, d=d, t=t, var=var, derived=derived, trace=trace)


def test_document_order_and_model_helpers(tmp_path):
    p, e = build(tmp_path)
    ids = [x.get("id") for x in document_order(p.model)]
    assert ids == ["3.14", "3.14.4", "3.14.4.2", "3.14.4.2 a)", "3.14.4.3", "3.14.4.4", "3.14.4.10",
                   "7.5", "7.5.1.72"]
    assert p.model.descendants([e["r2"].uuid]) == {e["r2"].uuid, e["a"].uuid}  # derived requirement excluded
    targets = p.model.descendants([e["r2"].uuid])
    assert {x.uuid for x in p.model.referencing(targets)} == {e["derived"].uuid, e["trace"].uuid}
    p.close()


def test_reader_chapters_filters_and_search(app, tmp_path):
    p, e = build(tmp_path)
    reader = SrsReader(p)
    reader.show()
    tabs = [reader.tabs.tabText(i) for i in range(reader.tabs.count())]
    assert tabs == ["Tutti (9)", "Capitolo 3 (7)", "Capitolo 7 (2)"]
    assert reader.count.text() == "6 voci"

    reader.tabs.setCurrentIndex(2)  # chapter 7
    assert [x.get("id") for x in reader.model.elements] == ["7.5", "7.5.1.72"]
    reader.tabs.setCurrentIndex(0)

    for c, box in reader.category_boxes.items():
        box.setChecked(c == "Terra")
    shown = {x.get("id") for x in reader.model.elements if x.get("item_type") == "Requisito"}
    assert shown == {"3.14.4.4", "7.5.1.72"}
    reader.show_headings.setChecked(False)
    assert all(x.get("item_type") not in ("Capitolo", "Sezione") for x in reader.model.elements)

    reader.show_headings.setChecked(True)
    assert [x.get("id") for x in reader.model.elements] == ["3.14", "3.14.4", "3.14.4.4", "7.5", "7.5.1.72"]

    for box in reader.category_boxes.values():
        box.setChecked(True)
    reader.search.setText("movement")
    # only the matching item, with the headings that contain it
    assert [x.get("id") for x in reader.model.elements] == ["3.14", "3.14.4", "3.14.4.2"]
    assert reader.count.text() == "1 voce"
    p.close()


def test_multiple_selection_and_group_delete(app, tmp_path, confirm_yes):
    p, e = build(tmp_path)
    reader = SrsReader(p)
    reader.show()
    deleted = []
    reader.elements_deleted.connect(lambda: deleted.append(True))
    rows = {x.get("id"): i for i, x in enumerate(reader.model.elements)}
    selection = reader.view.selectionModel()
    for ident in ("3.14.4.2", "3.14.4.3"):
        selection.select(reader.model.index(rows[ident]), QItemSelectionModel.Select)
    assert reader.delete_button.text() == "Elimina selezionate (2)"
    assert not reader.delete_button.isEnabled()  # read-only outside the edit mode
    reader.delete_selected()
    assert not deleted and len(p.model.of_kind("requirement")) == 9

    reader.edit_mode_button.click()
    assert reader.edit_mode.enabled and reader.delete_button.isEnabled()
    reader.delete_selected()
    assert deleted
    remaining = {x.get("id") for x in p.model.of_kind("requirement")}
    assert "3.14.4.2" not in remaining and "3.14.4.2 a)" not in remaining and "3.14.4.3" not in remaining
    assert p.model.get(e["derived"].uuid) is not None  # derived requirements are kept
    reader.reload()
    assert "3.14.4.2" not in {x.get("id") for x in reader.model.elements}
    p.close()


def test_requirement_page_is_read_only_until_edit_mode(app, tmp_path):
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

    p, e = build(tmp_path)
    mode = SrsEditMode()
    editor = ElementEditor(mode)
    editor.show()
    editor.edit(p, e["r2"])
    assert editor.read_only
    text = next(w for w in editor.widget().findChildren(QPlainTextEdit))
    assert text.isReadOnly()
    assert editor.edit_mode_button.isEnabled()
    text.setPlainText("changed while locked")
    editor.flush()
    assert e["r2"].get("text") == "When a movement is detected"

    editor.edit_mode_button.click()  # switch on from the item page
    assert mode.enabled and not editor.read_only
    editor.start_editing()  # and the sheet itself in edit mode
    line = next(w for w in editor.widget().findChildren(QLineEdit) if w.text() == "3.14.4.2")
    assert not line.isReadOnly()
    line.setText("3.14.4.2 bis")
    editor.flush()
    assert e["r2"].get("id") == "3.14.4.2"  # in the draft only, until «Salva»
    editor.save_changes()
    assert e["r2"].get("id") == "3.14.4.2 bis" and not editor.editing

    other = p.new_element("domain")
    editor.edit(p, other)  # other kinds are never locked
    assert not editor.read_only
    mode.set_enabled(False)
    assert not editor.read_only
    editor.close()
    p.close()


def test_tree_blocks_srs_changes_outside_edit_mode(app, tmp_path, confirm_yes):
    p, e = build(tmp_path)
    mode = SrsEditMode()
    tree = model_tree.ModelTree(mode)
    tree.set_project(p)
    tree.create("requirement")
    assert len(p.model.of_kind("requirement")) == 9 and "sola lettura" in confirm_yes[-1]
    tree.select(e["d"].uuid)
    tree._delete_selected()
    assert p.model.get(e["d"].uuid) is not None
    tree.create("derived_requirement", {"parent": e["d"].uuid})  # derived requirements are not SRS items
    assert len(p.model.of_kind("derived_requirement")) == 2
    mode.set_enabled(True)
    tree.create("requirement")
    assert len(p.model.of_kind("requirement")) == 10
    p.close()


def test_open_reader_from_tree_and_delete_all(app, tmp_path, confirm_yes):
    p, e = build(tmp_path)
    window = MainWindow()
    window.show()
    window._set_project(p)
    window.tree.srs_reader_requested.emit()
    assert window.reader is not None and window.pages.currentWidget() is window.reader
    window.reader.open_element.emit(e["var"].uuid)
    assert window.pages.currentWidget() is window.editor and window.editor.element is e["var"]

    window.tree.delete_all_requirements()  # read-only: asks to enable the edit mode (answered No)
    assert len(p.model.of_kind("requirement")) == 9 and not window.srs_edit_mode.enabled
    model_tree.QMessageBox.question = lambda *args: QMessageBox.Yes  # restored by the conftest fixture
    window.tree.delete_all_requirements()
    assert p.model.of_kind("requirement") == [] and window.srs_edit_mode.enabled
    window.pages.setCurrentWidget(window.reader)  # a hidden reader refreshes when it is shown again
    assert window.reader.model.elements == []
    assert window.editor.element is None
    window.save()
    window.close()


def test_double_click_expands_the_whole_branch(app, tmp_path):
    p, e = build(tmp_path)
    tree = model_tree.ModelTree(SrsEditMode())
    tree.set_project(p)
    requirements = tree._kind_items["requirement"]
    group = requirements.parent()
    _set = model_tree._set_expanded
    _set(group, False)
    requested = []
    tree.srs_reader_requested.connect(lambda: requested.append(1))

    tree._double_clicked(requirements, 0)  # «Voci SRS» opens the catalogue instead
    assert requested == [1] and not requirements.isExpanded()
    tree._double_clicked(group, 0)
    assert model_tree._fully_expanded(group)
    assert tree._items[e["r2"].uuid].isExpanded()  # down to the sub-items
    tree._double_clicked(group, 0)  # already fully expanded: collapses
    assert not group.isExpanded() and not requirements.isExpanded()
    p.close()


def test_reader_context_menu_opens_and_derives(app, tmp_path):
    p, e = build(tmp_path)
    window = MainWindow()
    window.show()
    window._set_project(p)
    window.open_srs_reader()
    menu = window.reader.context_menu(e["r10"])
    actions = {a.text().split(" ")[0]: a for a in menu.actions() if a.text()}
    go, delete = menu.actions()[0], actions["Elimina"]
    assert not delete.isEnabled()  # read-only
    assert "Alloca" in actions and "Deriva" in actions  # a clause: allocation and derivation from its row
    go.trigger()
    assert window.pages.currentWidget() is window.editor and window.editor.element is e["r10"]

    window.open_srs_reader()
    window.reader.context_menu(e["r10"]).actions()[1].trigger()
    derived = window.editor.element
    assert derived.kind == "derived_requirement" and derived.get("parent") == e["r10"].uuid
    assert derived.get("id") == "3.14.4.10-D1" and window.editor.back_label
    window.editor.back_requested.emit(derived.uuid)
    assert window.pages.currentWidget() is window.reader
    assert window.reader.view.currentIndex().data(srs_reader.ELEMENT_ROLE) is e["r10"]
    window.save()
    window.close()


def test_the_catalogue_in_its_own_window(app, tmp_path):
    p, e = build(tmp_path)
    window = MainWindow()
    window.show()
    window._set_project(p)
    window.open_srs_reader()
    reader = window.reader
    assert reader.window_button.text() == "Apri in altra finestra"  # next to «Sola lettura», «Elimina…»
    reader.window_button.click()  # detached: out of the tabs, in a window of its own
    assert window.reader_window is not None and window.reader_window.isVisible()
    assert window.pages.indexOf(reader) < 0 and reader.window() is window.reader_window
    assert reader.isVisible() and reader.view.isVisible()  # shown in it, not an empty window
    assert reader.window_button.text() == "Riporta nelle schede"

    reader.open_element.emit(e["r10"].uuid)  # an item opened from the window: its sheet in the main window
    assert window.pages.currentWidget() is window.editors[e["r10"].uuid]
    window.editor.back_requested.emit(e["r10"].uuid)  # «Torna al catalogo»: back to its window
    assert window.reader_window.isVisible() and window.pages.indexOf(reader) < 0

    reader.window_button.click()  # back to the tabs
    assert window.reader_window is None and window.pages.indexOf(reader) >= 0 and window.reader is reader
    assert reader.window_button.text() == "Apri in altra finestra"

    window.tree.srs_window_requested.emit()  # right click on «Voci SRS» › Apri in altra finestra
    assert window.reader_window is not None and window.reader is reader and window.pages.indexOf(reader) < 0
    window.reader_window.close()  # closing the window closes the catalogue, as closing its tab does
    assert window.reader is None and window.reader_window is None

    window.open_srs_window()  # directly in a window, also when the catalogue was not open
    assert window.reader_window is not None
    window._set_project(None)  # the project closes: its window too
    assert window.reader is None and window.reader_window is None
    window.close()


def test_external_actors_come_before_the_domains_in_the_tree(tmp_path):
    p, _ = build(tmp_path)
    tree = model_tree.ModelTree()
    tree.set_project(p)
    group = tree._kind_items["domain"].parent()
    kinds = [group.child(i).data(0, model_tree.KIND_ROLE) for i in range(group.childCount())]
    assert kinds[:3] == ["external_actor", "domain", "system_function"]


def test_tree_menu_offers_the_separate_window(app, tmp_path, monkeypatch):
    p, _ = build(tmp_path)
    tree = model_tree.ModelTree()
    tree.set_project(p)
    tree.resize(400, 600)
    tree.show()
    app.processEvents()
    shown = []

    class RecordedMenu(model_tree.QMenu):
        def exec(self, *args):  # not shown: its entries are recorded
            shown.append([a.text() for a in self.actions()])
    monkeypatch.setattr(model_tree, "QMenu", RecordedMenu)
    item = tree._kind_items["requirement"]
    tree._context_menu(tree.tree.visualItemRect(item).center())
    assert "Apri in altra finestra" in shown[0]


def test_import_srs_is_in_the_menu_of_the_srs_items_not_in_the_toolbar(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QToolBar
    from arcadia_tool.ui.main_window import MainWindow

    p, _ = build(tmp_path)
    window = MainWindow()
    window._set_project(p)
    assert "Importa SRS…" not in [a.text() for a in window.findChildren(QToolBar)[0].actions()]
    menus = []

    class RecordedMenu(model_tree.QMenu):
        def exec(self, *args):
            menus.append({a.text(): a for a in self.actions()})
    monkeypatch.setattr(model_tree, "QMenu", RecordedMenu)
    opened = []
    monkeypatch.setattr(window, "import_srs", lambda: opened.append(True))
    window.tree.import_requested.disconnect()
    window.tree.import_requested.connect(window.import_srs)
    tree = window.tree
    tree._context_menu(tree.tree.visualItemRect(tree._kind_items["requirement"]).center())
    assert list(menus[0])[0] == "Importa SRS…"
    menus[0]["Importa SRS…"].trigger()
    assert opened == [True]
    window._set_project(None)
    window.close()
