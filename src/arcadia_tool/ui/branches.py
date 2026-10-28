"""Versioni › Rami: the branches of the project, on this PC and on the remote (as last downloaded, «Aggiorna dal
repository»). A new branch starts from a chosen version of any branch; the project moves to a branch, or one of
the remote; the history of every branch, and the comparison between branches (also those of the remote, and the
working state).

The windows do not change the project: they leave the request (`request`) to the main window, which publishes or
discards the changes not yet published first, then moves the project and opens it again."""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from arcadia_tool.accounts import git_host
from arcadia_tool.model.teams import memberships
from arcadia_tool.ui.element_editor import card
from arcadia_tool.ui.theme import ACCENT, MUTED, icon

BRANCH_COLUMNS = (("Ramo", 250), ("Ultima versione", 0), ("Autore", 170), ("Dove", 250), ("Rispetto a main", 200))
BRANCH_PREFIX = "att/"
SHOW = (("all", "Tutti i rami"), ("local", "Solo su questo PC"), ("remote", "Solo nel repository"))


def version_text(v):
    return f"{v.timestamp:%d/%m/%Y %H:%M} · {v.title}" if v is not None else ""


def author_name(v):
    return v.author.split(" <")[0] if v is not None else ""


def suggested_name(project, user):
    """«att/<team>-»: the activity branches of a team start with its ID."""
    teams = memberships(project.model, user) if user is not None else []
    team = next((t.get("id") for t, _row in teams if t.get("id") and not t.get("design_authority")), None)
    team = team or next((t.get("id") for t, _row in teams if t.get("id")), None)
    return f"{BRANCH_PREFIX}{team}-" if team else BRANCH_PREFIX


class FetchWorker(QThread):
    done = Signal()
    failed = Signal(str)

    def __init__(self, project, credentials):
        super().__init__()
        self.project, self.credentials = project, credentials

    def run(self):
        try:
            self.project.fetch_branches(**self.credentials)
            self.done.emit()
        except Exception as exc:
            self.failed.emit(f"Aggiornamento non riuscito: {exc or exc.__class__.__name__}")


class Source:
    """A branch as it is in one place: on this PC (local) or in the repository (remote, as last downloaded). The
    same branch is two sources when it is in both: they can be compared with each other."""

    def __init__(self, name, head, remote=False, current=False):
        self.name, self.head, self.remote, self.current = name, head, remote, current
        self.key = f"{'remote' if remote else 'local'}:{name}"

    @property
    def label(self):
        return f"Repository › {self.name}" if self.remote else (
            f"Questo PC › {self.name}" + ("  (in uso)" if self.current else ""))


def branch_sources(project):
    """The branches of this PC (the one in use first), then those of the repository."""
    branches = project.branches()
    local = [Source(b.name, b.local, current=b.current) for b in branches if b.local]
    local.sort(key=lambda s: not s.current)
    if not any(s.current for s in local):  # a project with no version yet: its branch anyway
        local.insert(0, Source(project.current_branch(), project.repository.head(), current=True))
    return local + [Source(b.name, b.remote, remote=True) for b in branches if b.remote]


def find_source(sources, wanted):
    """The source for a key («local:main», «remote:main») or a name (on this PC if it is here, else in the
    repository), or the first one."""
    if wanted:
        for key in (wanted, f"local:{wanted}", f"remote:{wanted}"):
            found = next((s for s in sources if s.key == key), None)
            if found is not None:
                return found
    return sources[0] if sources else None


def fill_sources(combo, sources, wanted=None):
    combo.blockSignals(True)
    combo.clear()
    for s in sources:
        combo.addItem(icon("mdi6.cloud-outline" if s.remote else "mdi6.laptop", ACCENT if s.current else MUTED),
                      s.label, s.key)
    chosen = find_source(sources, wanted)
    if chosen is not None:
        combo.setCurrentIndex(max(combo.findData(chosen.key), 0))
    combo.blockSignals(False)


