"""Sending the published versions to the remote Git repository, with a window that shows how it goes."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from arcadia_tool.accounts import git_host
from arcadia_tool.ui.accounts import _Centered
from arcadia_tool.ui.theme import MUTED, icon

DIVERGED = ("Il ramo «{branch}» del repository contiene versioni che non hai ancora ricevuto (pubblicate da un "
            "collega): ricevile prima di inviare le tue, con «Ricevi ora». Le tue versioni restano registrate su "
            "questo PC.")


DENIED = ("Il repository ha rifiutato l'invio sul ramo «{branch}», pur non avendo versioni nuove da ricevere: "
          "probabilmente non hai il permesso di inviare su questo ramo (ramo protetto).\n\nRisposta del repository: "
          "{reason}\n\nLe tue versioni restano su questo PC, non inviate, e verrebbero riproposte a ogni ricezione. "
          "Spostale su un nuovo ramo da inviare (chi ha il permesso lo integrerà), oppure scartale.")
DENIED_WORDS = ("denied", "protected", "permission", "forbidden", "403", "not allowed", "declined", "unauthorized")


def _branches(names):
    return ", ".join(f"«{n}»" for n in names)


class PushWorker(QThread):
    done = Signal(str)  # the branch
    failed = Signal(str)

    def __init__(self, project, credentials):
        super().__init__()
        self.diverged = False
        self.denied = ""  # the answer of the remote when it refused versions that need nothing received first
        self.project, self.credentials = project, credentials

    def run(self):
        try:
            self.done.emit(self.project.push(**self.credentials))
        except Exception as exc:
            name, reason = exc.__class__.__name__, str(exc) or exc.__class__.__name__
            kind = self._refusal(exc)
            branch = self.project.push_branch()
            if kind == "diverged":
                self.diverged = True
                self.failed.emit(DIVERGED.format(branch=branch))
            elif kind == "denied":
                self.denied = reason
                self.failed.emit(DENIED.format(branch=branch, reason=reason))
            else:
                self.failed.emit(f"Invio non riuscito: {exc or name}\n\nLe versioni restano registrate su questo "
                                 "PC: puoi riprovare da Versioni › Invia al repository.")

    def _refusal(self, exc):
        """Why the remote refused: "diverged" (it has versions not received here), "denied" (it has nothing new, yet
        it refused: no permission on the branch, e.g. a protected one), or None (another failure, e.g. the network).
        The remote is read again to tell them apart; if it cannot be, the answer of the push decides."""
        name, text = exc.__class__.__name__, str(exc).lower()
        refused = name in ("DivergedBranches", "PushRefused") or "non-fast-forward" in text
        try:
            heads = self.project.fetch_branches(**self.credentials)
        except Exception:
            return "diverged" if refused else None
        theirs, head = heads.get(self.project.push_branch()), self.project.repository.head()
        if theirs and head and not self.project.repository.is_ancestor(theirs, head):
            return "diverged"
        if refused or any(word in text for word in DENIED_WORDS):
            return "denied"
        return None


class PushDialog(_Centered):
    """Sends the versions not yet sent to the working branch of the remote; `sent` tells if it succeeded."""

    def __init__(self, project, credentials, parent=None):
        super().__init__(parent)
        self.project, self.credentials, self.sent, self.worker = project, credentials, False, None
        self.receive_requested = False  # «Ricevi ora»: the remote has versions not received yet
        self.resolution = None  # the versions the remote refused: "move" to a new branch, or "discard"
        self.setWindowTitle("Invio al repository")
        self.resize(560, 0)
        url, branch = project.remote(), project.push_branch()
        count = len(project.unsent_versions())
        title = QLabel(f"Invio al ramo «{branch}» di {git_host(url) or url}", objectName="cardTitle")
        doomed = project.branches_to_delete()
        detail = QLabel(f"{count} {'versione' if count == 1 else 'versioni'} da inviare"
                        + (f" · {_branches(doomed)} da cancellare dal repository (integrat"
                           + ("o" if len(doomed) == 1 else "i") + ")" if doomed else "") + f" · {url}",
                        objectName="muted")
        detail.setWordWrap(True)
        self.status = QLabel("Connessione al repository…", objectName="muted")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # the time depends on the server: busy until it answers
        self.retry = QPushButton(icon("mdi6.refresh"), "Riprova")
        self.retry.clicked.connect(self.start)
        self.retry.setVisible(False)
        self.receive_button = QPushButton(icon("mdi6.cloud-download"), "Ricevi ora")
        self.receive_button.setToolTip("Riceve le versioni dei colleghi e le integra con le tue; poi puoi inviare")
        self.receive_button.clicked.connect(self._receive)
        self.receive_button.setVisible(False)
        self.move_button = QPushButton(icon("mdi6.source-branch-plus"), "Sposta su un nuovo ramo…")
        self.move_button.setToolTip("Le versioni non inviate passano a un nuovo ramo, da inviare; questo ramo torna "
                                    "come nel repository")
        self.move_button.clicked.connect(lambda: self._resolve("move"))
        self.move_button.setVisible(False)
        self.discard_button = QPushButton(icon("mdi6.delete-outline"), "Scarta le versioni non inviate…")
        self.discard_button.setToolTip("Il ramo torna come nel repository: le versioni non inviate vanno perse")
        self.discard_button.clicked.connect(lambda: self._resolve("discard"))
        self.discard_button.setVisible(False)
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.retry)
        buttons.addWidget(self.receive_button)
        buttons.addWidget(self.move_button)
        buttons.addWidget(self.discard_button)
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
        text = f"Invio completato: il ramo «{branch}» del repository è aggiornato."
        deleted, kept = getattr(self.project, "deleted_branches", []), getattr(self.project, "kept_branches", [])
        if deleted:
            text += f" Cancellat{'o' if len(deleted) == 1 else 'i'} dal repository: {_branches(deleted)}."
        if kept:
            text += (f" Non cancellat{'o' if len(kept) == 1 else 'i'}: {_branches(kept)}, perché nel frattempo vi "
                     "sono state inviate versioni non integrate.")
        self.status.setText(text)
        self.close_button.setEnabled(True)
        self.close_button.setFocus()

    def _failed(self, message):
        self.worker.wait()
        self.bar.setVisible(False)
        self.status.setStyleSheet("color: #B42318;")
        self.status.setText(message)
        denied = bool(self.worker.denied)
        if denied:  # remembered: receiving on the branch reminds of them (see MainWindow.receive_versions)
            self.project.set_push_refused(self.project.push_branch(), self.worker.denied)
        self.retry.setVisible(not self.worker.diverged and not denied)
        self.receive_button.setVisible(self.worker.diverged)
        self.move_button.setVisible(denied)
        self.discard_button.setVisible(denied)
        self.close_button.setEnabled(True)

    def _resolve(self, choice):
        self.resolution = choice
        self.accept()

    def _receive(self):
        self.receive_requested = True
        self.accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return  # not while sending: the window closes when the server has answered
        super().reject()
