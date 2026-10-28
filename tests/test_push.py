import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dulwich import porcelain
from dulwich.repo import Repo
from PySide6.QtWidgets import QApplication

from arcadia_tool.storage.project import Project, clone_project
from arcadia_tool.storage.repository import remote_branches

AUTHOR = "Mario Rossi <mario.rossi@example.com>"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def empty_remote(tmp_path):
    """An empty repository on a «server» (a bare repository reached by its path)."""
    porcelain.init(str(tmp_path / "server.git"), bare=True).close()
    return str(tmp_path / "server.git")


def project_with_remote(tmp_path, url, name="p"):
    p = Project.create(tmp_path / name, "EVC")
    p.repository.set_remote_url(url)
    return p


def test_versions_published_before_are_sent_to_an_empty_remote(tmp_path):
    url = empty_remote(tmp_path)
    p = project_with_remote(tmp_path, url)
    p.new_element("domain", name="Odometria")
    p.publish("Primo upload del progetto", AUTHOR)
    assert [v.title for v in p.unsent_versions()] == ["Primo upload del progetto"]  # recorded, not sent
    assert p.push_branch() == "master"  # no working branch: the local one
    assert p.push() == "master"
    assert remote_branches(url) == ["master"] and p.unsent_versions() == []
    assert p.local_settings()["branch"] == "master"

    p.new_element("domain", name="Localizzazione")
    p.publish("v2", AUTHOR)
    assert len(p.unsent_versions()) == 1
    p.push()
    assert p.unsent_versions() == []
    p.close()
    copy = Project.open(clone_project(url, tmp_path / "copy"))  # what a colleague downloads
    assert len(copy.model.of_kind("domain")) == 2 and len(copy.versions()) == 2
    assert copy.unsent_versions() == []  # downloaded: already on the remote, nothing to send
    copy.close()


def test_project_downloaded_before_has_nothing_to_send(tmp_path):
    """A project downloaded by an earlier version of the tool (no record of what was sent)."""
    import json

    url = empty_remote(tmp_path)
    p = project_with_remote(tmp_path, url)
    p.new_element("domain", name="Odometria")
    p.publish("Primo upload del progetto", AUTHOR)
    p.push()
    p.close()
    path = clone_project(url, tmp_path / "copy")
    (path / ".arcadia" / "local.json").write_text(json.dumps({"branch": "master"}), encoding="utf-8")
    copy = Project.open(path)
    assert copy.unsent_versions() == []  # the remote branch known to Git says it is there
    copy.new_element("domain", name="Localizzazione")
    copy.publish("v2", AUTHOR)
    assert [v.title for v in copy.unsent_versions()] == ["v2"]
    copy.close()


def test_working_branch_is_created_on_the_remote(tmp_path):
    url = empty_remote(tmp_path)
    p = project_with_remote(tmp_path, url)
    p.set_local_settings(branch="develop")
    p.new_element("domain", name="Odometria")
    p.publish("v1", AUTHOR)
    p.push()
    assert remote_branches(url) == ["develop"]
    p.close()


def test_versions_of_a_colleague_must_be_received_first(app, tmp_path):
    from arcadia_tool.ui.push import PushDialog

    url = empty_remote(tmp_path)
    mine = project_with_remote(tmp_path, url)
    mine.new_element("domain", name="Odometria")
    mine.publish("v1", AUTHOR)
    mine.push()
    colleague = Project.open(clone_project(url, tmp_path / "colleague"))
    colleague.new_element("domain", name="Localizzazione")
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    colleague.close()

    mine.new_element("domain", name="Velocità")
    mine.publish("mia", AUTHOR)
    dialog = PushDialog(mine, {})
    dialog.start()
    dialog.worker.wait(20000)
    for _ in range(50):
        app.processEvents()
    assert not dialog.sent and "non hai ancora ricevuto" in dialog.status.text()
    assert dialog.retry.isHidden() and not dialog.receive_button.isHidden()  # «Ricevi ora», not «Riprova»
    assert [v.title for v in mine.unsent_versions()] == ["mia"]  # kept here
    dialog.receive_button.click()
    assert dialog.receive_requested
    mine.close()


