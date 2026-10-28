"""The members of a team in its sheet (EPBS-1): a table of the users of the team, added, changed and removed with
their own window by a member of the Design Authority. Each member has the ID of their local account, which the
person tells the DA (Utente › Modifica account): the account is then recognized as that member (see model.teams)."""
import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from arcadia_tool.model.teams import ACCOUNT, normalize_account_id, person_key
from arcadia_tool.ui.theme import icon

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OWN_ID = ("Il tuo account non sarebbe più tra i membri dei team: non potresti più aprire il progetto. Il tuo ID "
          "non viene rimosso. Per lasciare il team, aggiungi prima te stesso con il tuo ID a un altro team, oppure "
          "chiedi a un altro membro della Design Authority di farlo.")
COLUMNS = ("Nome e cognome", "E-mail", "Ruolo", "ID account", "")
KEYS = ("name", "email", "role", ACCOUNT)
ACTIONS = 4


def own_id_error(parent):
    """The ID of the user was about to be removed from the teams (e.g. by mistake, by the DA themselves)."""
    QMessageBox.critical(parent, "Errore: rimozione del tuo ID", OWN_ID)


class MemberDialog(QDialog):
    """A new member (row None) or the details of one. `row` is the member on OK."""

    def __init__(self, row=None, others=(), parent=None):
        super().__init__(parent)
        self.row = dict(row or {})
        self.others = others  # the other members of the team: the same person is not added twice
        self.setWindowTitle("Nuovo membro del team" if row is None else "Dettagli del membro")
        self.setMinimumWidth(640)
        self.name = QLineEdit(self.row.get("name") or "")
        self.name.setPlaceholderText("es. Mario Rossi")
        self.account = QLineEdit(self.row.get(ACCOUNT) or "")
        self.account.setPlaceholderText("32 caratteri, es. 87d54dd9af00427385b975fbf98baeba")
        self.account.setToolTip("Chiedilo alla persona: è l'«ID» in alto nella finestra Utente › Modifica account "
                                "del suo ATLAS, generato quando ha creato l'account")
        self.email = QLineEdit(self.row.get("email") or "")
        self.role = QLineEdit(self.row.get("role") or "")
        self.role.setPlaceholderText("es. Analista di sistema")
        form = QFormLayout()
        form.addRow("Nome e cognome *", self.name)
        form.addRow("ID account *", self.account)
        form.addRow("E-mail", self.email)
        form.addRow("Ruolo", self.role)
        note = QLabel("Chiedi alla persona l'ID del suo account locale: è in alto nella finestra Utente › Modifica "
                      "account del suo ATLAS, che lo copia con un clic. Da quel momento ATLAS la riconosce come membro "
                      "di questo team, anche nelle versioni che pubblica.", objectName="muted")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aggiungi" if row is None else "Salva")
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.name.setFocus()

    def _accept(self):
        name = " ".join(self.name.text().split())
        email = self.email.text().strip()
        account = normalize_account_id(self.account.text())
        problems = []
        if not name:
            problems.append("Indica nome e cognome.")
        elif any(person_key(o.get("name")) == person_key(name) for o in self.others):
            problems.append(f"{name} è già tra i membri del team.")
        if not self.account.text().strip():
            problems.append("Indica l'ID dell'account della persona (Utente › Modifica account nel suo ATLAS).")
        elif not account:
            problems.append("L'ID account non è valido: sono 32 caratteri (cifre e lettere da a a f), come appare in "
                            "Utente › Modifica account.")
        elif any(normalize_account_id(o.get(ACCOUNT)) == account for o in self.others):
            problems.append("Questo ID account è già di un altro membro del team.")
        if email and not EMAIL.match(email):
            problems.append("L'indirizzo e-mail non è valido.")
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        self.row.update(name=name, email=email, role=self.role.text().strip(), **{ACCOUNT: account})
        self.row = {k: v for k, v in self.row.items() if v}
        self.accept()


class MembersWidget(QWidget):
    """value(): the rows {name, email, role, account}."""
    changed = Signal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model, self.rows = model, []
        self.locks_out = None  # function(rows) → True if the rows would leave the user outside the project
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        for column, mode in enumerate((QHeaderView.Stretch, QHeaderView.Stretch, QHeaderView.Stretch,
                                       QHeaderView.ResizeToContents, QHeaderView.ResizeToContents)):
            header.setSectionResizeMode(column, mode)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.itemDoubleClicked.connect(lambda item: self.edit_member(item.row()))
        self.empty = QLabel("Nessun membro: aggiungili con «Aggiungi membro…».", objectName="muted")
        self.add_button = QPushButton(icon("mdi6.account-plus-outline"), "Aggiungi membro…")
        self.add_button.clicked.connect(self.add_member)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addWidget(self.empty)
        layout.addLayout(buttons)

    def set_value(self, rows):
        self.rows = [dict(r) for r in rows or []]
        self._fill()

    def value(self):
        return [dict(r) for r in self.rows]

    def _fill(self):
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            for column, key in enumerate(KEYS):
                value = row.get(key) or ""
                item = QTableWidgetItem(value)
                if key == ACCOUNT:
                    item.setText(f"{value[:8]}…" if value else "da indicare")
                    item.setToolTip(value or "ID dell'account locale del membro non ancora indicato: finché manca, "
                                             "è riconosciuto da nome e cognome")
                self.table.setItem(i, column, item)
            self.table.setCellWidget(i, ACTIONS, self._actions(i))
        self.table.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        self.table.setFixedHeight(self.table.horizontalHeader().height() + 34 * len(self.rows) + 4)

    def _actions(self, i):
        holder = QWidget()
        box = QHBoxLayout(holder)
        box.setContentsMargins(4, 0, 4, 0)
        box.setSpacing(2)
        edit = QToolButton(autoRaise=True)
        edit.setIcon(icon("mdi6.pencil-outline"))
        edit.setToolTip("Modifica i dettagli del membro")
        edit.clicked.connect(lambda: self.edit_member(i))
        remove = QToolButton(autoRaise=True)
        remove.setIcon(icon("mdi6.trash-can-outline", "#B42318"))
        remove.setToolTip("Rimuovi il membro dal team")
        remove.clicked.connect(lambda: self.remove_member(i))
        box.addWidget(edit)
        box.addWidget(remove)
        return holder

    def _others(self, i=None):
        return [r for n, r in enumerate(self.rows) if n != i]

    def add_member(self):
        dialog = MemberDialog(None, self._others(), self)
        if dialog.exec():
            self.rows.append(dialog.row)
            self._fill()
            self.changed.emit()
            return dialog.row
        return None

    def edit_member(self, i):
        if not self.isEnabled() or not 0 <= i < len(self.rows):
            return
        dialog = MemberDialog(self.rows[i], self._others(i), self)
        if dialog.exec():
            rows = [dialog.row if n == i else r for n, r in enumerate(self.rows)]
            if self.locks_out is not None and self.locks_out(rows):  # e.g. the DA changing their own ID
                own_id_error(self)
                return
            self.rows[i] = dialog.row
            self._fill()
            self.changed.emit()

    def remove_member(self, i):
        if not 0 <= i < len(self.rows):
            return
        name = self.rows[i].get("name")
        if self.locks_out is not None and self.locks_out(self._others(i)):  # the DA removing themselves
            own_id_error(self)
            return
        if QMessageBox.question(self, "Rimuovi membro",
                                f"Rimuovere {name} dal team? Il suo account non sarà più riconosciuto come membro.") \
                != QMessageBox.Yes:
            return
        del self.rows[i]
        self._fill()
        self.changed.emit()
