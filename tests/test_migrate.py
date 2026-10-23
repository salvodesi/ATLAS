import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dulwich import porcelain
from dulwich.repo import Repo
from PySide6.QtWidgets import QApplication

from arcadia_tool.storage.project import Project, ProjectError, clone_project, migrate_repository, reload_project
from arcadia_tool.storage.repository import remote_branches, remote_branches_and_default

AUTHOR = "Mario Rossi <mario.rossi@example.com>"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def server(tmp_path, name):
    porcelain.init(str(tmp_path / f"{name}.git"), bare=True).close()
    return str(tmp_path / f"{name}.git")


def old_server_with_two_branches(tmp_path):
    """The «old» Git server: master (two versions) and develop (one version behind)."""
    url = server(tmp_path, "old")
    p = Project.create(tmp_path / "author", "EVC")
    p.repository.set_remote_url(url)
    p.new_element("domain", name="Odometria")
    first = p.publish("v1", AUTHOR)
    p.push()
    p.new_element("domain", name="Localizzazione")
    p.publish("v2", AUTHOR)
    p.push()
    p.repository.send_branch(url, first, "develop")
    p.close()
    return url


def test_migrate_all_or_some_branches_with_their_history(tmp_path):
    old = old_server_with_two_branches(tmp_path)
    new = server(tmp_path, "new")
    local = Project.open(clone_project(old, tmp_path / "local"))
    seen = []
    results = migrate_repository(local.path, old, new, ["master"], progress=lambda b, r: seen.append((b, r)))
    assert results == {"master": None} and seen == [("master", None)]
    assert remote_branches(new) == ["master"]  # only the branch chosen
    results = migrate_repository(local.path, old, new, ["develop", "master", "feature"])
    assert results["develop"] is None and results["master"] is None  # master again: already there, fine
    assert "non esiste" in results["feature"]
    assert remote_branches(new) == ["develop", "master"]
    copy = Project.open(clone_project(new, tmp_path / "copy"))  # the whole history is on the new server
    assert [v.title for v in copy.versions()] == ["v2", "v1"]
    copy.close()
    local.close()


def test_migration_does_not_overwrite_another_history(tmp_path):
    old = old_server_with_two_branches(tmp_path)
    new = server(tmp_path, "new")
    other = Project.create(tmp_path / "other", "Altro")  # the new server has its own «master» already
    other.repository.set_remote_url(new)
    other.new_element("domain", name="Altro")
    other.publish("altro", AUTHOR)
    other.push()
    other.close()
    local = Project.open(clone_project(old, tmp_path / "local"))
    results = migrate_repository(local.path, old, new, ["master", "develop"])
    assert "storia diversa" in results["master"] and results["develop"] is None
    local.close()


def _wait(app, dialog):
    for _ in range(400):
        app.processEvents()
        if dialog.worker is None or not dialog.worker.isRunning():
            break
        dialog.worker.wait(50)
    for _ in range(20):
        app.processEvents()


