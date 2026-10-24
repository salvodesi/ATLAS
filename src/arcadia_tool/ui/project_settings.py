"""Project › Impostazioni: what can be changed for the open project.

- Generale (shared with the team, in project.yaml): name, SRS baseline, description.
- Repository Git: URL of the remote, any Git server (shared, in project.yaml, and the «origin» of the local
  Git); working branch (this PC only); access to the server (user and password/token or SSH key, kept in the
  account of the logged-in user, never in the project); check of the connection.
- Verifiche (shared, in checks.yaml): profiles of checks of the methodology (none active by default), with the
  parameters, severity and scope of each check, kept until they are changed.
- Avanzate (this PC only): copy for the recovery, default folder of the SRS PDFs, local cache.
"""
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from arcadia_tool.accounts import AccountError, git_credentials, git_host
from arcadia_tool.storage.repository import remote_branches_and_default
from arcadia_tool.ui.accounts import GitAccessPanel, account_store
from arcadia_tool.ui.checks_settings import ChecksSettingsPage
from arcadia_tool.ui.rich_text import RichTextEdit
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.theme import MUTED, icon

RECOVERY_MINUTES = "recovery/minutes"
DEFAULT_RECOVERY_MINUTES = 1
SHARED = "Condiviso con il team: salvato nel progetto e pubblicato con le versioni."
LOCAL = "Solo su questo PC: non viene pubblicato."


def recovery_minutes():
    try:
        return max(1, int(settings().value(RECOVERY_MINUTES, DEFAULT_RECOVERY_MINUTES)))
    except (TypeError, ValueError):
        return DEFAULT_RECOVERY_MINUTES


