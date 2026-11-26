"""Branches of the project: created from a chosen version, switched, listed with those of the remote, their
history, and compared with each other (also the remote ones and the working state)."""
import pytest
from dulwich import porcelain

from arcadia_tool.storage.project import Project, ProjectError, clone_project
from arcadia_tool.storage.repository import remote_branches

AUTHOR = "Mario Rossi <mario.rossi@example.com>"


@pytest.fixture
def server(tmp_path):
    """A project on a «server» with two versions on main, downloaded by me and by a colleague."""
    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    first = Project.create(tmp_path / "first", "EVC")
    first.repository.set_remote_url(url)
    first.set_local_settings(branch="main")
    first.new_element("domain", name="Protezione")
    first.publish("v1", AUTHOR)
    first.new_element("domain", name="Localizzazione")
    first.publish("v2", AUTHOR)
    first.push()
    first.close()
    from dulwich.repo import Repo
    with Repo(url) as bare:  # the default branch of the server, as on GitLab
        bare.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")
    opened = []

    def download(name):
        p = Project.open(clone_project(url, tmp_path / name))
        opened.append(p)
        return p

    def reopen(p):
        p.close()
        again = Project.open(p.path)
        opened.append(again)
        return again

    yield url, download, reopen
    for p in opened:
        p.close()


def names(p):
    return sorted(d.get("name") for d in p.model.of_kind("domain"))


def test_a_download_keeps_the_line_endings_of_the_versions(server):
    """Git for Windows sets core.autocrlf=true for the whole system: the project downloaded must not look
    changed because of it."""
    url, download, reopen = server
    mine = download("mine")
    assert mine.repository._repo.get_config().get((b"core",), b"autocrlf") == b"false"
    assert b"\r" not in (mine.path / "project.yaml").read_bytes()
    assert not mine.has_unpublished_changes()


def test_a_branch_is_created_from_a_chosen_version_and_sent(server):
    url, download, reopen = server
    mine = download("mine")
    v1 = mine.versions()[-1]
    assert mine.check_branch_name("main") == "Il ramo «main» esiste già."
    assert "lettere" in mine.check_branch_name("att/con spazio")
    assert mine.check_branch_name("att/T2-odometria") is None
    mine.switch_branch("att/T2-odometria", v1.sha)
    mine = reopen(mine)
    assert mine.current_branch() == "att/T2-odometria" and names(mine) == ["Protezione"]  # as in v1
    assert mine.unsent_versions() == [] and not mine.branch_on_remote()  # nothing new, but the branch is not there
    mine.push()
    assert set(remote_branches(url)) == {"main", "att/T2-odometria"} and mine.branch_on_remote()
    mine.new_element("domain", name="Odometria")
    mine.publish("odometria", AUTHOR)
    assert [v.title for v in mine.unsent_versions()] == ["odometria"]


def test_branches_of_the_remote_are_listed_and_can_be_switched_to(server):
    url, download, reopen = server
    mine = download("mine")
    colleague = download("colleague")
    colleague.switch_branch("att/T3-chain", colleague.versions()[0].sha)
    colleague = reopen(colleague)
    colleague.new_element("domain", name="Chain")
    colleague.publish("chain", AUTHOR)
    colleague.push()

    assert {b.name for b in mine.branches()} == {"main"}  # created after my download: not known yet
    mine.fetch_branches()
    assert mine.fetched_at()
    branches = {b.name: b for b in mine.branches()}
    assert list(branches)[0] == "main" and branches["main"].current and branches["main"].main
    chain = branches["att/T3-chain"]
    assert chain.where == "solo nel repository" and chain.ahead == 1 and chain.behind == 0
    assert chain.last.title == "chain"
    assert [v.title for v in mine.branch_versions(chain.head)] == ["chain", "v2", "v1"]
    mine.switch_branch("att/T3-chain")
    mine = reopen(mine)
    assert mine.current_branch() == "att/T3-chain" and "Chain" in names(mine)
    assert mine.unsent_versions() == [] and mine.branch_on_remote()
    mine.switch_branch("main")
    assert "Chain" not in names(reopen(mine))


