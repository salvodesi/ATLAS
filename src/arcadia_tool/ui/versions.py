"""Publishing, history and on-demand comparison of model versions.

The diff is computed only here: when the user publishes (to review what is being published)
or explicitly asks to compare two states of the model.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from arcadia_tool.checks import ERROR, WARNING, count, problems
from arcadia_tool.diff.semantic import diff_models
from arcadia_tool.model.element import Model
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


class PublishDialog(QDialog):
    """user: the logged-in account, author of the version (not editable here)."""

    def __init__(self, project, parent=None, user=None):
        super().__init__(parent)
        self.project, self.sha = project, None
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
        info_layout.addLayout(form)
        self.send_only = False  # accepted only to send versions already recorded
        remote = project.remote()
        unsent = len(project.unsent_versions()) if remote else 0
        where = (f"e inviata al ramo «{project.push_branch()}» del repository {remote}" if remote else
                 "su questo PC (nessun repository remoto: impostalo in Progetto › Impostazioni › Repository Git)")
        note = QLabel(f"La versione viene registrata nella cronologia del progetto {where}. Le modifiche non ancora "
                      "salvate vengono salvate prima della pubblicazione.", objectName="muted")
        note.setWordWrap(True)
        info_layout.addWidget(note)
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

    def _publish(self):
        message = self.message.toPlainText().strip()
        name, email = self.author_name.text().strip(), self.author_email.text().strip()
        if not message:
            QMessageBox.warning(self, "Pubblica versione", "Scrivi una descrizione della versione.")
            return
        if not name or "@" not in email:
            QMessageBox.warning(self, "Pubblica versione", "Indica nome ed e-mail dell'autore.")
            return
        s = settings()
        s.setValue("author/name", name)
        s.setValue("author/email", email)
        try:
            self.sha = self.project.publish(message, f"{name} <{email}>")
        except NothingToSave:
            QMessageBox.information(self, "Pubblica versione", "Non ci sono modifiche da pubblicare.")
            return
        self.accept()


class CompareDialog(QDialog):
    """Manual comparison between two states chosen by the user."""

    def __init__(self, project, before=None, after=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Confronta versioni")
        self.resize(1240, 760)
        self.versions = project.versions()
        self.before, self.after = QComboBox(), QComboBox()
        for combo in (self.before, self.after):
            combo.addItem(icon("mdi6.pencil-outline"), WORKING_LABEL, WORKING)
            for v in self.versions:
                combo.addItem(icon("mdi6.history"), version_label(v), v.sha)
            combo.setMinimumWidth(360)
        self._select(self.before, before or (self.versions[0].sha if self.versions else WORKING))
        self._select(self.after, after or WORKING)
        swap = QPushButton(icon("mdi6.swap-horizontal"), "")
        swap.setToolTip("Inverti")
        swap.clicked.connect(self._swap)
        compare = primary(QPushButton(icon("mdi6.compare-horizontal", "white"), "Confronta"))
        compare.clicked.connect(self.compare)

        bar, bar_layout = card()
        row = QHBoxLayout()
        row.addWidget(QLabel("Da", objectName="formLabel"))
        row.addWidget(self.before)
        row.addWidget(swap)
        row.addWidget(QLabel("A", objectName="formLabel"))
        row.addWidget(self.after)
        row.addStretch()
        row.addWidget(compare)
        bar_layout.addLayout(row)

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

    def _swap(self):
        b, a = self.before.currentData(), self.after.currentData()
        self._select(self.before, a)
        self._select(self.after, b)

    def _clear_result(self):
        while self.result_layout.count():
            widget = self.result_layout.takeAt(0).widget()
            if widget:
                widget.setParent(None)

    def _placeholder(self):
        self._clear_result()
        hint = QLabel("Scegli i due stati del modello e premi «Confronta».", alignment=Qt.AlignCenter,
                      objectName="muted")
        self.result_layout.addWidget(hint, 1)

    def _model(self, state):
        if state == WORKING:
            return self.project.model
        return self.project.published_model(state) if state else Model()

    def compare(self):
        before, after = self.before.currentData(), self.after.currentData()
        if before == after:
            QMessageBox.information(self, "Confronta versioni", "Scegli due stati diversi.")
            return
        diff = diff_models(self._model(before), self._model(after))
        self._clear_result()
        self.result_layout.addWidget(DiffView(diff, self.before.currentText(), self.after.currentText()), 1)


class VersionDialog(QDialog):
    """A published version: date, author, description, where it is (sent to the repository or only on this PC)
    and every model element it added, changed or deleted with respect to the version before (the first one:
    all of its elements)."""

    def __init__(self, project, versions, row, remote, unsent, parent=None):
        super().__init__(parent)
        version = versions[row]
        previous = versions[row + 1] if row + 1 < len(versions) else None
        self.setWindowTitle(f"Versione {version.short} · {version.title}")
        self.resize(1240, 780)
        self.diff = diff_models(project.published_model(previous.sha) if previous else Model(),
                                project.published_model(version.sha))
        if not remote:
            where = "Solo su questo PC (nessun repository remoto configurato)"
        elif version.sha in unsent:
            where = f"Solo su questo PC: non ancora inviata al repository {remote}"
        else:
            where = f"Inviata al ramo «{project.push_branch()}» del repository {remote}"
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
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Cronologia delle pubblicazioni")
        self.resize(960, 560)
        self.versions = project.versions()
        remote = project.remote()
        unsent = {v.sha for v in project.unsent_versions()} if remote else set()
        self.table = QTableWidget(len(self.versions), len(HISTORY_COLUMNS))
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
        for r, v in enumerate(self.versions):
            name, _, email = v.author.partition(" <")
            state = ("solo su questo PC" if v.sha in unsent else "inviata") if remote else "solo su questo PC"
            values = (f"{v.timestamp:%d/%m/%Y %H:%M}", name, v.title, state, v.short)
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(v.message if c != 1 else v.author)
                if c == 3:
                    item.setForeground(QColor("#166534" if text == "inviata" else MUTED))
                if c == 4:
                    item.setFont(QFont("Consolas", 9))
                self.table.setItem(r, c, item)
        self.table.doubleClicked.connect(lambda index: self.show_version(index.row()))
        self.unsent, self.remote = unsent, remote

        previous = QPushButton(icon("mdi6.compare-horizontal"), "Confronta con la precedente")
        current = QPushButton(icon("mdi6.pencil-outline"), "Confronta con lo stato attuale")
        two = QPushButton(icon("mdi6.select-compare"), "Confronta le due selezionate")
        previous.clicked.connect(self.compare_previous)
        current.clicked.connect(self.compare_current)
        two.clicked.connect(self.compare_two)
        close = QPushButton("Chiudi")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (previous, current, two):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(close)

        body, body_layout = card()
        if self.versions:
            body_layout.addWidget(self.table, 1)
        else:
            body_layout.addWidget(QLabel("Nessuna versione pubblicata.", alignment=Qt.AlignCenter,
                                         objectName="muted"), 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(body, 1)
        layout.addLayout(buttons)

    def _rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _open(self, before, after):
        CompareDialog(self.project, before, after, self).exec()

    def show_version(self, row):
        """Double click: what the version contains and where it is (sent to the repository or not)."""
        if 0 <= row < len(self.versions):
            VersionDialog(self.project, self.versions, row, self.remote, self.unsent, self).exec()

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
