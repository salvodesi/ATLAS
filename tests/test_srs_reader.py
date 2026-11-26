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
    # The titles and sections: always, those containing what is shown.
    assert [x.get("id") for x in reader.model.elements] == ["3.14", "3.14.4", "3.14.4.4", "7.5", "7.5.1.72"]

    for box in reader.category_boxes.values():
        box.setChecked(True)
    reader.search.setText("movement")
    # only the matching item, with the headings that contain it
    assert [x.get("id") for x in reader.model.elements] == ["3.14", "3.14.4", "3.14.4.2"]
    assert reader.count.text() == "1 voce"
    p.close()


def test_a_large_catalogue_opens_with_a_loading_bar_and_measures_figures_without_decoding_them(app, tmp_path,
                                                                                              monkeypatch):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    p = Project.create(tmp_path / "p", "Prova")
    section = p.new_element("requirement", id="3.1", item_type="Sezione", sequence=0)
    for n in range(1, srs_reader.SLOW_LAYOUT_ITEMS + 60):
        p.new_element("requirement", id=f"3.1.{n}", item_type="Requisito", parent=section.uuid, sequence=n,
                      text=f"Il treno deve fare la cosa numero {n}.")
    image = QImage(320, 160, QImage.Format_RGB32)
    image.fill(0xFFFFFF)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    figure = p.new_element("requirement", id="3.1.999", item_type="Voce", parent=section.uuid, sequence=999,
                           title="Figura 1", figure="assets/srs/figura1.png")
    p.set_asset("assets/srs/figura1.png", bytes(buffer.data()))  # not saved yet: read from memory
    steps = []

    class RecordedLoading(srs_reader.QProgressDialog):
        def setValue(self, value):
            super().setValue(value)
            steps.append((value, self.maximum(), self.labelText(), self.isVisible()))
    monkeypatch.setattr(srs_reader, "QProgressDialog", RecordedLoading)
    reader = SrsReader(p)
    reader.resize(900, 700)
    reader.show()
    total = srs_reader.SLOW_LAYOUT_ITEMS + 61  # the items and their section
    assert steps and steps[-1][:2] == (total, total) and all(shown for *_rest, shown in steps)
    assert f"{total} di {total} voci" in steps[-1][2]
    assert not [w for w in app.topLevelWidgets() if isinstance(w, RecordedLoading) and w.isVisible()]
    delegate = reader.view.itemDelegate()
    # The height of the figure is from its size, read from the header of the image: decoded only to paint it.
    assert delegate._figure_sizes[figure.uuid] == (320, 160) and figure.uuid not in delegate._pixmaps
    width = reader.view.viewport().width()
    caption = p.new_element("requirement", id="3.1.998", item_type="Voce", parent=section.uuid, title="Figura 1")
    delegate.measure([caption])
    # Shown at 1/1.6 of its pixels: 100 px higher than the same item without the figure.
    assert delegate._sizes[(figure.uuid, width, "")].height() >= delegate._sizes[(caption.uuid, width, "")].height() + 100
    steps.clear()
    reader.refresh()  # measured already: no loading bar
    assert not steps
    reader.search.setText("il treno")  # a search: all the items found measured again, without the loading bar
    assert reader.count.text() == f"{srs_reader.SLOW_LAYOUT_ITEMS + 59} voci" and not steps
    reader.search.clear()
    row = next(i for i, e in enumerate(reader.model.elements) if e.uuid == figure.uuid)
    reader.view.scrollTo(reader.model.index(row))
    reader.view.viewport().grab()  # painted: its image is loaded now
    assert not delegate._pixmaps[figure.uuid].isNull()
    reader.close()


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
    go, delete = actions["Apri"], actions["Elimina"]
    assert not delete.isEnabled()  # read-only
    assert "Mappa" in actions and "Deriva" in actions  # a clause: allocation and derivation from its row
    go.trigger()
    assert window.pages.currentWidget() is window.editor and window.editor.element is e["r10"]

    window.open_srs_reader()
    window.reader.derive_requested.emit(e["r10"].uuid)  # one requirement derived from the item, in its sheet
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


