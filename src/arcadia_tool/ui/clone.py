"""File › Scarica progetto da Git: a project that is not on this PC yet, downloaded from a Git remote (any
server) with the access of the logged-in account, then opened."""
import re
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from arcadia_tool.accounts import AccountError, git_credentials, git_host
from arcadia_tool.storage.project import clone_project
from arcadia_tool.ui.accounts import GitAccessPanel, _Centered, account_store
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.project_settings import _RUNNING, BranchesWorker
from arcadia_tool.ui.theme import MUTED, icon


def folder_name(url):
    """Name of the local folder for a remote: its last part without «.git» (…/evc/modello.git → modello)."""
    name = re.split(r"[/:\\]", url.strip().rstrip("/"))[-1]
    return re.sub(r"\.git$", "", name) or "progetto"


class CloneWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, url, target, branch, credentials):
        super().__init__()
        self.url, self.target, self.branch, self.credentials = url, target, branch, credentials

    def run(self):
        try:
            self.done.emit(clone_project(self.url, self.target, self.branch, **self.credentials))
        except Exception as exc:  # unreachable server, refused access, not an ARCADIA project…
            self.failed.emit(str(exc) or exc.__class__.__name__)


class CloneDialog(_Centered):
    """`path` is the downloaded project when the dialog is accepted."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user, self.path, self.worker = user, None, None
        # Branches (development trees) of the remote, once read: None while unknown.
        self.known_branches, self.default_branch = None, None
        self.branch_chosen = False  # the user picked a branch (needed when there are several)
        self._clone_after_check = False
        self._checked_url = None  # the repository whose branches were read
        self.setWindowTitle("Scarica progetto da Git")
        self.resize(760, 0)
        intro = QLabel("Scarica un progetto che non è ancora su questo PC da un repository Git remoto (GitLab, "
                       "GitHub, server interno…). Al termine il progetto viene aperto.", objectName="muted")
        intro.setWordWrap(True)

        box = QFrame(objectName="card")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(16, 12, 16, 14)
        box_layout.addWidget(QLabel("REPOSITORY", objectName="sectionCaption"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.remote = QLineEdit()
        self.remote.setPlaceholderText("https://server/gruppo/progetto.git  oppure  git@server:gruppo/progetto.git")
        self.remote.editingFinished.connect(self._remote_changed)
        self.branch = QComboBox()
        self.branch.setEditable(True)
        self.branch.lineEdit().setPlaceholderText("ramo (albero di sviluppo) assegnato dalla DA")
        self.branch.activated.connect(self._branch_picked)
        self.branch.lineEdit().textEdited.connect(self._branch_picked)
        self.check_button = QPushButton(icon("mdi6.lan-connect"), "Verifica connessione")
        self.check_button.clicked.connect(self.check_connection)
        branch_row = QHBoxLayout()
        branch_row.addWidget(self.branch, 1)
        branch_row.addWidget(self.check_button)
        self.parent_folder = QLineEdit(settings().value("clone/folder", str(Path.home() / "Documents")))
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.parent_folder, 1)
        folder_row.addWidget(browse)
        self.name = QLineEdit()
        self.name.setPlaceholderText("nome della cartella del progetto")
        form.addRow("URL del repository", self.remote)
        form.addRow("Ramo", branch_row)
        form.addRow("Scarica in", folder_row)
        form.addRow("Cartella", self.name)
        box_layout.addLayout(form)

        access = QFrame(objectName="card")
        access_layout = QVBoxLayout(access)
        access_layout.setContentsMargins(16, 12, 16, 14)
        access_layout.addWidget(QLabel("ACCESSO AL SERVER", objectName="sectionCaption"))
        self.access_note = QLabel(objectName="muted")
        self.access_note.setWordWrap(True)
        access_layout.addWidget(self.access_note)
        self.access = GitAccessPanel(account_store(), user) if user else None
        if self.access is not None:
            access_layout.addWidget(self.access)

        self.status = QLabel(objectName="muted")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.clone_button = QPushButton(icon("mdi6.download", "white"), "Scarica")
        self.clone_button.setProperty("primary", True)
        self.clone_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Annulla")
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.clone_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addWidget(box)
        layout.addWidget(access)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)
        self._remote_changed()
        self.remote.setFocus()

    @property
    def target(self):
        return Path(self.parent_folder.text().strip()) / self.name.text().strip()

    def _branch_picked(self, *_):
        self.branch_chosen = True

    def selected_branch(self):
        """The branch name (the list shows «main (predefinito)» for the default one)."""
        index = self.branch.currentIndex()
        if index >= 0 and self.branch.currentText() == self.branch.itemText(index) and self.branch.itemData(index):
            return self.branch.itemData(index)
        return self.branch.currentText().strip()

    def _remote_changed(self):
        url = self.remote.text().strip()
        if url != self._checked_url:  # another repository: its branches are to be read again
            self.known_branches, self.default_branch, self.branch_chosen = None, None, False
        if url and not self.name.text().strip():
            self.name.setText(folder_name(url))
        host = git_host(url)
        if self.access is None:
            self.access_note.setText("Nessun utente collegato: accedi per scaricare progetti da Git.")
            return
        if self.access.host != host or not host:
            self.access.show_server(url)
        self.access.setEnabled(bool(host))
        self.access_note.setText(
            f"Credenziali di {self.user.full_name} per «{host}»: salvate nel tuo account (solo su questo PC)."
            if host else "Indica l'URL del repository (un percorso locale non richiede credenziali).")

    def _credentials(self, url):
        if self.access is None:
            return {}
        return git_credentials(self.user, url, self.access.access(), self.access.secret())

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Dove scaricare il progetto", self.parent_folder.text())
        if folder:
            self.parent_folder.setText(folder)

    def check_connection(self):
        url = self.remote.text().strip()
        if not url:
            self.status.setText("Indica l'URL del repository.")
            return
        self._remote_changed()
        self.check_button.setEnabled(False)
        self._status("Lettura dei rami del repository…", MUTED)
        self._checked_url = url
        self.worker = BranchesWorker(url, self._credentials(url), with_default=True)
        self.worker.done.connect(self._branches)
        self.worker.failed.connect(self._not_connected)
        self.worker.start()

    def _not_connected(self, reason):
        self._clone_after_check = False
        self._busy(False)
        self._status(f"Connessione non riuscita: {reason}", "#B42318")

    def _branches(self, found):
        branches, default = found
        self.known_branches, self.default_branch = branches, default
        self._busy(False)
        wanted = self.selected_branch()
        self.branch.clear()
        for name in branches:  # the default branch first, marked
            if name == default:
                self.branch.insertItem(0, f"{name} (predefinito)", name)
            else:
                self.branch.addItem(name, name)
        keep = wanted if wanted in branches else (default or (branches[0] if branches else ""))
        index = self.branch.findData(keep)
        if index >= 0:
            self.branch.setCurrentIndex(index)
        else:
            self.branch.setCurrentText(keep)
        if len(branches) == 1:
            self.branch_chosen = True  # nothing to choose
        if not branches:
            self._clone_after_check = False
            self._status("Il repository è vuoto: non c'è un progetto da scaricare.", "#9A6700")
            return
        listed = ", ".join(f"{b} (predefinito)" if b == default else b for b in branches)
        self._status(f"Rami disponibili ({len(branches)}): {listed}.", "#166534")
        if self._clone_after_check:
            self._clone_after_check = False
            self.start()

    def _status(self, text, color):
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(text)

    def start(self):
        url = self.remote.text().strip()
        problems = []
        if not url:
            problems.append("Indica l'URL del repository.")
        if not self.parent_folder.text().strip() or not self.name.text().strip():
            problems.append("Indica dove scaricare il progetto e il nome della cartella.")
        elif self.target.exists() and any(self.target.iterdir()):
            problems.append(f"La cartella {self.target} esiste già e non è vuota: scegli un altro nome.")
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        self._remote_changed()
        if self.access is not None and self.access.host:
            try:
                self.access.save()  # in the account, for the next projects of the same server
            except AccountError as exc:
                QMessageBox.warning(self, self.windowTitle(), str(exc))
                return
        if self.known_branches is None:  # the branches are read first, then the download goes on
            self._clone_after_check = True
            self._busy(True)
            self.check_connection()
            return
        branch = self.selected_branch()
        if len(self.known_branches) > 1 and not self.branch_chosen:
            self._status(f"Il repository ha {len(self.known_branches)} rami (alberi di sviluppo): scegli quello da "
                         "scaricare e premi di nuovo «Scarica».", "#9A6700")
            self.branch.setFocus()
            self.branch.showPopup()
            self.branch_chosen = True  # the list was shown: the next «Scarica» takes the branch selected
            return
        if branch not in self.known_branches:
            QMessageBox.warning(self, self.windowTitle(), f"Il ramo «{branch}» non esiste nel repository. Rami "
                                f"disponibili: {', '.join(self.known_branches)}.")
            return
        settings().setValue("clone/folder", self.parent_folder.text().strip())
        self._busy(True)
        self._status(f"Download del ramo «{branch}» di {url} in corso (tutti i rami vengono scaricati, quello "
                     "scelto diventa il ramo di lavoro)…", MUTED)
        self.worker = CloneWorker(url, self.target, branch, self._credentials(url))
        self.worker.done.connect(self._cloned)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _busy(self, busy):
        self.progress.setVisible(busy)
        for w in (self.clone_button, self.check_button, self.remote, self.branch, self.parent_folder, self.name):
            w.setEnabled(not busy)
        if self.access is not None:
            self.access.setEnabled(not busy and bool(self.access.host))

    def _cloned(self, path):
        self.path = path
        self.accept()

    def _failed(self, reason):
        self._busy(False)
        self._status(f"Download non riuscito: {reason}", "#B42318")

    def done(self, result):
        worker = self.worker
        if worker is not None and worker.isRunning():
            if isinstance(worker, CloneWorker) and result != QDialog.DialogCode.Accepted:
                if QMessageBox.question(self, self.windowTitle(), "Il download è in corso: attendere che finisca "
                                        "prima di chiudere?") == QMessageBox.Yes:
                    return
            _RUNNING.append(worker)  # kept until it ends; its result is ignored
            worker.done.disconnect()
            worker.failed.disconnect()
            worker.finished.connect(lambda: _RUNNING.remove(worker))
        super().done(result)