def test_a_missing_branch_cannot_be_switched_to(server):
    _url, download, _reopen = server
    mine = download("mine")
    with pytest.raises(ProjectError):
        mine.switch_branch("non-esiste")


@pytest.fixture
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def activity_branch(download, reopen, name="att/T3-chain", element="Chain"):
    """A colleague creates an activity branch from main, publishes one version on it and sends it."""
    colleague = download(f"colleague-{element}")
    colleague.switch_branch(name, colleague.versions()[0].sha)
    colleague = reopen(colleague)
    colleague.new_element("domain", name=element)
    colleague.publish(element.lower(), AUTHOR)
    colleague.push()
    return colleague


def test_the_window_of_the_branches_lists_them_and_asks_for_a_new_one(app, server, monkeypatch):
    from arcadia_tool.ui.branches import BranchesDialog, NewBranchDialog

    url, download, reopen = server
    mine = download("mine")
    activity_branch(download, reopen)
    dialog = BranchesDialog(mine, {})
    assert dialog.table.rowCount() == 1 and "non ancora aggiornati" in dialog.fetched.text()
    mine.fetch_branches()  # what «Aggiorna Lista» does (in a thread)
    dialog.fill()
    rows = {dialog.table.item(r, 0).text(): r for r in range(dialog.table.rowCount())}
    assert set(rows) == {"main  (in uso)", "att/T3-chain"}
    r = rows["att/T3-chain"]
    assert dialog.table.item(r, 3).text() == "solo nel repository" and dialog.table.item(r, 4).text() == "1 avanti"
    assert dialog.table.item(rows["main  (in uso)"], 4).text() == "ramo principale"
    dialog.table.selectRow(rows["main  (in uso)"])
    assert not dialog.switch_button.isEnabled()  # already in use
    dialog.table.selectRow(r)
    assert dialog.switch_button.isEnabled()
    labels = [b.text() for b in dialog.findChildren(type(dialog.switch_button))]
    assert "Cronologia" not in labels and not any(t.startswith("Confronta con il mio") or "rispetto a main" in t
                                                  for t in labels)  # the versions: in «Versioni Modello»
    dialog.switch()
    assert dialog.request == ("switch", "att/T3-chain")

    new = NewBranchDialog(mine, None, mine.versions()[-1].sha)  # from v1
    assert new.name.text() == "att/" and new.version.currentData() == mine.versions()[-1].sha
    new.name.setText("att/T2-odometria")
    new._accept()
    assert (new.name_value, new.sha, new.send) == ("att/T2-odometria", mine.versions()[-1].sha, True)
    warnings = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    again = NewBranchDialog(mine, None)
    again.name.setText("main")
    again._accept()
    assert "esiste già" in warnings[-1] and again.name_value is None