def test_a_click_on_an_srs_item_in_the_tree_goes_to_its_row_on_the_tab_of_its_chapter(app, tmp_path):
    p, e = build(tmp_path)
    window = MainWindow()
    window.show()
    window._set_project(p)
    tree = window.tree
    for key, chapter in (("var", 7), ("r2", 3), ("a", 3)):  # «Tutti» at first, then from another chapter
        item = tree._items[e[key].uuid]
        tree.tree.setCurrentItem(item)
        tree._clicked(item, 0)
        app.processEvents()
        reader = window.reader
        assert window.pages.currentWidget() is reader and reader.chapter == chapter
        assert reader.tabs.tabData(reader.tabs.currentIndex()) == chapter
        assert reader.view.currentIndex().data(srs_reader.ELEMENT_ROLE) is e[key]  # its row, selected
        assert tree.tree.currentItem() is item  # the tree keeps it: the next click is on another one
    tree._clicked(tree._items[e["derived"].uuid], 0) if e["derived"].uuid in tree._items else None
    assert reader.view.currentIndex().data(srs_reader.ELEMENT_ROLE) is e["a"]  # not an SRS item: nothing moves
    window._set_project(None)
    window.close()


def test_the_adr_not_yet_approved_about_an_item_are_badges_of_its_row(app, tmp_path):
    from arcadia_tool.model.schema import ADR_EXCLUSION, ADR_OTHER, ADR_SHARED

    p, e = build(tmp_path)
    shared = p.new_element("adr", id="ADR-012", title="Condivisione", adr_type=ADR_SHARED, status="Proposta",
                           shared_items=[e["r2"].uuid])
    review = p.new_element("adr", id="ADR-003", title="Altro", adr_type=ADR_OTHER, status="In revisione DA",
                           srs_items=[e["r2"].uuid, e["a"].uuid])
    p.new_element("adr", id="ADR-020", adr_type=ADR_OTHER, status="Decisa", srs_items=[e["r10"].uuid])
    p.new_element("adr", id="ADR-021", adr_type=ADR_EXCLUSION, status="Proposta", da_decision="Respinta",
                  excluded_item=[e["r10"].uuid])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window._set_project(p)
    window.go_to_srs_item(e["r2"].uuid)
    app.processEvents()
    reader = window.reader
    delegate = reader.delegate
    texts = lambda key: [srs_reader.adr_badge_text(a) for a in delegate.adr_badges(e[key])]
    assert texts("r2") == ["ADR-003 - In revisione DA", "ADR-012 - Proposta"]  # by their ID
    assert texts("a") == ["ADR-003 - In revisione DA"]
    assert texts("r10") == ["ADR-021 - Respinta"]  # decided: none; rejected: shown, it is not approved
    index = reader.view.currentIndex()
    assert index.data(srs_reader.ELEMENT_ROLE) is e["r2"]
    rect = reader.view.visualRect(index)
    chips = delegate._layout(e["r2"], rect)[3]
    places = chips[4]
    assert [adr for _box, adr in places] == [review, shared]
    assert all(box.right() <= rect.right() for box, _adr in places)  # in the column of the categories
    assert places[0][0].top() > chips[1]  # under the chip of its category
    tip = delegate.badge_tip(index, places[1][0].center())
    assert tip.startswith("ADR-012 - Proposta: Condivisione") and "clic per aprirla" in tip
    opened = []
    reader.open_element.connect(opened.append)
    reader.run_action(shared.uuid, srs_reader.OPEN_ADR)  # what a click on the badge does
    assert opened == [shared.uuid]
    previous = shared.copy()
    shared.set("status", "Decisa")  # approved: its badge goes
    p.update(shared, previous)
    reader.element_changed(shared)
    assert texts("r2") == ["ADR-003 - In revisione DA"]
    assert not reader.grab().isNull()  # drawn
    window._set_project(None)
    window.close()


def test_the_list_to_show_the_items_with_an_adr_in_a_state(app, tmp_path):
    from arcadia_tool.model.schema import ADR_OTHER, ADR_SECTION

    p, e = build(tmp_path)
    p.new_element("adr", id="ADR-001", adr_type=ADR_OTHER, status="Proposta", srs_items=[e["r2"].uuid])
    p.new_element("adr", id="ADR-002", adr_type=ADR_SECTION, status="Revisionato DA", realloc_item=[e["sec"].uuid])
    p.new_element("adr", id="ADR-004", adr_type=ADR_OTHER, status="Revisionato DA", da_decision="Commenti DA",
                  srs_items=[e["t"].uuid])
    p.new_element("adr", id="ADR-005", adr_type=ADR_OTHER, status="Decisa", da_decision="Accolta con modifiche",
                  srs_items=[e["d"].uuid])  # approved: in no state of the list
    decided = p.new_element("adr", id="ADR-003", adr_type=ADR_OTHER, status="Decisa", srs_items=[e["var"].uuid])
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window._set_project(p)
    window.open_srs_reader()
    app.processEvents()
    reader = window.reader
    combo = reader.adr_view
    shown = lambda: [x.get("id") for x in reader.model.elements]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Tutte", "Proposta (1)", "In revisione DA (0)", "Revisionato DA (1)", "Commenti DA (1)",
        "Superata (0)"]  # not «Accolta» nor «Accolta con modifiche», nor «Respinta»
    assert combo.currentData() is None and "3.14.4.3" in shown()  # «Tutte»: every item
    combo.setCurrentIndex(combo.findData("Proposta"))
    assert shown() == ["3.14", "3.14.4", "3.14.4.2"]
    combo.setCurrentIndex(combo.findData("Revisionato DA"))
    assert shown() == ["3.14", "3.14.4"]  # the section, with an ADR of its own
    combo.setCurrentIndex(combo.findData("Commenti DA"))
    assert shown() == ["3.14", "3.14.4", "3.14.4.4"]
    combo.setCurrentIndex(combo.findData("Proposta"))
    previous = decided.copy()
    decided.set("status", "Proposta")  # back to proposed: its item comes in
    p.update(decided, previous)
    reader.element_changed(decided)
    assert shown() == ["3.14", "3.14.4", "3.14.4.2", "7.5", "7.5.1.72"] and combo.itemText(1) == "Proposta (2)"
    reader.go_to(e["r10"].uuid)  # from outside, an item without an ADR: «Tutte» again
    assert combo.currentData() is None and "3.14.4.10" in shown()
    window._set_project(None)
    window.close()


