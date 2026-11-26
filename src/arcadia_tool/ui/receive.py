"""Versioni › Ricevi dal repository: the versions published by the others on the working branch, merged with
those of this PC (see storage.merge). What both changed in different ways is chosen here, row by row."""
import re
from html import escape

import yaml
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from arcadia_tool.accounts import git_host
from arcadia_tool.model.element import Model
from arcadia_tool.diff.semantic import ADDED, CHANGE_LABELS, MODIFIED, REMOVED, word_diff
from arcadia_tool.model.schema import KINDS_BY_NAME
from arcadia_tool.model.serialization import loads
from arcadia_tool.storage.merge import OURS, THEIRS
from arcadia_tool.storage.project import Receive
from arcadia_tool.ui.theme import CHANGE_BG, CHANGE_COLORS, MUTED, icon, kind_icon

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# The quick choices of a selective integration: (label, the kinds, or the group of the schema).
SELECTIVE_GROUPS = (("ADR", ("adr",), None), ("CQ", ("clarification",), None), ("SA-1", ("domain",), None),
                    ("SA-2", ("system_function",), None), ("SA-3", ("trace_record",), None),
                    ("SA-4", ("derived_requirement",), None), ("Altre schede SA", (), "System Analysis"),
                    ("LA", (), "Logical Architecture"), ("Team", ("team",), None))
CHOICES = ((None, "— scegli —"), (OURS, "Mantieni quella di questo PC"), (THEIRS, "Usa quella ricevuta"))
SETTINGS_LABELS = {"project.yaml": "Impostazioni del progetto", "checks.yaml": "Impostazioni delle verifiche"}
VALUE_LENGTH = 160


class ReceiveWorker(QThread):
    done = Signal(object)  # the Receive
    failed = Signal(str)

    def __init__(self, project, credentials, prepare=None):
        super().__init__()
        self.project, self.credentials, self.prepare = project, credentials, prepare

    def run(self):
        try:
            self.done.emit(self.prepare() if self.prepare else self.project.prepare_receive(**self.credentials))
        except Exception as exc:
            self.failed.emit(f"Operazione non riuscita: {exc or exc.__class__.__name__}")


def highlighted(ops, wanted, colour, background):
    """The text of one side of a word diff (see semantic.word_diff), as HTML, with what only it has marked."""
    html = ""
    for op, text in ops:
        if op == "=" or op == wanted:
            piece = escape(text).replace("\n", "<br>")
            html += (f"<span style='color:{colour}; background:{background}; font-weight:600'>{piece}</span>"
                     if op == wanted else piece)
    return html


class ConflictDetail(QWidget):
    """The conflict selected: the two values whole, side by side, with the differences marked word by word."""

    def __init__(self):
        super().__init__()
        self.ours, self.theirs = QTextBrowser(), QTextBrowser()
        self.ours_title, self.theirs_title = (QLabel(t, objectName="formLabel") for t in ("Su questo PC", "Ricevuto"))
        grid = QHBoxLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        for title, browser in ((self.ours_title, self.ours), (self.theirs_title, self.theirs)):
            browser.setMinimumHeight(90)
            column = QVBoxLayout()
            column.addWidget(title)
            column.addWidget(browser, 1)
            grid.addLayout(column, 1)

    def show_values(self, ours, theirs, local=False):
        """ours, theirs: the two values, as text."""
        ops = word_diff(ours, theirs)
        self.ours_title.setText("La tua modifica non pubblicata" if local else "Su questo PC")
        self.ours.setHtml(highlighted(ops, "-", CHANGE_COLORS[REMOVED], CHANGE_BG[REMOVED]))
        self.theirs.setHtml(highlighted(ops, "+", CHANGE_COLORS[ADDED], CHANGE_BG[ADDED]))


