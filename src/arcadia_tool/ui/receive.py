"""Versioni › Ricevi dal repository: the versions published by the others on the working branch, merged with
those of this PC (see storage.merge). What both changed in different ways is chosen here, row by row."""
import re

import yaml
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from arcadia_tool.accounts import git_host
from arcadia_tool.model.element import Model
from arcadia_tool.model.schema import KINDS_BY_NAME
from arcadia_tool.model.serialization import loads
from arcadia_tool.storage.merge import OURS, THEIRS
from arcadia_tool.storage.project import Receive
from arcadia_tool.ui.theme import MUTED, icon

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CHOICES = ((None, "— scegli —"), (OURS, "Mantieni quella di questo PC"), (THEIRS, "Usa quella ricevuta"))
SETTINGS_LABELS = {"project.yaml": "Impostazioni del progetto", "checks.yaml": "Impostazioni delle verifiche"}
VALUE_LENGTH = 160


class ReceiveWorker(QThread):
    done = Signal(object)  # the Receive
    failed = Signal(str)

    def __init__(self, project, credentials):
        super().__init__()
        self.project, self.credentials = project, credentials

    def run(self):
        try:
            self.done.emit(self.project.prepare_receive(**self.credentials))
        except Exception as exc:
            self.failed.emit(f"Ricezione non riuscita: {exc or exc.__class__.__name__}")


