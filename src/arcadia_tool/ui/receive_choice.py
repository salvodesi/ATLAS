"""Versioni › Ricevi dal repository: which branches of this PC receive the versions of the remote — the one in use,
some chosen among those of this PC, or all of them."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
                               QRadioButton, QVBoxLayout)

CURRENT, CHOSEN, ALL = "current", "chosen", "all"


class ReceiveChoiceDialog(QDialog):
    """The choice of the branches to update. branches(): the names chosen, the one in use first if among them."""

    def __init__(self, names, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ricevi dal repository")
        self.setMinimumWidth(460)
        self.current, self.names = current, list(names)
        layout = QVBoxLayout(self)
        intro = QLabel("Quali rami di questo PC aggiornare con le versioni del repository?")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.group = QButtonGroup(self)
        self.options = {}
        for key, text in ((CURRENT, f"Il ramo in uso («{current}»)"), (CHOSEN, "I rami scelti dall'elenco"),
                          (ALL, f"Tutti i rami di questo PC ({len(self.names)})")):
            button = QRadioButton(text)
            self.group.addButton(button)
            self.options[key] = button
            layout.addWidget(button)
            if key == CHOSEN:
                self.list = QListWidget(objectName="receiveBranches")
                for name in self.names:
                    item = QListWidgetItem(f"{name} (in uso)" if name == current else name)
                    item.setData(Qt.UserRole, name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if name == current else Qt.Unchecked)
                    self.list.addItem(item)
                self.list.setMaximumHeight(160)
                layout.addWidget(self.list)
        note = QLabel("Il ramo in uso riceve le versioni e le unisce alle tue, come sempre. Gli altri rami prendono le "
                      "versioni del repository solo se non ne hanno di proprie da inviare; altrimenti si ricevono "
                      "passando a quel ramo.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Ricevi")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.group.buttonToggled.connect(lambda *_: self._update())
        self.list.itemChanged.connect(lambda *_: self._update())
        self.options[CURRENT].setChecked(True)
        self._update()

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

    def _update(self):
        self.list.setEnabled(self.choice() == CHOSEN)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.branches()))
