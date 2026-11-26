"""Versioni › Rami: the branches of the project, on this PC and on the remote (as last downloaded, «Aggiorna Lista»);
«Aggiorna Tutto», or the right click on a branch, brings the branches of this PC up to the remote (those only there
downloaded). A new branch starts from a chosen version of any branch; the project moves to a branch, or one of
the remote, or the whole model to a version of one (restored on the branch, or the branch brought back to it); the
history of every branch, and the comparison between branches (also those of the remote, and the working state).

The windows do not change the project: they leave the request (`request`) to the main window, which publishes or
discards the changes not yet published first, then moves the project and opens it again."""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from arcadia_tool.accounts import git_host
from arcadia_tool.model.teams import memberships
from arcadia_tool.ui.element_editor import card
from arcadia_tool.ui.theme import ACCENT, MUTED, icon

BRANCH_COLUMNS = (("Ramo", 250), ("Ultima versione", 0), ("Autore", 170), ("Dove", 250),
                  ("Rispetto al ramo principale", 220))
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


_RUNNING = set()  # downloads left to finish after their window was closed (kept alive until they end)


def finish_in_background(worker):
    """The window is closed while it downloads the branches: the download goes on and ends by itself (the branches
    of the remote are then up to date), nothing is shown of it."""
    for signal in (worker.done, worker.failed):
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            pass
    _RUNNING.add(worker)
    worker.finished.connect(lambda: _RUNNING.discard(worker))


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


