"""Versioni › Ricevi dal repository: which branches receive the versions of the remote — the one in use, some chosen
among those of this PC and of the remote, or all of them (those only on the remote are downloaded to this PC)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
                               QRadioButton, QVBoxLayout)

CURRENT, CHOSEN, ALL = "current", "chosen", "all"


def _versions(n):
    return f"{n} {'versione' if n == 1 else 'versioni'}"


def branch_outcome(state, count):
    """What a branch not in use received (a state of Project.update_local_branches), said to the user."""
    from arcadia_tool.storage.project import Project as P
    return {P.BRANCH_UPDATED: f"ricevute {_versions(count)}",
            P.BRANCH_UP_TO_DATE: "già aggiornato",
            P.BRANCH_AHEAD: f"già aggiornato; {_versions(count)} di questo PC da inviare",
            P.BRANCH_DIVERGED: f"{_versions(count)} nel repository da unire alle tue: passa al ramo e ricevi",
            P.BRANCH_NOT_ON_REMOTE: "non è nel repository",
            P.BRANCH_DOWNLOADED: "scaricato su questo PC",
            P.BRANCH_REFUSED: f"{_versions(count)} di questo PC rifiutate dal repository (permessi): passa al ramo "
                              "e spostale su un nuovo ramo, o scartale"}[state]


def branches_report(report):
    """The lines «• name: outcome» of a report of Project.update_local_branches."""
    return "\n".join(f"• {name}: {branch_outcome(state, count)}" for name, state, count in report)


class ReceiveChoiceDialog(QDialog):
    """The choice of the branches to update. branches(): the names chosen, the one in use first if among them."""

    def __init__(self, names, current, remote_only=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ricevi dal repository")
        self.setMinimumWidth(460)
        self.current, self.names, self.remote_only = current, list(names), set(remote_only)
        layout = QVBoxLayout(self)
        intro = QLabel("Quali rami aggiornare con le versioni del repository?")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.group = QButtonGroup(self)
        self.options = {}
        for key, text in ((CURRENT, f"Il ramo in uso («{current}»)"), (CHOSEN, "I rami scelti dall'elenco"),
                          (ALL, f"Tutti i rami ({len(self.names)})")):
            button = QRadioButton(text)
            self.group.addButton(button)
            self.options[key] = button
            layout.addWidget(button)
            if key == CHOSEN:
                self.list = QListWidget(objectName="receiveBranches")
                for name in self.names:
                    item = QListWidgetItem(f"{name} (in uso)" if name == current else
                                           f"{name} (solo nel repository)" if name in self.remote_only else name)
                    item.setData(Qt.UserRole, name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if name == current else Qt.Unchecked)
                    self.list.addItem(item)
                self.list.setMaximumHeight(160)
                layout.addWidget(self.list)
        note = QLabel("Il ramo in uso riceve le versioni e le unisce alle tue, come sempre. Gli altri rami prendono le "
                      "versioni del repository solo se non ne hanno di proprie da inviare; altrimenti si ricevono "
                      "passando a quel ramo. I rami presenti solo nel repository vengono scaricati su questo PC.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Ricevi")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.chosen = {self.current}  # the ticks of «I rami scelti dall'elenco», kept while another option is on
        self.group.buttonToggled.connect(lambda _button, on: on and self._show_choice())
        self.list.itemChanged.connect(lambda *_: self._ticked())
        self.options[CURRENT].setChecked(True)
        self._show_choice()

    def choice(self):
        return next(k for k, b in self.options.items() if b.isChecked())

    def branches(self):
        if self.choice() == CURRENT:
            chosen = [self.current]
        elif self.choice() == ALL:
            chosen = list(self.names)
        else:
            chosen = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                      if self.list.item(i).checkState() == Qt.Checked]
        return sorted(chosen, key=lambda n: n != self.current)

    def _show_choice(self):
        """The list ticks what the option updates: the branch in use, all of them, or those chosen by hand."""
        choice = self.choice()
        ticked = {self.current} if choice == CURRENT else set(self.names) if choice == ALL else self.chosen
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in ticked else Qt.Unchecked)
            # Ticks changeable only for the branches chosen by hand; the list stays enabled, so it scrolls.
            flags = item.flags() | Qt.ItemIsUserCheckable if choice == CHOSEN else item.flags() & ~Qt.ItemIsUserCheckable
            item.setFlags(flags)
        self.list.blockSignals(False)
        self._update()

    def _ticked(self):
        if self.choice() == CHOSEN:
            self.chosen = {self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                           if self.list.item(i).checkState() == Qt.Checked}
        self._update()

    def _update(self):
        """The button says what is updated: the branch in use, or how many branches."""
        chosen = self.branches()
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(bool(chosen))
        ok.setText("Aggiorna il ramo in uso" if chosen == [self.current] else
                   f"Aggiorna «{chosen[0]}»" if len(chosen) == 1 else f"Aggiorna {len(chosen)} rami" if chosen else
                   "Aggiorna")