def test_history_and_comparison_of_any_branch(app, server):
    from arcadia_tool.ui.versions import CompareDialog, HistoryDialog, WORKING

    url, download, reopen = server
    mine = download("mine")
    activity_branch(download, reopen)
    mine.fetch_branches()
    history = HistoryDialog(mine)
    assert [history.table.item(r, 2).text() for r in range(history.table.rowCount())] == ["v2", "v1"]
    history.branch.setCurrentIndex(history.branch.findData("remote:att/T3-chain"))
    assert [history.table.item(r, 2).text() for r in range(history.table.rowCount())] == ["chain", "v2", "v1"]
    assert history.table.item(0, 3).text() == "inviata"  # on the remote

    branch = next(b for b in mine.branches() if b.name == "att/T3-chain")
    main = next(b for b in mine.branches() if b.name == "main")
    direct = CompareDialog(mine, before=main.head, after=branch.head, before_branch="main",
                           after_branch="att/T3-chain")
    view = direct.result_layout.itemAt(0).widget()
    assert view is not None and "Chain" in str([c.label for c in view.diff.changes])

    # main goes on meanwhile: «since common» shows only what the branch changed
    mine.new_element("domain", name="Odometria")
    mine.publish("odometria", AUTHOR)
    head = mine.versions()[0].sha
    direct = CompareDialog(mine, before=head, after=branch.head, before_branch="main", after_branch="att/T3-chain")
    labels = [c.label for c in direct.result_layout.itemAt(0).widget().diff.changes]
    assert any("Odometria" in x for x in labels) and any("Chain" in x for x in labels)
    common = CompareDialog(mine, before=head, after=branch.head, before_branch="main", after_branch="att/T3-chain",
                           since_common=True)
    labels = [c.label for c in common.result_layout.itemAt(0).widget().diff.changes]
    assert labels and all("Chain" in x for x in labels)

    working = CompareDialog(mine, before=branch.head, after=WORKING, before_branch="att/T3-chain")
    assert working.right.state == WORKING and working.left.branch.currentData() == "remote:att/T3-chain"


def test_the_main_window_creates_a_branch_from_a_version_and_switches(app, server, monkeypatch):
    import arcadia_tool.ui.main_window as main_window
    from arcadia_tool.storage.repository import remote_branches

    url, download, reopen = server
    mine = download("mine")
    sent = []

    class Push:  # the window that sends: here the push at once
        def __init__(self, project, credentials, parent=None):
            self.project = project

        def exec(self):
            sent.append(self.project.push())
    monkeypatch.setattr(main_window, "PushDialog", Push)
    window = main_window.MainWindow()
    window._set_project(mine)
    v1 = mine.versions()[-1].sha
    window.open_project = lambda path, confirmed=False, **_kw: window._set_project(Project.open(path))
    window.branch_request(("create", "att/T2-odometria", v1, True))
    assert window.project.current_branch() == "att/T2-odometria" and names(window.project) == ["Protezione"]
    assert sent == ["att/T2-odometria"] and "att/T2-odometria" in remote_branches(url)
    assert "ramo «att/T2-odometria»" in window.status_project.text()

    window.project.new_element("domain", name="Odometria")
    window.project.save()  # saved, not published: the user discards it to go back to main
    monkeypatch.setattr(window, "_ready_to_leave_branch", lambda: True)
    window.branch_request(("switch", "main"))
    assert window.project.current_branch() == "main" and names(window.project) == ["Localizzazione", "Protezione"]
    window._set_project(None)
    window.close()


def _checked(app, window):
    """The check of the updates of check_for_updates, waited for (it runs in a thread)."""
    window.update_check.wait(20000)
    for _ in range(20):
        app.processEvents()


def test_opening_and_switching_branch_check_for_updates_in_the_background(app, server, monkeypatch,
                                                                          no_modal_message_boxes):
    import arcadia_tool.ui.main_window as main_window
    from PySide6.QtWidgets import QMessageBox

    url, download, reopen = server
    mine = download("mine")
    mine.switch_branch("att/T2", mine.versions()[0].sha)
    mine = reopen(mine)
    mine.push()
    mine.switch_branch("main")
    path = mine.path
    mine.close()
    window = main_window.MainWindow()
    received = []
    monkeypatch.setattr(window, "receive_versions", lambda: received.append(window.project.current_branch()))
    asked = lambda: [t for kind, t in no_modal_message_boxes if kind == "question" and "Riceverle ora" in t]
    # Nothing new on the repository: no question, only the status bar.
    window.open_project(str(path), confirmed=True, ask_update=True)
    _checked(app, window)
    assert asked() == [] and received == []
    assert "nessun aggiornamento" in window.statusBar().currentMessage()
    # A colleague sends a version to main: the next opening finds it, and asks.
    colleague = download("colleague")
    colleague.new_element("domain", name="Frenatura")
    colleague.publish("frenatura", AUTHOR)
    colleague.push()
    head = window.project.repository.head()
    window.open_project(str(path), confirmed=True, ask_update=True)
    _checked(app, window)
    assert len(asked()) == 1 and "«main»" in asked()[0] and "nuove versioni" in asked()[0]  # not downloaded yet
    assert received == [] and "da ricevere" in window.statusBar().currentMessage()  # «No»
    assert window.project.repository.head() == head  # only read: nothing downloaded, nothing changed
    window.open_project(str(path), confirmed=True, ask_update=False)  # opened again by the tool: not checked
    assert window.update_check.isFinished() and len(asked()) == 1
    # On moving to a branch: checked too («Sì»: received).
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.branch_request(("switch", "att/T2"))
    _checked(app, window)
    assert window.project.current_branch() == "att/T2" and received == []  # att/T2 has nothing new
    window.branch_request(("switch", "main"))
    _checked(app, window)
    assert received == ["main"]
    window._set_project(None)
    window.close()


