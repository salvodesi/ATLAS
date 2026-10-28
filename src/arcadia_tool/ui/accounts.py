"""Account windows: creation and change of a local account, login at the start of the tool, and the panel of
the access to a Git server (used in the project settings, kept in the account)."""
import copy
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from arcadia_tool import APP_FULL_NAME, DATA_NAME, accounts
from arcadia_tool.accounts import HTTPS, SSH, Account, AccountError, AccountStore, GitAccess
from arcadia_tool.ui.branding import image_label, symbol
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.theme import icon

LOGIN_LOGO_SIZE = 112


def account_store():
    """Accounts of this PC, in the user folder of the tool (next to its settings file)."""
    return AccountStore(Path(settings().fileName()).parent / DATA_NAME)


class _Centered(QDialog):
    """Shown in the middle of its parent window (also of a main window just maximized)."""

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()
        # Right away, and again once the system has added the title bar to the frame (a few pixels).
        QTimer.singleShot(0, self._center)
        QTimer.singleShot(60, self._center)

    def _fit(self):
        """As tall as its content once shown (the style, applied then, makes some rows taller)."""
        layout = self.layout()
        if layout is not None:
            layout.activate()
            needed = max(layout.totalMinimumSize().height(), self.sizeHint().height())
            if self.height() < needed:
                self.resize(self.width(), needed)

    def _center(self):
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            # The whole dialog (title bar included) on the centre of the visible area of the window.
            offset = parent.window().geometry().center() - self.frameGeometry().center()
            self.move(self.pos() + offset)


def _card(title):
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.addWidget(QLabel(title.upper(), objectName="sectionCaption"))
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    layout.addLayout(form)
    return frame, form


