"""Progetto › Genera: «Schede Arcadia» writes the artefacts of the SA phases and the ADR in Excel, filled in from
the model, as the settings of the project say; «Impostazioni…» chooses them with ticks (all, or some), with the
domains to include and the folder to write them in, saved with the project."""
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog,
                               QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from arcadia_tool.documents.generate import (ALL, REGISTER, chosen, generate, load_settings, make_doc, planned_files,
                                             problems, save_settings, subjects)
from arcadia_tool.documents.sa import ARTIFACTS
from arcadia_tool.documents.values import by_id
from arcadia_tool.storage.adr_register import open_adrs
from arcadia_tool.ui.theme import MUTED, icon

KEY_ROLE = Qt.UserRole  # an SA artefact (its code), the register of the open ADR, or an ADR (its uuid)
TITLE = "Genera schede Arcadia"


def run_generation(parent, project, codes, adrs, register, domains, folder, author="", ask=True):
    """The files of the artefacts in the folder, with a loading bar (existing ones: replaced, after asking), then
    a summary with «Apri cartella» (ask). Returns the paths written, or None if cancelled or failed."""
    existing = [f for f in planned_files(project, folder, codes, adrs, register) if f.exists()]
    if existing and ask and QMessageBox.question(
            parent, TITLE, "Nella cartella ci sono già questi file, che verranno sostituiti:\n\n"
            + "\n".join(f.name for f in existing) + "\n\nContinuare?") != QMessageBox.Yes:
        return None
    progress = QProgressDialog("Generazione delle schede Arcadia…", None, 0, 0, parent)
    progress.setWindowTitle(TITLE)
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.setMinimumWidth(420)
    progress.show()
    QApplication.processEvents()

    def step(done, total, what):
        progress.setLabelText(f"Generazione: {what}")
        progress.setMaximum(total)
        progress.setValue(done)
        QApplication.processEvents()

    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        written = generate(project, folder, codes, adrs, register, author, domains, step)
    except OSError as exc:  # a file open in Excel, a folder that cannot be written
        QMessageBox.critical(parent, TITLE, f"Le schede non sono state generate: {exc}")
        return None
    finally:
        QApplication.restoreOverrideCursor()
        progress.close()
        progress.deleteLater()
    if ask:
        box = QMessageBox(QMessageBox.Information, TITLE, f"Generati {len(written)} file in:\n{folder}\n\n"
                          + "\n".join(Path(f).name for f in written), parent=parent)
        open_folder = box.addButton("Apri cartella", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    return written


def generate_from_settings(parent, project, author="", ask=True, open_settings=None):
    """«Schede Arcadia»: the artefacts of the settings of the project; if they are not valid, says why (and offers
    to open the settings: open_settings())."""
    settings = load_settings(project)
    found = problems(project, settings, author)
    if found:
        if ask:
            box = QMessageBox(QMessageBox.Information, TITLE, "Le schede non si possono generare:\n\n"
                              + "\n".join(f"• {p}" for p in found), parent=parent)
            settings_button = box.addButton("Impostazioni…", QMessageBox.ActionRole) if open_settings else None
            box.addButton(QMessageBox.Close)
            box.exec()
            if settings_button is not None and box.clickedButton() is settings_button:
                open_settings()
        return None
    codes, adrs, register, domains, folder = chosen(project, settings)
    return run_generation(parent, project, codes, adrs, register, domains, folder, author, ask)


class DocumentationDialog(QDialog):
    """The settings of «Schede Arcadia»: what to generate and where. «Salva» saves them with the project; «Salva e
    genera» generates too. written: the files of the last generation."""

    def __init__(self, project, author="", parent=None):
        super().__init__(parent)
        self.project, self.author = project, author
        self.written = []
        saved = load_settings(project)
        # The artefacts wanted, also those without data now (generated when the model has some).
        self.intended = set(saved["codes"]) if saved else {a.code for a in ARTIFACTS}
        self.setWindowTitle("Impostazioni delle schede Arcadia")
        self.resize(980, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Schede Arcadia da generare in Excel", objectName="cardTitle"))
        layout.addWidget(QLabel(
            "Spunta gli artefatti da generare con Progetto › Genera › Schede Arcadia: ogni artefatto è un file Excel "
            "con il disegno del suo template, compilato dal modello (un foglio per dominio o per chain, o un foglio "
            "unico). Gli artefatti senza dati nel modello non si possono scegliere ora. La scelta si salva con il "
            "progetto ed è condivisa con il team; la cartella di destinazione vale per questo PC.",
            objectName="muted", wordWrap=True))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Artefatto", "Contenuto"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.sa_group = self._group("System Analysis (SA-1 … SA-7)")
        self.sa_items = {}
        for artifact in ARTIFACTS:
            item = QTreeWidgetItem([f"{artifact.code} · {artifact.title}", ""])
            item.setData(0, KEY_ROLE, artifact.code)
            self.sa_group.addChild(item)
            self.sa_items[artifact.code] = item
        self.adr_group = self._group("Decisioni architetturali (X-1)")
        self.register_item = QTreeWidgetItem(["Registro delle ADR aperte", ""])
        self.register_item.setData(0, KEY_ROLE, REGISTER)
        self.adr_group.addChild(self.register_item)
        self.adr_items = {}
        adrs_ticked = saved["adrs"] if saved else ALL
        for adr in by_id(project.model.of_kind("adr")):
            item = QTreeWidgetItem([f"{adr.get('id') or ''} · {adr.get('title') or ''}".strip(" ·"),
                                    " · ".join(t for t in (adr.get("adr_type"), adr.get("status")) if t)])
            item.setData(0, KEY_ROLE, adr.uuid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if adrs_ticked == ALL or adr.uuid in adrs_ticked else Qt.Unchecked)
            self.adr_group.addChild(item)
            self.adr_items[adr.uuid] = item
        self._register_wanted = saved["register"] if saved else True

        domains_box = QWidget()
        domains_layout = QVBoxLayout(domains_box)
        domains_layout.setContentsMargins(0, 0, 0, 0)
        domains_layout.addWidget(QLabel("Domini da includere (SA)", objectName="formLabel"))
        self.all_domains = QCheckBox("Tutti i domini")
        domains_layout.addWidget(self.all_domains)
        self.domains = QListWidget()
        wanted = saved["domains"] if saved else None
        for d in by_id(project.model.of_kind("domain")):
            entry = QListWidgetItem(" ".join(t for t in (d.get("id"), d.get("name")) if t))
            entry.setData(Qt.UserRole, d.uuid)
            entry.setFlags(entry.flags() | Qt.ItemIsUserCheckable)
            entry.setCheckState(Qt.Checked if wanted is None or d.uuid in wanted else Qt.Unchecked)
            self.domains.addItem(entry)
        self.all_domains.setChecked(self.chosen_domains() is None)
        domains_layout.addWidget(self.domains, 1)
        self.all_domains.toggled.connect(self._all_domains)
        self.domains.itemChanged.connect(self._domain_changed)
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(domains_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([700, 260])
        layout.addWidget(splitter, 1)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Cartella di destinazione", objectName="formLabel"))
        self.folder = QLineEdit((saved or {}).get("folder") or
                                str(Path(project.path).parent / f"Documentazione {project.name}"))
        browse = QPushButton(icon("mdi6.folder-open-outline"), "Sfoglia…")
        browse.clicked.connect(lambda _=False: self.browse())
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)
        self.summary = QLabel(objectName="muted")
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        self.generate_button = QPushButton(icon("mdi6.file-document-multiple-outline"), "Salva e genera")
        self.generate_button.clicked.connect(lambda _=False: self.save_and_generate())
        self.save_button = QPushButton(icon("mdi6.content-save-outline", "white"), "Salva")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(lambda _=False: self.save() and self.accept())
        buttons.addButton(self.generate_button, QDialogButtonBox.ActionRole)
        buttons.addButton(self.save_button, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tree.itemChanged.connect(self._changed)
        self._refresh_counts()
        for group in (self.sa_group, self.adr_group):
            group.setExpanded(True)

    def _group(self, text):
        """A group: its tick ticks (or unticks) the artefacts in it that can be chosen; it shows whether they are all
        ticked, some or none (see _changed)."""
        group = QTreeWidgetItem([text, ""])
        group.setFlags(group.flags() | Qt.ItemIsUserCheckable)
        group.setCheckState(0, Qt.Checked)
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)
        self.tree.addTopLevelItem(group)
        return group

    def browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Cartella di destinazione", self.folder.text())
        if folder:
            self.folder.setText(folder)

    # --- domains ------------------------------------------------------------------------------------------------

    def chosen_domains(self):
        """The domains ticked; None: all of them."""
        ticked = [self.domains.item(i).data(Qt.UserRole) for i in range(self.domains.count())
                  if self.domains.item(i).checkState() == Qt.Checked]
        return None if len(ticked) == self.domains.count() else ticked

    def _all_domains(self, checked):
        self.domains.blockSignals(True)
        for i in range(self.domains.count()):
            self.domains.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.domains.blockSignals(False)
        self._refresh_counts()

    def _domain_changed(self, _item):
        self.all_domains.blockSignals(True)
        self.all_domains.setChecked(self.chosen_domains() is None)
        self.all_domains.blockSignals(False)
        self._refresh_counts()

    # --- what can be generated ---------------------------------------------------------------------------------

    def _refresh_counts(self):
        """How many sheets or rows each artefact has with the domains chosen; those without data cannot be
        chosen."""
        doc = make_doc(self.project, self.author, self.chosen_domains())
        self.tree.blockSignals(True)
        for artifact in ARTIFACTS:
            item = self.sa_items[artifact.code]
            if item.flags() & Qt.ItemIsEnabled and item.data(0, Qt.CheckStateRole) is not None:
                self._remember(item, artifact.code)
            n = len(subjects(doc, artifact.code))
            one, many = artifact.unit
            self._available(item, n, f"{n} {one if n == 1 else many}" + (f" (un foglio per {one})"
                                                                           if artifact.per and n else ""),
                            artifact.code in self.intended)
        open_count = len(open_adrs(self.project.model))
        self._available(self.register_item, open_count,
                        f"{open_count} ADR aperte" if open_count != 1 else "1 ADR aperta", self._register_wanted)
        for group in (self.sa_group, self.adr_group):
            if not self._choosable(group):  # nothing to choose in it
                group.setFlags(group.flags() & ~Qt.ItemIsUserCheckable & ~Qt.ItemIsEnabled)
            else:
                group.setFlags(group.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        self._group_states()
        self.tree.blockSignals(False)
        self._update()

    def _remember(self, item, code):
        if item.checkState(0) == Qt.Checked:
            self.intended.add(code)
        else:
            self.intended.discard(code)

    @staticmethod
    def _available(item, n, text, wanted):
        if n:
            if not item.flags() & Qt.ItemIsEnabled or item.data(0, Qt.CheckStateRole) is None:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(0, Qt.Checked if wanted else Qt.Unchecked)
            item.setText(1, text)
            item.setForeground(1, QBrush(QColor(MUTED)))
            item.setToolTip(0, "")
        else:  # not ticked (a state all the same: else the group has no tick of its own), cannot be chosen
            item.setCheckState(0, Qt.Unchecked)
            item.setFlags((item.flags() & ~Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
            item.setText(1, "nessun dato nel modello")
            item.setToolTip(0, "Il modello non ha ancora elementi per questo artefatto (con i domini scelti)"
                            + (": se resta spuntato nelle impostazioni, si genera quando ne avrà." if wanted else "."))

    @staticmethod
    def _choosable(group):
        return [group.child(i) for i in range(group.childCount()) if group.child(i).flags() & Qt.ItemIsEnabled]

    def _changed(self, item, _column=0):
        """A group ticked: its artefacts that can be chosen too; an artefact ticked: its group shows all, some or
        none."""
        self.tree.blockSignals(True)
        if item in (self.sa_group, self.adr_group):
            state = Qt.Unchecked if item.checkState(0) == Qt.Unchecked else Qt.Checked
            item.setCheckState(0, state)
            for child in self._choosable(item):
                child.setCheckState(0, state)
        for code, child in self.sa_items.items():
            if child.flags() & Qt.ItemIsEnabled:
                self._remember(child, code)
        if self.register_item.flags() & Qt.ItemIsEnabled:
            self._register_wanted = self.register_item.checkState(0) == Qt.Checked
        self._group_states()
        self.tree.blockSignals(False)
        self._update()

    def _group_states(self):
        for group in (self.sa_group, self.adr_group):
            states = {c.checkState(0) for c in self._choosable(group)}
            group.setCheckState(0, Qt.Checked if states == {Qt.Checked} else
                                Qt.Unchecked if states <= {Qt.Unchecked} else Qt.PartiallyChecked)

    def selection(self):
        """(the SA artefacts, the ADR, the register of the open ADR) ticked, among those that can be chosen now."""
        ticked = lambda item: bool(item.flags() & Qt.ItemIsEnabled) and item.checkState(0) == Qt.Checked  # noqa
        codes = [code for code, item in self.sa_items.items() if ticked(item)]
        adrs = [self.project.model.get(u) for u, item in self.adr_items.items() if ticked(item)]
        return codes, [a for a in adrs if a is not None], ticked(self.register_item)

    def _update(self, *_args):
        codes, adrs, register = self.selection()
        files = len(codes) + (1 if adrs or register else 0)
        self.summary.setText("Nessun artefatto da generare con il modello di ora." if not files else
                             f"Con il modello di ora si generano {files} file: "
                             + ", ".join(codes + (["X-1"] if adrs or register else [])))

    # --- «Salva», «Salva e genera» -------------------------------------------------------------------------------

    def save(self):
        """The settings saved with the project (the choice in project.yaml, the folder for this PC)."""
        folder = self.folder.text().strip()
        if not folder:
            QMessageBox.information(self, self.windowTitle(), "Scegli la cartella di destinazione.")
            return False
        _codes, adrs, _register = self.selection()
        every = len(adrs) == len(self.adr_items)  # all of them: also those created later
        codes = [a.code for a in ARTIFACTS if a.code in self.intended]
        save_settings(self.project, codes, ALL if every else [a.uuid for a in adrs], self._register_wanted,
                      self.chosen_domains(), folder)
        return True

    def save_and_generate(self, ask=True):
        if not self.save():
            return None
        written = generate_from_settings(self, self.project, self.author, ask)
        if written is not None:
            self.written = written
            self.accept()
        return written
