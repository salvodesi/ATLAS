"""Versioni › Ricevi dal repository on the branches: the one in use, some chosen, or all of them (those only on the
remote are downloaded)."""
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


def test_a_branch_only_on_the_remote_is_downloaded(team):
    mine, colleague, reopen = team
    main, v = colleague.current_branch(), colleague.versions()[0].sha
    colleague.switch_branch("att/T9", v)
    colleague = reopen(colleague)
    colleague.new_element("domain", name="Nuovo")
    colleague.publish("nuovo", AUTHOR)
    colleague.push()
    assert "att/T9" not in mine.repository.local_heads()
    mine.fetch_branches()
    assert "att/T9" in mine.receivable_branches()
    assert mine.update_local_branches(["att/T9"]) == [("att/T9", Project.BRANCH_DOWNLOADED, 0)]
    assert mine.repository.local_heads()["att/T9"] == colleague.repository.local_heads()["att/T9"]
    assert mine.current_branch() == main  # the branch in use does not change
    assert mine.update_local_branches(["att/T9"]) == [("att/T9", Project.BRANCH_UP_TO_DATE, 0)]


def test_the_choice_of_the_branches(team):
    from arcadia_tool.ui.receive_choice import ALL, CHOSEN, ReceiveChoiceDialog

    QApplication.instance() or QApplication([])
    dialog = ReceiveChoiceDialog(["main", "att/T2", "att/T3"], "main", ["att/T3"])
    assert dialog.list.item(2).text() == "att/T3 (solo nel repository)"
    assert dialog.options[ALL].text() == "Tutti i rami (3)"
    assert dialog.buttons.button(QDialogButtonBox.Ok).text() == "Aggiorna il ramo in uso"
    assert dialog.choice() == "current" and dialog.branches() == ["main"]
    assert dialog.list.isEnabled()  # it scrolls, whatever the option
    assert not dialog.list.item(1).flags() & Qt.ItemIsUserCheckable  # but its ticks follow the option
    dialog.options[CHOSEN].setChecked(True)
    assert dialog.list.item(1).flags() & Qt.ItemIsUserCheckable and dialog.branches() == ["main"]  # in use ticked
    dialog.list.item(0).setCheckState(Qt.Unchecked)
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()  # nothing chosen
    dialog.list.item(2).setCheckState(Qt.Checked)
    assert dialog.branches() == ["att/T3"] and dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert dialog.buttons.button(QDialogButtonBox.Ok).text() == "Aggiorna «att/T3»"
    dialog.options[ALL].setChecked(True)
    assert dialog.branches() == ["main", "att/T2", "att/T3"]
    assert dialog.buttons.button(QDialogButtonBox.Ok).text() == "Aggiorna 3 rami"
    assert all(dialog.list.item(i).checkState() == Qt.Checked for i in range(3))  # all of them ticked
    dialog.options[CHOSEN].setChecked(True)
    assert dialog.branches() == ["att/T3"]  # the choice made before, back
    dialog.options["current"].setChecked(True)
    assert [dialog.list.item(i).checkState() == Qt.Checked for i in range(3)] == [True, False, False]
    dialog.deleteLater()


def test_the_window_receives_the_branch_in_use_and_reports_the_others(team, monkeypatch):
    from arcadia_tool.ui import main_window, receive_choice

    QApplication.instance() or QApplication([])
    mine, colleague, reopen = team
    mine, colleague, main = _two_branches(mine, colleague, reopen)
    colleague.new_element("domain", name="Odometria")
    colleague.publish("odometria", AUTHOR)
    colleague.push()
    colleague.switch_branch("att/T9", colleague.versions()[0].sha)
    colleague = reopen(colleague)
    colleague.push()  # a branch only on the remote

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
    monkeypatch.setattr(window, "receive_versions",
                        lambda: received.append((window.project.current_branch(), len(shown))))
    busy = []
    monkeypatch.setattr(main_window, "run_busy", lambda parent, text, work: busy.append(text) or work(busy.append))
    window.receive_from_repository()
    assert received == [(main, 1)]  # the branch in use after the report of the others
    assert "Aggiornamento di 2 rami…" in busy
    assert "Aggiornamento del ramo «att/T2» (1 di 2)…" in busy and "Aggiornamento del ramo «att/T9» (2 di 2)…" in busy
    assert shown[-1].startswith("Aggiornamento di 2 rami completato:")
    assert f"Ora si ricevono le versioni del ramo in uso «{main}»" in shown[-1]
    assert shown and "• att/T2: ricevute 1 versione" in shown[-1]
    assert "• att/T9: scaricato su questo PC" in shown[-1]
    assert "att/T9" in window.project.repository.local_heads()
    window._set_project(None)
    window.close()