class NewBranchDialog(QDialog):
    """A new branch from a version of a branch: the name, where it starts, whether to send it at once.
    On OK: name, sha, send."""

    def __init__(self, project, user=None, start=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.name_value = self.sha = None
        self.send = False
        self.setWindowTitle("Nuovo ramo")
        self.setMinimumWidth(820)
        self.name = QLineEdit(suggested_name(project, user))
        self.name.setPlaceholderText("es. att/T2-odometria")
        self.name.setToolTip("Rami di attività: att/<team>-<attività>, brevi, integrati poi in main dalla Design "
                             "Authority")
        self.branch = QComboBox()
        self.version = QComboBox()
        self.version.setMinimumWidth(420)
        self.choices = branch_sources(project)
        main = project.main_branch()
        # A version chosen (e.g. in the history): the branch in use by default; else main.
        fill_sources(self.branch, self.choices, None if start is not None else main)
        self.branch.currentIndexChanged.connect(lambda _i: self._fill_versions())
        self._fill_versions(start)
        self.send_box = QCheckBox("Invia subito il ramo al repository, così è visibile al team")
        self.send_box.setChecked(bool(project.remote()))
        self.send_box.setEnabled(bool(project.remote()))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.addRow("Nome del ramo", self.name)
        form.addRow("Parte dal ramo", self.branch)
        form.addRow("Dalla versione", self.version)
        note = QLabel("Il progetto passa sul nuovo ramo e riparte esattamente da quella versione; le versioni che "
                      "pubblicherai andranno su questo ramo.", objectName="muted")
        note.setWordWrap(True)
        create = QPushButton(icon("mdi6.source-branch-plus", "white"), "Crea ramo")
        create.setProperty("primary", True)
        create.clicked.connect(self._accept)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.send_box)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.name.setFocus()
        self.name.setCursorPosition(len(self.name.text()))

    def _selected_branch(self):
        return find_source(self.choices, self.branch.currentData())

    def _fill_versions(self, start=None):
        self.version.clear()
        b = self._selected_branch()
        if b is None:
            return
        for v in self.project.branch_versions(b.head) if b.head else []:
            self.version.addItem(icon("mdi6.history"), version_text(v), v.sha)
        if start is not None and self.version.findData(start) >= 0:
            self.version.setCurrentIndex(self.version.findData(start))
        elif start is not None:  # a version of another branch (e.g. of the history of a remote branch)
            v = self.project.repository.version(start)
            self.version.insertItem(0, icon("mdi6.history"), version_text(v), v.sha)
            self.version.setCurrentIndex(0)

    def _accept(self):
        name = self.name.text().strip()
        problem = self.project.check_branch_name(name)
        if problem is None and not self.version.currentData():
            problem = "Scegli la versione da cui parte il ramo."
        if problem:
            QMessageBox.warning(self, self.windowTitle(), problem)
            return
        self.name_value, self.sha, self.send = name, self.version.currentData(), self.send_box.isChecked()
        self.accept()