def test_the_selected_row_stays_when_a_filter_is_set_or_removed(app, tmp_path):
    p, e = build(tmp_path)
    window = MainWindow()
    window.resize(1400, 500)  # short: the list scrolls
    window.show()
    window._set_project(p)
    for n in range(40):  # many clauses before the one selected
        p.new_element("requirement", id=f"3.14.4.{20 + n}", item_type="Requisito", parent=e["sec"].uuid,
                      category=["Bordo"], text=f"Clausola {n}")
    p.new_element("requirement", id="3.14.4.99", item_type="Requisito", parent=e["sec"].uuid, category=["Terra"],
                  text="Selected")
    window._model_changed()
    window.open_srs_reader()
    app.processEvents()
    reader = window.reader
    target = next(x for x in p.model.of_kind("requirement") if x.get("id") == "3.14.4.99")
    reader.reveal(target.uuid)
    app.processEvents()
    current = lambda: reader.view.currentIndex().data(srs_reader.ELEMENT_ROLE)
    visible = lambda: reader.view.viewport().rect().intersects(
        reader.view.visualRect(reader.model.index(reader.model.elements.index(target))))
    reader.category_boxes["Bordo"].setChecked(False)  # a filter that keeps it
    app.processEvents()
    assert current() is target and reader.selected_elements() == [target] and visible()
    reader.category_boxes["Bordo"].setChecked(True)  # removed: still on its row, not on the first of the chapter
    app.processEvents()
    assert current() is target and reader.selected_elements() == [target] and visible()
    assert reader.view.verticalScrollBar().value() > 0
    reader.category_boxes["Terra"].setChecked(False)  # a filter that hides it: nothing selected
    app.processEvents()
    assert reader.selected_elements() == []
    window._set_project(None)
    window.close()


def test_the_categories_are_a_list_with_ticks_between_requisiti_and_the_state_of_the_adr(app, tmp_path):
    p, e = build(tmp_path)
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window._set_project(p)
    window.open_srs_reader()
    app.processEvents()
    reader = window.reader
    pick = reader.category_pick
    row = next(reader.layout().itemAt(1).widget().layout().itemAt(i).layout()
               for i in range(reader.layout().itemAt(1).widget().layout().count())
               if reader.layout().itemAt(1).widget().layout().itemAt(i).layout() is not None
               and reader.layout().itemAt(1).widget().layout().itemAt(i).layout().indexOf(pick) >= 0)
    assert row.indexOf(reader.scope) < row.indexOf(pick) < row.indexOf(reader.adr_view)
    assert pick.currentText() == "Tutte" and reader.category_boxes["Bordo"].text() == "Bordo (4)"
    reader.category_boxes["Terra"].setChecked(False)
    assert pick.currentText() == "Bordo e altre 4" and "3.14.4.4" not in [x.get("id") for x in reader.model.elements]
    for c, box in reader.category_boxes.items():
        box.setChecked(c == "Definizione")
    assert pick.currentText() == "Definizione"
    assert [x.get("id") for x in reader.model.elements if x.get("item_type") == "Requisito"] == ["3.14.4.3"]
    for box in reader.category_boxes.values():
        box.setChecked(False)
    assert pick.currentText() == "Nessuna"
    window._set_project(None)
    window.close()


