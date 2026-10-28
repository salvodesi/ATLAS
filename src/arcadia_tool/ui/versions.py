"""Publishing, history and on-demand comparison of model versions.

The diff is computed only here: when the user publishes (to review what is being published)
or explicitly asks to compare two states of the model.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from arcadia_tool.checks import ERROR, WARNING, count, problems
from arcadia_tool.diff.semantic import diff_models
from arcadia_tool.model.element import Model
from arcadia_tool.model.teams import memberships
from arcadia_tool.storage.repository import NothingToSave
from arcadia_tool.ui.checks_panel import SEVERITY_COLORS, enabled_count, run_checks, summary
from arcadia_tool.ui.diff_view import DiffView
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.element_editor import card
from arcadia_tool.ui.theme import BORDER, MUTED, icon

WORKING = "working"
WORKING_LABEL = "Stato attuale (non pubblicato)"


def version_label(v):
    return f"{v.timestamp:%d/%m/%Y %H:%M} · {v.title}"


def primary(button):
    button.setProperty("primary", True)
    return button


def with_member(message, project, user):
    """The message of a version, with who publishes it when they are a member of a team (name, team and ID of the
    account): the versions are recognized as theirs also if their name is written differently."""
    if user is None:
        return message
    rows = memberships(project.model, user)
    if not rows:
        return message
    teams = ", ".join(project.model.label(t) for t, _row in rows)
    name = rows[0][1].get("name") or user.full_name
    return f"{message}\n\nMembro: {name} ({teams}) · account {user.id}"


class PublishDialog(QDialog):
    """user: the logged-in account, author of the version (not editable here)."""

    def __init__(self, project, parent=None, user=None):
        super().__init__(parent)
        self.project, self.sha, self.user = project, None, user
        self.setWindowTitle("Pubblica versione")
        self.resize(1240, 760)
        versions = project.versions()
        base_label = version_label(versions[0]) if versions else "Nessuna versione pubblicata"
        self.diff = diff_models(project.published_model(), project.model)
        # Changed only in the files of the project shared with the team (checks.yaml, project.yaml): also to publish.
        self.settings_changed = not self.diff and project.has_unpublished_changes()
        publishable = bool(self.diff) or self.settings_changed

        s = settings()
        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("Cosa cambia in questa versione, es. «SA-2 DF06: aggiunte le funzioni di "
                                        "supervisione dei movimenti»")
        self.message.setFixedHeight(110)
        self.author_name = QLineEdit(user.full_name if user else s.value("author/name", ""))
        self.author_email = QLineEdit(user.email if user else s.value("author/email", ""))
        if user is not None:  # every change is associated with the account that publishes it
            for field in (self.author_name, self.author_email):
                field.setReadOnly(True)
                field.setObjectName("readonly")
                field.setToolTip("Dall'account con cui hai effettuato l'accesso (menu Utente › Modifica account)")
        info, info_layout = card("Pubblicazione")
        form = QFormLayout()
        form.addRow("Descrizione", self.message)
        form.addRow("Autore", self.author_name)
        form.addRow("E-mail", self.author_email)
        # Where the version goes: the branch in use, or a new branch created now from the current version.
        from arcadia_tool.ui.branches import suggested_name
        self.on_current = QRadioButton(f"Sul ramo in uso «{project.current_branch()}»")
        self.on_new = QRadioButton("Su un nuovo ramo:")
        self.on_current.setChecked(True)
        self.new_branch = QLineEdit(suggested_name(project, user))
        self.new_branch.setPlaceholderText("es. att/T2-odometria")
        self.new_branch.setToolTip("Il nuovo ramo parte dall'ultima versione del ramo in uso e diventa il ramo "
                                   "di lavoro; poi viene inviato al repository")
        self.new_branch.setEnabled(False)
        self.on_new.toggled.connect(self.new_branch.setEnabled)
        self.on_new.toggled.connect(lambda on: self.new_branch.setFocus() if on else None)
        self.on_new.toggled.connect(lambda _on: self._where())
        self.new_branch.textChanged.connect(lambda _t: self._where())
        branch_row = QHBoxLayout()
        branch_row.addWidget(self.on_current)
        branch_row.addSpacing(16)
        branch_row.addWidget(self.on_new)
        branch_row.addWidget(self.new_branch, 1)
        form.addRow("Ramo", branch_row)
        info_layout.addLayout(form)
        self.send_only = False  # accepted only to send versions already recorded
        remote = project.remote()
        unsent = len(project.unsent_versions()) if remote else 0
        self.note = QLabel(objectName="muted")
        self.note.setWordWrap(True)
        self._where()
        info_layout.addWidget(self.note)
        info_layout.addWidget(self._checks_summary(project))

        if versions and remote:  # where the last version is: on the repository or only here
            base_label += " (solo su questo PC)" if unsent else " (inviata al repository)"
        # Without changes the current state is the last version itself: said so, not «non pubblicato».
        working_label = (WORKING_LABEL if self.diff else
                         "Stato attuale: modello identico, cambiate le impostazioni del progetto"
                         if self.settings_changed else "Stato attuale: identico, nulla da pubblicare")
        changes, changes_layout = card("Modifiche rispetto all'ultima pubblicazione")
        changes_layout.addWidget(DiffView(self.diff, base_label, working_label), 1)

        self.publish_button = primary(QPushButton(icon("mdi6.cloud-upload-outline", "white"), "Pubblica"))
        self.publish_button.setEnabled(publishable)
        self.publish_button.clicked.connect(self._publish)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        if self.settings_changed:
            buttons.addWidget(QLabel("Nessuna modifica al modello · cambiate le impostazioni condivise del progetto "
                                     "(verifiche, nome, descrizione…): vengono pubblicate.", objectName="muted"))
        elif not self.diff and unsent:
            # Nothing new to record, but versions recorded here and never sent (e.g. published before a remote
            # was set): they can be sent now.
            self.publish_button.setText("Invia al repository")
            self.publish_button.setEnabled(True)
            self.publish_button.clicked.disconnect()
            self.publish_button.clicked.connect(self._send_only)
            buttons.addWidget(QLabel(f"Nessuna modifica da pubblicare · {unsent} "
                                     f"{'versione' if unsent == 1 else 'versioni'} da inviare al repository.",
                                     objectName="muted"))
        elif not self.diff:
            buttons.addWidget(QLabel("Nessuna modifica da pubblicare.", objectName="muted"))
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.publish_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(info)
        layout.addWidget(changes, 1)
        layout.addLayout(buttons)

    def _checks_summary(self, project):
        """Findings of the active checks on what is being published: shown, they never block the publication."""
        enabled = enabled_count(project)
        label = QLabel(objectName="muted")
        label.setWordWrap(True)
        self.findings = []
        if not enabled:
            label.setText("Verifiche del modello: nessun controllo attivo (Progetto › Impostazioni › Verifiche).")
            return label
        if problems(project.checks, project.model):
            label.setText("Verifiche del modello non eseguite: le impostazioni non sono corrette (Progetto › "
                          "Impostazioni › Verifiche).")
            return label
        self.findings = run_checks(project)
        counts = count(self.findings)
        color = SEVERITY_COLORS[ERROR] if counts[ERROR] else SEVERITY_COLORS[WARNING] if counts[WARNING] else "#166534"
        label.setText(f"<span style='color:{color}; font-weight:600'>Verifiche del modello ({enabled} controlli "
                      f"attivi): {summary(counts)}.</span> Non bloccano la pubblicazione; per il dettaglio usa «Verifica "
                      "modello» (F7).")
        return label

    def _send_only(self):
        self.send_only = True
        self.accept()

    def target_branch(self):
        """The branch the version goes to: the one in use, or the new one written."""
        return self.new_branch.text().strip() if self.on_new.isChecked() else self.project.current_branch()

    def _where(self):
        remote = self.project.remote()
        branch = self.target_branch() or "…"
        new = " (nuovo, creato ora dall'ultima versione del ramo in uso)" if self.on_new.isChecked() else ""
        where = (f"e inviata al ramo «{branch}»{new} del repository {remote}" if remote else
                 f"sul ramo «{branch}»{new}, su questo PC (nessun repository remoto: impostalo in Progetto › "
                 "Impostazioni › Repository Git)")
        self.note.setText(f"La versione viene registrata nella cronologia del progetto {where}. Le modifiche non "
                          "ancora salvate vengono salvate prima della pubblicazione.")

    def _publish(self):
        message = self.message.toPlainText().strip()
        name, email = self.author_name.text().strip(), self.author_email.text().strip()
        if not message:
            QMessageBox.warning(self, "Pubblica versione", "Scrivi una descrizione della versione.")
            return
        if not name or "@" not in email:
            QMessageBox.warning(self, "Pubblica versione", "Indica nome ed e-mail dell'autore.")
            return
        new_branch = self.new_branch.text().strip() if self.on_new.isChecked() else None
        if self.on_new.isChecked():
            problem = self.project.check_branch_name(new_branch)
            if problem:
                QMessageBox.warning(self, "Pubblica versione", problem)
                return
        s = settings()
        s.setValue("author/name", name)
        s.setValue("author/email", email)
        try:
            text, author = with_member(message, self.project, self.user), f"{name} <{email}>"
            self.sha = (self.project.publish_on_new_branch(new_branch, text, author) if new_branch else
                        self.project.publish(text, author))
        except NothingToSave:
            QMessageBox.information(self, "Pubblica versione", "Non ci sono modifiche da pubblicare.")
            return
        self.accept()


class CompareSide:
    """One side of a comparison: a branch (of this PC or of the remote) and one of its versions; on the branch in
    use, also the working state."""

    def __init__(self, project, branch=None, state=None):
        self.project = project
        self.branch, self.version = QComboBox(), QComboBox()
        self.branch.setMinimumWidth(300)
        self.version.setMinimumWidth(340)
        self.reload(branch)
        self.branch.currentIndexChanged.connect(lambda _i: self.fill())
        self.fill(state)

    def reload(self, branch=None):
        """The branches of this PC and of the repository (e.g. after «Aggiorna dal repository»)."""
        from arcadia_tool.ui.branches import branch_sources, fill_sources

        self.choices = branch_sources(self.project)
        fill_sources(self.branch, self.choices, branch)

    def selected_branch(self):
        from arcadia_tool.ui.branches import find_source

        return find_source(self.choices, self.branch.currentData())

    def fill(self, state=None):
        self.version.clear()
        b = self.selected_branch()
        if b is None or b.current:
            self.version.addItem(icon("mdi6.pencil-outline"), WORKING_LABEL, WORKING)
        versions = self.project.branch_versions(b.head) if b is not None and b.head else []
        for v in versions:
            self.version.addItem(icon("mdi6.history"), version_label(v), v.sha)
        if state is not None and self.version.findData(state) < 0 and state != WORKING:
            v = self.project.repository.version(state)  # a version not in this branch: shown anyway
            self.version.addItem(icon("mdi6.history"), version_label(v), v.sha)
        if state is not None:
            self.version.setCurrentIndex(max(self.version.findData(state), 0))

    @property
    def state(self):
        return self.version.currentData()

    def label(self):
        return f"{self.branch.currentText().replace('  (in uso)', '')} · {self.version.currentText()}"


class CompareDialog(QDialog):
    """Comparison between two states chosen by the user: each a version of a branch, on this PC or in the
    repository (local with local, local with remote, remote with remote), or the working state. since_common:
    only what «A» changed since the version it has in common with «Da» (e.g. what an activity branch changed since
    it started from main). credentials: to download the branches of the repository when the window opens (and
    with «Aggiorna dal repository»)."""

    def __init__(self, project, before=None, after=None, parent=None, before_branch=None, after_branch=None,
                 since_common=False, credentials=None):
        super().__init__(parent)
        self.project, self.credentials, self.worker = project, credentials, None
        self.setWindowTitle("Confronta versioni")
        self.resize(1320, 780)
        self.versions = project.versions()
        current = project.current_branch()
        self.left = CompareSide(project, before_branch or current,
                                before or (self.versions[0].sha if self.versions else WORKING))
        self.right = CompareSide(project, after_branch or current, after or WORKING)
        self.before, self.after = self.left.version, self.right.version
        swap = QPushButton(icon("mdi6.swap-horizontal"), "")
        swap.setToolTip("Inverti")
        swap.clicked.connect(self._swap)
        self.common = QCheckBox("Solo ciò che ha cambiato «A» dal punto di partenza comune con «Da»")
        self.common.setToolTip("Es. le modifiche di un ramo di attività da quando è nato da main, senza quelle "
                               "entrate nel frattempo in main")
        self.common.setChecked(since_common)
        compare = primary(QPushButton(icon("mdi6.compare-horizontal", "white"), "Confronta"))
        compare.clicked.connect(self.compare)
        self.fetch_button = QPushButton(icon("mdi6.cloud-sync-outline"), "Aggiorna dal repository")
        self.fetch_button.setToolTip("Scarica i rami del repository (il progetto non cambia), per confrontarli")
        self.fetch_button.setEnabled(bool(project.remote()))
        self.fetch_button.clicked.connect(self.fetch)
        self.fetched = QLabel(objectName="muted")
        self._fetched_text()

        bar, bar_layout = card()
        grid = QFormLayout()
        grid.setHorizontalSpacing(12)
        for label, side in (("Da", self.left), ("A", self.right)):
            row = QHBoxLayout()
            row.addWidget(side.branch)
            row.addWidget(side.version, 1)
            if side is self.left:
                row.addWidget(swap)
            grid.addRow(QLabel(label, objectName="formLabel"), row)
        bar_layout.addLayout(grid)
        options = QHBoxLayout()
        options.addWidget(self.common)
        options.addStretch()
        options.addWidget(self.fetched)
        options.addWidget(self.fetch_button)
        options.addWidget(compare)
        bar_layout.addLayout(options)

        self.result, self.result_layout = card()
        self._placeholder()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(bar)
        layout.addWidget(self.result, 1)
        if before or after:
            self.compare()

    @staticmethod
    def _select(combo, state):
        combo.setCurrentIndex(max(combo.findData(state), 0))

    # --- the branches of the repository ---------------------------------------------------------------

    def _fetched_text(self, text=None):
        when = self.project.fetched_at().replace("T", " ")
        self.fetched.setStyleSheet(f"color: {MUTED};")
        self.fetched.setText(text or (f"Rami del repository al {when}" if when else
                                      "Rami del repository non ancora scaricati" if self.project.remote() else
                                      "Nessun repository remoto"))

    def showEvent(self, event):
        super().showEvent(event)
        if self.credentials is not None and self.project.remote() and self.worker is None:
            self.fetch()  # the repository as it is now, when the window opens

    def fetch(self):
        from arcadia_tool.ui.branches import FetchWorker

        if self.worker is not None and self.worker.isRunning():
            return
        self.fetch_button.setEnabled(False)
        self._fetched_text("Download dei rami del repository…")
        self.worker = FetchWorker(self.project, self.credentials or {})
        self.worker.done.connect(self._fetch_done)
        self.worker.failed.connect(self._fetch_failed)
        self.worker.start()

    def _fetch_done(self):
        self.worker.wait()
        self.fetch_button.setEnabled(True)
        for side in (self.left, self.right):
            key, state = side.branch.currentData(), side.state
            side.reload(key)
            side.fill(state)
        self._fetched_text()

    def _fetch_failed(self, message):
        self.worker.wait()
        self.fetch_button.setEnabled(True)
        self._fetched_text(message)
        self.fetched.setStyleSheet("color: #B42318;")

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return  # not while downloading
        super().reject()

    def _swap(self):
        lb, ls = self.left.branch.currentData(), self.left.state
        rb, rs = self.right.branch.currentData(), self.right.state
        self.left.branch.setCurrentIndex(max(self.left.branch.findData(rb), 0))
        self.left.fill(rs)
        self.right.branch.setCurrentIndex(max(self.right.branch.findData(lb), 0))
        self.right.fill(ls)

    def _clear_result(self):
        while self.result_layout.count():
            widget = self.result_layout.takeAt(0).widget()
            if widget:
                widget.setParent(None)

    def _placeholder(self):
        self._clear_result()
        hint = QLabel("Scegli i due stati del modello (ramo e versione) e premi «Confronta».", alignment=Qt.AlignCenter,
                      objectName="muted")
        self.result_layout.addWidget(hint, 1)

    def _model(self, state):
        if state == WORKING:
            return self.project.model
        return self.project.published_model(state) if state else Model()

    def compare(self):
        before, after = self.left.state, self.right.state
        before_label, after_label = self.left.label(), self.right.label()
        if self.common.isChecked():
            if WORKING in (before, after):
                QMessageBox.information(self, "Confronta versioni", "Il punto di partenza comune si cerca tra due "
                                        "versioni pubblicate: scegli una versione anche al posto dello stato attuale.")
                return
            base = self.project.repository.merge_base(before, after)
            if base is None:
                QMessageBox.information(self, "Confronta versioni", "Le due versioni non hanno un punto di "
                                        "partenza comune.")
                return
            before, before_label = base, f"punto di partenza comune · {version_label(self.project.repository.version(base))}"
        if before == after:
            QMessageBox.information(self, "Confronta versioni",
                                    "Nessuna differenza: «A» non ha modifiche rispetto al punto di partenza comune."
                                    if self.common.isChecked() else "Scegli due stati diversi.")
            return
        diff = diff_models(self._model(before), self._model(after))
        self._clear_result()
        self.result_layout.addWidget(DiffView(diff, before_label, after_label), 1)


class VersionDialog(QDialog):
    """A published version: date, author, description, where it is (sent to the repository or only on this PC)
    and every model element it added, changed or deleted with respect to the version before (the first one:
    all of its elements)."""

    def __init__(self, project, versions, row, remote, unsent, parent=None, branch=None):
        super().__init__(parent)
        version = versions[row]
        # The version it comes from in the history of its branch (for an integration, the one of this branch).
        parents = project.repository.parents(version.sha)
        previous = project.repository.version(parents[0]) if parents else None
        branch = branch or project.push_branch()
        self.setWindowTitle(f"Versione {version.short} · {version.title}")
        self.resize(1240, 780)
        self.diff = diff_models(project.published_model(previous.sha) if previous else Model(),
                                project.published_model(version.sha))
        if not remote:
            where = "Solo su questo PC (nessun repository remoto configurato)"
        elif version.sha in unsent:
            where = f"Solo su questo PC: non ancora inviata al repository {remote}"
        else:
            where = f"Inviata al ramo «{branch}» del repository {remote}"
        info, info_layout = card("Versione")
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        for label, value in (("Data", f"{version.timestamp:%d/%m/%Y %H:%M}"), ("Autore", version.author),
                             ("Descrizione", version.message), ("Codice", version.sha), ("Repository", where),
                             ("Rispetto a", version_label(previous) if previous else
                              "Prima versione: tutti gli elementi del modello sono nuovi")):
            text = QLabel(value)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if label == "Repository":
                text.setStyleSheet(f"color: {'#166534' if where.startswith('Inviata') else MUTED};"
                                   " font-weight: 600;")
            form.addRow(QLabel(label, objectName="formLabel"), text)
        info_layout.addLayout(form)
        changes, changes_layout = card(f"Elementi del modello nella versione ({len(self.diff.changes)})")
        changes_layout.addWidget(DiffView(self.diff, version_label(previous) if previous else "Nessuna versione",
                                          version_label(version)), 1)
        close = QPushButton("Chiudi")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(info)
        layout.addWidget(changes, 1)
        layout.addLayout(buttons)


# Columns of the history: (title, width; 0 = the one that takes the remaining space).
HISTORY_COLUMNS = (("Data", 140), ("Autore", 190), ("Descrizione", 0), ("Repository", 140), ("Versione", 96))


class HistoryDialog(QDialog):
    """The published versions of a branch (the one in use, or another of this PC or of the remote). request, on
    accept: ("create", name, sha, send), a new branch from a version (see ui.branches)."""

    def __init__(self, project, parent=None, branch=None, user=None):
        super().__init__(parent)
        self.project, self.user, self.request = project, user, None
        self.setWindowTitle("Cronologia delle pubblicazioni")
        self.resize(1080, 600)
        from arcadia_tool.ui.branches import branch_sources, fill_sources
        self.choices = branch_sources(project)
        self.branch = QComboBox()
        self.branch.setMinimumWidth(360)
        fill_sources(self.branch, self.choices, branch)
        self.branch.currentIndexChanged.connect(lambda _i: self.fill())
        self.table = QTableWidget(0, len(HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels([title for title, _ in HISTORY_COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        # Every column with its own width and some space, divided by a light line (they ran together).
        self.table.setStyleSheet(f"QTableWidget::item {{ padding: 0 6px; border-right: 1px solid {BORDER}; }}")
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(False)
        for c, (_, width) in enumerate(HISTORY_COLUMNS):
            if width:
                header.setSectionResizeMode(c, QHeaderView.Interactive)
                header.resizeSection(c, width)
            else:
                header.setSectionResizeMode(c, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda index: self.show_version(index.row()))
        self.empty = QLabel("Nessuna versione pubblicata.", alignment=Qt.AlignCenter, objectName="muted")

        previous = QPushButton(icon("mdi6.compare-horizontal"), "Confronta con la precedente")
        current = QPushButton(icon("mdi6.pencil-outline"), "Confronta con lo stato attuale")
        two = QPushButton(icon("mdi6.select-compare"), "Confronta le due selezionate")
        previous.clicked.connect(self.compare_previous)
        current.clicked.connect(self.compare_current)
        two.clicked.connect(self.compare_two)
        new = QPushButton(icon("mdi6.source-branch-plus"), "Crea ramo da questa versione…")
        new.setToolTip("Un nuovo ramo di attività che parte dalla versione selezionata")
        new.clicked.connect(self.new_branch)
        close = QPushButton("Chiudi")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (previous, current, two, new):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(close)

        top = QHBoxLayout()
        top.addWidget(QLabel("Ramo", objectName="formLabel"))
        top.addWidget(self.branch)
        top.addStretch()
        body, body_layout = card()
        body_layout.addLayout(top)
        body_layout.addWidget(self.table, 1)
        body_layout.addWidget(self.empty, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(body, 1)
        layout.addLayout(buttons)
        self.fill()

    def selected_branch(self):
        from arcadia_tool.ui.branches import find_source

        return find_source(self.choices, self.branch.currentData())

    def fill(self):
        b = self.selected_branch()
        self.versions = self.project.branch_versions(b.head) if b is not None and b.head else []
        current = b is None or b.current
        self.remote = self.project.remote()
        self.unsent = {v.sha for v in self.project.unsent_versions()} if self.remote and current else set()
        remote_head = None
        if b is not None:
            remote_head = b.head if b.remote else self.project.repository.remote_heads().get(b.name)
        on_remote = set(v.sha for v in self.project.branch_versions(remote_head)) if remote_head else set()
        self.table.setRowCount(len(self.versions))
        for r, v in enumerate(self.versions):
            name, _, email = v.author.partition(" <")
            if not self.remote:
                state = "solo su questo PC"
            elif current:
                state = "solo su questo PC" if v.sha in self.unsent else "inviata"
            else:
                state = "inviata" if v.sha in on_remote else "solo su questo PC"
            values = (f"{v.timestamp:%d/%m/%Y %H:%M}", name, v.title, state, v.short)
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(v.message if c != 1 else v.author)
                if c == 3:
                    item.setForeground(QColor("#166534" if text == "inviata" else MUTED))
                if c == 4:
                    item.setFont(QFont("Consolas", 9))
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(self.versions))
        self.empty.setVisible(not self.versions)

    def new_branch(self):
        from arcadia_tool.ui.branches import NewBranchDialog
        rows = self._rows()
        if len(rows) != 1:
            QMessageBox.information(self, "Nuovo ramo", "Seleziona la versione da cui parte il ramo.")
            return
        dialog = NewBranchDialog(self.project, self.user, self.versions[rows[0]].sha, self)
        if dialog.exec():
            self.request = ("create", dialog.name_value, dialog.sha, dialog.send)
            self.accept()

    def _rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _open(self, before, after):
        b = self.selected_branch()
        name = b.name if b is not None else None
        after_branch = self.project.current_branch() if after == WORKING else name
        CompareDialog(self.project, before, after, self, before_branch=name, after_branch=after_branch).exec()

    def show_version(self, row):
        """Double click: what the version contains and where it is (sent to the repository or not)."""
        if 0 <= row < len(self.versions):
            b = self.selected_branch()
            VersionDialog(self.project, self.versions, row, self.remote, self.unsent, self,
                          branch=b.name if b is not None else None).exec()

    def compare_previous(self):
        rows = self._rows()
        if len(rows) != 1:
            QMessageBox.information(self, "Confronto", "Seleziona una versione.")
            return
        r = rows[0]
        before = self.versions[r + 1].sha if r + 1 < len(self.versions) else None
        if before is None:
            QMessageBox.information(self, "Confronto", "È la prima versione pubblicata: non ha una precedente.")
            return
        self._open(before, self.versions[r].sha)

    def compare_current(self):
        rows = self._rows()
        if len(rows) != 1:
            QMessageBox.information(self, "Confronto", "Seleziona una versione.")
            return
        self._open(self.versions[rows[0]].sha, WORKING)

    def compare_two(self):
        rows = self._rows()
        if len(rows) != 2:
            QMessageBox.information(self, "Confronto", "Seleziona due versioni (Ctrl+clic).")
            return
        newer, older = rows
        self._open(self.versions[older].sha, self.versions[newer].sha)