class AccountDialog(_Centered):
    """New account (account None) or change of an existing one. `account` is the saved account on «Salva».

    The access to the Git servers is not here: it is set for each project (Progetto › Impostazioni ›
    Repository Git) and kept in the account."""

    def __init__(self, store, account=None, parent=None, first=False):
        super().__init__(parent)
        self.store = store
        self.new = account is None
        self.account = Account() if self.new else copy.deepcopy(account)  # a copy until «Salva»
        self.setWindowTitle("Nuovo account" if self.new else "Account utente")
        self.resize(640, 0)

        intro = QLabel(
            "Prima di usare il tool crea il tuo account locale: ogni modifica pubblicata è associata a un utente." if first
            else "Dati del tuo account locale. Per essere riconosciuto come membro di un team, comunica l'ID alla "
                 "Design Authority del progetto.", objectName="muted")
        intro.setWordWrap(True)
        person, form = _card("Utente")
        self.ident = QLineEdit(self.account.id, readOnly=True, objectName="readonly")
        self.ident.setToolTip("Identificativo univoco dell'account, assegnato alla creazione: comunicalo alla "
                              "Design Authority, che lo indica aggiungendoti a un team")
        self.ident.setFocusPolicy(Qt.NoFocus)
        copy_id = QPushButton(icon("mdi6.content-copy"), "")
        copy_id.setToolTip("Copia l'ID dell'account, da inviare alla Design Authority")
        copy_id.clicked.connect(lambda: QApplication.clipboard().setText(self.account.id))
        ident_row = QWidget()
        ident_layout = QHBoxLayout(ident_row)
        ident_layout.setContentsMargins(0, 0, 0, 0)
        ident_layout.addWidget(self.ident, 1)
        ident_layout.addWidget(copy_id)
        self.first_name = QLineEdit(self.account.first_name)
        self.last_name = QLineEdit(self.account.last_name)
        self.username = QLineEdit(self.account.username)
        self.username.setPlaceholderText("es. mrossi")
        self.email = QLineEdit(self.account.email)
        self.email.setPlaceholderText("autore delle versioni pubblicate (Git)")
        self.password = QLineEdit(echoMode=QLineEdit.Password)
        self.confirm = QLineEdit(echoMode=QLineEdit.Password)
        if not self.new:
            self.password.setPlaceholderText("lascia vuoto per non cambiarla")
            self.confirm.setPlaceholderText("lascia vuoto per non cambiarla")
        for label, widget in (("ID", ident_row), ("Nome", self.first_name), ("Cognome", self.last_name),
                              ("Username", self.username), ("E-mail", self.email),
                              ("Password", self.password), ("Conferma password", self.confirm)):
            form.addRow(label, widget)
        git_note = QLabel("L'accesso ai repository Git (utente e password o chiave SSH) si imposta per ogni progetto "
                          "in Progetto › Impostazioni › Repository Git e resta salvato nel tuo account.",
                          objectName="muted")
        git_note.setWordWrap(True)
        servers = sorted(self.account.git)
        if servers:
            git_note.setText(git_note.text() + f" Server già configurati: {', '.join(servers)}.")

        save = QPushButton(icon("mdi6.check", "white"), "Crea account" if self.new else "Salva")
        save.setProperty("primary", True)
        save.clicked.connect(self._save)
        cancel = QPushButton("Esci" if first else "Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addWidget(person)
        layout.addWidget(git_note)
        layout.addLayout(buttons)
        self.first_name.setFocus()

    def _save(self):
        a = self.account
        a.first_name, a.last_name = self.first_name.text().strip(), self.last_name.text().strip()
        a.username, a.email = self.username.text().strip(), self.email.text().strip()
        password = self.password.text()
        problems = accounts.validate(a, self.store, password, self.new)
        if password != self.confirm.text():
            problems.append("Le due password non coincidono.")
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        try:
            if password:
                a.set_password(password)
        except AccountError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        (self.store.add if self.new else self.store.replace)(a)
        self.accept()


class GitAccessPanel(QWidget):
    """How the logged-in account reaches a Git server: user and password/token (HTTP/HTTPS) or the SSH key used
    for clone and push, generated here or loaded. Shown in the project settings; saved in the account."""
    changed = Signal()

    def __init__(self, store, account, parent=None):
        super().__init__(parent)
        self.store, self.account, self.host = store, account, ""
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.auth_https = QRadioButton(accounts.AUTH_LABELS[HTTPS])
        self.auth_ssh = QRadioButton(accounts.AUTH_LABELS[SSH])
        group = QButtonGroup(self)
        group.addButton(self.auth_https)
        group.addButton(self.auth_ssh)
        choice = QHBoxLayout()
        choice.addWidget(self.auth_https)
        choice.addWidget(self.auth_ssh)
        choice.addStretch()
        form.addRow("Autenticazione", choice)
        self.pages = QStackedWidget()

        https = QWidget()
        https_form = QFormLayout(https)
        https_form.setContentsMargins(0, 0, 0, 0)
        https_form.setLabelAlignment(Qt.AlignRight)
        self.git_username = QLineEdit()
        self.git_secret = QLineEdit(echoMode=QLineEdit.Password)
        self.git_secret.setPlaceholderText("password o token di accesso personale del server Git")
        https_form.addRow("Utente Git", self.git_username)
        https_form.addRow("Password / token", self.git_secret)
        https_form.addRow("", QLabel("Conservata nel Gestione credenziali di Windows.", objectName="muted"))

        ssh = QWidget()
        ssh_layout = QVBoxLayout(ssh)
        ssh_layout.setContentsMargins(0, 0, 0, 0)
        self.ssh_path = QLineEdit(readOnly=True, objectName="readonly")
        self.ssh_path.setPlaceholderText("nessuna chiave")
        generate = QPushButton(icon("mdi6.key-plus"), "Genera nuova chiave")
        generate.clicked.connect(self._generate_key)
        load = QPushButton(icon("mdi6.folder-key-outline"), "Carica chiave esistente…")
        load.clicked.connect(self._load_key)
        row = QHBoxLayout()
        row.addWidget(self.ssh_path, 1)
        row.addWidget(generate)
        row.addWidget(load)
        ssh_layout.addLayout(row)
        ssh_layout.addWidget(QLabel("Chiave privata usata per scaricare e inviare il progetto (clone, push).",
                                    objectName="muted"))

        self.pages.addWidget(https)
        self.pages.addWidget(ssh)
        form.addRow(self.pages)
        self.auth_https.toggled.connect(lambda on: self.pages.setCurrentIndex(0 if on else 1))
        for signal in (self.auth_https.toggled, self.git_username.textChanged, self.git_secret.textChanged):
            signal.connect(lambda *_: self.changed.emit())

    def show_server(self, url):
        """Fill the panel with what the account keeps for the server of `url`."""
        self.host = accounts.git_host(url)
        access = self.account.git_access(self.host) if self.account else GitAccess()
        (self.auth_ssh if access.auth == SSH else self.auth_https).setChecked(True)
        self.pages.setCurrentIndex(1 if access.auth == SSH else 0)
        self.git_username.setText(access.username)
        self.git_secret.setText(accounts.git_secret(self.account, self.host) if self.account and self.host else "")
        self.ssh_path.setText(access.ssh_key)

    def access(self):
        return GitAccess(SSH if self.auth_ssh.isChecked() else HTTPS, self.git_username.text().strip(),
                         self.ssh_path.text())

    def secret(self):
        return self.git_secret.text()

    def save(self):
        """Keep the access in the account (the password/token in the credential store). Raises AccountError."""
        problems = accounts.validate_git_access(self.access())
        if problems:
            raise AccountError("\n".join(problems))
        self.account.set_git_access(self.host, self.access())
        if self.access().auth == HTTPS:
            accounts.set_git_secret(self.account, self.host, self.secret())
        self.store.replace(self.account)

    def _generate_key(self):
        if self.ssh_path.text() and QMessageBox.question(
                self, "Chiave SSH", "Sostituire la chiave attuale con una nuova? La nuova chiave pubblica andrà "
                "aggiunta di nuovo al server Git.") != QMessageBox.Yes:
            return
        self.ssh_path.setText(accounts.generate_ssh_key(self.account, self.store.keys_folder))
        self.changed.emit()

    def _load_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chiave privata SSH", str(Path.home() / ".ssh"))
        if not path:
            return
        problem = accounts.check_ssh_key(path)
        if problem:
            QMessageBox.warning(self, "Chiave SSH", problem)
            return
        self.ssh_path.setText(path)
        self.changed.emit()


class LoginDialog(_Centered):
    """Access with a local account; without accounts the first one is created (mandatory)."""

    def __init__(self, store, parent=None, current=None):
        super().__init__(parent)
        self.store, self.account = store, None
        self.setWindowTitle("Accesso")
        self.resize(460, 0)
        logo = image_label(symbol(), LOGIN_LOGO_SIZE)
        full_name = QLabel(APP_FULL_NAME, objectName="muted", alignment=Qt.AlignCenter)
        intro = QLabel("Accedi con il tuo account locale: le modifiche che pubblichi sono associate a te.",
                       objectName="muted")
        intro.setWordWrap(True)
        self.username = QComboBox()
        self.username.setEditable(True)
        for a in store.accounts:
            self.username.addItem(f"{a.username} – {a.full_name}", a.username)
        last = current.username if current else settings().value("accounts/last", "")
        index = self.username.findData(last)
        self.username.setCurrentIndex(max(index, 0))
        self.password = QLineEdit(echoMode=QLineEdit.Password)
        self.password.returnPressed.connect(self._login)
        self.error = QLabel(objectName="muted")
        self.error.setStyleSheet("color: #B42318;")
        form = QFormLayout()
        form.addRow("Utente", self.username)
        form.addRow("Password", self.password)
        new = QPushButton(icon("mdi6.account-plus-outline"), "Nuovo account…")
        new.clicked.connect(self._new_account)
        login = QPushButton(icon("mdi6.login", "white"), "Accedi")
        login.setProperty("primary", True)
        login.setDefault(True)
        login.clicked.connect(self._login)
        cancel = QPushButton("Annulla" if current else "Esci")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(new)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(login)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(logo)
        layout.addWidget(full_name)
        layout.addSpacing(6)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addLayout(buttons)
        self.password.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        # The minimum height of Qt does not count the wrapped intro at the actual width: the rows would overlap.
        self.resize(self.width(), max(self.height(), self.layout().totalHeightForWidth(self.width())))

    def selected_username(self):
        data = self.username.currentData()
        text = self.username.currentText().strip()
        return data if data and text.startswith(data) else text.split(" ", 1)[0]

    def _login(self):
        account = self.store.login(self.selected_username(), self.password.text())
        if account is None:
            self.error.setText("Utente o password non corretti.")
            self.password.selectAll()
            return
        self.account = account
        settings().setValue("accounts/last", account.username)
        self.accept()

    def _new_account(self):
        dialog = AccountDialog(self.store, parent=self)
        if dialog.exec():
            self.account = dialog.account
            settings().setValue("accounts/last", dialog.account.username)
            self.accept()


def require_login(parent=None, current=None):
    """The account to work with: login, or creation of the first account. None if the user gives up."""
    store = account_store()
    if not store.accounts:
        dialog = AccountDialog(store, parent=parent, first=True)
        if not dialog.exec():
            return None
        settings().setValue("accounts/last", dialog.account.username)
        return dialog.account
    dialog = LoginDialog(store, parent, current)
    return dialog.account if dialog.exec() else None