class BranchesDialog(QDialog):
    """The branches of the project. request, on accept: ("switch", name) or ("create", name, sha, send)."""

    def __init__(self, project, credentials, user=None, parent=None):
        super().__init__(parent)
        self.project, self.credentials, self.user = project, credentials, user
        self.request, self.worker, self.branches = None, None, []
        self.setWindowTitle("Rami del progetto")
        self.resize(1180, 560)
        url = project.remote()
        title = QLabel(f"Rami del progetto · repository {git_host(url) or url}" if url else
                       "Rami del progetto (nessun repository remoto)", objectName="cardTitle")
        self.fetched = QLabel(objectName="muted")
        self.fetch_button = QPushButton(icon("mdi6.cloud-sync-outline"), "Aggiorna dal repository")
        self.fetch_button.setToolTip("Scarica i rami del repository senza cambiare il progetto")
        self.fetch_button.setEnabled(bool(url))
        self.fetch_button.clicked.connect(self.fetch)
        self.which = QComboBox()
        for key, label in SHOW:
            self.which.addItem(icon({"all": "mdi6.source-branch", "local": "mdi6.laptop",
                                    "remote": "mdi6.cloud-outline"}[key]), label, key)
        self.which.setToolTip("Quali rami mostrare: tutti, solo quelli di questo PC o solo quelli del repository")
        self.which.currentIndexChanged.connect(lambda _i: self.fill())
        top = QHBoxLayout()
        top.addWidget(title)
        top.addSpacing(12)
        top.addWidget(self.which)
        top.addStretch()
        top.addWidget(self.fetched)
        top.addWidget(self.fetch_button)

        self.table = QTableWidget(0, len(BRANCH_COLUMNS))
        self.table.setHorizontalHeaderLabels([t for t, _ in BRANCH_COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        for c, (_t, width) in enumerate(BRANCH_COLUMNS):
            header.setSectionResizeMode(c, QHeaderView.Stretch if not width else QHeaderView.Interactive)
            if width:
                header.resizeSection(c, width)
        self.table.itemSelectionChanged.connect(self._update)
        self.table.doubleClicked.connect(lambda _index: self.history())

        self.switch_button = QPushButton(icon("mdi6.source-branch-check"), "Passa a questo ramo")
        self.switch_button.clicked.connect(self.switch)
        self.new_button = QPushButton(icon("mdi6.source-branch-plus"), "Nuovo ramo…")
        self.new_button.clicked.connect(lambda: self.new_branch())
        self.history_button = QPushButton(icon("mdi6.history"), "Cronologia")
        self.history_button.clicked.connect(self.history)
        self.compare_working = QPushButton(icon("mdi6.pencil-outline"), "Confronta con il mio stato attuale")
        self.compare_working.clicked.connect(lambda: self.compare("working"))
        self.compare_main = QPushButton(icon("mdi6.compare-horizontal"), "Cosa ha cambiato rispetto a main")
        self.compare_main.setToolTip("Le modifiche del ramo da quando è nato da main (senza quelle entrate nel "
                                     "frattempo in main)")
        self.compare_main.clicked.connect(lambda: self.compare("main"))
        close = QPushButton("Chiudi")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        for b in (self.switch_button, self.new_button, self.history_button, self.compare_working,
                  self.compare_main):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(close)

        body, body_layout = card()
        body_layout.addLayout(top)
        body_layout.addWidget(self.table, 1)
        self.status = QLabel(objectName="muted")
        self.status.setWordWrap(True)
        body_layout.addWidget(self.status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(body, 1)
        layout.addLayout(buttons)
        self.fill()

    # --- the list -------------------------------------------------------------------------------------

    @property
    def mode(self):
        return self.which.currentData() or "all"

    def _head(self, b):
        """The last version of a branch as shown: on this PC, in the repository, or the one of this PC if both."""
        return b.remote if self.mode == "remote" else b.local if self.mode == "local" else b.head

    def _key(self, b):
        """The source of the branch for the history and the comparisons (see branch_sources)."""
        return f"remote:{b.name}" if self.mode == "remote" or not b.local else f"local:{b.name}"

    def fill(self):
        mode = self.mode
        self.branches = [b for b in self.project.branches()
                         if mode == "all" or (b.local if mode == "local" else b.remote)]
        for b in self.branches:
            b.last = self.project.repository.version(self._head(b))
        fetched = self.project.fetched_at().replace("T", " ")
        self.fetched.setText(f"Rami del repository aggiornati al {fetched}" if fetched else
                             "Rami del repository: non ancora aggiornati")
        self.table.setRowCount(len(self.branches))
        bold = QFont()
        bold.setBold(True)
        for r, b in enumerate(self.branches):
            relation = "" if b.main or b.ahead is None else (
                "allineato" if not b.ahead and not b.behind else
                ", ".join(p for p in (f"{b.ahead} avanti" if b.ahead else "",
                                      f"{b.behind} indietro" if b.behind else "") if p))
            values = (b.name + ("  (in uso)" if b.current else ""), version_text(b.last), author_name(b.last),
                      b.where, "ramo principale" if b.main else relation)
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setIcon(icon("mdi6.source-branch", ACCENT if b.current else MUTED))
                    if b.current:
                        item.setFont(bold)
                    item.setData(Qt.UserRole, b.name)
                if c == 1 and b.last is not None:
                    item.setToolTip(b.last.message)
                if c == 4 and relation and not b.main:
                    item.setToolTip(f"{b.ahead} versioni del ramo non sono in main; main ha {b.behind} versioni "
                                    "che il ramo non ha")
                self.table.setItem(r, c, item)
        current = next((r for r, b in enumerate(self.branches) if b.current), 0)
        if self.branches:
            self.table.selectRow(current)
        else:
            self.status.setStyleSheet(f"color: {MUTED};")
            self.status.setText("Nessun ramo nel repository: usa «Aggiorna dal repository»." if mode == "remote"
                                else "Nessun ramo da mostrare.")
        self._update()

    def selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        return self.branches[min(rows)] if rows else None

    def _update(self):
        b = self.selected()
        self.switch_button.setEnabled(b is not None and not b.current)
        self.history_button.setEnabled(b is not None)
        self.compare_working.setEnabled(b is not None and not b.current)
        main = self.project.main_branch()
        self.compare_main.setEnabled(b is not None and main is not None and b.name != main)
        self.new_button.setEnabled(bool(self.project.branches()))

    # --- the repository -------------------------------------------------------------------------------

    def fetch(self):
        self.fetch_button.setEnabled(False)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText("Download dei rami del repository…")
        self.worker = FetchWorker(self.project, self.credentials)
        self.worker.done.connect(self._fetched)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _fetched(self):
        self.worker.wait()
        self.fetch_button.setEnabled(True)
        self.status.setText("Rami del repository aggiornati: il progetto non è cambiato.")
        self.fill()

    def _failed(self, message):
        self.worker.wait()
        self.fetch_button.setEnabled(True)
        self.status.setStyleSheet("color: #B42318;")
        self.status.setText(message)

    # --- actions --------------------------------------------------------------------------------------

    def switch(self):
        b = self.selected()
        if b is not None and not b.current:
            self.request = ("switch", b.name)
            self.accept()

    def new_branch(self, start=None):
        dialog = NewBranchDialog(self.project, self.user, start or (self.selected().head if self.selected() else
                                                                    None), self)
        if dialog.exec():
            self.request = ("create", dialog.name_value, dialog.sha, dialog.send)
            self.accept()

    def history(self):
        from arcadia_tool.ui.versions import HistoryDialog
        b = self.selected()
        if b is None:
            return
        dialog = HistoryDialog(self.project, self, branch=self._key(b), user=self.user)
        dialog.exec()
        if dialog.request is not None:
            self.request = dialog.request
            self.accept()

    def compare(self, what):
        from arcadia_tool.ui.versions import WORKING, CompareDialog
        b = self.selected()
        if b is None:
            return
        if what == "working":
            CompareDialog(self.project, before=self._head(b), after=WORKING, parent=self,
                          before_branch=self._key(b)).exec()
        else:
            main = self.project.main_branch()
            main_branch = next(x for x in self.project.branches() if x.name == main)
            main_head = main_branch.head
            CompareDialog(self.project, before=main_head, after=self._head(b), parent=self, before_branch=main,
                          after_branch=self._key(b), since_common=True).exec()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return  # not while downloading
        super().reject()
