import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QTabBar

import arcadia_tool.ui.versions as versions
from arcadia_tool.diff import semantic
from arcadia_tool.model.schema import KINDS
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.diff_view import DiffView, change_html
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.theme import apply_theme

AUTHOR = "Tester <tester@example.com>"


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def diff_calls(monkeypatch):
    calls = []
    original = semantic.diff_models

    def counting(before, after):
        calls.append(1)
        return original(before, after)

    monkeypatch.setattr(versions, "diff_models", counting)
    return calls


def test_editing_every_kind_and_saving_never_computes_a_diff(app, tmp_path, diff_calls):
    window = MainWindow()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    project = window.project
    for k in KINDS:
        if k.name == "diagram":
            continue  # a graphic view opens its drawing, not a sheet (see test_diagrams)
        element = project.new_element(k.name)
        window._select(element)  # its own tab, as when it is opened from the model tree
        # A new element opens in edit mode; an SRS item (imported) read-only even when not saved yet.
        assert window.editor.editing != (k.name == "requirement")
        window.editor.start_editing()
        line = next((w for w in window.editor.widget().findChildren(QLineEdit) if not w.isReadOnly()), None)
        if line is not None:
            line.setText(f"X-{k.name}")
            assert window.editor.dirty
        window.editor.save_changes()  # «Salva» of the sheet: applied and saved
        assert project.model.get(element.uuid) is element and not window.editor.editing
        if line is not None:
            assert f"X-{k.name}" in element.values.values()
    assert not project.is_modified and not window.save_action.isEnabled()
    assert diff_calls == []
    window.close()


