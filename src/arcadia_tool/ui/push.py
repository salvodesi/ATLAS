"""Sending the published versions to the remote Git repository, with a window that shows how it goes."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from arcadia_tool.accounts import git_host
from arcadia_tool.ui.accounts import _Centered
from arcadia_tool.ui.theme import MUTED, icon

DIVERGED = ("Il ramo «{branch}» del repository contiene versioni che non hai ancora ricevuto (pubblicate da un "
            "collega): ricevile prima di inviare le tue. Le tue versioni restano registrate su questo PC.")


class PushWorker(QThread):
    done = Signal(str)  # the branch
    failed = Signal(str)

    def __init__(self, project, credentials):
        super().__init__()
        self.project, self.credentials = project, credentials

    def run(self):
        try:
            self.done.emit(self.project.push(**self.credentials))
        except Exception as exc:
            name = exc.__class__.__name__
            if name in ("DivergedBranches", "PushRefused") or "non-fast-forward" in str(exc).lower():
                self.failed.emit(DIVERGED.format(branch=self.project.push_branch()))
            else:
                self.failed.emit(f"Invio non riuscito: {exc or name}\n\nLe versioni restano registrate su questo "
                                 "PC: puoi riprovare da Versioni › Invia al repository.")


class PushDialog(_Centered):
    """Sends the versions not yet sent to the working branch of the remote; `sent` tells if it succeeded."""

    def __init__(self, project, credentials, parent=None):
        super().__init__(parent)
        self.project, self.credentials, self.sent, self.worker = project, credentials, False, None
        self.setWindowTitle("Invio al repository")
        self.resize(560, 0)
        url, branch = project.remote(), project.push_branch()
        count = len(project.unsent_versions())
        title = QLabel(f"Invio al ramo «{branch}» di {git_host(url) or url}", objectName="cardTitle")
        detail = QLabel(f"{count} {'versione' if count == 1 else 'versioni'} da inviare · {url}", objectName="muted")
        detail.setWordWrap(True)
        self.status = QLabel("Connessione al repository…", objectName="muted")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # the time depends on the server: busy until it answers
        self.retry = QPushButton(icon("mdi6.refresh"), "Riprova")
        self.retry.clicked.connect(self.start)
        self.retry.setVisible(False)
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.retry)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        for w in (title, detail, self.bar, self.status):
            layout.addWidget(w)
        layout.addLayout(buttons)

    def exec(self):
        self.start()
        return super().exec()

    def start(self):
        self.retry.setVisible(False)
        self.close_button.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText("Invio in corso…")
        self.worker = PushWorker(self.project, self.credentials)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, branch):
        self.worker.wait()
        self.sent = True
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.status.setStyleSheet("color: #166534;")
        self.status.setText(f"Invio completato: il ramo «{branch}» del repository è aggiornato.")
        self.close_button.setEnabled(True)
        self.close_button.setFocus()

    def _failed(self, message):
        self.worker.wait()
        self.bar.setVisible(False)
        self.status.setStyleSheet("color: #B42318;")
        self.status.setText(message)
        self.retry.setVisible(True)
        self.close_button.setEnabled(True)

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return  # not while sending: the window closes when the server has answered
        super().reject()
