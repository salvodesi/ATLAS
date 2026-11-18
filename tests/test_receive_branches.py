"""Versioni › Ricevi dal repository on the branches of this PC: the one in use, some chosen, or all of them."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from arcadia_tool.storage.project import Project
from tests.test_receive import AUTHOR, team  # noqa: F401  (the fixture)


def _two_branches(mine, colleague, reopen):
    """«att/T2» on the remote and on my PC, with main in use on my PC; the colleague then adds a version to it."""
    main, v = mine.current_branch(), mine.versions()[0].sha
    mine.switch_branch("att/T2", v)
    mine = reopen(mine)
    mine.push()
    mine.switch_branch(main)
    mine = reopen(mine)
    colleague.fetch_branches()
    colleague.switch_branch("att/T2")
    colleague = reopen(colleague)
    return mine, colleague, main


def test_a_branch_not_in_use_takes_the_versions_of_the_remote(team):
    mine, colleague, reopen = team
    mine, colleague, main = _two_branches(mine, colleague, reopen)
    colleague.new_element("domain", name="Odometria")
    colleague.publish("odometria", AUTHOR)
    colleague.push()
    before = mine.repository.local_heads()[main]
    report = mine.update_local_branches([main, "att/T2"])
    assert report == [("att/T2", Project.BRANCH_UPDATED, 1)]  # the branch in use: skipped
    assert mine.repository.local_heads()["att/T2"] == colleague.repository.local_heads()["att/T2"]
    assert mine.repository.local_heads()[main] == before and mine.current_branch() == main
    assert mine.update_local_branches(["att/T2"]) == [("att/T2", Project.BRANCH_UP_TO_DATE, 0)]


def test_a_branch_with_versions_of_its_own_is_not_moved(team):
    mine, colleague, reopen = team
    mine, colleague, main = _two_branches(mine, colleague, reopen)
    mine.switch_branch("att/T2")
    mine = reopen(mine)
    mine.new_element("domain", name="Mia")
    mine.publish("mia", AUTHOR)
    mine.switch_branch(main)
    mine = reopen(mine)
    mine_head = mine.repository.local_heads()["att/T2"]
    assert mine.update_local_branches(["att/T2"]) == [("att/T2", Project.BRANCH_AHEAD, 1)]
    colleague.new_element("domain", name="Sua")
    colleague.publish("sua", AUTHOR)
    colleague.push()
    assert mine.update_local_branches(["att/T2"]) == [("att/T2", Project.BRANCH_DIVERGED, 1)]
    assert mine.repository.local_heads()["att/T2"] == mine_head  # merged only from the branch itself


def test_the_choice_of_the_branches(team):
    from arcadia_tool.ui.receive_choice import ALL, CHOSEN, ReceiveChoiceDialog

    QApplication.instance() or QApplication([])
    dialog = ReceiveChoiceDialog(["main", "att/T2", "att/T3"], "main")
    assert dialog.choice() == "current" and dialog.branches() == ["main"] and not dialog.list.isEnabled()
    dialog.options[CHOSEN].setChecked(True)
    assert dialog.list.isEnabled() and dialog.branches() == ["main"]  # the one in use ticked at first
    dialog.list.item(0).setCheckState(Qt.Unchecked)
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()  # nothing chosen
    dialog.list.item(2).setCheckState(Qt.Checked)
    assert dialog.branches() == ["att/T3"] and dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dialog.options[ALL].setChecked(True)
    assert dialog.branches() == ["main", "att/T2", "att/T3"]
    dialog.deleteLater()


def test_the_window_receives_the_branch_in_use_and_reports_the_others(team, monkeypatch):
    from arcadia_tool.ui import main_window, receive_choice

    QApplication.instance() or QApplication([])
    mine, colleague, reopen = team
    mine, colleague, main = _two_branches(mine, colleague, reopen)
    colleague.new_element("domain", name="Odometria")
    colleague.publish("odometria", AUTHOR)
    colleague.push()

    class AllBranches(receive_choice.ReceiveChoiceDialog):
        def exec(self):
            self.options[receive_choice.ALL].setChecked(True)
            return True
    monkeypatch.setattr(receive_choice, "ReceiveChoiceDialog", AllBranches)
    shown = []
    monkeypatch.setattr(main_window.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    window = main_window.MainWindow()
    window._set_project(mine)
    received = []
    monkeypatch.setattr(window, "receive_versions", lambda: received.append(window.project.current_branch()))
    monkeypatch.setattr(main_window, "run_busy", lambda parent, text, work: work(lambda _t: None))
    window.receive_from_repository()
    assert received == [main]
    assert shown and "• att/T2: ricevute 1 versione" in shown[-1]
    window._set_project(None)
    window.close()