def test_a_project_without_repository_is_not_asked_to_receive(app, tmp_path, monkeypatch, no_modal_message_boxes):
    import arcadia_tool.ui.main_window as main_window

    p = Project.create(tmp_path / "p", "Prova")
    p.close()
    window = main_window.MainWindow()
    window.open_project(str(tmp_path / "p"), confirmed=True, ask_update=True)
    assert window.project is not None
    assert not [t for kind, t in no_modal_message_boxes if "Ricevere ora" in t]
    window._set_project(None)
    window.close()


def test_a_version_is_published_on_a_new_branch_created_at_publication(app, server, monkeypatch):
    from arcadia_tool.ui.versions import PublishDialog

    url, download, reopen = server
    mine = download("mine")
    main_head = mine.versions()[0].sha
    mine.new_element("domain", name="Odometria")
    dialog = PublishDialog(mine)
    assert dialog.on_current.isChecked() and "«main»" in dialog.on_current.text()
    assert not dialog.new_branch.isEnabled()
    dialog.on_new.setChecked(True)
    assert dialog.new_branch.isEnabled() and dialog.new_branch.text() == "att/"
    dialog.new_branch.setText("main")
    warnings = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    dialog.message.setPlainText("odometria")
    dialog.author_name.setText("Mario Rossi")
    dialog.author_email.setText("mario.rossi@example.com")
    dialog._publish()
    assert "esiste già" in warnings[-1] and dialog.sha is None and mine.current_branch() == "main"
    dialog.new_branch.setText("att/T2-odometria")
    assert "«att/T2-odometria» (nuovo" in dialog.note.text()
    dialog._publish()
    assert dialog.sha and mine.current_branch() == "att/T2-odometria"
    assert mine.repository.local_heads()["main"] == main_head  # main does not have it
    assert mine.repository.parents(dialog.sha) == [main_head]  # it starts from the last version of main
    assert [v.title for v in mine.unsent_versions()] == ["odometria"] and not mine.branch_on_remote()
    mine.push()
    assert "att/T2-odometria" in remote_branches(url)


def test_the_same_branch_on_this_pc_and_in_the_repository_are_compared(app, server):
    from arcadia_tool.ui.branches import branch_sources
    from arcadia_tool.ui.versions import CompareDialog

    url, download, reopen = server
    mine = download("mine")
    colleague = download("colleague")
    colleague.new_element("domain", name="Del collega")
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    mine.new_element("domain", name="Mia")
    mine.publish("mia", AUTHOR)  # not sent: main here and main in the repository differ
    mine.fetch_branches()
    sources = branch_sources(mine)
    assert [s.label for s in sources] == ["Questo PC › main  (in uso)", "Repository › main"]
    dialog = CompareDialog(mine, before_branch="remote:main", after_branch="local:main",
                           before=sources[1].head, after=sources[0].head)
    assert dialog.left.branch.currentText() == "Repository › main"
    assert [s.branch.count() for s in (dialog.left, dialog.right)] == [2, 2]
    labels = [c.label for c in dialog.result_layout.itemAt(0).widget().diff.changes]
    assert any("Mia" in x for x in labels) and any("Del collega" in x for x in labels)
    common = CompareDialog(mine, before_branch="remote:main", after_branch="local:main", before=sources[1].head,
                           after=sources[0].head, since_common=True)
    labels = [c.label for c in common.result_layout.itemAt(0).widget().diff.changes]
    assert labels and all("Mia" in x for x in labels)  # only what this PC did since they split


