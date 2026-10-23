import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dulwich.repo import Repo
from PySide6.QtWidgets import QApplication

from arcadia_tool.accounts import Account
from arcadia_tool.storage.project import Project, ProjectError, clone_project
from arcadia_tool.storage.repository import remote_branches_and_default

AUTHOR = "Mario Rossi <mario.rossi@example.com>"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def remote_with_two_branches(tmp_path):
    """A published project whose «develop» branch is one version behind «master»."""
    p = Project.create(tmp_path / "remote", "EVC")
    p.new_element("domain", name="Odometria")
    first = p.publish("v1", AUTHOR)
    repo = Repo(str(p.path))
    repo.refs[b"refs/heads/develop"] = first.encode()
    repo.close()
    p.new_element("domain", name="Localizzazione")
    p.publish("v2", AUTHOR)
    p.close()
    return tmp_path / "remote"


def test_clone_a_branch_of_the_project(tmp_path):
    remote = remote_with_two_branches(tmp_path)
    assert remote_branches_and_default(str(remote)) == (["develop", "master"], "master")
    path = clone_project(str(remote), tmp_path / "local", branch="develop")
    p = Project.open(path)
    assert [e.get("name") for e in p.model.of_kind("domain")] == ["Odometria"]  # develop: one version behind
    assert p.local_settings()["branch"] == "develop"  # the working branch
    assert p.repository.remote_url() == str(remote) and len(p.versions()) == 1
    p.close()
    master = Project.open(clone_project(str(remote), tmp_path / "master"))  # no branch: the default one
    assert len(master.model.of_kind("domain")) == 2
    master.close()


def test_clone_refuses_what_is_not_a_project(tmp_path):
    from dulwich import porcelain

    other = tmp_path / "other"  # a Git repository that is not an ARCADIA project
    porcelain.init(str(other)).close()
    (other / "README.md").write_text("altro", encoding="utf-8")
    porcelain.add(str(other), [str(other / "README.md")])
    porcelain.commit(str(other), message=b"readme", author=AUTHOR.encode(), committer=AUTHOR.encode())
    with pytest.raises(ProjectError, match="non contiene un progetto ARCADIA"):
        clone_project(str(other), tmp_path / "local")
    assert not (tmp_path / "local").exists()  # the folder created for the download is removed
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ProjectError, match="non è vuota"):
        clone_project(str(other), tmp_path / "busy")


def test_clone_dialog_asks_which_branch_when_there_are_several(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import accounts as ui
    from arcadia_tool.ui.clone import CloneDialog, folder_name
    from arcadia_tool.ui.main_window import MainWindow

    assert folder_name("git@server:evc/modello.git") == "modello"
    assert folder_name("https://server/evc/modello.git/") == "modello"
    remote = remote_with_two_branches(tmp_path)
    user = Account(first_name="Mario", last_name="Rossi", username="mrossi", email="mario.rossi@example.com")
    monkeypatch.setattr(ui, "account_store", lambda: ui.AccountStore(tmp_path / "accounts"))

    def run(dialog):
        if dialog.worker is not None:
            dialog.worker.wait(20000)
        for _ in range(100):
            app.processEvents()
            if dialog.worker is None or not dialog.worker.isRunning():
                break

    dialog = CloneDialog(user)
    monkeypatch.setattr(dialog.branch, "showPopup", lambda: None)
    dialog.remote.setText(str(remote))
    dialog._remote_changed()
    dialog.parent_folder.setText(str(tmp_path))
    assert dialog.name.text() == "remote"
    dialog.name.setText("evc-locale")
    dialog.start()  # branches unknown: read first
    run(dialog)
    assert dialog.known_branches == ["develop", "master"] and dialog.default_branch == "master"
    assert dialog.branch.itemText(0) == "master (predefinito)" and dialog.selected_branch() == "master"
    assert "scegli quello da scaricare" in dialog.status.text() and dialog.path is None  # several: choose
    dialog.branch.setCurrentIndex(dialog.branch.findData("develop"))
    dialog.start()
    run(dialog)
    assert dialog.path == tmp_path / "evc-locale" and dialog.result() == 1  # accepted

    window = MainWindow()
    window.set_user(user)
    window.open_project(str(dialog.path), confirmed=True)
    assert window.project.local_settings()["branch"] == "develop"
    start_buttons = [b.text() for b in window.start.findChildren(type(dialog.clone_button))]
    assert "Scarica da Git" in start_buttons
    file_menu = window.menuBar().actions()[0].menu()
    assert "Scarica progetto da Git…" in [a.text() for a in file_menu.actions()]
    window.close()