@pytest.mark.parametrize("case", ["unsent", "sent", "local"])
def test_delete_a_project_from_the_start_page(app, tmp_path, monkeypatch, case):
    import arcadia_tool.ui.main_window as main_window
    from PySide6.QtWidgets import QMessageBox
    from arcadia_tool.ui.dialogs import settings

    url = empty_remote(tmp_path)
    p = project_with_remote(tmp_path, url if case != "local" else "")
    p.new_element("domain", name="Odometria")
    p.publish("v1", AUTHOR)
    if case == "sent":
        p.push()
    p.close()
    trashed, shown = [], {}
    monkeypatch.setattr(main_window, "move_to_trash", lambda path: trashed.append(path))  # not the real bin
    window = main_window.MainWindow()
    window._remember(p.path)
    assert window.start.recent_layout.count() == 2  # the caption and the row of the project

    def answer(box, click):
        shown["text"] = box.informativeText()
        shown["box"] = box
        shown["button"] = next(b for b in box.buttons() if (b.text() == "Sposta nel Cestino") == click)
    monkeypatch.setattr(main_window.QMessageBox, "clickedButton", lambda box: shown["button"])
    monkeypatch.setattr(main_window.QMessageBox, "exec", lambda box: answer(box, click=False))
    window.delete_project(str(p.path))  # cancelled: nothing happens
    assert trashed == [] and str(p.path) in settings().value("recent", [], list)
    expected = {"unsent": "1 versioni pubblicate non sono state inviate", "sent": "sono sul repository",
                "local": "esiste solo su questo PC"}[case]
    assert expected in shown["text"] and "Cestino" in shown["text"]

    monkeypatch.setattr(main_window.QMessageBox, "exec", lambda box: answer(box, click=True))
    window.delete_project(str(p.path))
    assert trashed == [p.path] and str(p.path) not in (settings().value("recent", [], list) or [])
    window.close()


def test_forget_a_project_keeps_its_folder(app, tmp_path):
    import arcadia_tool.ui.main_window as main_window

    p = project_with_remote(tmp_path, "")
    p.close()
    window = main_window.MainWindow()
    window._remember(p.path)
    window.forget_project(str(p.path))
    assert window.start.recent_layout.count() == 2 and (p.path / "project.yaml").exists()  # only the note
    window.close()


def test_version_detail_from_the_history(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import versions

    url = empty_remote(tmp_path)
    p = project_with_remote(tmp_path, url)
    odometry = p.new_element("domain", name="Odometria")
    p.new_element("domain", name="Localizzazione")
    p.publish("Primo upload del progetto", AUTHOR)
    p.push()
    odometry.set("name", "Odometria e velocità")
    p.update(odometry)
    p.publish("Rinominato il dominio", AUTHOR)

    publish = versions.PublishDialog(p)  # nothing changed since the last version
    texts = [l.text() for l in publish.findChild(versions.DiffView).findChildren(versions.QLabel)]
    assert not publish.diff and any("identico, nulla da pubblicare" in t for t in texts)
    assert any("(solo su questo PC)" in t for t in texts)  # the last version is not sent yet

    shown = []
    monkeypatch.setattr(versions.VersionDialog, "exec", lambda dialog: shown.append(dialog))
    history = versions.HistoryDialog(p)
    history.show_version(1)  # double click on the first version (the oldest, last row)
    first = shown[-1]
    assert len(first.diff.changes) == 2 and all(c.change == "added" for c in first.diff.changes)
    labels = [l.text() for l in first.findChildren(versions.QLabel)]
    assert any(t.startswith("Inviata al ramo «master»") for t in labels)
    history.show_version(0)  # the newer one: only the renamed domain, not sent yet
    second = shown[-1]
    assert [c.change for c in second.diff.changes] == ["modified"]
    assert any(t.startswith("Solo su questo PC") for t in (l.text() for l in second.findChildren(versions.QLabel)))
    p.close()


def test_ssh_is_started_without_a_console_window(monkeypatch):
    import subprocess
    import arcadia_tool.storage.repository as repository

    started = {}

    import io

    class FakeProcess:  # what dulwich reads and writes: streams
        def __init__(self):
            self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()

    def popen(args, **options):
        started.update(args=args, **options)
        return FakeProcess()
    monkeypatch.setattr(repository.subprocess, "Popen", popen)
    vendor = repository._WindowlessSSHVendor()
    key = r"C:\Users\Mario Rossi\AppData\Roaming\RFI\ARCADIA Tool\keys\mrossi_ed25519"  # spaces in the path
    vendor.run_command("gitlab.com", "git-upload-pack 'gruppo/progetto.git'", username="git", key_filename=key,
                       ssh_command="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new")
    args = started["args"]
    assert args[:4] == ["ssh", "-o", "BatchMode=yes", "-o"] and args[args.index("-i") + 1] == key
    assert args[-2:] == ["git@gitlab.com", "git-upload-pack 'gruppo/progetto.git'"]
    assert started["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_publish_dialog_offers_to_send_what_was_recorded_before(app, tmp_path):
    from arcadia_tool.ui.versions import PublishDialog

    url = empty_remote(tmp_path)
    p = project_with_remote(tmp_path, url)
    p.new_element("domain", name="Odometria")
    p.publish("Primo upload del progetto", AUTHOR)
    dialog = PublishDialog(p)  # no change to publish, one version not sent
    assert dialog.publish_button.isEnabled() and dialog.publish_button.text() == "Invia al repository"
    dialog.publish_button.click()
    assert dialog.send_only and dialog.result() == 1
    p.close()