class DestinationView(QWidget):
    """The right side of a selective integration: the model of the branch of destination as it will be with the
    elements ticked on the left: those arriving, changing and going away are marked; the rest as it is."""
    ROLE = Qt.UserRole

    def __init__(self, selection, into):
        super().__init__()
        self.here = selection.here
        self.title = QLabel(f"<b>Destinazione: «{into}» dopo l'integrazione</b>")
        self.summary = QLabel(objectName="muted")
        self.search = QLineEdit(placeholderText="Filtra per ID o nome", objectName="search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._filter())
        self.only_changes = QCheckBox("Solo ciò che cambia")
        self.only_changes.toggled.connect(lambda _on: self._filter())
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.only_changes)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Elemento", "Con l'integrazione"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        layout.addLayout(filters)
        layout.addWidget(self.tree, 1)
        self.changes = {c.uuid: c for c in selection.diff.changes}
        self.rows, self.groups = {}, {}
        self.chosen = set()
        self.renumbered = {}  # uuid of a row showing another number → how it read before
        self.arriving = set()  # the rows of the elements not in the branch of destination (id of the row)
        for kind in KINDS_BY_NAME:
            arriving = [c for c in selection.diff.changes if c.kind == kind and c.change == ADDED]
            present = self.here.of_kind(kind)
            if not arriving and not present:
                continue
            group = QTreeWidgetItem(self.tree, [KINDS_BY_NAME[kind].plural, ""])
            group.setIcon(0, kind_icon(kind))
            self.groups[kind] = group
            for e in present:
                self.rows[e.uuid] = QTreeWidgetItem(group, [self.here.label(e), ""])
            for c in arriving:
                self.rows[c.uuid] = QTreeWidgetItem(group, [c.label, ""])
                self.arriving.add(id(self.rows[c.uuid]))
        self.show_chosen(set())

    def show_chosen(self, chosen):
        """The ticks on the left changed: what they do here. Only the rows of the changes: the model can be large."""
        added = set(chosen) - self.chosen
        self.chosen = set(chosen)
        for uuid, change in self.changes.items():
            row, on = self.rows[uuid], uuid in self.chosen
            font = row.font(0)
            font.setStrikeOut(on and change.change == REMOVED)
            font.setBold(on)
            for column in (0, 1):
                row.setFont(column, font)
                row.setForeground(column, QBrush(QColor(CHANGE_COLORS[change.change])) if on else QBrush())
                row.setBackground(column, QBrush(QColor(CHANGE_BG[change.change])) if on else QBrush())
            row.setText(1, ("In arrivo" if change.change == ADDED else CHANGE_LABELS[change.change]) if on else "")
        for uuid in self.chosen:
            self.groups[self.changes[uuid].kind].setExpanded(True)
        count = {k: sum(1 for u in self.chosen if self.changes[u].change == k) for k in (ADDED, MODIFIED, REMOVED)}
        self.summary.setText(f"{count[ADDED]} in arrivo · {count[MODIFIED]} modificati · {count[REMOVED]} rimossi")
        self._filter()
        if added:
            self.tree.scrollToItem(self.rows[sorted(added)[0]])

    def show_numbers(self, renumbered, branch):
        """The final numbers. renumbered: (uuid, old, new) as computed by the integration; branch: where the elements
        arriving come from."""
        for uuid, text in self.renumbered.items():
            self.rows[uuid].setText(0, text)
        self.renumbered = {}
        for uuid, old, new in renumbered:
            row = self.rows.get(uuid)
            if row is None:
                continue
            text = row.text(0)
            self.renumbered[uuid] = text
            where = f" in {branch}" if id(row) in self.arriving else ""
            row.setText(0, f"{new}{text[len(old):] if text.startswith(old) else ' ' + text} (era {old}{where})")
        self._filter()

    def _filter(self):
        text = self.search.text().strip().lower()
        only = self.only_changes.isChecked()
        for group in self.groups.values():
            visible = 0
            for i in range(group.childCount()):
                row = group.child(i)
                on = bool(row.text(1))
                waiting = not on and id(row) in self.arriving  # not in the destination unless ticked
                hidden = waiting or (only and not on) or (bool(text) and text not in row.text(0).lower())
                row.setHidden(hidden)
                visible += not hidden
            group.setHidden(not visible)
            group.setText(1, str(visible))