def test_the_branches_shown_can_be_all_local_or_remote(app, server):
    from PySide6.QtWidgets import QToolBar
    from arcadia_tool.ui.branches import BranchesDialog
    import arcadia_tool.ui.main_window as main_window

    url, download, reopen = server
    mine = download("mine")
    activity_branch(download, reopen)
    mine.switch_branch("att/T2-locale", mine.versions()[-1].sha)  # only here
    mine = reopen(mine)
    mine.fetch_branches()
    dialog = BranchesDialog(mine, {})

    def shown():
        return sorted(dialog.table.item(r, 0).text() for r in range(dialog.table.rowCount()))
    assert shown() == ["att/T2-locale  (in uso)", "att/T3-chain", "main"]
    dialog.which.setCurrentIndex(dialog.which.findData("local"))
    assert shown() == ["att/T2-locale  (in uso)", "main"]
    dialog.which.setCurrentIndex(dialog.which.findData("remote"))
    assert shown() == ["att/T3-chain", "main"]
    dialog.table.selectRow(0)
    assert dialog._key(dialog.selected()).startswith("remote:")

    window = main_window.MainWindow()
    actions = [a.text() for a in window.findChildren(QToolBar)[0].actions()]
    order = ["Versioni Modello", "Vista d'insieme", "Rami…", "Ricevi dal repository…", "Confronta…",
             "Pubblica…"]
    assert [a for a in actions if a in order] == order  # the order of the bar
    window.close()


def test_the_model_is_checked_out_at_a_version_of_this_pc_restored_or_with_the_branch_moved(server):
    url, download, reopen = server
    mine = download("mine")
    mine.new_element("domain", name="Solo qui")
    mine.publish("v3 solo qui", AUTHOR)  # a version of this PC, not sent
    v3, v2, v1 = (v.sha for v in mine.versions())
    # Restored: the branch stays at its last version, the model of v1 is a change to publish.
    mine.checkout_version("main", v1)
    mine = reopen(mine)
    assert names(mine) == ["Protezione"] and mine.repository.head() == v3 and mine.has_unpublished_changes()
    assert [v.title for v in mine.unsent_versions()] == ["v3 solo qui"]
    mine.publish("ripristino di v1", AUTHOR)
    assert names(reopen(mine)) == ["Protezione"]
    mine = reopen(mine)
    # Moved: the branch goes back to v2, the later versions are no longer on it here.
    mine.checkout_version("main", v2, move_branch=True)
    mine = reopen(mine)
    assert mine.repository.head() == v2 and not mine.has_unpublished_changes()
    assert names(mine) == ["Localizzazione", "Protezione"] and mine.unsent_versions() == []
    assert [v.title for v in mine.versions()] == ["v2", "v1"]
    with pytest.raises(ProjectError):
        mine.checkout_version("main", "0" * 40)