def test_sheets_open_read_only_and_apply_changes_only_with_save(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from arcadia_tool.ui import element_editor

    window = MainWindow()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    p = window.project
    domain = p.new_element("domain", name="Odometria")
    p.save()  # not new any more: it opens read-only
    window.tree.reload()
    window.tree.select(domain.uuid)
    editor = window.editor
    assert not editor.editing and editor.modify_button.text() == "Modifica"
    name = next(w for w in editor.widget().findChildren(QLineEdit) if w.text() == "Odometria")
    assert name.isReadOnly()
    asked = []
    monkeypatch.setattr(element_editor.QMessageBox, "question",
                        lambda *args: asked.append(args[1]) or QMessageBox.Yes)
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    app.sendEvent(name, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a"))  # trying to type
    assert asked == ["Scheda in sola lettura"] and name.text() == "Odometria"
    app.processEvents()  # the switch to edit mode happens right after the question
    assert editor.editing
    name = next(w for w in editor.widget().findChildren(QLineEdit) if w.text() == "Odometria")
    name.setText("Odometria e localizzazione")
    assert editor.dirty and window.pages.tabText(0).startswith("● ")  # changes not saved
    editor.flush()
    assert domain.get("name") == "Odometria"  # not applied without «Salva»

    answers = iter(["cancel", "Scarta"])  # what the user clicks in the «save or discard?» question
    clicked = {}

    def ask(box):
        wanted = next(answers)
        clicked[box] = next(b for b in box.buttons() if (box.buttonRole(b) == QMessageBox.RejectRole
                                                       if wanted == "cancel" else b.text() == wanted))
    monkeypatch.setattr(element_editor.QMessageBox, "exec", ask)
    monkeypatch.setattr(element_editor.QMessageBox, "clickedButton", lambda box: clicked[box])
    window._close_page(0)  # closing with changes in progress: «Annulla» keeps the tab open
    assert window.pages.count() == 1 and editor.dirty
    window._close_page(0)  # «Scarta»: closed, nothing applied
    assert window.pages.count() == 0 and domain.get("name") == "Odometria"

    window.tree.clear_selection()
    window.tree.select(domain.uuid)
    window.editor.start_editing()
    next(w for w in window.editor.widget().findChildren(QLineEdit) if w.text() == "Odometria").setText("Odo")
    window.editor.save_changes()
    assert domain.get("name") == "Odo" and not window.editor.editing and not p.is_modified  # saved to disk
    window.close()


def test_element_tab_named_after_the_element_and_closable(app, tmp_path):
    window = MainWindow()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    assert window.pages.count() == 0  # nothing opened yet: no tab, the logo instead
    assert window.work_area.currentWidget() is window.no_pages
    domain = window.project.new_element("domain", name="Odometria")
    window.tree.reload()
    window.tree.select(domain.uuid)
    assert window.pages.count() == 1 and window.pages.tabText(0) == "DF01 Odometria"
    assert window.work_area.currentWidget() is window.pages
    bar = window.pages.tabBar()
    assert window.pages.tabsClosable() and any(  # the «x», on the side chosen by the style
        bar.tabButton(0, side) is not None for side in (QTabBar.LeftSide, QTabBar.RightSide))
    name = next(w for w in window.editor.widget().findChildren(QLineEdit) if w.text() == "Odometria")
    name.setText("Odometria e localizzazione")
    window.editor.save_changes()
    assert window.pages.tabText(0) == "DF01 Odometria e localizzazione"
    window._close_page(0)
    assert window.pages.count() == 0 and window.editor.element is None
    assert window.work_area.currentWidget() is window.no_pages
    window.tree.select(domain.uuid)  # the same element opens again
    assert window.pages.count() == 1 and window.editor.element is domain
    window.save()
    window.close()


def test_one_tab_per_element_closed_only_by_the_user(app, tmp_path, monkeypatch):
    window = MainWindow()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    p = window.project
    domain = p.new_element("domain", name="Odometria")
    system = p.new_element("system_function", name="Calcola", domain=domain.uuid)
    window.tree.reload()
    window.tree.select(domain.uuid)
    window.tree.select(system.uuid)
    assert [window.pages.tabText(i) for i in range(window.pages.count())] == ["DF01 Odometria", "SF-DF01-01 Calcola"]
    window._select(None)  # a click on a group of the tree: the tabs stay open
    assert window.pages.count() == 2 and window.editor.element is system
    window.tree.select(domain.uuid)  # already open: its tab comes forward, no new tab
    assert window.pages.count() == 2 and window.editor.element is domain
    assert "include" not in window.editor.widgets and "exclude" not in window.editor.widgets
    p.delete_element(system.uuid)  # a deleted element closes its tab
    window._model_changed()
    assert window.pages.count() == 1 and p.model.get(system.uuid) is None
    window.save()
    window.close()


def test_logical_function_parent_and_component_are_chosen_in_windows(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.ui.element_editor import ElementEditor

    p = Project.create(tmp_path / "p", "Prova")
    system = p.new_element("system_function", name="Calcola")
    parent = p.new_element("logical_function", name="Gestisce le boe", refines=system.uuid)
    child = p.new_element("logical_function", name="Conta le boe", refines=system.uuid)
    component = p.new_element("logical_component", name="Odometria")
    offered = {}

    def choose(project, element, field, parent_widget=None):
        f = element.schema.field(field)
        offered[field] = [e for e in project.model.of_kind(*f.ref_kinds) if e.uuid != element.uuid]
        return {"parent": parent.uuid, "component": component.uuid}[field]
    monkeypatch.setattr(srs_trace, "choose_element", choose)
    editor = ElementEditor()
    editor.edit(p, child, editing=True)
    assert not isinstance(editor.widgets["parent"], type(editor.widgets.get("refines")))  # no drop-down
    editor._pick(child.schema.field("parent"))
    editor._pick(child.schema.field("component"))
    editor.save_changes()
    assert child.get("parent") == parent.uuid and child.get("component") == component.uuid
    assert child not in offered["parent"]  # a function is not its own parent
    p.close()


@pytest.mark.parametrize("choice", ["Mantieni", "Rimuovi tutto"])
def test_project_menu_cleans_the_project(app, tmp_path, monkeypatch, choice):
    from PySide6.QtWidgets import QMessageBox

    window = MainWindow()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    p = window.project
    menus = [a.text() for a in window.menuBar().actions()]
    assert menus[:2] == ["&File", "&Progetto"]
    project_menu = window.menuBar().actions()[1].menu()
    assert [a.text() for a in project_menu.actions() if a.text()] == [
        "Chiudi progetto", "Pulisci progetto…", "Rimuovi tutte le voci SRS…", "Ricarica dal repository…",
        "Migra repository…", "Verifica modello", "Impostazioni verifiche…", "Impostazioni…"]
    assert not window.remove_srs_action.isEnabled()  # no SRS items yet
    domain = p.new_element("domain", name="Odometria")
    item = p.new_element("requirement", id="3.4.1", item_type="Sezione", primary_domain=domain.uuid)
    p.new_element("system_function", name="Calcola", domain=domain.uuid)
    window._model_changed()
    assert window.remove_srs_action.isEnabled() and window.clean_action.isEnabled()

    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(
        b for b in self.buttons() if b.text().startswith(choice)))
    window.clean_project()
    left = list(p.model)
    if choice == "Mantieni":
        assert left == [item] and item.get("primary_domain") is None  # no reference to a removed domain
    else:
        assert left == [] and not window.remove_srs_action.isEnabled()
    window.save()
    window.close()


def test_publish_and_compare_compute_the_diff_on_request(app, tmp_path, diff_calls):
    project = Project.create(tmp_path / "p", "Prova")
    dom = project.new_element("domain")
    dom.set("id", "DF06")
    project.update(dom)

    dialog = versions.PublishDialog(project)
    assert len(diff_calls) == 1 and dialog.publish_button.isEnabled()
    dialog.message.setPlainText("Prima pubblicazione")
    dialog.author_name.setText("Tester")
    dialog.author_email.setText("tester@example.com")
    dialog._publish()
    assert dialog.sha and not project.is_modified

    empty = versions.PublishDialog(project)
    assert not empty.publish_button.isEnabled()

    sf = project.new_element("system_function")
    sf.set("id", "SF-DF06-04")
    sf.set("domain", dom.uuid)
    sf.set("mode_availability", {"SB": "X"})
    project.update(sf)
    v1 = dialog.sha
    calls_before = len(diff_calls)
    compare = versions.CompareDialog(project)
    assert len(diff_calls) == calls_before  # opening the dialog alone does not compare
    compare.compare()
    assert len(diff_calls) == calls_before + 1
    preset = versions.CompareDialog(project, v1, versions.WORKING)
    assert len(diff_calls) == calls_before + 2
    history = versions.HistoryDialog(project)
    assert history.table.rowCount() == 1
    project.close()


def test_automatic_id_in_editor_and_import_dialog(app, tmp_path):
    from arcadia_tool.importers.srs_pdf import Classification, SrsItem
    from arcadia_tool.ui.import_srs import ImportSrsDialog

    window = MainWindow()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    project = window.project
    df = project.new_element("domain")
    window.tree.reload()
    window.tree.create("system_function", {"domain": df.uuid})
    sf = window.tree.current_element()
    assert sf.get("id") == "SF-DF01-01"
    assert window.editor.id_edit.isReadOnly() and window.editor.id_edit.text() == "SF-DF01-01"
    assert not window.editor.renumber_button.isVisible()

    dialog = ImportSrsDialog(project, window)
    chapters = {3: [SrsItem("3.14", "Capitolo", title="Supervise"),
                    SrsItem("3.14.4", "Sezione", title="Standstill supervision"),
                    SrsItem("3.14.4.2", "Requisito", text="When a movement is detected")]}
    dialog._on_done(chapters, {"3.14.4.2": Classification(["Bordo"])})
    assert dialog.import_button.isEnabled()
    dialog._apply()
    assert dialog.created == 3
    window.tree.reload()
    req = next(e for e in project.model.of_kind("requirement") if e.get("id") == "3.14.4.2")
    item = window.tree._items[req.uuid]
    assert item.parent().data(0, Qt.UserRole + 1) is not None  # nested under its section
    window.tree.filter.setText("movement")
    assert not item.isHidden()
    window.save()  # otherwise closing asks whether to save
    window.close()


def test_import_results_survive_the_worker_thread(app, tmp_path, monkeypatch):
    """Regression: chapters (keyed by number) were lost when sent through the Qt signal."""
    import arcadia_tool.ui.import_srs as import_srs
    from arcadia_tool.importers.srs_pdf import Classification, SrsItem

    monkeypatch.setattr(import_srs, "parse_chapter", lambda path, progress=None, *args: [
        SrsItem("3.14.4", "Sezione", title="Standstill supervision"),
        SrsItem("3.14.4.2", "Requisito", text="When a movement is detected")])
    monkeypatch.setattr(import_srs, "parse_classification",
                        lambda path, progress=None, *args: {"3.14.4.2": Classification(["Bordo"])})
    project = Project.create(tmp_path / "p", "Prova")
    dialog = import_srs.ImportSrsDialog(project)
    dialog.add_paths(["SUBSET-026-3 v360.pdf", "SUBSET-026-9 v360.pdf"])
    dialog._analyse()
    dialog.worker.wait(10000)
    for _ in range(50):
        app.processEvents()
        if dialog.plan is not None:
            break
    assert dialog.plan is not None
    assert {p.id for p in dialog.plan.new} == {"3.14.4", "3.14.4.2"}
    assert dialog.import_button.isEnabled()
    project.close()


def test_analysis_in_progress_can_be_cancelled(app, tmp_path, monkeypatch):
    import time
    import arcadia_tool.ui.import_srs as import_srs

    def slow_parse(path, progress=None, *args):
        for page in range(1, 1000):
            time.sleep(0.01)
            progress(page, 999)
        return []

    monkeypatch.setattr(import_srs, "parse_chapter", slow_parse)
    project = Project.create(tmp_path / "p", "Prova")
    dialog = import_srs.ImportSrsDialog(project)
    dialog.add_paths(["SUBSET-026-3 v360.pdf"])
    dialog._analyse_clicked()
    assert dialog.analysing() and dialog.analyse_button.text() == "Interrompi importazione"
    assert not dialog.add_button.isEnabled()
    time.sleep(0.1)
    dialog._analyse_clicked()  # «Interrompi importazione»
    dialog.worker.wait(5000)
    for _ in range(20):
        app.processEvents()
    assert not dialog.analysing()
    assert dialog.analyse_button.text() == "Importa" and dialog.add_button.isEnabled()
    assert dialog.plan is None and not dialog.import_button.isEnabled()

    dialog._analyse_clicked()  # Annulla while analysing: interrupts and closes, nothing imported
    assert dialog.analysing()
    dialog.reject()
    assert not dialog.analysing() and len(project.model) == 0
    project.close()


def test_diff_view_renders_every_change(app, tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    fc = project.new_element("functional_chain")
    fc.set("steps", [{"cycle": "C0", "what": "riceve"}])
    sf = project.new_element("system_function")
    sf.set("description", "Supervisiona il fermo")
    sf.set("mode_availability", {"SB": "X"})
    project.update(fc)
    project.update(sf)
    v1 = project.publish("v1", AUTHOR)
    sf.set("mode_availability", {"SB": "O", "FS": "X"})
    sf.set("description", "Supervisiona lo stato di fermo del treno")
    fc.set("steps", [{"cycle": "C1", "what": "riceve"}, {"what": "Attesa"}])
    project.update(sf)
    project.update(fc)
    diff = semantic.diff_models(project.published_model(v1), project.model)
    view = DiffView(diff, "a", "b")
    assert view.tree.topLevelItemCount() == 2
    for change in diff.changes:
        assert "<table" in change_html(diff, change)
    project.close()