class ReceiveDialog(QDialog):
    """applied: the versions were received (the project must be opened again); merged: a version of integration
    was recorded (to send); publish_first: the user asked to publish the changes of this PC first.
    integrate: (branch, version): Rami › Integra, the branch integrated into the one in use (same merge)."""

    def __init__(self, project, credentials, author=None, parent=None, integrate=None, user=None, keep_local=False):
        super().__init__(parent)
        self.keep_local = keep_local  # Ricevi: the changes not published stay, on top of what is received
        self.project, self.credentials, self.author, self.user = project, credentials, author, user
        self.integrate = integrate
        self.moved_to = None  # «Sposta su un nuovo ramo»: the branch the versions of this PC went to
        self.receive, self.worker, self._lookup = None, None, None
        self.applied = self.merged = self.publish_first = False
        self.result = None
        self.setWindowTitle("Integra ramo" if integrate else
                            f"Ricevi dal repository · ramo in uso «{project.current_branch()}»")
        self.resize(980, 380)
        url, branch = project.remote(), project.push_branch()
        title = QLabel(f"Integrazione del ramo «{integrate[0]}» nel ramo in uso «{project.current_branch()}»"
                       if integrate else f"Ricezione dal ramo «{branch}» di {git_host(url) or url}",
                       objectName="cardTitle")
        self.status = QLabel("Preparazione dell'integrazione…" if integrate else "Connessione al repository…",
                             objectName="muted")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.versions = QLabel(objectName="formLabel")  # «N versioni ricevute», over their list
        self.versions.setVisible(False)
        self.version_list = QTreeWidget(objectName="receivedVersions")
        self.version_list.setHeaderLabels(["Versione", "Autore", "Data"])
        self.version_list.setRootIsDecorated(False)
        self.version_list.setAlternatingRowColors(True)
        self.version_list.setMaximumHeight(160)
        self.version_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2):
            self.version_list.header().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.version_list.header().setStretchLastSection(False)
        self.version_list.setVisible(False)
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
        self.conflicts.setSelectionBehavior(QTableWidget.SelectRows)
        self.conflicts.setSelectionMode(QTableWidget.SingleSelection)
        self.conflicts.currentCellChanged.connect(lambda row, *_: self._show_conflict(row))
        self.conflict_list = []  # the conflicts of the rows of the table
        self.conflict_detail = ConflictDetail()
        self.conflict_detail.setVisible(False)
        self.conflict_area = QSplitter(Qt.Vertical)
        self.conflict_area.addWidget(self.conflicts)
        self.conflict_area.addWidget(self.conflict_detail)
        self.conflict_area.setSizes([170, 170])
        self.all_ours = QPushButton("Tutte quelle di questo PC")
        self.all_ours.clicked.connect(lambda: self._choose_all(OURS))
        self.all_theirs = QPushButton("Tutte quelle ricevute")
        self.all_theirs.clicked.connect(lambda: self._choose_all(THEIRS))
        self.retry = QPushButton(icon("mdi6.refresh"), "Riprova")
        self.retry.clicked.connect(self.start)
        self.publish_button = QPushButton(icon("mdi6.cloud-upload-outline"), "Pubblica le modifiche…")
        self.publish_button.clicked.connect(self._publish_first)
        self.keep_button = QPushButton(icon("mdi6.source-merge", "white"), "Integra mantenendo le modifiche locali")
        self.keep_button.setProperty("primary", True)
        self.keep_button.setToolTip("Integra, in modo completo o selettivo: le modifiche non pubblicate restano sopra "
                                    "l'integrazione, ancora da pubblicare")
        self.keep_button.clicked.connect(self._integrate_keeping)
        self.move_button = QPushButton(icon("mdi6.source-branch-plus"), "Sposta le mie versioni su un nuovo ramo…")
        self.move_button.setToolTip("Le tue versioni non inviate passano a un nuovo ramo, da inviare; il ramo "
                                    "principale torna come sul repository. La DA integrerà poi il tuo ramo.")
        self.move_button.clicked.connect(self._move_to_branch)
        self.apply_button = QPushButton(icon("mdi6.cloud-download-outline", "white"), "Ricevi")
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.apply)
        self.close_button = QPushButton("Chiudi")
        self.close_button.clicked.connect(self.reject)
        # Integra: the message of the version recorded (the title, a description if wanted), proposed by ATLAS.
        self.message = QLineEdit()
        self.message.setToolTip("Il titolo della versione di integrazione, come appare in «Versioni Modello» e nel "
                                "repository. ATLAS aggiunge in fondo l'elenco di ciò che è integrato.")
        self.message.textEdited.connect(lambda _t: setattr(self, "_message_edited", True))  # typed: it stays
        self.description = QPlainTextEdit(placeholderText="Descrizione (facoltativa)")
        self.description.setMaximumHeight(56)
        self._message_edited = False
        self.message_row = QWidget()
        message_layout = QGridLayout(self.message_row)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.addWidget(QLabel("Messaggio della versione:", objectName="formLabel"), 0, 0)
        message_layout.addWidget(self.message, 0, 1)
        message_layout.addWidget(self.description, 1, 1)
        reset = QPushButton(icon("mdi6.restore"), "")
        reset.setToolTip("Torna al messaggio proposto da ATLAS")
        reset.clicked.connect(lambda _=False: self._reset_message())
        message_layout.addWidget(reset, 0, 2)
        self.message_row.setVisible(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.all_ours)
        buttons.addWidget(self.all_theirs)
        buttons.addStretch()
        for b in (self.retry, self.publish_button, self.move_button, self.close_button, self.keep_button,
                  self.apply_button):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        for w in (title, self.bar, self.status, self.versions, self.version_list):
            layout.addWidget(w)
        # Integra: the preview of the result (the branch in use → after the merge, as in «Pubblica»), over the
        # conflicts left to the user; it follows the choices.
        self.preview = self.preview_view = self.preview_shown = self.destination = None
        self._preview_timer = QTimer(self, singleShot=True, interval=300)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.conflicts_title = QLabel(objectName="formLabel")
        self.conflicts_title.setVisible(False)
        self.selection = None  # selective integration (see storage.selective)
        self._selective_timer = QTimer(self, singleShot=True, interval=250)
        self._selective_timer.timeout.connect(self._selective_update)
        self.full_mode = QRadioButton("Integrazione completa")
        self.full_mode.setChecked(True)
        self.selective_mode = QRadioButton("Integrazione selettiva: solo gli elementi scelti")
        self.selective_mode.setToolTip("Prende dall'altro ramo solo gli elementi spuntati, con quelli a cui sono legati; "
                                       "il resto del ramo potrà essere integrato in seguito")
        self.selective_mode.toggled.connect(lambda _on: self._mode_changed())
        self.mode_row = QWidget()
        mode_layout = QHBoxLayout(self.mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(self.full_mode)
        mode_layout.addWidget(self.selective_mode)
        mode_layout.addStretch()
        self.mode_row.setVisible(False)
        self.groups_row = QWidget()
        self.groups_layout = QHBoxLayout(self.groups_row)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_row.setVisible(False)
        if integrate or keep_local:
            from arcadia_tool.ui.versions import maximizable
            maximizable(self)
            self.resize(1240, 800)
            if integrate:
                self.apply_button.setText("Integra")
                self.apply_button.setIcon(icon("mdi6.source-merge", "white"))
                self.close_button.setText("Annulla integrazione")
                self.close_button.setToolTip("Chiude senza integrare: il progetto non cambia")
            self.preview = QWidget()
            self.preview.setLayout(QVBoxLayout())
            self.preview.layout().setContentsMargins(0, 0, 0, 0)
            self.preview.setVisible(False)
            lower = QWidget()
            lower_layout = QVBoxLayout(lower)
            lower_layout.setContentsMargins(0, 0, 0, 0)
            lower_layout.addWidget(self.conflicts_title)
            lower_layout.addWidget(self.conflict_area, 1)
            splitter = QSplitter(Qt.Vertical)
            splitter.addWidget(self.preview)
            splitter.addWidget(lower)
            splitter.setSizes([520, 220])
            layout.addWidget(self.mode_row)
            layout.addWidget(self.groups_row)
            layout.addWidget(splitter, 1)
        else:
            layout.addWidget(self.conflict_area, 1)
        layout.addWidget(self.message_row)
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
        prepare = ((lambda: self.project.prepare_integration(*self.integrate, keep_local=self.keep_local))
                   if self.integrate else
                   (lambda: self.project.prepare_receive(keep_local=True, **self.credentials)) if self.keep_local else
                   None)
        self.worker = ReceiveWorker(self.project, self.credentials, prepare)
        self.worker.done.connect(self.show_receive)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _integrate_keeping(self):
        self.keep_local = True
        self.start()

    def _buttons(self, apply=False, conflicts=False, retry=False, publish=False, move=False, keep=False):
        self.keep_button.setVisible(keep)
        self.apply_button.setVisible(apply)
        self.move_button.setVisible(move)
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

    def _show_versions(self, versions):
        """The versions received, newest first, one per row: title, author, date."""
        count = len(versions)
        self.versions.setText(f"{count} {'versione ricevuta' if count == 1 else 'versioni ricevute'}")
        self.version_list.clear()
        for v in versions:
            row = QTreeWidgetItem([v.title, v.author.split("<")[0].strip(), f"{v.timestamp:%d/%m/%Y %H:%M}"])
            row.setToolTip(0, v.title)
            self.version_list.addTopLevelItem(row)
        self.versions.setVisible(bool(count))
        self.version_list.setVisible(bool(count))

    def show_receive(self, receive):
        if self.worker is not None:
            self.worker.wait()
        self.receive = receive
        self.bar.setVisible(False)
        branch, into = receive.branch, receive.into
        if receive.state == Receive.UP_TO_DATE:
            self.status.setText(f"Il ramo in uso «{into}» contiene già tutte le versioni di «{branch}»: nulla da "
                                "integrare." if into else
                                f"Nessuna nuova versione sul ramo «{branch}»: il progetto è aggiornato.")
            return
        if receive.state == Receive.UNRELATED:
            self.status.setStyleSheet("color: #B42318;")
            self.status.setText(f"I rami «{branch}» e «{into}» non hanno nessuna versione in comune: sono progetti "
                                "nati separatamente, e integrarli raddoppierebbe voci SRS, domini, funzioni e team. "
                                "Non si integrano: scegli uno dei due come base e riporta in esso il lavoro "
                                "dell'altro.")
            return
        if receive.state == Receive.PUBLISH_FIRST and into:
            self.status.setText("Qui ci sono modifiche non ancora pubblicate. Puoi integrare mantenendole, in modo "
                                "completo o selettivo: restano da pubblicare, e se gli stessi campi cambiano da "
                                "entrambe le parti scegli tu quale tenere. Oppure pubblicale prima.")
            self._buttons(publish=True, keep=True)
            return
        if receive.state == Receive.NO_BRANCH:
            self.status.setText(f"Il ramo «{branch}» non è ancora nel repository: inviando le tue versioni viene "
                                "creato.")
            return
        count = len(receive.incoming)
        self._show_versions(receive.incoming)
        if receive.state == Receive.PUBLISH_FIRST:
            self.status.setText("Sia tu sia i colleghi avete pubblicato nuove versioni, e qui ci sono modifiche "
                                "non ancora pubblicate. Pubblicale prima: poi le versioni vengono integrate in una "
                                "nuova versione.")
            self._buttons(publish=True)
            return
        denied = self._merge_denied()
        if denied:  # only the Design Authority merges into the main branch
            self.status.setStyleSheet("color: #B42318;")
            self.status.setText(denied if into else
                                f"{denied}\n\nQui ci sono versioni tue non ancora inviate e sul repository versioni "
                                "dei colleghi: unirle sarebbe un'unione nel ramo principale. Sposta le tue versioni su "
                                "un nuovo ramo e invialo: la DA lo integrerà.")
            self._buttons(move=not into)
            return
        result = receive.result
        if into:
            what = (f"Le versioni di «{branch}» e quelle di «{into}» vengono integrate in una nuova versione di "
                    f"«{into}», da inviare poi al repository. Come con «Ricevi», l'unione è per scheda e per campo, "
                    "gli identificativi doppi vengono rinumerati e le tracciature collegate riallineate."
                    if receive.state == Receive.MERGE else
                    f"«{into}» non ha versioni che «{branch}» non abbia: prende le versioni di «{branch}» così come "
                    "sono.")
        else:
            what = (f"Le versioni ricevute e le tue ({len(self.project.unsent_versions())} non ancora inviate) "
                    "vengono integrate in una nuova versione, da inviare poi al repository."
                    if receive.state == Receive.MERGE else
                    "Il progetto viene aggiornato con le versioni ricevute; le modifiche non ancora pubblicate "
                    "restano da pubblicare.")
        if receive.local is not None:
            what += " Le modifiche non ancora pubblicate restano da pubblicare, sopra il risultato."
        if receive.foreign:
            count = len(receive.foreign)
            which = "versione è un'unione fatta" if count == 1 else "versioni sono unioni fatte"
            what += (f"\n\nAttenzione: {count} {which} "
                     "fuori da ATLAS (con Git): gli identificativi potrebbero essere doppi e le tracciature non "
                     "allineate. Dopo, esegui «Verifica modello» (GEN-02, ID duplicati) e correggi le schede.")
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
        if self.preview is not None:
            self._show_preview(result)
        if self.integrate:
            self.mode_row.setVisible(True)

    def _refill_conflicts(self, conflicts, kept):
        """The table again, with the choices already made ({conflict key: choice})."""
        self._fill_conflicts(conflicts)
        for row in range(self.conflicts.rowCount()):
            choice = kept.get(self.conflicts.item(row, 0).data(Qt.UserRole))
            if choice:
                combo = self.conflicts.cellWidget(row, 3)
                combo.setCurrentIndex(combo.findData(choice))

    def _show_conflict(self, row):
        if 0 <= row < len(self.conflict_list):
            c = self.conflict_list[row]
            self.conflict_detail.show_values(self._value(c, c.ours), self._value(c, c.theirs), c.local)

    def _fill_conflicts(self, conflicts):
        self.conflict_list = list(conflicts)
        self.conflicts.setRowCount(len(conflicts))
        self.conflicts.setVisible(bool(conflicts))
        self.conflict_detail.setVisible(bool(conflicts))
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
            choice.currentIndexChanged.connect(lambda _i: self._preview_timer.start())
            choice.activated.connect(lambda _i, r=row: self.conflicts.selectRow(r))  # its values, while choosing
            self.conflicts.setCellWidget(row, 3, choice)
        self.conflicts.resizeRowsToContents()
        if conflicts:
            self.conflicts.selectRow(0)
            self._show_conflict(0)

    # --- the preview of the integration ---------------------------------------------------------------------------

    def _show_preview(self, result):
        """The branch in use → after the merge (the choices made so far; the conflicts not chosen yet as here)."""
        from arcadia_tool.diff.semantic import diff_models
        from arcadia_tool.storage.merge import merged_model
        from arcadia_tool.ui.diff_view import DiffView

        diff = diff_models(self.project.model, merged_model(result.files))
        into, branch = self.receive.into, self.receive.branch
        view = (DiffView(diff, f"«{into}» ora", f"«{into}» dopo l'integrazione di «{branch}»") if into else
                DiffView(diff, "Il modello ora", f"Il modello dopo la ricezione da «{branch}»"))
        self._set_preview(view, view)
        conflicts = self.conflicts.rowCount()
        auto = len(result.received) + len(result.merged)
        self.conflicts_title.setText(
            f"Unite automaticamente: {auto} schede ({len(result.merged)} campo per campo"
            + (f", {len(result.renumbered)} identificativi rinumerati" if result.renumbered else "")
            + (f", {len(result.relinked)} tracciature riallineate" if result.relinked else "") + ")"
            + (f" · da risolvere: {conflicts} {'conflitto' if conflicts == 1 else 'conflitti'} (scegli per ciascuno "
               "quale versione tenere: l'anteprima si aggiorna)" if conflicts else " · nessun conflitto"))
        self.conflicts_title.setVisible(True)
        self.preview_result = result

    def _refresh_preview(self):
        if self.receive is not None and self.preview is not None and not self.selective:
            self._show_preview(self.receive.merge(self.choices()))

    # --- the selective integration ----------------------------------------------------------------------------------

    @property
    def selective(self):
        return self.receive is not None and self.receive.only is not None

    def _set_preview(self, shown, view):
        """shown: the widget of the preview; view: its DiffView."""
        if self.preview_shown is not None:
            self.preview_shown.setParent(None)
            self.preview_shown.deleteLater()
        self.preview_shown, self.preview_view = shown, view
        self.preview.layout().addWidget(shown)
        self.preview.setVisible(True)

    def _mode_changed(self):
        if self.selective_mode.isChecked():
            self._start_selective()
            return
        self.receive.only = None
        self.groups_row.setVisible(False)
        self.status.setText(self._full_status)
        result = self.receive.merge()
        self._fill_conflicts(result.conflicts)
        self._buttons(apply=True, conflicts=bool(result.conflicts))
        self._update_apply()
        self._show_preview(result)

    def _locked(self):
        """What cannot be ticked: a removal still used here; for who is not of the DA, the SRS items (they follow what
        is linked to them)."""
        from arcadia_tool.model.teams import edit_denied

        locked = {u: "Non si può togliere: la usano ancora " + ", ".join(names)
                  for u, names in self.selection.blocked.items()}
        reason = edit_denied(self.project.model, self.user, "requirement")
        if reason:
            for c in self.selection.diff.changes:
                if c.kind == "requirement":
                    locked.setdefault(c.uuid, reason)
        return locked

    def _start_selective(self):
        from arcadia_tool.ui.busy import run_busy
        from arcadia_tool.ui.diff_view import DiffView

        if self.selection is None:
            self.selection = run_busy(self, "Confronto dei due rami…", lambda _report: self.receive.selection())
        into, branch = self.receive.into, self.receive.branch
        view = DiffView(self.selection.diff, "", "", self.selection.needs, self._locked(), "Va insieme a: ")
        view.title.setText(f"<b>Mittente: «{branch}»</b>")
        view.splitter.setOrientation(Qt.Vertical)
        view.splitter.setSizes([360, 150])
        view.chosen = set()
        view._refresh_ticks()
        self.destination = DestinationView(self.selection, into)
        view.selection_changed.connect(lambda: self.destination.show_chosen(view.chosen))
        view.selection_changed.connect(self._selective_timer.start)
        panes = QSplitter(Qt.Horizontal)
        panes.addWidget(view)
        panes.addWidget(self.destination)
        panes.setSizes([620, 620])
        self._set_preview(panes, view)
        self._full_status = self.status.text()
        self.status.setText(f"Spunta a sinistra gli elementi di «{branch}» da portare in «{into}»: a destra vedi come "
                            "cambia il modello. Gli elementi legati si selezionano da soli; il resto del ramo potrà "
                            "essere integrato in seguito.")
        self.receive.only = set()
        self._fill_groups()
        self._selective_update()

    def _group_changes(self, kinds, group):
        """Added or changed, not removed: a deletion is taken only with its own tick."""
        locked = self.preview_view.locked
        named = {k for _label, ks, _group in SELECTIVE_GROUPS for k in ks}
        return [c.uuid for c in self.selection.diff.changes if c.change != REMOVED and c.uuid not in locked
                and (c.kind in kinds or (group and KINDS_BY_NAME[c.kind].group == group and c.kind not in named))]

    def _fill_groups(self):
        while self.groups_layout.count():
            widget = self.groups_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.groups_layout.addWidget(QLabel("Seleziona:", objectName="muted"))
        self.group_buttons = {}
        for label, kinds, group in SELECTIVE_GROUPS:
            uuids = self._group_changes(kinds, group)
            if uuids:
                button = QPushButton(f"{label} ({len(uuids)})")
                button.setToolTip("Spunta le aggiunte e le modifiche di queste schede, con ciò a cui sono legate")
                button.clicked.connect(lambda _=False, u=uuids: self.preview_view.set_chosen(
                    self.preview_view.chosen | set(u)))
                self.groups_layout.addWidget(button)
                self.group_buttons[label] = button
        clear = QPushButton("Deseleziona tutto")
        clear.clicked.connect(lambda _=False: self.preview_view.set_chosen(set()))
        self.groups_layout.addWidget(clear)
        self.groups_layout.addStretch()
        self.groups_row.setVisible(True)

    def _selective_update(self):
        """The ticks changed: the conflicts of the elements chosen (the choices already made stay) and what happens."""
        if not self.selective:
            return
        kept = self.choices()
        self.receive.only = set(self.preview_view.chosen)
        merged = self.receive.merge()
        conflicts = merged.conflicts
        self.destination.show_numbers(merged.renumbered, self.receive.branch)
        self._refill_conflicts(conflicts, kept)
        self._buttons(apply=True, conflicts=bool(conflicts))
        changes = [c for c in self.selection.diff.changes if c.uuid in self.receive.only]
        count = {k: sum(1 for c in changes if c.change == k) for k in (ADDED, MODIFIED, REMOVED)}
        self.conflicts_title.setText(
            f"Selezionati {len(changes)}: {count[ADDED]} da aggiungere, {count[MODIFIED]} da modificare, "
            f"{count[REMOVED]} da rimuovere"
            + (f" · {len(merged.renumbered)} identificativi rinumerati (a destra il numero finale)"
               if merged.renumbered else "")
            + (f" · da risolvere: {len(conflicts)} conflitti" if conflicts else ""))
        self.conflicts_title.setVisible(True)
        self._update_apply()

    def _element(self, conflict):
        data = self.receive.ours.get(conflict.path) or self.receive.theirs_files.get(conflict.path)
        try:
            return loads(data.decode("utf-8")) if data else None
        except Exception:
            return None

    def _where(self, conflict):
        where = self._place(conflict)
        return f"{where} (tua modifica non pubblicata)" if conflict.local else where

    def _place(self, conflict):
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

    def _reset_message(self):
        self._message_edited = False
        self._update_apply()

    def message_text(self):
        """The message written for the version: the title, then the description."""
        title, description = self.message.text().strip(), self.description.toPlainText().strip()
        return f"{title}\n\n{description}" if title and description else title

    def _update_message(self):
        """Integra: the message is asked when a version is recorded; until the user writes it, it follows what is
        chosen (e.g. the number of the elements of a selective integration)."""
        shown = bool(self.integrate) and self.receive is not None and not self.apply_button.isHidden() \
            and self.project.creates_version(self.receive)
        self.message_row.setVisible(shown)
        if shown and not self._message_edited:
            self.message.blockSignals(True)
            self.message.setText(self.project.default_message(self.receive))
            self.message.blockSignals(False)

    def _update_apply(self, *_args):
        self._update_message()
        missing = self.conflicts.rowCount() - len(self.choices())
        empty = self.selective and not self.receive.only
        self.apply_button.setEnabled(missing == 0 and not empty)
        self.apply_button.setToolTip("Spunta almeno un elemento" if empty else
                                     f"Scegli ancora {missing} modifiche" if missing else "")

    def _merge_denied(self):
        """Why the user may not make the merge prepared (into the main branch), or None."""
        r = self.receive
        if r is None or r.state != Receive.MERGE:
            return None
        return self.project.main_denied(self.user, r.into or r.branch)

    def _move_to_branch(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from arcadia_tool.ui.branches import suggested_name
        name, ok = QInputDialog.getText(self, "Sposta su un nuovo ramo", "Nome del nuovo ramo:",
                                        text=suggested_name(self.project, self.user))
        if not ok or not name.strip():
            return
        try:
            self.project.move_unsent_to_branch(name.strip())
        except Exception as exc:
            QMessageBox.warning(self, "Sposta su un nuovo ramo", str(exc))
            return
        self.moved_to = name.strip()
        self.accept()

    def apply(self):
        if self.receive is None or self._merge_denied():
            return
        kept = self.choices()
        message = self.message_text() if not self.message_row.isHidden() else None
        self.result = self.project.apply_receive(self.receive, kept, self.author, message)
        if not self.result.resolved:  # the choices made have shown others (with the changes not published)
            self._refill_conflicts(self.result.conflicts, kept)
            self._buttons(apply=True, conflicts=True)
            self._update_apply()
            return
        if self.result.resolved:
            self.applied = True
            self.merged = self.receive.state == Receive.MERGE or self.selective
            self.accept()

    def _publish_first(self):
        self.publish_first = True
        self.accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            return  # not while downloading: the window closes when the server has answered
        super().reject()