def test_the_model_is_checked_out_at_a_version_of_a_branch_of_the_remote(server):
    url, download, reopen = server
    mine = download("mine")
    colleague = download("colleague")
    colleague.switch_branch("att/T3-chain", colleague.versions()[0].sha)
    colleague = reopen(colleague)
    colleague.new_element("domain", name="Chain")
    colleague.publish("chain", AUTHOR)
    colleague.new_element("domain", name="Chain 2")
    colleague.publish("chain 2", AUTHOR)
    colleague.push()
    mine.fetch_branches()
    chain = next(b for b in mine.branches() if b.name == "att/T3-chain")
    assert chain.local is None
    first = mine.branch_versions(chain.remote)[1].sha  # «chain», only in the repository
    mine.checkout_version("att/T3-chain", first, move_branch=True)
    mine = reopen(mine)
    assert mine.current_branch() == "att/T3-chain" and "Chain" in names(mine) and "Chain 2" not in names(mine)
    assert mine.repository.head() == first and mine.unsent_versions() == []  # behind the repository: nothing new
    # Restored: the branch of this PC stays at «chain», the model of the last version of the repository is to publish.
    mine.checkout_version("att/T3-chain", chain.remote)
    mine = reopen(mine)
    assert "Chain 2" in names(mine) and mine.repository.head() == first and mine.has_unpublished_changes()