def test_migration_dialog_with_some_branches(app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    from arcadia_tool.accounts import Account
    from arcadia_tool.ui import accounts as ui
    from arcadia_tool.ui import migrate as migrate_ui
    from arcadia_tool.ui.main_window import MainWindow

    monkeypatch.setattr(ui, "account_store", lambda: ui.AccountStore(tmp_path / "accounts"))
    monkeypatch.setattr(migrate_ui, "account_store", lambda: ui.AccountStore(tmp_path / "accounts"))
    old = old_server_with_two_branches(tmp_path)
    new = server(tmp_path, "new")
    window = MainWindow()
    window.set_user(Account(first_name="Mario", last_name="Rossi", username="mrossi", email="m@example.com"))
    window.open_project(str(clone_project(old, tmp_path / "local")), confirmed=True)
    project_menu = window.menuBar().actions()[1].menu()
    assert {"Ricarica dal repository…", "Migra repository…"} <= {a.text() for a in project_menu.actions()}

    dialog = migrate_ui.MigrationDialog(window.project, window.user, window)
    assert dialog.source.text() == old  # the current repository
    dialog.read_branches()
    _wait(app, dialog)
    assert dialog.checked_branches() == ["develop", "master"]  # all of them by default
    dialog.branches.item(0).setCheckState(Qt.Unchecked)  # only master
    dialog.target.setText(new)
    monkeypatch.setattr(migrate_ui.QMessageBox, "question", lambda *a: QMessageBox.Yes)  # use the new one
    dialog.migrate()
    _wait(app, dialog)
    assert dialog.results == {"master": None} and dialog.use_destination
    assert "migrato" in dialog.branches.item(1).text() and remote_branches(new) == ["master"]

    import arcadia_tool.ui.main_window as main_window
    monkeypatch.setattr(migrate_ui.MigrationDialog, "exec", lambda d: None)
    monkeypatch.setattr(main_window, "MigrationDialog", lambda *a: dialog)  # the one already run
    window.migrate_repository()
    assert window.project.remote() == new and window.project.settings["remote"] == new
    window.close()


def test_reload_after_the_address_changed_in_the_settings(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.main_window as main_window
    from arcadia_tool.ui import migrate as migrate_ui

    old = old_server_with_two_branches(tmp_path)
    new = server(tmp_path, "new")
    migrate_repository(tmp_path / "author", old, new, ["master"])
    colleague = Project.open(clone_project(new, tmp_path / "colleague"))
    colleague.new_element("domain", name="Velocità")
    colleague.publish("v3 sul nuovo server", AUTHOR)
    colleague.push()
    colleague.close()

    window = main_window.MainWindow()
    window.open_project(str(clone_project(old, tmp_path / "mine")), confirmed=True)
    window.project.update_settings(remote=new)  # what «Salva» of the settings does
    window.project.repository.set_remote_url(new)
    chosen = {}

    def answer(box):
        chosen["button"] = next(b for b in box.buttons() if b.text() == "Ricarica dal nuovo repository")
    monkeypatch.setattr(main_window.QMessageBox, "exec", answer)
    monkeypatch.setattr(main_window.QMessageBox, "clickedButton", lambda box: chosen["button"])
    monkeypatch.setattr(migrate_ui.ReloadDialog, "exec", lambda d: (d.worker.start(), _wait(app, d)))
    window._remote_changed()
    p = window.project
    assert p is not None and p.versions()[0].title == "v3 sul nuovo server"  # reloaded and opened again
    assert sorted(e.get("name") for e in p.model.of_kind("domain")) == ["Localizzazione", "Odometria", "Velocità"]
    window.close()


def test_reload_the_project_from_a_new_address(tmp_path):
    old = old_server_with_two_branches(tmp_path)
    new = server(tmp_path, "new")
    mine = Project.open(clone_project(old, tmp_path / "mine"))
    mine.close()
    with pytest.raises(ProjectError, match="vuoto"):  # nothing on the new server yet
        reload_project(tmp_path / "mine", new)

    elsewhere = Project.open(clone_project(old, tmp_path / "elsewhere", branch="develop"))
    elsewhere.close()
    migrate_repository(tmp_path / "elsewhere", old, new, ["develop", "master"])
    other = Project.open(clone_project(new, tmp_path / "other", branch="develop"))  # a colleague on the new
    other.new_element("domain", name="Velocità")
    other.publish("v3 sul nuovo server", AUTHOR)
    other.push()
    other.close()

    assert reload_project(tmp_path / "mine", new, "develop") == "develop"
    p = Project.open(tmp_path / "mine")
    assert sorted(e.get("name") for e in p.model.of_kind("domain")) == ["Odometria", "Velocità"]
    assert p.repository.remote_url() == new and p.push_branch() == "develop" and p.unsent_versions() == []
    assert p.versions()[0].title == "v3 sul nuovo server"
    p.close()
    with pytest.raises(ProjectError, match="non esiste"):
        reload_project(tmp_path / "mine", new, "feature")