class BranchesWorker(QThread):
    """The branches of a remote: done(branches) or, with_default, done((branches, default branch))."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, url, credentials, with_default=False):
        super().__init__()
        self.url, self.credentials, self.with_default = url, credentials, with_default

    def run(self):
        try:
            found = remote_branches_and_default(self.url, **self.credentials)
            self.done.emit(found if self.with_default else found[0])
        except Exception as exc:  # unreachable server, refused access, wrong URL…: shown to the user
            self.failed.emit(str(exc) or exc.__class__.__name__)


def _page(title, scope):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    card = QFrame(objectName="card")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(16, 12, 16, 14)
    card_layout.addWidget(QLabel(title.upper(), objectName="sectionCaption"))
    note = QLabel(scope, objectName="muted")
    note.setWordWrap(True)
    card_layout.addWidget(note)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    card_layout.addLayout(form)
    layout.addWidget(card)
    layout.addStretch()
    return page, form


class ProjectSettingsDialog(QDialog):
    SECTIONS = ("Generale", "Repository Git", "Verifiche", "Avanzate")

    def __init__(self, project, user=None, parent=None, section="Generale"):
        super().__init__(parent)
        self.project, self.user, self.worker = project, user, None
        self.remote_changed = self.checks_changed = False  # set by «Salva»
        self.setWindowTitle(f"Impostazioni del progetto · {project.name}")
        self.resize(1180, 760)

        self.sections = QListWidget()
        self.sections.setFixedWidth(200)
        self.pages = QStackedWidget()
        self.checks_page = ChecksSettingsPage(project)
        for name, glyph, page in (("Generale", "mdi6.tune-variant", self._general()),
                                  ("Repository Git", "mdi6.source-branch", self._git()),
                                  ("Verifiche", "mdi6.clipboard-check-outline", self._checks()),
                                  ("Avanzate", "mdi6.cog-outline", self._advanced())):
            self.sections.addItem(QListWidgetItem(icon(glyph), name))
            self.pages.addWidget(page)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(self.SECTIONS.index(section))

        save = QPushButton(icon("mdi6.check", "white"), "Salva")
        save.setProperty("primary", True)
        save.clicked.connect(self._save)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)

    # --- pages ---------------------------------------------------------------------------------------

    def _general(self):
        page, form = _page("Generale", SHARED)
        p = self.project
        self.name = QLineEdit(p.name)
        self.baseline = QLineEdit(p.baseline)
        self.baseline.setPlaceholderText("es. SUBSET-026 v3.6.0")
        self.description = RichTextEdit(p.description, height=80)
        folder = QLineEdit(str(p.path), readOnly=True, objectName="readonly")
        open_folder = QPushButton(icon("mdi6.folder-open-outline"), "Apri cartella")
        open_folder.clicked.connect(lambda _=False: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.path))))
        row = QHBoxLayout()
        row.addWidget(folder, 1)
        row.addWidget(open_folder)
        versions = p.versions()
        last = (f"{versions[0].timestamp:%d/%m/%Y %H:%M} · {versions[0].author} · {versions[0].title}"
                if versions else "Nessuna versione pubblicata")
        form.addRow("Nome del progetto", self.name)
        form.addRow("Baseline SRS", self.baseline)
        form.addRow("Descrizione", self.description)
        form.addRow("Cartella", row)
        form.addRow("Elementi", QLabel(str(len(p.model))))
        form.addRow("Ultima pubblicazione", QLabel(last))
        return page

    def _git(self):
        page, form = _page("Repository Git remoto", "L'URL è condiviso con il team (salvato nel progetto); ramo di "
                           "lavoro e credenziali restano solo su questo PC. Funziona con qualunque server Git "
                           "(GitLab, GitHub, Gitea, server interno…), via HTTP/HTTPS o SSH.")
        self.remote = QLineEdit(self.project.repository.remote_url() or self.project.settings.get("remote", ""))
        self.remote.setPlaceholderText("https://server/gruppo/progetto.git  oppure  git@server:gruppo/progetto.git")
        self.branch = QComboBox()
        self.branch.setEditable(True)
        branch = self.project.local_settings().get("branch", "")
        if branch:
            self.branch.addItem(branch)
        self.branch.setCurrentText(branch)
        self.branch.lineEdit().setPlaceholderText("ramo di lavoro assegnato dalla DA, es. develop")
        self.check_button = QPushButton(icon("mdi6.lan-connect"), "Verifica connessione")
        self.check_button.clicked.connect(self.check_connection)
        self.check_result = QLabel(objectName="muted")
        self.check_result.setWordWrap(True)
        form.addRow("URL del repository", self.remote)
        form.addRow("Ramo di lavoro", self.branch)

        # Access to the server: set here, kept in the account of the user (one per server), not in the project.
        access = QFrame(objectName="card")
        access_layout = QVBoxLayout(access)
        access_layout.setContentsMargins(14, 10, 14, 12)
        access_layout.addWidget(QLabel("ACCESSO AL SERVER", objectName="sectionCaption"))
        self.access_note = QLabel(objectName="muted")
        self.access_note.setWordWrap(True)
        access_layout.addWidget(self.access_note)
        self.access = GitAccessPanel(account_store(), self.user) if self.user else None
        if self.access is not None:
            access_layout.addWidget(self.access)
        form.addRow(access)
        self.remote.editingFinished.connect(self._show_access)
        self._show_access()
        check_row = QHBoxLayout()
        check_row.addWidget(self.check_button)
        check_row.addStretch()
        form.addRow("", check_row)
        form.addRow("", self.check_result)
        return page

    def _checks(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = QFrame(objectName="card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 14)
        card_layout.addWidget(QLabel("VERIFICHE DEL MODELLO", objectName="sectionCaption"))
        card_layout.addWidget(self.checks_page, 1)
        layout.addWidget(card, 1)
        return page

    def _advanced(self):
        page, form = _page("Avanzate", LOCAL)
        self.recovery = QSpinBox(minimum=1, maximum=60, suffix=" min")
        self.recovery.setValue(recovery_minutes())
        self.pdf_folder = QLineEdit(settings().value("import/folder", ""))
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self._browse_pdf)
        row = QHBoxLayout()
        row.addWidget(self.pdf_folder, 1)
        row.addWidget(browse)
        rebuild = QPushButton(icon("mdi6.database-refresh-outline"), "Ricostruisci la cache locale")
        rebuild.setToolTip("Rilegge i file del modello e riscrive la copia locale che velocizza l'apertura (utile "
                           "dopo modifiche fatte fuori dal tool)")
        rebuild.clicked.connect(self._rebuild_cache)
        form.addRow("Copia di recupero ogni", self.recovery)
        form.addRow("Cartella dei PDF SRS", row)
        form.addRow("Cache locale", rebuild)
        return page

    # --- actions -------------------------------------------------------------------------------------

    def _show_access(self):
        """The access kept in the account for the server of the URL (another server, another access)."""
        url = self.remote.text().strip()
        host = git_host(url)
        if self.access is None:
            self.access_note.setText("Nessun utente collegato: accedi per impostare le credenziali.")
            return
        if self.access.host == host and host:
            return
        self.access.show_server(url)
        self.access.setEnabled(bool(host))
        if host:
            self.access_note.setText(
                f"Credenziali di {self.user.full_name} per il server «{host}»: salvate nel tuo account (solo su "
                "questo PC), non nel progetto. Valgono per tutti i progetti dello stesso server.")
        else:
            self.access_note.setText("Indica l'URL del repository per impostare le credenziali del server "
                                     "(un percorso locale non ne richiede).")

    def check_connection(self):
        url = self.remote.text().strip()
        if not url:
            self.check_result.setText("Indica l'URL del repository.")
            return
        self._show_access()
        self.check_button.setEnabled(False)
        self.check_result.setStyleSheet(f"color: {MUTED};")
        self.check_result.setText("Connessione in corso…")
        credentials = (git_credentials(self.user, url, self.access.access(), self.access.secret())
                       if self.access is not None else {})
        self.worker = BranchesWorker(url, credentials)
        self.worker.done.connect(self._connected)
        self.worker.failed.connect(self._not_connected)
        self.worker.start()

    def _connected(self, branches):
        self.check_button.setEnabled(True)
        current = self.branch.currentText()
        self.branch.clear()
        self.branch.addItems(branches)
        self.branch.setCurrentText(current or (branches[0] if branches else ""))
        self.check_result.setStyleSheet("color: #166534;")
        self.check_result.setText(f"Connessione riuscita: {len(branches)} rami" if branches else
                                  "Connessione riuscita: il repository non ha ancora rami.")

    def _not_connected(self, reason):
        self.check_button.setEnabled(True)
        self.check_result.setStyleSheet("color: #B42318;")
        self.check_result.setText(f"Connessione non riuscita: {reason}")

    def _browse_pdf(self):
        folder = QFileDialog.getExistingDirectory(self, "Cartella dei PDF SRS", self.pdf_folder.text())
        if folder:
            self.pdf_folder.setText(folder)

    def _rebuild_cache(self):
        self.project.rebuild_cache()
        QMessageBox.information(self, "Cache locale", "Cache locale ricostruita.")

    def _save(self):
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, self.windowTitle(), "Il nome del progetto non può essere vuoto.")
            self.sections.setCurrentRow(0)
            return
        self._show_access()
        if self.access is not None and self.access.host:
            try:
                self.access.save()  # in the account, not in the project
            except AccountError as exc:
                QMessageBox.warning(self, self.windowTitle(), str(exc))
                self.sections.setCurrentRow(1)
                return
        remote = self.remote.text().strip()
        self.remote_changed = bool(remote) and remote != self.project.remote()  # the project may be reloaded
        checks = self.checks_page.value()
        self.checks_changed = checks != self.project.checks
        self.project.update_settings(name=name, baseline=self.baseline.text().strip(),
                                     description=self.description.markdown(), remote=remote)
        if self.checks_changed:
            self.project.update_checks(checks)
        self.project.repository.set_remote_url(remote)  # also the standard «origin» of the local Git
        self.project.set_local_settings(branch=self.branch.currentText().strip())
        s = settings()
        s.setValue(RECOVERY_MINUTES, self.recovery.value())
        if self.pdf_folder.text().strip():
            s.setValue("import/folder", self.pdf_folder.text().strip())
        self.accept()

    def done(self, result):
        worker = self.worker
        if worker is not None and worker.isRunning():
            # Closed while a slow server answers: the thread is kept until it ends, its answer ignored.
            _RUNNING.append(worker)
            worker.done.disconnect()
            worker.failed.disconnect()
            worker.finished.connect(lambda: _RUNNING.remove(worker))
        super().done(result)


_RUNNING = []  # connection checks still running after their window was closed
