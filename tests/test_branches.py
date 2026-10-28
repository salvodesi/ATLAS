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
    mine.fetch_branches()  # what «Aggiorna dal repository» does (in a thread)
    dialog.fill()
    rows = {dialog.table.item(r, 0).text(): r for r in range(dialog.table.rowCount())}
    assert set(rows) == {"main  (in uso)", "att/T3-chain"}
    r = rows["att/T3-chain"]
    assert dialog.table.item(r, 3).text() == "solo nel repository" and dialog.table.item(r, 4).text() == "1 avanti"
    assert dialog.table.item(rows["main  (in uso)"], 4).text() == "ramo principale"
    dialog.table.selectRow(rows["main  (in uso)"])
    assert not dialog.switch_button.isEnabled()  # already in use
    dialog.table.selectRow(r)
    assert dialog.switch_button.isEnabled() and dialog.compare_main.isEnabled()
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
    window.open_project = lambda path, confirmed=False: window._set_project(Project.open(path))
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
    assert actions.index("Rami…") == actions.index("Pubblica…") - 1  # right before «Pubblica»
    window.close()
