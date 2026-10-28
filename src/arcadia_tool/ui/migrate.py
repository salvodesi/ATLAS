"""Remote repository of a project: reload it from the remote (e.g. after its address changed) and migrate its
history from one Git server to another (all the branches or some of them)."""
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from arcadia_tool.accounts import AccountError, git_credentials, git_host
from arcadia_tool.storage.project import migrate_repository, reload_project
from arcadia_tool.ui.accounts import GitAccessPanel, _Centered, account_store
from arcadia_tool.ui.project_settings import _RUNNING, BranchesWorker
from arcadia_tool.ui.theme import MUTED, icon

OK, REFUSED = "#166534", "#B42318"


class _Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    step = Signal(str, object)  # branch, outcome (None: sent)

    def __init__(self, job):
        super().__init__()
        self.job = job

    def run(self):
        try:
            self.done.emit(self.job(self))
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


def _keep_running(worker):
    """A window closed while its thread works: the thread is kept until it ends, its result ignored."""
    if worker is not None and worker.isRunning():
        _RUNNING.append(worker)
        worker.done.disconnect()
        worker.failed.disconnect()
        worker.finished.connect(lambda: _RUNNING.remove(worker))


class ReloadDialog(_Centered):
    """Reload a (closed) project from its remote: `branch` is the branch loaded when it succeeded."""

    def __init__(self, path, url, branch, credentials, parent=None):
        super().__init__(parent)
        self.branch, self.worker = None, None
        self.setWindowTitle("Ricarica il progetto dal repository")
        self.resize(560, 0)
        title = QLabel(f"Caricamento da {git_host(url) or url}", objectName="cardTitle")
        detail = QLabel(f"Ramo «{branch}»" if branch else "Ramo predefinito del repository", objectName="muted")
        self.status = QLabel("Download della storia del progetto…", objectName="muted")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.close_button = QPushButton("Chiudi")
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        for w in (title, detail, self.bar, self.status):
            layout.addWidget(w)
        layout.addLayout(buttons)
        self.worker = _Worker(lambda _w: reload_project(path, url, branch, **credentials))
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)

    def exec(self):
        self.worker.start()
        return super().exec()

    def _done(self, branch):
        self.worker.wait()
        self.branch = branch
        self.accept()

    def _failed(self, reason):
        self.worker.wait()
        self.bar.setVisible(False)
        self.status.setStyleSheet(f"color: {REFUSED};")
        self.status.setText(f"Caricamento non riuscito: {reason}\n\nIl progetto locale non è stato cambiato.")
        self.close_button.setEnabled(True)

    def reject(self):
        if self.worker.isRunning():
            return  # not while downloading: the window closes when the server has answered
        super().reject()