class UpdateWorker(QThread):
    """«Aggiorna Tutto» or «Aggiorna questo ramo»: the remote downloaded, then the branches (`names`, or all of them)
    updated with Project.update_local_branches. done((report, behind)): behind, the versions of the remote the branch
    in use lacks (to receive with Ricevi, which merges), None if it is not among them or not on the remote."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, project, credentials, names=None):
        super().__init__()
        self.project, self.credentials, self.names = project, credentials, names

    def run(self):
        try:
            p = self.project
            heads = p.fetch_branches(**self.credentials)
            names = sorted(p.receivable_branches()) if self.names is None else list(self.names)
            current = p.current_branch()
            report = p.update_local_branches([n for n in names if n != current], heads)
            behind = None
            mine, theirs = p.repository.local_heads().get(current), heads.get(current)
            if current in names and theirs:
                behind = 0 if mine and p.repository.is_ancestor(theirs, mine) else len(
                    p.repository.versions_between(mine, theirs))
            self.done.emit((report, behind))
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


class CheckoutDialog(QDialog):
    """The whole model at a version of a branch, of this PC or of the repository: restored on the branch (a change
    to publish) or the branch brought back to it. On OK: name, sha, move_branch."""

    def __init__(self, project, start=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.name_value = self.sha = None
        self.move_branch = False
        self.setWindowTitle("Checkout di una versione del modello")
        self.setMinimumWidth(860)
        self.branch = QComboBox()
        self.version = QComboBox()
        self.version.setMinimumWidth(440)
        self.choices = branch_sources(project)
        fill_sources(self.branch, self.choices, start)
        self.branch.currentIndexChanged.connect(lambda _i: self._fill_versions())
        self.version.currentIndexChanged.connect(lambda _i: self._explain())
        self.restore = QRadioButton("Ripristina il modello di questa versione sul ramo (consigliato)")
        self.restore.setToolTip("Il ramo resta alla sua ultima versione: il modello diventa quello della versione "
                                "scelta e le differenze sono modifiche da pubblicare, inviate come le altre")
        self.move = QRadioButton("Riporta il ramo a questa versione (forzato)")
        self.move.setToolTip("Le versioni successive non sono più sul ramo su questo PC; il repository non cambia")
        self.restore.setChecked(True)
        for b in (self.restore, self.move):
            b.toggled.connect(lambda _on: self._explain())
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(16)
        form.addRow("Ramo", self.branch)
        form.addRow("Versione", self.version)
        self.note = QLabel(objectName="muted")
        self.note.setWordWrap(True)
        self.go = QPushButton(icon("mdi6.source-commit", "white"), "Checkout")
        self.go.setProperty("primary", True)
        self.go.clicked.connect(self._accept)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.go)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.restore)
        layout.addWidget(self.move)
        layout.addWidget(self.note)
        layout.addLayout(buttons)
        self._fill_versions()

    def selected_branch(self):
        return find_source(self.choices, self.branch.currentData())

    def _fill_versions(self):
        self.version.blockSignals(True)
        self.version.clear()
        b = self.selected_branch()
        for v in self.project.branch_versions(b.head) if b is not None and b.head else []:
            self.version.addItem(icon("mdi6.history"), f"{version_text(v)} · {author_name(v)} · {v.short}", v.sha)
        self.version.blockSignals(False)
        self._explain()

    def later(self):
        """The versions of the branch on this PC after the one chosen: (all, those only on this PC)."""
        b, sha = self.selected_branch(), self.version.currentData()
        local = self.project.repository.local_heads().get(b.name) if b is not None else None
        if not sha or not local or not self.project.repository.is_ancestor(sha, local):
            return [], []
        later = self.project.repository.versions_between(sha, local)
        remote = self.project.repository.remote_heads().get(b.name)
        on_remote = {v.sha for v in self.project.branch_versions(remote)} if remote else set()
        return later, [v for v in later if v.sha not in on_remote]

    def _explain(self):
        b, sha = self.selected_branch(), self.version.currentData()
        self.go.setEnabled(bool(sha))
        if b is None or not sha:
            self.note.setText("Nessuna versione su questo ramo.")
            return
        where = "" if b.current else f" Il progetto passa sul ramo «{b.name}»."
        if self.restore.isChecked():
            self.note.setText(f"Il modello completo diventa quello della versione scelta.{where} Il ramo resta alla "
                              "sua ultima versione: ciò che cambia rispetto a essa è una modifica da pubblicare "
                              "(«Pubblica»), che viene inviata al repository come le altre.")
            return
        later, only_here = self.later()
        text = (f"Il ramo «{b.name}» su questo PC torna alla versione scelta.{where} "
                f"Le {len(later)} versioni successive non sono più sul ramo" if later else
                f"Il ramo «{b.name}» su questo PC torna alla versione scelta.{where}")
        if later and only_here:
            text += f": {len(only_here)} di esse sono solo su questo PC e vanno perse"
        elif later:
            text += " su questo PC, ma restano nel repository: ricevendo le versioni tornano"
        self.note.setText(text + ". Il repository non cambia.")

    def _accept(self):
        b, sha = self.selected_branch(), self.version.currentData()
        if b is None or not sha:
            return
        _later, only_here = self.later() if self.move.isChecked() else ([], [])
        if only_here and QMessageBox.warning(
                self, self.windowTitle(), f"{len(only_here)} versioni pubblicate solo su questo PC, dopo quella "
                "scelta, andranno perse. Continuare?", QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        self.name_value, self.sha, self.move_branch = b.name, sha, self.move.isChecked()
        self.accept()


class BranchesDialog(QDialog):
    """The branches of the project. request, on accept: ("switch", name), ("create", name, sha, send) or
    ("checkout", name, sha, move_branch)."""

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
        self.fetch_button = QPushButton(icon("mdi6.cloud-sync-outline"), "Aggiorna Lista")
        self.fetch_button.setToolTip("Rilegge i rami del repository, senza cambiare il progetto né i rami di questo PC")
        self.fetch_button.setEnabled(bool(url))
        self.fetch_button.clicked.connect(self.fetch)
        self.update_all_button = QPushButton(icon("mdi6.cloud-download-outline"), "Aggiorna Tutto")
        self.update_all_button.setToolTip("Aggiorna tutti i rami di questo PC con le versioni del repository e scarica "
                                          "quelli che sono solo nel repository; il ramo in uso si riceve poi come con "
                                          "«Ricevi dal repository». Clic destro su un ramo: solo quello.")
        self.update_all_button.setEnabled(bool(url))
        self.update_all_button.clicked.connect(lambda _=False: self.update_branches())
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
        top.addWidget(self.update_all_button)

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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.menu = None

        self.switch_button = QPushButton(icon("mdi6.source-branch-check"), "Passa a questo ramo")
        self.switch_button.clicked.connect(self.switch)
        self.new_button = QPushButton(icon("mdi6.source-branch-plus"), "Nuovo ramo…")
        self.new_button.clicked.connect(lambda: self.new_branch())
        self.delete_button = QPushButton(icon("mdi6.trash-can-outline"), "Elimina ramo locale…")
        self.delete_button.clicked.connect(lambda _=False: self.delete_local())
        self.delete_remote_button = QPushButton(icon("mdi6.cloud-remove-outline"), "Elimina ramo remoto…")
        self.delete_remote_button.clicked.connect(lambda _=False: self.delete_remote())
        self.checkout_button = QPushButton(icon("mdi6.source-commit"), "Checkout di una versione…")
        self.checkout_button.setToolTip("Il modello completo a una versione del ramo selezionato, di questo PC o "
                                        "del repository")
        self.checkout_button.clicked.connect(self.checkout)
        self.integrate_button = QPushButton(icon("mdi6.source-merge"), "Integra nel ramo in uso…")
        self.integrate_button.setToolTip("Unisce le versioni del ramo selezionato in quello in uso, con ATLAS: per "
                                         "scheda e per campo, gli identificativi doppi rinumerati e le tracciature "
                                         "riallineate (un'unione fatta con Git non lo fa)")
        self.integrate_button.clicked.connect(self.integrate)
        # The versions of a branch: «Versioni Modello» (a double click on the branch opens them).
        close = QPushButton("Chiudi")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        for b in (self.switch_button, self.new_button, self.delete_button, self.delete_remote_button,
                  self.checkout_button, self.integrate_button):
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
        main = self.project.main_branch()
        self.table.horizontalHeaderItem(4).setText(f"Rispetto a «{main}»" if main else "Rispetto al ramo principale")
        for r, b in enumerate(self.branches):
            relation = "" if b.main else "nessuna versione in comune" if b.unrelated else "" if b.ahead is None else (
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
                    item.setToolTip(f"Il ramo non ha versioni in comune con «{main}»" if b.unrelated else
                                    f"Avanti: {b.ahead} versioni del ramo non sono in «{main}». Indietro: «{main}» ha "
                                    f"{b.behind} versioni che il ramo non ha.")
                self.table.setItem(r, c, item)
        current = next((r for r, b in enumerate(self.branches) if b.current), 0)
        if self.branches:
            self.table.selectRow(current)
        else:
            self.status.setStyleSheet(f"color: {MUTED};")
            self.status.setText("Nessun ramo nel repository: usa «Aggiorna Lista»." if mode == "remote"
                                else "Nessun ramo da mostrare.")
        self._update()

    def selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        return self.branches[min(rows)] if rows else None

    def _update(self):
        b = self.selected()
        self.switch_button.setEnabled(b is not None and not b.current)
        self.checkout_button.setEnabled(b is not None)
        why = self._not_deletable(b)
        self.delete_button.setEnabled(not why)
        self.delete_button.setToolTip(why or "Toglie il ramo da questo PC; quello del repository, se c'è, resta")
        why = "Seleziona un ramo" if b is None else self.project.remote_delete_denied(self.user, b.name)
        self.delete_remote_button.setEnabled(not why)
        self.delete_remote_button.setToolTip(why or "Toglie il ramo dal repository, per tutti; la copia di questo PC, "
                                                    "se c'è, resta")
        denied = self.integrate_denied()
        self.integrate_button.setEnabled(b is not None and not b.current and not denied)
        self.integrate_button.setToolTip(denied or self.integrate_button.toolTip())
        self.new_button.setEnabled(bool(self.project.branches()))

    # --- the repository -------------------------------------------------------------------------------

    def branch_menu(self, row):
        """The menu of the right click on a branch: «Aggiorna questo ramo» (see update_branches)."""
        b = self.branches[row]
        self.table.selectRow(row)
        menu = QMenu(self)
        action = menu.addAction(icon("mdi6.cloud-download-outline"),
                                "Aggiorna questo ramo (ramo in uso)" if b.current else "Aggiorna questo ramo",
                                lambda _=False, name=b.name: self.update_branches([name]))
        action.setEnabled(bool(self.project.remote()) and not self._busy())
        return menu

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.branches):
            return
        self.menu = self.branch_menu(row)
        self.menu.popup(self.table.viewport().mapToGlobal(pos))

    def _busy(self):
        return self.worker is not None and self.worker.isRunning()

    def _set_busy(self, busy):
        has_remote = bool(self.project.remote())
        self.fetch_button.setEnabled(has_remote and not busy)
        self.update_all_button.setEnabled(has_remote and not busy)

    def update_branches(self, names=None):
        """«Aggiorna Tutto» (names None) or «Aggiorna questo ramo»: the branches take the versions of the remote, in a
        thread; then what each received, and the branch in use received if it lacks some (see _updated)."""
        if self._busy():
            return
        self._set_busy(True)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText("Aggiornamento di tutti i rami dal repository…" if names is None else
                            f"Aggiornamento del ramo «{names[0]}» dal repository…" if len(names) == 1 else
                            f"Aggiornamento di {len(names)} rami dal repository…")
        self.worker = UpdateWorker(self.project, self.credentials, names)
        self.worker.done.connect(self._updated)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _updated(self, result):
        from arcadia_tool.ui.receive_choice import branches_report

        self.worker.wait()
        self._set_busy(False)
        report, behind = result
        self.fill()
        current = self.project.current_branch()
        lines = branches_report(report)
        if behind is not None:
            mine = f"• {current} (in uso): " + ("già aggiornato" if not behind else
                                                f"{behind} {'nuova versione' if behind == 1 else 'nuove versioni'} "
                                                "nel repository")
            lines = "\n".join(line for line in (mine, lines) if line)
        count = len(report) + (behind is not None)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText(f"Aggiornamento completato: {count} {'ramo' if count == 1 else 'rami'}.")
        if lines:
            QMessageBox.information(self, "Aggiorna i rami", f"Esito dell'aggiornamento:\n\n{lines}")
        if behind and QMessageBox.question(
                self, "Aggiorna i rami", f"Il ramo in uso «{current}» ha {behind} "
                f"{'nuova versione' if behind == 1 else 'nuove versioni'} nel repository: si ricevono unendole alle "
                "tue, come con «Ricevi dal repository». Riceverle ora? (la finestra dei rami si chiude)") \
                == QMessageBox.Yes:
            self.request = ("receive",)
            self.accept()

    def fetch(self):
        self._set_busy(True)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText("Download dei rami del repository…")
        self.worker = FetchWorker(self.project, self.credentials)
        self.worker.done.connect(self._fetched)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _fetched(self):
        self.worker.wait()
        self._set_busy(False)
        self.status.setText("Lista dei rami aggiornata: il progetto e i rami di questo PC non sono cambiati.")
        self.fill()

    def _failed(self, message):
        self.worker.wait()
        self._set_busy(False)
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

    def _not_deletable(self, b):
        """Why the branch cannot be deleted from this PC, or None."""
        if b is None:
            return "Seleziona un ramo"
        if b.current:
            return "È il ramo in uso: passa prima a un altro ramo"
        if not b.local or self.mode == "remote":
            return "È un ramo del repository: si elimina solo la copia di questo PC"
        return None

    def delete_local(self):
        """The branch off this PC; then, if it is in the repository too and the user may, the question of removing
        it from there as well."""
        b = self.selected()
        if self._not_deletable(b):
            return
        if self._remove_local(b) and b.remote and not self.project.remote_delete_denied(self.user, b.name):
            self._remove_remote(b, also=True)
        self.fill()
        self._update()

    def delete_remote(self):
        """The branch off the repository; then, if this PC has it too, the question of removing it from here as well."""
        b = self.selected()
        if b is None or self.project.remote_delete_denied(self.user, b.name):
            return
        if self._remove_remote(b) and b.local and not b.current:
            self._remove_local(b, also=True)
        self.fill()

    @staticmethod
    def _versions(count):
        return f"{count} {'versione' if count == 1 else 'versioni'}"

    def _remove_local(self, b, also=False):
        """Asks, then deletes the branch of this PC. also: asked after removing it from the repository. True if done."""
        only_here = self.project.versions_only_on_local_branch(b.name)
        lost = (f"\n\nAttenzione: {self._versions(len(only_here))} di questo ramo non sono né su altri rami né nel "
                "repository e andranno perse." if only_here else "")
        if also:
            text = f"Il ramo «{b.name}» è stato eliminato dal repository. Eliminare anche la copia di questo PC?{lost}"
        else:
            where = ("Il ramo resta nel repository: potrai riaverlo su questo PC passando a quel ramo." if b.remote
                     else "Non è nel repository: su questo PC non resterà nessuna sua copia.")
            text = f"Eliminare il ramo «{b.name}» da questo PC?\n\n{where}{lost}"
        if QMessageBox.question(self, "Elimina ramo locale", text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return False
        try:
            self.project.delete_local_branch(b.name)
        except Exception as exc:
            QMessageBox.warning(self, "Elimina ramo locale", str(exc))
            return False
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText(f"Ramo «{b.name}» eliminato da questo PC" + (" e dal repository." if also else "."))
        return True

    def _remove_remote(self, b, also=False):
        """Asks, then removes the branch from the repository. also: asked after deleting it from this PC. True if
        done."""
        from arcadia_tool.ui.busy import run_busy

        only_there = self.project.versions_only_on_remote_branch(b.name)
        lost = (f"\n\nAttenzione: {self._versions(len(only_there))} di questo ramo non sono su nessun altro ramo, né "
                "qui né nel repository: nessuno le avrà più." if only_there else "")
        if also:
            text = (f"Il ramo «{b.name}» è stato eliminato da questo PC. Eliminarlo anche dal repository?\n\n"
                    f"Sparisce per tutto il team.{lost}")
        else:
            here = ("La copia di questo PC resta: potrai inviarla di nuovo." if b.local else
                    "Su questo PC non c'è una copia del ramo.")
            text = f"Eliminare il ramo «{b.name}» dal repository?\n\nSparisce per tutto il team. {here}{lost}"
        if QMessageBox.question(self, "Elimina ramo remoto", text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return False
        try:
            run_busy(self, f"Eliminazione di «{b.name}» dal repository…",
                     lambda _report: self.project.delete_remote_branch(b.name, self.user, **self.credentials))
        except Exception as exc:
            QMessageBox.warning(self, "Elimina ramo remoto", f"Il ramo non è stato eliminato: {exc}")
            return False
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText(f"Ramo «{b.name}» eliminato dal repository" + (" e da questo PC." if also else "."))
        return True

    def integrate_denied(self):
        """Why the user may not integrate into the branch in use, or None: the main branch only by the Design
        Authority (its members), once it has members."""
        return self.project.main_denied(self.user)

    def integrate(self):
        b = self.selected()
        if b is None or b.current or self.integrate_denied():
            return
        self.request = ("integrate", b.name, self._head(b) or b.head)
        self.accept()

    def checkout(self):
        b = self.selected()
        if b is None:
            return
        dialog = CheckoutDialog(self.project, self._key(b), self)
        if dialog.exec():
            denied = dialog.move_branch and self.project.main_denied(self.user, dialog.name_value)
            if denied:  # the main branch brought back to a version: a change only the DA makes
                QMessageBox.warning(self, "Checkout", denied)
                return
            self.request = ("checkout", dialog.name_value, dialog.sha, dialog.move_branch)
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
        options = {"parent": self, "integrating": True, "user": self.user}
        if what == "working":
            dialog = CompareDialog(self.project, before=self._head(b), after=WORKING, before_branch=self._key(b),
                                   **options)
        else:
            main = self.project.main_branch()
            main_branch = next(x for x in self.project.branches() if x.name == main)
            main_head = main_branch.head
            dialog = CompareDialog(self.project, before=main_head, after=self._head(b), before_branch=main,
                                   after_branch=self._key(b), since_common=True, **options)
        dialog.exec()
        if dialog.request is not None:  # «Integra…»: from the main window
            self.request = dialog.request
            self.accept()

    def done(self, result):
        """Closed (X, Esc, «Chiudi»), also while downloading the branches: the download ends by itself."""
        if self.worker is not None and self.worker.isRunning():
            finish_in_background(self.worker)
        super().done(result)