class ReceiveDialog(QDialog):
    """applied: the versions were received (the project must be opened again); merged: a version of integration
    was recorded (to send); publish_first: the user asked to publish the changes of this PC first."""

    def __init__(self, project, credentials, author=None, parent=None):
        super().__init__(parent)
        self.project, self.credentials, self.author = project, credentials, author
        self.receive, self.worker, self._lookup = None, None, None
        self.applied = self.merged = self.publish_first = False
        self.result = None
        self.setWindowTitle("Ricevi dal repository")
        self.resize(980, 380)
        url, branch = project.remote(), project.push_branch()
        title = QLabel(f"Ricezione dal ramo «{branch}» di {git_host(url) or url}", objectName="cardTitle")
        self.status = QLabel("Connessione al repository…", objectName="muted")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.versions = QLabel(objectName="muted")
        self.versions.setWordWrap(True)
        self.versions.setTextFormat(Qt.RichText)
        self.conflicts = QTableWidget(0, 4)
        self.conflicts.setHorizontalHeaderLabels(["Scheda e campo", "Su questo PC", "Ricevuto", "Scelta"])
        header = self.conflicts.horizontalHeader()
        for column, mode in enumerate((QHeaderView.Interactive, QHeaderView.Stretch, QHeaderView.Stretch,
                                       QHeaderView.Fixed)):
            header.setSectionResizeMode(column, mode)
        header.resizeSection(0, 260)
        header.resizeSection(3, 270)  # the choice (a list in the cell)
        self.conflicts.verticalHeader().setVisible(False)
        self.conflicts.setWordWrap(True)
        self.conflicts.setVisible(False)
        self.all_ours = QPushButton("Tutte quelle di questo PC")
        self.all_ours.clicked.connect(lambda: self._choose_all(OURS))
        self.all_theirs = QPushButton("Tutte quelle ricevute")
        self.all_theirs.clicked.connect(lambda: self._choose_all(THEIRS))
        self.retry = QPushButton(icon("mdi6.refresh"), "Riprova")
        self.retry.clicked.connect(self.start)
        self.publish_button = QPushButton(icon("mdi6.cloud-upload-outline"), "Pubblica le modifiche…")
        self.publish_button.clicked.connect(self._publish_first)
        self.apply_button = QPushButton(icon("mdi6.cloud-download-outline", "white"), "Ricevi")
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.apply)
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.all_ours)
        buttons.addWidget(self.all_theirs)
        buttons.addStretch()
        for b in (self.retry, self.publish_button, self.close_button, self.apply_button):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        for w in (title, self.bar, self.status, self.versions):
            layout.addWidget(w)
        layout.addWidget(self.conflicts, 1)
        layout.addLayout(buttons)
        self._buttons()

    def exec(self):
        self.start()
        return super().exec()

    def start(self):
        self._buttons()
        self.bar.setVisible(True)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText("Download delle versioni del ramo…")
        self.worker = ReceiveWorker(self.project, self.credentials)
        self.worker.done.connect(self.show_receive)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _buttons(self, apply=False, conflicts=False, retry=False, publish=False):
        self.apply_button.setVisible(apply)
        self.all_ours.setVisible(conflicts)
        self.all_theirs.setVisible(conflicts)
        self.retry.setVisible(retry)
        self.publish_button.setVisible(publish)

    def _failed(self, message):
        if self.worker is not None:
            self.worker.wait()
        self.bar.setVisible(False)
        self.status.setStyleSheet("color: #B42318;")
        self.status.setText(message)
        self._buttons(retry=True)

    # --- what is received -------------------------------------------------------------------------

    def show_receive(self, receive):
        if self.worker is not None:
            self.worker.wait()
        self.receive = receive
        self.bar.setVisible(False)
        branch = receive.branch
        if receive.state == Receive.UP_TO_DATE:
            self.status.setText(f"Nessuna nuova versione sul ramo «{branch}»: il progetto è aggiornato.")
            return
        if receive.state == Receive.NO_BRANCH:
            self.status.setText(f"Il ramo «{branch}» non è ancora nel repository: inviando le tue versioni viene "
                                "creato.")
            return
        count = len(receive.incoming)
        self.versions.setText(f"<b>{count} {'versione ricevuta' if count == 1 else 'versioni ricevute'}</b>: " +
                              "; ".join(f"{v.title} ({v.author.split('<')[0].strip()}, {v.timestamp:%d/%m %H:%M})"
                                        for v in receive.incoming[:8]) + ("…" if count > 8 else ""))
        if receive.state == Receive.PUBLISH_FIRST:
            self.status.setText("Sia tu sia i colleghi avete pubblicato nuove versioni, e qui ci sono modifiche "
                                "non ancora pubblicate. Pubblicale prima: poi le versioni vengono integrate in una "
                                "nuova versione.")
            self._buttons(publish=True)
            return
        result = receive.result
        what = (f"Le versioni ricevute e le tue ({len(self.project.unsent_versions())} non ancora inviate) vengono "
                "integrate in una nuova versione, da inviare poi al repository." if receive.state == Receive.MERGE
                else "Il progetto viene aggiornato con le versioni ricevute; le modifiche non ancora pubblicate "
                     "restano da pubblicare.")
        if result.conflicts:
            what += (f"\n\n{len(result.conflicts)} modifiche sono state fatte in modo diverso qui e nelle versioni "
                     "ricevute: scegli quale tenere per ciascuna.")
        else:
            merged = f", {len(result.merged)} schede integrate campo per campo" if result.merged else ""
            what += f"\n\n{len(result.received)} file ricevuti{merged}, nessun conflitto."
        self.status.setText(what)
        self._fill_conflicts(result.conflicts)
        self._buttons(apply=True, conflicts=bool(result.conflicts))
        self._update_apply()

    def _fill_conflicts(self, conflicts):
        self.conflicts.setRowCount(len(conflicts))
        self.conflicts.setVisible(bool(conflicts))
        if conflicts:
            self.resize(self.width(), 620)
        for row, c in enumerate(conflicts):
            where = QTableWidgetItem(self._where(c))
            where.setData(Qt.UserRole, c.key)
            self.conflicts.setItem(row, 0, where)
            for column, value in ((1, c.ours), (2, c.theirs)):
                text = self._value(c, value)
                item = QTableWidgetItem(text if len(text) <= VALUE_LENGTH else text[:VALUE_LENGTH] + "…")
                item.setToolTip(text)
                self.conflicts.setItem(row, column, item)
            choice = QComboBox()
            choice.setMinimumWidth(250)
            for data, label in CHOICES:
                choice.addItem(label, data)
            choice.currentIndexChanged.connect(self._update_apply)
            self.conflicts.setCellWidget(row, 3, choice)
        self.conflicts.resizeRowsToContents()

    def _element(self, conflict):
        data = self.receive.ours.get(conflict.path) or self.receive.theirs_files.get(conflict.path)
        try:
            return loads(data.decode("utf-8")) if data else None
        except Exception:
            return None

    def _where(self, conflict):
        if conflict.uuid is None:
            name = SETTINGS_LABELS.get(conflict.path, conflict.path)
            return f"{name}: {conflict.field}" if conflict.field else name
        element = self._element(conflict)
        if element is None:
            return conflict.path
        schema = KINDS_BY_NAME[element.kind]
        label = " · ".join(str(v) for v in (element.get("id"), element.get("name") or element.get("title")) if v)
        sheet = f"{schema.label} {label}".strip()
        if conflict.field is None:
            return f"{sheet}: eliminata da una parte, modificata dall'altra"
        f = schema.field(conflict.field)
        return f"{sheet} › {f.label if f is not None else conflict.field}"

    def _label(self, uuid):
        if self._lookup is None:
            elements = []
            for files in (self.receive.theirs_files, self.receive.ours):
                for path, data in files.items():
                    if path.startswith("model/") and path.endswith(".yaml"):
                        elements.append(loads(data.decode("utf-8")))
            self._lookup = Model(elements)
        element = self._lookup.get(uuid)
        return self._lookup.label(element) if element is not None else uuid

    def _value(self, conflict, value):
        if conflict.field is None:  # the whole file: there, or deleted
            return "(eliminata)" if value is None else "(presente, modificata)"
        if value is None:
            return "(vuoto)"
        if isinstance(value, str) and UUID.match(value):
            return self._label(value)
        if isinstance(value, list) and all(isinstance(v, str) and UUID.match(v) for v in value):
            return ", ".join(self._label(v) for v in value)
        if isinstance(value, (list, dict)):
            return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=200).strip()
        return str(value)

    # --- choices and receiving ---------------------------------------------------------------------

    def choices(self):
        result = {}
        for row in range(self.conflicts.rowCount()):
            choice = self.conflicts.cellWidget(row, 3).currentData()
            if choice:
                result[self.conflicts.item(row, 0).data(Qt.UserRole)] = choice
        return result

    def _choose_all(self, choice):
        for row in range(self.conflicts.rowCount()):
            combo = self.conflicts.cellWidget(row, 3)
            combo.setCurrentIndex(combo.findData(choice))

    def _update_apply(self, *_args):
        missing = self.conflicts.rowCount() - len(self.choices())
        self.apply_button.setEnabled(missing == 0)
        self.apply_button.setToolTip(f"Scegli ancora {missing} modifiche" if missing else "")

    def apply(self):
        if self.receive is None:
            return
        self.result = self.project.apply_receive(self.receive, self.choices(), self.author)
        if self.result.resolved:
            self.applied = True
            self.merged = self.receive.state == Receive.MERGE
            self.accept()

    def _publish_first(self):
        self.publish_first = True
        self.accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return  # not while downloading: the window closes when the server has answered
        super().reject()