class MigrationDialog(_Centered):
    """Progetto › Migra repository: branches of the origin, each with its whole history, to the destination.

    `use_destination` is True when, at the end, the user chose to make the destination the project's remote."""

    def __init__(self, project, user, parent=None):
        super().__init__(parent)
        self.project, self.user, self.worker = project, user, None
        self.results, self.use_destination = {}, False
        self.setWindowTitle("Migra il repository")
        self.resize(820, 0)
        intro = QLabel("Copia i rami del progetto, ciascuno con tutta la sua storia, da un repository Git a un altro "
                       "(anche di un altro server). Un ramo che nella destinazione esiste già con una storia diversa "
                       "non viene sovrascritto.", objectName="muted")
        intro.setWordWrap(True)
        store = account_store()
        self.source, self.source_access, source_box = self._side("Origine", project.remote(), store)
        self.target, self.target_access, target_box = self._side("Destinazione", "", store)
        sides = QHBoxLayout()
        sides.addWidget(source_box, 1)
        sides.addWidget(target_box, 1)

        branches_box = QFrame(objectName="card")
        branches_layout = QVBoxLayout(branches_box)
        branches_layout.setContentsMargins(16, 12, 16, 14)
        branches_layout.addWidget(QLabel("RAMI DA MIGRARE", objectName="sectionCaption"))
        read = QPushButton(icon("mdi6.source-branch"), "Leggi i rami dell'origine")
        read.clicked.connect(self.read_branches)
        all_ = QPushButton("Tutti")
        all_.clicked.connect(lambda _=False: self._check_all(True))
        none = QPushButton("Nessuno")
        none.clicked.connect(lambda _=False: self._check_all(False))
        row = QHBoxLayout()
        row.addWidget(read)
        row.addStretch()
        row.addWidget(all_)
        row.addWidget(none)
        branches_layout.addLayout(row)
        self.branches = QListWidget()
        self.branches.setMinimumHeight(140)
        branches_layout.addWidget(self.branches)
        self.read_button = read

        self.status = QLabel(objectName="muted")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.migrate_button = QPushButton(icon("mdi6.transfer", "white"), "Migra")
        self.migrate_button.setProperty("primary", True)
        self.migrate_button.clicked.connect(self.migrate)
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.migrate_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addLayout(sides)
        layout.addWidget(branches_box)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def _side(self, title, url, store):
        box = QFrame(objectName="card")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(16, 12, 16, 14)
        box_layout.addWidget(QLabel(title.upper(), objectName="sectionCaption"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        edit = QLineEdit(url)
        edit.setCursorPosition(0)  # the URL shown from its start (the server), also when the field is narrow
        edit.setPlaceholderText("git@server:gruppo/progetto.git  o  https://server/gruppo/progetto.git")
        form.addRow("URL", edit)
        box_layout.addLayout(form)
        access = GitAccessPanel(store, self.user) if self.user else None
        if access is not None:
            box_layout.addWidget(access)
            edit.editingFinished.connect(lambda: self._show_access(edit, access))
            self._show_access(edit, access)
        return edit, access, box

    def _show_access(self, edit, access):
        host = git_host(edit.text())
        if access.host != host or not host:
            access.show_server(edit.text())
        access.setEnabled(bool(host))

    def _credentials(self, edit, access):
        if access is None:
            return {}
        self._show_access(edit, access)
        return git_credentials(self.user, edit.text().strip(), access.access(), access.secret())

    def _check_all(self, checked):
        for i in range(self.branches.count()):
            self.branches.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def checked_branches(self):
        return [self.branches.item(i).data(Qt.UserRole) for i in range(self.branches.count())
                if self.branches.item(i).checkState() == Qt.Checked]

    def _status(self, text, color=MUTED):
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(text)

    def read_branches(self):
        url = self.source.text().strip()
        if not url:
            self._status("Indica l'URL dell'origine.", REFUSED)
            return
        self.read_button.setEnabled(False)
        self._status("Lettura dei rami dell'origine…")
        self.worker = BranchesWorker(url, self._credentials(self.source, self.source_access), with_default=True)
        self.worker.done.connect(self._branches_read)
        self.worker.failed.connect(self._read_failed)
        self.worker.start()

    def _read_failed(self, reason):
        self.read_button.setEnabled(True)
        self._status(f"Connessione all'origine non riuscita: {reason}", REFUSED)

    def _branches_read(self, found):
        branches, default = found
        self.read_button.setEnabled(True)
        self.branches.clear()
        for name in branches:
            item = QListWidgetItem(f"{name} (predefinito)" if name == default else name)
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)  # all of them unless the user unticks some
            self.branches.addItem(item)
        self._status(f"{len(branches)} rami nell'origine: scegli quelli da migrare." if branches
                     else "L'origine non ha rami: non c'è nulla da migrare.", OK if branches else REFUSED)

    def migrate(self):
        source, target = self.source.text().strip(), self.target.text().strip()
        branches = self.checked_branches()
        problems = []
        if not source or not target:
            problems.append("Indica l'URL dell'origine e quello della destinazione.")
        elif source == target:
            problems.append("Origine e destinazione sono lo stesso repository.")
        if not branches:
            problems.append("Leggi i rami dell'origine e spunta quelli da migrare.")
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        for edit, access in ((self.source, self.source_access), (self.target, self.target_access)):
            if access is None:
                continue
            self._show_access(edit, access)
            if access.host:
                try:
                    access.save()  # in the account, one per server
                except AccountError as exc:
                    QMessageBox.warning(self, self.windowTitle(), str(exc))
                    return
        source_credentials = self._credentials(self.source, self.source_access)
        target_credentials = self._credentials(self.target, self.target_access)
        path = self.project.path
        self.migrate_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.bar.setRange(0, len(branches))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self._status(f"Download della storia da {git_host(source) or source} e invio a {git_host(target) or target}…")

        def job(worker):
            return migrate_repository(path, source, target, branches, source_credentials, target_credentials,
                                      progress=lambda branch, outcome: worker.step.emit(branch, outcome))
        self.worker = _Worker(job)
        self.worker.step.connect(self._branch_done)
        self.worker.done.connect(self._migrated)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _branch_done(self, branch, outcome):
        self.bar.setValue(self.bar.value() + 1)
        for i in range(self.branches.count()):
            item = self.branches.item(i)
            if item.data(Qt.UserRole) == branch:
                item.setText(f"{branch} — {'migrato' if outcome is None else outcome}")
                item.setForeground(QColor(OK if outcome is None else REFUSED))

    def _migrated(self, results):
        self.worker.wait()
        self.results = results
        self.close_button.setEnabled(True)
        self.migrate_button.setEnabled(True)
        sent = [b for b, outcome in results.items() if outcome is None]
        failed = len(results) - len(sent)
        self._status(f"Migrazione terminata: {len(sent)} rami migrati" + (f", {failed} no (vedi l'elenco)." if failed
                                                                           else "."), OK if not failed else REFUSED)
        if sent and self.target.text().strip() != self.project.remote():
            answer = QMessageBox.question(
                self, self.windowTitle(), "Usare il repository di destinazione per questo progetto? I prossimi invii "
                f"andranno a {self.target.text().strip()}.")
            self.use_destination = answer == QMessageBox.Yes

    def _failed(self, reason):
        self.worker.wait()
        self.bar.setVisible(False)
        self.close_button.setEnabled(True)
        self.migrate_button.setEnabled(True)
        self._status(f"Migrazione non riuscita: {reason}", REFUSED)

    def reject(self):
        if self.worker is not None and self.worker.isRunning() and isinstance(self.worker, _Worker):
            return  # not while migrating
        _keep_running(self.worker)
        super().reject()