def test_the_window_of_the_branches_asks_for_the_checkout_of_a_version(app, server, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import arcadia_tool.ui.main_window as main_window
    from arcadia_tool.ui.branches import BranchesDialog, CheckoutDialog

    url, download, reopen = server
    mine = download("mine")
    mine.new_element("domain", name="Solo qui")
    mine.publish("v3 solo qui", AUTHOR)
    v3, v2, v1 = (v.sha for v in mine.versions())
    dialog = CheckoutDialog(mine, "local:main")
    assert [dialog.version.itemData(i) for i in range(dialog.version.count())] == [v3, v2, v1]
    assert dialog.restore.isChecked() and "modifica da pubblicare" in dialog.note.text()
    dialog.version.setCurrentIndex(2)
    dialog.move.setChecked(True)
    later, only_here = dialog.later()
    assert len(later) == 2 and [v.sha for v in only_here] == [v3]
    assert "1 di esse sono solo su questo PC e vanno perse" in dialog.note.text()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    dialog._accept()
    assert dialog.sha is None  # cancelled: the version of this PC would be lost
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    dialog._accept()
    assert (dialog.name_value, dialog.sha, dialog.move_branch) == ("main", v1, True)

    branches = BranchesDialog(mine, {})
    assert branches.checkout_button.isEnabled()
    monkeypatch.setattr(CheckoutDialog, "exec", lambda d: (d.version.setCurrentIndex(1), d._accept(), True)[2])
    branches.checkout()
    assert branches.request == ("checkout", "main", v2, False)
    window = main_window.MainWindow()
    window._set_project(mine)
    window.open_project = lambda path, confirmed=False, **_kw: window._set_project(Project.open(path))
    window.branch_request(branches.request)
    assert names(window.project) == ["Localizzazione", "Protezione"] and window.project.has_unpublished_changes()
    assert "le differenze sono da pubblicare" in window.statusBar().currentMessage()
    window._set_project(None)
    window.close()


def test_the_versions_of_the_model_show_the_local_version_to_publish_or_discard(app, server, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import arcadia_tool.ui.main_window as main_window
    from arcadia_tool.ui.versions import HistoryDialog

    url, download, reopen = server
    mine = download("mine")
    history = HistoryDialog(mine)
    assert history.local is None and history.table.rowCount() == 2  # nothing local: the two versions
    assert not history.publish_button.isEnabled() and not history.discard_button.isEnabled()
    # Saved, not published; and not saved yet.
    mine.new_element("domain", name="Salvata non pubblicata")
    mine.save()
    added = mine.new_element("domain", name="Non salvata")
    history = HistoryDialog(mine)
    assert history.table.rowCount() == 3 and history.table.item(0, 4).text() == "locale"
    assert history.table.item(0, 2).text() == "Versione locale: 2 modifiche non pubblicate (1 non ancora salvate)"
    assert history.publish_button.isEnabled() and history.discard_button.isEnabled()
    history.table.selectRow(1)
    assert history._rows() == [0]  # the versions keep their index: the local row is not one of them
    history.table.selectRow(0)
    assert history._rows() == []
    history.publish()
    assert history.request == ("publish",)
    # Discarded from the window of the versions: back to the last version published of the branch, everything that
    # is not in it removed (saved, not saved, new files).
    window = main_window.MainWindow()
    window._set_project(mine)
    window.open_project = lambda path, confirmed=False, **_kw: window._set_project(Project.open(path))
    extra = mine.path / "model" / "x" / "readings"
    extra.mkdir(parents=True, exist_ok=True)
    (extra / "lettura.yaml").write_text("kind: reading\nuuid: 1\n", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(HistoryDialog, "exec", lambda d: d.discard())
    window.history()
    assert names(window.project) == ["Localizzazione", "Protezione"] and added.uuid not in window.project.model.elements
    assert not window.project.has_unpublished_changes() and not window.project.is_modified
    assert not (extra / "lettura.yaml").exists()
    assert window.history_action.text() == "Versioni Modello"
    window._set_project(None)
    window.close()


def test_the_window_of_the_versions_has_no_buttons_to_compare(app, server):
    from PySide6.QtWidgets import QPushButton
    from arcadia_tool.ui.versions import HistoryDialog

    url, download, reopen = server
    labels = [b.text() for b in HistoryDialog(download("mine")).findChildren(QPushButton)]
    assert not any(t.startswith("Confronta") for t in labels)  # «Confronta» of the toolbar
    assert "Crea ramo da questa versione…" in labels and "Pubblica…" in labels


def test_the_windows_close_while_they_download_the_branches(app, server, monkeypatch):
    import threading
    from arcadia_tool.ui import branches
    from arcadia_tool.ui.versions import CompareDialog

    url, download, reopen = server
    mine = download("mine")
    release = threading.Event()
    real = mine.fetch_branches
    monkeypatch.setattr(mine, "fetch_branches", lambda **k: (release.wait(10), real(**k)))  # a slow network
    compare = CompareDialog(mine, parent=None, credentials={})
    compare.show()  # the download starts with the window
    app.processEvents()
    assert compare.worker is not None and compare.worker.isRunning()
    compare.reject()  # the X
    assert not compare.isVisible() and compare.worker in branches._RUNNING  # closed, the download goes on
    worker = compare.worker
    release.set()
    worker.wait(10000)
    app.processEvents()
    assert worker not in branches._RUNNING and mine.fetched_at()  # ended by itself: the branches are up to date
    window = branches.BranchesDialog(mine, {})
    release.clear()
    window.fetch()
    window.accept()  # «Chiudi» too
    assert not window.isVisible() and window.worker in branches._RUNNING
    release.set()
    window.worker.wait(10000)
    app.processEvents()


def _run_update(app, dialog, names=None):
    """«Aggiorna Tutto» (names None) or «Aggiorna questo ramo», waited for (the worker runs in a thread)."""
    dialog.update_branches(names)
    dialog.worker.wait(20000)
    app.processEvents()


def test_the_window_of_the_branches_updates_all_of_them_or_one(app, server, monkeypatch):
    from arcadia_tool.ui import branches

    url, download, reopen = server
    mine = download("mine")
    activity_branch(download, reopen)  # only in the repository, for me
    colleague = download("colleague-main")
    colleague.new_element("domain", name="Frenatura")
    colleague.publish("frenatura", AUTHOR)
    colleague.push()  # main has a new version
    shown, asked = [], []
    monkeypatch.setattr(branches.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(branches.QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or branches.QMessageBox.No)
    dialog = branches.BranchesDialog(mine, {})
    assert dialog.fetch_button.text() == "Aggiorna Lista" and dialog.update_all_button.text() == "Aggiorna Tutto"
    _run_update(app, dialog)
    assert "att/T3-chain" in mine.repository.local_heads()  # downloaded to this PC
    assert "• att/T3-chain: scaricato su questo PC" in shown[-1]
    assert "• main (in uso): 1 nuova versione nel repository" in shown[-1]
    assert "Riceverle ora?" in asked[-1] and dialog.request is None  # not now: the window stays
    assert dialog.fetch_button.isEnabled() and dialog.update_all_button.isEnabled()
    rows = {dialog.table.item(r, 0).text(): r for r in range(dialog.table.rowCount())}
    assert dialog.table.item(rows["att/T3-chain"], 3).text() == "su questo PC e nel repository"

    # Right click on a branch: only that one.
    activity = download("colleague-chain-2")
    activity.switch_branch("att/T3-chain")
    activity = reopen(activity)
    activity.new_element("domain", name="Altro")
    activity.publish("altro", AUTHOR)
    activity.push()
    row = next(r for r, b in enumerate(dialog.branches) if b.name == "att/T3-chain")
    menu = dialog.branch_menu(row)
    action = next(a for a in menu.actions() if a.text() == "Aggiorna questo ramo")
    asked.clear()
    action.trigger()
    dialog.worker.wait(20000)
    app.processEvents()
    assert shown[-1].endswith("• att/T3-chain: ricevute 1 versione") and not asked  # the branch in use: not asked
    assert mine.repository.local_heads()["att/T3-chain"] == activity.repository.local_heads()["att/T3-chain"]
    # On the branch in use: received in the main window, which merges.
    row = next(r for r, b in enumerate(dialog.branches) if b.current)
    assert [a.text() for a in dialog.branch_menu(row).actions()] == ["Aggiorna questo ramo (ramo in uso)"]
    monkeypatch.setattr(branches.QMessageBox, "question", lambda *a, **k: branches.QMessageBox.Yes)
    _run_update(app, dialog, [mine.current_branch()])
    assert dialog.request == ("receive",)
    menu.deleteLater()
    dialog.deleteLater()


def test_reading_the_branches_offers_to_delete_those_no_longer_in_the_repository(app, server, monkeypatch):
    from arcadia_tool.ui import branches

    url, download, reopen = server
    mine = download("mine")
    main = mine.current_branch()
    for name in ("att/inviato", "att/con-lavoro"):
        mine.switch_branch(name, mine.versions()[0].sha)
        mine = reopen(mine)
        mine.push()
    mine.new_element("domain", name="Solo qui")
    mine.publish("solo qui", AUTHOR)  # att/con-lavoro: one version not sent
    mine.switch_branch(main)
    mine = reopen(mine)
    mine.switch_branch("att/nuovo", mine.versions()[0].sha)  # never sent
    mine = reopen(mine)
    mine.switch_branch(main)
    mine = reopen(mine)
    colleague = download("colleague")
    colleague.fetch_branches()
    for name in ("att/inviato", "att/con-lavoro"):
        colleague.delete_remote_branch(name)  # deleted from the repository by someone else
    shown = []

    def answer(dialog):
        shown.append([dialog.list.item(i).text() for i in range(dialog.list.count())])
        return True  # «Elimina da questo PC» with the ticks proposed
    monkeypatch.setattr(branches.LocalOnlyDialog, "exec", answer)
    dialog = branches.BranchesDialog(mine, {})
    dialog.fetch()  # «Aggiorna Lista»
    dialog.worker.wait(20000)
    for _ in range(20):
        app.processEvents()
    texts = shown[0]
    assert [t.split("  —  ")[0] for t in texts] == ["att/con-lavoro", "att/inviato", "att/nuovo"]  # not main
    assert "eliminato dal repository" in texts[1] and "andrebbero perse" in texts[0]
    assert "mai inviato" in texts[2]
    local = mine.repository.local_heads()
    assert "att/inviato" not in local  # deleted: gone from the repository, nothing of its own
    assert "att/con-lavoro" in local and "att/nuovo" in local  # not ticked: kept
    assert "att/inviato" in dialog.status.text()
    shown.clear()
    dialog.fetch()  # again: those kept are offered again, none ticked now
    dialog.worker.wait(20000)
    for _ in range(20):
        app.processEvents()
    assert len(shown) == 1 and set(mine.repository.local_heads()) >= {"att/con-lavoro", "att/nuovo"}
    dialog.deleteLater()
