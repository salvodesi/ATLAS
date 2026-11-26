"""The members of a team in its sheet (EPBS-1): a table of the users of the team, added, changed and removed with
their own window by a member of the Design Authority. Each member has the ID of their local account, which the
person tells the DA (Utente › Modifica account): the account is then recognized as that member (see model.teams).
A person who works on more PCs has an account on each, so more IDs, all of them written in their row."""
import re

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from arcadia_tool.model.teams import (ACCOUNT, MAIN_PUSH, account_ids, accounts_value, normalize_account_id,
                                      person_key)
from arcadia_tool.ui.theme import icon

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OWN_ID = ("Il tuo account non sarebbe più tra i membri dei team: non potresti più aprire il progetto. Il tuo ID "
          "non viene rimosso. Per lasciare il team, aggiungi prima te stesso con il tuo ID a un altro team, oppure "
          "chiedi a un altro membro della Design Authority di farlo.")
COLUMNS = ("Nome e cognome", "E-mail", "Ruolo", "ID account", "Ramo principale", "")
KEYS = ("name", "email", "role", ACCOUNT)
MAIN = 4  # the tick «Invia sul ramo principale»
ACTIONS = 5
MAIN_TIP = ("Può modificare il ramo principale (pubblicare, inviare, integrare). Se nessun membro di nessun team è "
            "spuntato, possono farlo i membri della Design Authority; se qualcuno è spuntato, solo i membri spuntati "
            "(anche della DA). Spunta chi ha il permesso di inviare sul ramo principale nel repository.")


def own_id_error(parent):
    """The ID of the user was about to be removed from the teams (e.g. by mistake, by the DA themselves)."""
    QMessageBox.critical(parent, "Errore: rimozione del tuo ID", OWN_ID)


