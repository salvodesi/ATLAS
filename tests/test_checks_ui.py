import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QToolBar

from arcadia_tool.checks import CHECKS
from arcadia_tool.checks.config import ChecksConfig, Profile
from arcadia_tool.storage.project import Project
import arcadia_tool.ui.main_window as main_window
from arcadia_tool.ui.checks_settings import CODE_ROLE
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.project_settings import ProjectSettingsDialog
from arcadia_tool.ui.theme import apply_theme
from arcadia_tool.ui.versions import PublishDialog


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def set_checks(project, enabled, params=None, **profile):
    project.update_checks(ChecksConfig({"Predefinito": Profile(list(enabled), dict(params or {}), **profile)}))


def _item(page, code):
    for group in page.groups.values():
        for i in range(group.childCount()):
            if group.child(i).data(0, CODE_ROLE) == code:
                return group.child(i)
    raise KeyError(code)


def test_a_click_on_the_box_of_a_single_check_turns_it_on_and_off(app, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest

    project = Project.create(tmp_path / "p", "Prova")
    dialog = ProjectSettingsDialog(project, section="Verifiche")
    page = dialog.checks_page
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    page.groups["SA2"].setExpanded(True)
    app.processEvents()
    item = _item(page, "SA2-03")
    rect = page.tree.visualItemRect(item)
    box = QPoint(rect.left() + 16, rect.center().y())  # on its icon (drawn 5–20 px after the indentation)

    def click(point):  # the cursor too, where a real click is
        QCursor.setPos(page.tree.viewport().mapToGlobal(point))
        QTest.mouseClick(page.tree.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    click(box)
    assert page.enabled == {"SA2-03"}
    click(QPoint(rect.left() + 60, box.y()))
    assert page.enabled == {"SA2-03"}  # on its code and title: only its details
    click(box)
    assert page.enabled == set()
    dialog.close()


def test_settings_start_with_no_check_and_keep_the_choice(app, tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    dialog = ProjectSettingsDialog(project, section="Verifiche")
    page = dialog.checks_page
    assert dialog.pages.currentWidget().isAncestorOf(page)
    assert page.enabled == set() and "0 controlli attivi" in page.counter.text()
    assert [page.tree.topLevelItem(i).text(0) for i in range(3)] == [
        "Controlli generali", "Voci SRS e matrice sezioni/domini (A4)", "SA-1 Domini funzionali"]
    page._clicked(page.groups["SA2"])  # a whole group
    page._clicked(_item(page, "SA2-03"))  # then one of its checks off
    page._clicked(_item(page, "LA2-02"))
    page.tree.setCurrentItem(_item(page, "IND-03"))  # its details on the right: the threshold
    page.detail.widget().findChildren(QSpinBox)[0].setValue(9)
    assert "personalizzati" in page.counter.text()
    dialog._save()
    assert dialog.checks_changed
    expected = {c.code for c in CHECKS if c.group == "SA2"} - {"SA2-03"} | {"LA2-02"}
    assert set(project.checks.profile.enabled) == expected
    assert (tmp_path / "p" / "checks.yaml").exists() and "checks" not in project.settings

    reopened = Project.open(tmp_path / "p")  # saved in checks.yaml: kept until changed
    stored = reopened.checks.profile
    assert set(stored.enabled) == expected and stored.param("IND-03", "fan_threshold") == 9
    again = ProjectSettingsDialog(reopened, section="Verifiche")
    assert again.checks_page.enabled == expected
    again._save()
    assert not again.checks_changed  # nothing changed: nothing to run again


@pytest.fixture
def problems_shown(monkeypatch):
    shown = []
    monkeypatch.setattr(main_window, "show_check_problems", lambda parent, problems: shown.append(problems))
    return shown


def test_verify_without_checks_or_with_wrong_settings_says_what_is_wrong(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    window = MainWindow()
    window._set_project(project)
    assert window.checks_dock.isVisibleTo(window) and not window.checks_dock.expanded  # there, collapsed
    window.verify_model()
    assert problems_shown == [["Nessuna verifica selezionata: scegli i controlli da eseguire."]]
    assert not window.checks.has_run and not window.checks_dock.expanded

    set_checks(project, ["SA5-13", "SA7-15", "XX-01"], {"SA7-15": {"procedure_domain": "eliminato"}})
    window.verify_model()
    text = " ".join(problems_shown[-1])
    assert "SA5-13" in text and "Domini di codifica" in text and "XX-01" in text
    assert "SA7-15" in text and "Dominio delle procedure" in text and "esistono nel modello" in text
    assert not window.checks.has_run
    window.close()


def test_the_panel_opens_after_a_run_and_stays_open_only_if_pinned(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    project.new_element("system_function", name="Funzione")
    set_checks(project, ["SA2-01"])
    window = MainWindow()
    window._set_project(project)
    dock = window.checks_dock
    assert not dock.expanded and dock.title.text() == "Analisi del modello"  # no run yet
    # The checks run only from the toolbar of the window, not from the panel.
    assert "Verifica modello" in [a.text() for a in window.findChildren(QToolBar)[0].actions()]
    assert not [b for b in dock.findChildren(QPushButton) if "Esegui" in b.text()]
    window.verify_model()  # the run opens the panel
    assert problems_shown == [] and dock.expanded and "1 errore" in dock.title.text()
    app.focusChanged.emit(None, window.tree.tree)  # back from another application (Alt+Tab): still open
    assert dock.expanded
    dialog = QDialog(window)
    app.focusChanged.emit(QLineEdit(dialog), window.tree.tree)  # back from a dialog: still open
    assert dock.expanded
    app.focusChanged.emit(window.tree.tree, dock.panel.search)  # inside the panel itself
    assert dock.expanded
    app.focusChanged.emit(dock.panel.search, window.tree.tree)  # back to work elsewhere: not pinned, it collapses
    assert not dock.expanded

    dock.toggle()
    dock.set_pinned(True)  # the pin next to the ×
    dock.clicked_outside(window.tree)
    assert dock.expanded
    window._set_project(None)
    window._set_project(Project.open(tmp_path / "p"))  # pinned: open also before a run, and kept on this PC
    assert dock.expanded and MainWindow().checks_dock.pinned
    dock.close_panel()  # the ×: collapsed (still there) and no longer pinned
    assert not dock.expanded and not dock.pinned and dock.isVisibleTo(window)
    window.close()


def test_verify_button_below_the_tree_needs_valid_settings(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    window = MainWindow()
    window._set_project(project)
    texts = [b.text() for b in window.tree.findChildren(QPushButton)]
    # In place of «Nuovo» and «Elimina» (still in the context menu); «Nuova vista…» is in «Viste grafiche».
    assert texts == ["Nuova vista…", "Verifica modello"]
    button = window.verify_button
    assert button.property("primary") and not button.isEnabled()
    assert "Nessuna verifica selezionata" in button.toolTip()
    dialog = ProjectSettingsDialog(project, section="Verifiche")
    dialog.checks_page._clicked(_item(dialog.checks_page, "SA5-13"))  # needs the coding domains
    dialog._save()
    window._refresh_state()
    assert not button.isEnabled() and "Domini di codifica" in button.toolTip()
    set_checks(project, ["SA2-01"])
    window._refresh_state()
    assert button.isEnabled()
    button.click()
    assert window.checks.has_run and window.checks_dock.expanded and problems_shown == []
    window.close()


def test_the_collapsed_panel_spans_the_window(app, tmp_path):
    window = MainWindow()
    window.resize(1400, 800)
    window.show()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    app.processEvents()
    dock = window.checks_dock
    assert not dock.expanded
    assert dock.width() >= window.width() - 20 and dock.bar.width() >= window.width() - 20
    window.close()


def test_the_panel_reports_the_sheet_and_opens_it(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    domain = project.new_element("domain", name="Protezione dei movimenti", mission="Impedire i movimenti.")
    function = project.new_element("system_function", name="Supervisionare lo standstill", domain=domain.uuid)
    project.save()
    window = MainWindow()
    window._set_project(project)
    set_checks(project, ["SA2-07", "SA1-03"])
    window.checks.refresh()
    window.verify_model()
    codes = {f.code: f for f in window.checks.findings}
    assert set(codes) == {"SA2-07", "SA1-03"}
    assert codes["SA2-07"].element == function.uuid and codes["SA1-03"].element == domain.uuid
    group = window.checks.tree.topLevelItem(0)
    assert group.text(0) == "SA-1 Domini funzionali"
    sa2 = window.checks.tree.topLevelItem(1)
    finding = sa2.child(0)
    assert finding.text(1) == "SA2-07" and finding.text(2) == project.model.label(function)

    window.checks._open(finding)  # double click: the sheet opens in its tab
    editor = window.editors[function.uuid]
    assert window.pages.currentWidget() is editor
    texts = " ".join(label.text() for label in editor.widget().findChildren(QLabel)).lower()
    assert "sa2-07" in texts and "verifiche" in texts  # and shows its findings at the top

    window.save()  # once run, the checks follow the saved model
    function.set("sections", [project.new_element("requirement", id="3.14.4", item_type="Sezione").uuid])
    project.update(function)
    window.save()
    assert "SA2-07" not in {f.code for f in window.checks.findings}
    window.close()


def test_double_click_goes_to_the_field_and_the_run_shows_its_progress(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    function = project.new_element("system_function", name="Supervisionare lo standstill", is_new=True)
    set_checks(project, ["SA2-01", "SA2-07", "SA2-10"])
    window = MainWindow()
    window.resize(1300, 800)
    window.show()
    window._set_project(project)
    window.verify_model()
    progress = window.checks.progress  # the window shown during the run: check n of N
    assert [s[:2] for s in progress.steps] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    # At the end it stays open with the outcome, until «Chiudi».
    assert progress.isVisible() and "3 controlli eseguiti" in progress.label.text()
    assert progress.close_button.isEnabled() and progress.stop_button.isHidden()  # «Interrompi» only while running
    progress.close_button.click()
    assert not progress.isVisible()

    fields = {f.code: f.field for f in window.checks.findings}
    assert fields == {"SA2-01": "domain", "SA2-07": "@srs", "SA2-10": "new_reason"}
    group = window.checks.tree.topLevelItem(0)
    rows = {group.child(i).text(1): group.child(i) for i in range(group.childCount())}
    for code in ("SA2-01", "SA2-07", "SA2-10"):
        window.checks._open(rows[code])  # double click: the sheet, at the field with the problem
        app.processEvents()
        editor = window.editors[function.uuid]
        target = editor.widgets[fields[code]]
        overlay = editor.highlight
        assert overlay is not None and overlay.isVisible()
        top_left = target.parentWidget().mapTo(editor.widget(), target.geometry().topLeft())
        assert overlay.geometry().contains(top_left), code
    window.close()


def test_the_run_can_be_stopped(app, tmp_path, problems_shown, monkeypatch):
    import arcadia_tool.ui.checks_panel as checks_panel
    project = Project.create(tmp_path / "p", "Prova")
    project.new_element("system_function", name="Funzione", is_new=True)
    set_checks(project, ["SA2-01", "SA2-07", "SA2-10"])
    original = checks_panel.CheckProgress.step

    def step(self, done, total, check):
        if done == 1 and check is not None:
            self.stop_button.click()  # «Interrompi» while the second check is about to run
        return original(self, done, total, check)
    monkeypatch.setattr(checks_panel.CheckProgress, "step", step)
    window = MainWindow()
    window._set_project(project)
    window.verify_model()
    progress = window.checks.progress
    assert progress.stopped and progress.isVisible() and progress.stop_button.isHidden()
    assert "interrotta: eseguiti 1 controlli su 3" in progress.label.text()
    assert {f.code for f in window.checks.findings} == {"SA2-01"}  # only the checks already run
    assert "interrotta" in window.checks.status.text() and "interrotta" in window.checks_dock.title.text()

    window.save()  # once run, the checks follow the saves: all of them, without the window
    assert window.checks.progress is progress and window.checks.stopped_at is None
    assert {f.code for f in window.checks.findings} == {"SA2-01", "SA2-07", "SA2-10"}
    window.close()


def test_errors_do_not_block_the_publication(app, tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    project.new_element("system_function", name="Funzione")
    set_checks(project, ["SA2-01"])
    dialog = PublishDialog(project)
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "1 errore" in texts and "Non bloccano la pubblicazione" in texts
    assert dialog.publish_button.isEnabled()


class _User:
    def __init__(self, full_name):
        self.full_name, self.username, self.email = full_name, "u", "u@example.org"


def test_only_the_design_authority_accepts_a_finding_as_an_exception(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    function = project.new_element("system_function", name="Funzione")
    project.new_element("team", id="T1", name="DA", members=["Anna Bianchi"], design_authority=True)
    set_checks(project, ["SA2-01"])
    window = MainWindow()
    window._set_project(project)
    window.set_user(_User("Mario Rossi"))
    window.verify_model()
    [finding] = window.checks.findings
    assert window.checks.design_authority() is None  # not a member of the DA: the menu entry is disabled
    window.checks._ask_exception(finding)
    assert not window.checks.findings[0].waived

    window.set_user(_User("Anna Bianchi"))
    assert window.checks.design_authority() == "Anna Bianchi"
    window.checks.accept_exception(finding, "Funzione di prova", "Anna Bianchi")
    assert window.checks.findings[0].waived and window.checks.findings_for(function.uuid) == []
    assert "1 eccezione" in window.checks_dock.title.text() and "0 errori" in window.checks_dock.title.text()
    assert window.checks.tree.isHidden()  # hidden until the filter of the exceptions is on
    window.checks.filters["eccezioni"].setChecked(True)
    row = window.checks.tree.topLevelItem(0).child(0)
    assert "Funzione di prova" in row.child(0).text(0) and "Anna Bianchi" in row.child(0).text(0)

    reopened = Project.open(tmp_path / "p")  # in checks.yaml, shared with the team
    [e] = reopened.checks.exceptions
    assert e["reason"] == "Funzione di prova" and e["author"] == "Anna Bianchi"
    window.checks.revoke_exception(window.checks.findings[0])
    assert not window.checks.findings[0].waived and Project.open(tmp_path / "p").checks.exceptions == []
    window.close()


def test_the_profile_is_chosen_in_the_toolbar(app, tmp_path, problems_shown):
    project = Project.create(tmp_path / "p", "Prova")
    project.new_element("system_function", name="Funzione")
    config = ChecksConfig({"Predefinito": Profile(["SA2-01"]), "Gate LA": Profile(["SA2-07"])})
    project.update_checks(config)
    window = MainWindow()
    window._set_project(project)
    combo = window.profile_combo
    assert window.profile_action.isVisible() or not window.isVisible()
    assert [combo.itemText(i) for i in range(combo.count())] == ["Predefinito", "Gate LA"]
    combo.setCurrentText("Gate LA")
    window.verify_model()
    assert {f.code for f in window.checks.findings} == {"SA2-07"}
    assert Project.open(tmp_path / "p").checks.active == "Gate LA"  # in checks.yaml: shared with the team
    assert "active: Gate LA" in (tmp_path / "p" / "checks.yaml").read_text(encoding="utf-8")
    assert project.has_unpublished_changes()  # to publish
    window.close()


def test_the_details_of_a_check_change_severity_scope_and_parameters(app, tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    domain = project.new_element("domain", id="DF01", name="Dominio")
    dialog = ProjectSettingsDialog(project, section="Verifiche")
    page = dialog.checks_page
    page.tree.setCurrentItem(_item(page, "SA5-13"))
    detail = page.detail.widget()
    texts = " ".join(label.text() for label in detail.findChildren(QLabel))
    assert "SA5-13" in texts and "Domini di codifica" in texts and "non indicato" in texts
    from PySide6.QtWidgets import QComboBox, QListWidget
    from PySide6.QtCore import Qt
    severity = detail.findChildren(QComboBox)[0]
    severity.setCurrentIndex(severity.findData("I"))
    lists = detail.findChildren(QListWidget)
    lists[-1].item(0).setCheckState(Qt.Checked)  # the coding domains
    profile = page.config.profile
    assert profile.severity == {"SA5-13": "I"}
    assert profile.params == {"SA5-13": {"coding_domains": [domain.uuid]}}
    assert _item(page, "SA5-13").text(1) == "Informazione"
    reset = [b for b in detail.findChildren(QPushButton) if "Ripristina" in b.text()][0]
    assert reset.isEnabled()
    reset.click()
    assert not profile.customized("SA5-13")

    page.config.add_profile("Gate SA")  # profiles: new one, copy of the current
    page._profile_changed()
    assert page.profile.currentText() == "Gate SA" and page.remove.isEnabled()
    dialog._save()
    assert list(project.checks.profiles) == ["Predefinito", "Gate SA"]


def test_settings_alone_can_be_published(app, tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    project.new_element("system_function", name="Funzione")
    project.publish("Prima versione", "Anna <anna@example.org>")
    assert not PublishDialog(project).publish_button.isEnabled()  # nothing changed
    set_checks(project, ["SA2-01"])  # only checks.yaml changes
    dialog = PublishDialog(project)
    assert dialog.settings_changed and dialog.publish_button.isEnabled()
    dialog.message.setPlainText("Verifiche del team")
    dialog.author_name.setText("Anna")
    dialog.author_email.setText("anna@example.org")
    dialog._publish()
    assert dialog.sha
    from dulwich.object_store import tree_lookup_path
    repo = project.repository._repo  # the version has the file
    _mode, blob = tree_lookup_path(repo.object_store.__getitem__, repo[dialog.sha.encode()].tree, b"checks.yaml")
    assert b"SA2-01" in repo[blob].data
    assert not project.has_unpublished_changes()