def test_a_click_on_a_derived_requirement_opens_it_and_a_section_shows_its_adr(app, tmp_path):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from arcadia_tool.model.schema import ADR_SECTION

    p, e = build(tmp_path)
    adr = p.new_element("adr", id="ADR-030", title="Sezione", adr_type=ADR_SECTION, status="Proposta",
                        realloc_item=e["sec"].uuid)
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window._set_project(p)
    window.go_to_srs_item(e["r2"].uuid)
    app.processEvents()
    reader, delegate = window.reader, window.reader.delegate
    opened = []
    reader.open_element.connect(opened.append)

    def click(point):
        for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            event = QMouseEvent(kind, QPointF(point), QPointF(reader.view.viewport().mapToGlobal(point)),
                                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(reader.view.viewport(), event)
        app.processEvents()
    # The purple badge of the derived requirement of 3.14.4.2: its sheet, not the one of the clause.
    index = reader.view.currentIndex()
    rect = reader.view.visualRect(index)
    text_box = delegate._layout(e["r2"], rect)[-2][0]
    badges = reader._link_badges(e["r2"])
    n = next(i for i, b in enumerate(badges) if b[1] == "derived")
    chip = delegate._badge_places(text_box, badges)[n][0]
    assert delegate.link_at(index, chip.center()) == e["derived"].uuid
    click(chip.center())
    assert opened == [e["derived"].uuid]
    assert "clic per aprirlo" in delegate.badge_tip(index, chip.center())
    # The ADR about a section (3.14.4): its badge on the row of the section, right-aligned, clickable.
    assert [x.uuid for x in delegate.adr_badges(e["sec"])] == [adr.uuid]
    section_index = reader.model.index(next(r for r in range(reader.model.rowCount())
                                            if reader.model.index(r, 0).data(srs_reader.ELEMENT_ROLE) is e["sec"]), 0)
    reader.view.scrollTo(section_index)
    app.processEvents()
    section_rect = reader.view.visualRect(section_index)
    chips = delegate._layout(e["sec"], section_rect)[3]
    assert chips is not None and chips[2] == []  # no categories on a heading: the ADR only
    box, shown = chips[4][0]
    assert shown is adr and box.right() <= section_rect.right()
    assert delegate.adr_at(section_index, box.center()) is adr
    click(box.center())
    assert opened[-1] == adr.uuid
    assert not reader.grab().isNull()  # drawn
    window._set_project(None)
    window.close()


def test_the_requests_for_clarification_about_an_item_are_badges_of_its_row(app, tmp_path):
    from arcadia_tool.model.schema import ADR_OTHER

    p, e = build(tmp_path)
    adr = p.new_element("adr", id="ADR-003", title="Altro", adr_type=ADR_OTHER, status="Proposta",
                        srs_items=[e["r2"].uuid])
    second = p.new_element("clarification", id="CQ-02", clause=e["r2"].uuid, status="Chiusa", problem="Già chiarita")
    first = p.new_element("clarification", id="CQ-01", clause=e["r2"].uuid, status="Aperta",
                          problem="Il testo non dice quando")
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window._set_project(p)
    window.go_to_srs_item(e["r2"].uuid)
    app.processEvents()
    reader, delegate = window.reader, window.reader.delegate
    texts = lambda key: [srs_reader.adr_badge_text(x) for x in delegate.adr_badges(e[key])]
    assert texts("r2") == ["ADR-003 - Proposta", "CQ-01 - Aperta", "CQ-02 - Chiusa"]  # the ADR, then the CQ by ID
    assert texts("r10") == []
    assert srs_reader.badge_colors(first) == srs_reader.CQ_STATUS_COLORS["Aperta"]
    assert srs_reader.badge_colors(second) == srs_reader.CQ_STATUS_COLORS["Chiusa"]
    index = reader.view.currentIndex()
    places = delegate._layout(e["r2"], reader.view.visualRect(index))[3][4]
    assert [x for _box, x in places] == [adr, first, second]
    tip = delegate.badge_tip(index, places[1][0].center())
    assert tip.startswith("CQ-01 - Aperta: richiesta di chiarimento") and "Il testo non dice quando" in tip
    opened = []
    reader.open_element.connect(opened.append)
    reader.run_action(first.uuid, srs_reader.OPEN_ADR)  # what a click on its badge does
    assert opened == [first.uuid]
    previous = first.copy()
    first.set("status", "Chiusa")  # closed in its sheet: the badge follows
    p.update(first, previous)
    reader.element_changed(first)
    assert texts("r2") == ["ADR-003 - Proposta", "CQ-01 - Chiusa", "CQ-02 - Chiusa"]
    assert not reader.grab().isNull()  # drawn
    window._set_project(None)
    window.close()