class AccountsList(QWidget):
    """The IDs of the accounts of a member, one per PC: a list, a field to add one (pasted, Invio or «Aggiungi»;
    more at once, separated by spaces or commas) and «Rimuovi» for the one selected."""

    def __init__(self, ids=(), parent=None):
        super().__init__(parent)
        self.list = QListWidget()
        self.list.setToolTip("Gli ID degli account della persona, uno per ogni PC su cui lavora")
        line = max(self.list.fontMetrics().lineSpacing(), 16) + 10  # a line with its icon
        self.list.setFixedHeight(line * 4 + 6)  # four PCs at sight, then it scrolls
        self.list.itemSelectionChanged.connect(self._update)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Incolla un ID, es. 87d54dd9af00427385b975fbf98baeba")
        self.entry.setToolTip("Chiedilo alla persona: è l'«ID» in alto nella finestra Utente › Modifica account del "
                              "suo ATLAS, generato quando ha creato l'account. Chi lavora su più PC ha un account, e "
                              "un ID, su ciascuno: aggiungili tutti")
        self.entry.returnPressed.connect(lambda: self.add())
        self.entry.installEventFilter(self)  # Invio adds the ID: it does not also press «Salva» of the window
        self.entry.textChanged.connect(lambda _t: self._update())
        self.add_button = QPushButton(icon("mdi6.plus"), "Aggiungi")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda _checked=False: self.add())
        self.remove_button = QPushButton(icon("mdi6.minus"), "Rimuovi")
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(self.remove)
        row = QHBoxLayout()
        row.addWidget(self.entry, 1)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addLayout(row)
        self.set_ids(ids)

    def eventFilter(self, watched, event):
        enter = event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if watched is self.entry and enter:
            if self.entry.text().strip():
                self.add()
                return True
        return super().eventFilter(watched, event)

    def set_ids(self, ids):
        self.list.clear()
        for a in dict.fromkeys(ids):
            self.list.addItem(QListWidgetItem(icon("mdi6.laptop"), a))
        self._update()

    def set_text(self, text):
        """The IDs written in a text (e.g. pasted all at once): the valid ones in the list, the others left in the
        field."""
        self.set_ids([])
        self.entry.setText(text)
        self.add(warn=False)

    def ids(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def pending(self):
        """What is written in the field and not added yet."""
        return [t for t in re.split(r"[\s,;]+", self.entry.text()) if t]

    def add(self, warn=True):
        written = self.pending()
        invalid = [t for t in written if not normalize_account_id(t)]
        for a in (normalize_account_id(t) for t in written):
            if a and a not in self.ids():
                self.list.addItem(QListWidgetItem(icon("mdi6.laptop"), a))
        self.entry.setText(" ".join(invalid))
        if invalid and warn:
            QMessageBox.warning(self, "ID account", f"«{invalid[0]}» non è un ID valido: un ID ha 32 caratteri "
                                "(cifre e lettere da a a f), come appare in Utente › Modifica account.")
        self._update()

    def remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._update()

    def _update(self):
        self.add_button.setEnabled(bool(self.entry.text().strip()))
        self.remove_button.setEnabled(bool(self.list.selectedItems()))


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
        # A list: one ID for each PC the person works on (each PC has its own local account).
        self.account = AccountsList(account_ids(self.row))
        self.email = QLineEdit(self.row.get("email") or "")
        self.role = QLineEdit(self.row.get("role") or "")
        self.role.setPlaceholderText("es. Analista di sistema")
        self.main_push = QCheckBox("Può inviare sul ramo principale")
        self.main_push.setChecked(bool(self.row.get(MAIN_PUSH)))
        self.main_push.setToolTip(MAIN_TIP)
        form = QFormLayout()
        form.addRow("Nome e cognome *", self.name)
        form.addRow("ID account *\n(uno per postazione)", self.account)
        form.addRow("E-mail", self.email)
        form.addRow("Ruolo", self.role)
        form.addRow("Ramo principale", self.main_push)
        note = QLabel("Chiedi alla persona l'ID del suo account locale: è in alto nella finestra Utente › Modifica "
                      "account del suo ATLAS, che lo copia con un clic. Da quel momento ATLAS la riconosce come membro "
                      "di questo team, anche nelle versioni che pubblica. Se lavora su più PC, ha un ID per ciascuno: "
                      "aggiungili tutti alla lista.", objectName="muted")
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
        # The IDs of the list, and one written in the field and not added yet: taken too.
        pending = self.account.pending()
        written = self.account.ids() + pending
        invalid = [t for t in pending if not normalize_account_id(t)]
        accounts = list(dict.fromkeys(normalize_account_id(t) for t in written if normalize_account_id(t)))
        problems = []
        if not name:
            problems.append("Indica nome e cognome.")
        elif any(person_key(o.get("name")) == person_key(name) for o in self.others):
            problems.append(f"{name} è già tra i membri del team.")
        if not written:
            problems.append("Indica l'ID dell'account della persona (Utente › Modifica account nel suo ATLAS).")
        elif invalid:
            listed = ", ".join(f"«{t}»" for t in invalid)
            said = f"L'ID {listed} non è valido" if len(invalid) == 1 else f"Gli ID {listed} non sono validi"
            problems.append(f"{said}: un ID ha 32 caratteri (cifre e lettere da a a f), come appare in Utente › "
                            "Modifica account.")
        else:
            for other in self.others:
                shared = [a for a in accounts if a in account_ids(other)]
                if shared:
                    problems.append(f"L'ID {shared[0][:8]}… è già di un altro membro del team "
                                    f"({other.get('name') or 'senza nome'}).")
        if email and not EMAIL.match(email):
            problems.append("L'indirizzo e-mail non è valido.")
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        self.row.update(name=name, email=email, role=self.role.text().strip(), **{ACCOUNT: accounts_value(accounts)},
                        **{MAIN_PUSH: self.main_push.isChecked()})
        self.row = {k: v for k, v in self.row.items() if v}  # «main_push» only when ticked
        self.accept()


class MembersWidget(QWidget):
    """value(): the rows {name, email, role, account}."""
    changed = Signal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model, self.rows = model, []
        self.locks_out = None  # function(rows) → True if the rows would leave the user outside the project
        # A read-only sheet: the members are only shown; adding, changing or removing one asks to switch to edit
        # mode (locked), else the change would stay in the table and never reach the model.
        self.editable, self.locked = True, None
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        for column, mode in enumerate((QHeaderView.Stretch, QHeaderView.Stretch, QHeaderView.Stretch,
                                       QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
                                       QHeaderView.ResizeToContents)):
            header.setSectionResizeMode(column, mode)
        self.table.horizontalHeaderItem(MAIN).setToolTip(MAIN_TIP)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.itemDoubleClicked.connect(lambda item: item.column() != MAIN and self.edit_member(item.row()))
        self.table.itemChanged.connect(self._ticked)
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
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            for column, key in enumerate(KEYS):
                value = row.get(key) or ""
                item = QTableWidgetItem(value if isinstance(value, str) else "")
                if key == ACCOUNT:
                    ids = account_ids(row)
                    more = f" (+{len(ids) - 1})" if len(ids) > 1 else ""
                    item.setText(f"{ids[0][:8]}…{more}" if ids else "da indicare")
                    item.setToolTip("\n".join(ids) if ids else "ID dell'account locale del membro non ancora "
                                    "indicato: finché manca, è riconosciuto da nome e cognome")
                self.table.setItem(i, column, item)
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            tick.setCheckState(Qt.Checked if row.get(MAIN_PUSH) else Qt.Unchecked)
            tick.setToolTip(MAIN_TIP)
            self.table.setItem(i, MAIN, tick)
            self.table.setCellWidget(i, ACTIONS, self._actions(i))
        self.table.blockSignals(False)
        self.table.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        self.table.setFixedHeight(self.table.horizontalHeader().height() + 34 * len(self.rows) + 4)

    def _ticked(self, item):
        """«Ramo principale» ticked or not in the table: the member may send to the main branch (see MAIN_PUSH)."""
        i = item.row()
        if item.column() != MAIN or not 0 <= i < len(self.rows):
            return
        on = item.checkState() == Qt.Checked
        if bool(self.rows[i].get(MAIN_PUSH)) == on:
            return
        if not self._may_change():  # a read-only sheet: the tick goes back
            self._fill()
            return
        row = dict(self.rows[i])
        if on:
            row[MAIN_PUSH] = True
        else:
            row.pop(MAIN_PUSH, None)
        self.rows[i] = row
        self.changed.emit()

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

    def _may_change(self):
        if self.editable:
            return True
        if self.locked is not None:
            self.locked()
        return False

    def add_member(self):
        if not self._may_change():
            return None
        dialog = MemberDialog(None, self._others(), self)
        if dialog.exec():
            self.rows.append(dialog.row)
            self._fill()
            self.changed.emit()
            return dialog.row
        return None

    def edit_member(self, i):
        if not self.isEnabled() or not 0 <= i < len(self.rows) or not self._may_change():
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
        if not 0 <= i < len(self.rows) or not self._may_change():
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
