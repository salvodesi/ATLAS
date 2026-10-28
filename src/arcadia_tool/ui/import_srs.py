"""Import of SRS items from the SUBSET-026 PDF chapters: choose files, analyse, preview, confirm."""
from html import escape
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from arcadia_tool.importers.srs_merge import apply_import, plan_import
from arcadia_tool.importers.srs_pdf import (chapter_of, chapter_of_item, parse_chapter, parse_classification,
                                            table_clauses)
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.element_editor import card
from arcadia_tool.ui.srs_reader import confirm_delete
from arcadia_tool.ui.theme import CHANGE_BG, CHANGE_COLORS, MUTED, icon

CLASSIFICATION_CHAPTER = 9
DETAIL_IMAGE_WIDTH = 420
FIELD_LABELS = {"title": "titolo", "text": "testo", "item_type": "tipo", "page": "pagina", "baseline": "baseline",
                "category": "categoria", "import_note": "note", "parent": "padre", "replaces": "voce sostituita",
                "srs_refs": "riferimenti", "mode_availability": "disponibilità nei modi (rimossa)"}


def _describe(path):
    chapter = chapter_of(path)
    if chapter == CLASSIFICATION_CHAPTER:
        return "Capitolo 9 · classificazione delle clausole"
    if chapter == 7:
        return "Capitolo 7 · linguaggio: variabili e pacchetti"
    if chapter == 8:
        return "Capitolo 8 · messaggi"
    return f"Capitolo {chapter}" if chapter else "Capitolo non riconosciuto dal nome del file"


class AnalysisCancelled(Exception):
    pass


class ParseWorker(QThread):
    progress = Signal(str, int, int)
    # object, not dict: a dict would be converted to a Qt map, which only keeps string keys
    # (chapters are keyed by number and would arrive empty).
    done = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self._cancel_requested = False

    def cancel(self):
        """Stop at the next page; the results analysed so far are discarded."""
        self._cancel_requested = True

    def _report(self, name, page, total):
        if self._cancel_requested:
            raise AnalysisCancelled()
        self.progress.emit(name, page, total)

    def run(self):
        chapters, classification = {}, None
        # Chapter 9 first: it tells which clauses contain a table without caption, to be imported as image.
        paths = sorted(self.paths, key=lambda p: chapter_of(p) != CLASSIFICATION_CHAPTER)
        try:
            for path in paths:
                name = Path(path).name
                report = lambda page, total, name=name: self._report(name, page, total)
                chapter = chapter_of(path)
                if chapter == CLASSIFICATION_CHAPTER:
                    classification = parse_classification(path, report)
                else:
                    items = parse_chapter(path, report, table_clauses(classification, chapter))
                    if items:
                        chapters[chapter or chapter_of_item(items[0].id)] = items
                if self._cancel_requested:
                    raise AnalysisCancelled()
        except AnalysisCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # shown to the user, the dialog stays usable
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(chapters, classification)


def _badge(text, kind):
    label = QLabel(text)
    fg, bg = (CHANGE_COLORS[kind], CHANGE_BG[kind]) if kind in CHANGE_COLORS else (MUTED, "#EEF1F5")
    label.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:10px; padding:2px 10px; font-weight:600;")
    return label


def _table(headers, rows, payloads=None):
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(r, c, item)
        if payloads is not None:
            table.item(r, 0).setData(Qt.UserRole, payloads[r])
    header = table.horizontalHeader()
    for c in range(len(headers) - 1):
        header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
    header.setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)
    return table


def _summary(values):
    text = values.get("title") or values.get("text") or ""
    return " ".join(text.split())[:160]


class ImportSrsDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project, self.plan, self.worker = project, None, None
        self.created = self.updated = self.deleted = 0
        self.setWindowTitle("Importa voci SRS")
        self.resize(1180, 780)

        files, files_layout = card("File PDF del SUBSET-026")
        hint = QLabel("Seleziona i capitoli da importare (es. SUBSET-026-3, -4, -5) e, per la classificazione "
                      "delle voci, il capitolo 9. Le voci vengono riconosciute dal numero di clausola: le "
                      "sezioni hanno 3 livelli (3.4.1), i requisiti 4 o più (3.4.1.5).", objectName="muted")
        hint.setWordWrap(True)
        self.files = QListWidget()
        self.files.setMaximumHeight(130)
        self.add_button = QPushButton(icon("mdi6.file-pdf-box"), "Aggiungi PDF…")
        self.remove_button = QPushButton(icon("mdi6.trash-can-outline"), "Rimuovi")
        self.add_button.clicked.connect(self._add_files)
        self.remove_button.clicked.connect(self._remove_files)
        self.baseline = QLineEdit(project.baseline)
        self.analyse_button = QPushButton(icon("mdi6.magnify-scan", "white"), "Importa")
        self.analyse_button.setProperty("primary", True)
        self.analyse_button.clicked.connect(self._analyse_clicked)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        form = QFormLayout()
        form.addRow("Baseline", self.baseline)
        buttons.addLayout(form)
        buttons.addWidget(self.analyse_button)
        files_layout.addWidget(hint)
        files_layout.addWidget(self.files)
        files_layout.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.hide()
        files_layout.addWidget(self.progress)

        self.preview, self.preview_layout = card("Anteprima dell'import")
        self.preview_layout.addWidget(QLabel("Aggiungi i file e premi «Importa»: nessuna modifica viene applicata "
                                             "al modello prima della conferma.", objectName="muted",
                                             alignment=Qt.AlignCenter), 1)

        self.import_button = QPushButton(icon("mdi6.database-import-outline", "white"), "Importa")
        self.import_button.setProperty("primary", True)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._apply)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(cancel)
        bottom.addWidget(self.import_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(files)
        layout.addWidget(self.preview, 1)
        layout.addLayout(bottom)

    # --- files ---------------------------------------------------------------------------------

    def add_paths(self, paths):
        present = {self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())}
        for path in sorted(paths, key=lambda p: chapter_of(p) or 99):
            if path in present:
                continue
            item = QListWidgetItem(icon("mdi6.file-pdf-box", "#B42318"), f"{Path(path).name}    —    {_describe(path)}")
            item.setData(Qt.UserRole, path)
            self.files.addItem(item)

    def _add_files(self):
        start = settings().value("import/folder", "")
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF del SUBSET-026", start, "PDF (*.pdf)")
        if paths:
            settings().setValue("import/folder", str(Path(paths[0]).parent))
            self.add_paths(paths)

    def _remove_files(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))

    def _paths(self):
        return [self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())]

    # --- analysis ------------------------------------------------------------------------------

    def analysing(self):
        return self.worker is not None and self.worker.isRunning()

    def _analyse_clicked(self):
        if self.analysing():
            self.cancel_analysis()
        else:
            self._analyse()

    def _analyse(self):
        paths = self._paths()
        if not paths:
            QMessageBox.information(self, "Importa voci SRS", "Aggiungi almeno un capitolo del SUBSET-026.")
            return
        self.plan = None
        self.import_button.setEnabled(False)
        self._set_analysing(True)
        self.progress.show()
        self.progress.setRange(0, 0)
        self.worker = ParseWorker(paths)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _set_analysing(self, running):
        self.analyse_button.setEnabled(True)
        if running:
            self.analyse_button.setIcon(icon("mdi6.stop-circle-outline", "white"))
            self.analyse_button.setText("Interrompi importazione")
        else:
            self.analyse_button.setIcon(icon("mdi6.magnify-scan", "white"))
            self.analyse_button.setText("Importa")
        for widget in (self.files, self.add_button, self.remove_button, self.baseline):
            widget.setEnabled(not running)

    def cancel_analysis(self, wait=False):
        """Interrupt the analysis in progress (it stops at the next page); nothing is imported."""
        if not self.analysing():
            return
        self.worker.cancel()
        self.analyse_button.setEnabled(False)
        self.progress.setFormat("Interruzione in corso…")
        if wait:
            self.worker.wait()

    def _on_cancelled(self):
        self.progress.hide()
        self._set_analysing(False)
        self.import_button.setEnabled(False)
        self._show_message("Analisi interrotta: nessuna voce è stata importata. Premi «Importa» per ripartire.")

    def _on_progress(self, name, page, total):
        self.progress.setRange(0, total)
        self.progress.setValue(page)
        self.progress.setFormat(f"Analisi di {name}: pagina {page} di {total}")

    def _on_failed(self, message):
        self.progress.hide()
        self._set_analysing(False)
        QMessageBox.critical(self, "Importa voci SRS", f"Analisi non riuscita.\n\n{message}")

    def _on_done(self, chapters, classification):
        self.progress.hide()
        self._set_analysing(False)
        self.plan = plan_import(self.project.model, chapters, classification, self.baseline.text().strip())
        self._show_plan(self.plan, classification is not None)
        self._update_import_button()

    def _delete_missing_requested(self):
        box = getattr(self, "delete_missing", None)
        return bool(self.plan and self.plan.missing and box is not None and box.isChecked())

    def _update_import_button(self, *_):
        total = len(self.plan.new) + len(self.plan.updates) if self.plan else 0
        deleting = self._delete_missing_requested()
        self.import_button.setEnabled(bool(total) or deleting)
        text = f"Importa {total} voci" if total else "Importa"
        if deleting:
            text += f" ed elimina {len(self.plan.missing)}"
        self.import_button.setText(text)

    def _clear_preview(self):
        while self.preview_layout.count() > 1:
            widget = self.preview_layout.takeAt(1).widget()
            if widget:
                widget.hide()
                widget.deleteLater()  # later: it may be the sender of the signal that clears

    def _show_message(self, text):
        self._clear_preview()
        self.preview_layout.addWidget(QLabel(text, objectName="muted", alignment=Qt.AlignCenter), 1)

    def _show_plan(self, plan, classified):
        self._clear_preview()
        badges = QHBoxLayout()
        chapters = ", ".join(str(c) for c in plan.chapters) or "nessuno (solo classificazione)"
        badges.addWidget(QLabel(f"<b>Capitoli analizzati:</b> {chapters}"
                                + ("" if classified else "  ·  <i>senza capitolo 9: categorie non aggiornate</i>")))
        badges.addStretch()
        badges.addWidget(_badge(f"{len(plan.new)} nuove", "added"))
        badges.addWidget(_badge(f"{len(plan.updates)} aggiornate", "modified"))
        badges.addWidget(_badge(f"{plan.unchanged} invariate", ""))
        badges.addWidget(_badge(f"{len(plan.warnings)} da verificare", "modified"))
        badges.addWidget(_badge(f"{len(plan.missing)} non più presenti", "removed"))
        holder = QWidget()
        badges.setContentsMargins(0, 0, 0, 0)
        holder.setLayout(badges)

        figure = lambda p: "Sì" if p.image else ""
        updates = [p for _, p, _ in plan.updates]
        tables = [
            (_table(["ID", "Tipo", "Categoria", "Figura", "Contenuto"],
                    [(p.id, p.values.get("item_type") or "", ", ".join(p.values.get("category") or []), figure(p),
                      _summary(p.values)) for p in plan.new], plan.new), f"Nuove ({len(plan.new)})"),
            (_table(["ID", "Campi aggiornati", "Figura", "Contenuto"],
                    [(p.id, ", ".join(FIELD_LABELS.get(c, c) for c in changed), figure(p), _summary(p.values))
                     for _, p, changed in plan.updates], updates), f"Aggiornate ({len(plan.updates)})"),
            (_table(["ID", "Figura", "Nota"], [(p.id, figure(p), p.values.get("import_note") or "")
                                              for p in plan.warnings], plan.warnings),
             f"Da verificare ({len(plan.warnings)})"),
            (_table(["ID", "Contenuto"], [(e.get("id"), _summary(e.values)) for e in plan.missing], plan.missing),
             f"Non più presenti ({len(plan.missing)})"),
        ]
        if plan.renamed or plan.discarded:
            aligned = [(old, new, "rinominata secondo il capitolo 9") for old, new in plan.renamed.items()]
            aligned += [(old, "—", "non elencata nel capitolo 9: il testo resta nella clausola")
                        for old in plan.discarded]
            tables.append((_table(["Nel testo", "Nel capitolo 9", "Esito"], aligned),
                           f"Allineate al cap. 9 ({len(aligned)})"))
        tabs = QTabWidget()
        for table, title in tables:
            table.currentCellChanged.connect(lambda row, _c, _pr, _pc, t=table: self._show_detail(t, row))
            tabs.addTab(table, title)
        tabs.currentChanged.connect(lambda i: self._show_detail(tables[i][0], tables[i][0].currentRow()))

        self.detail = QLabel(alignment=Qt.AlignTop | Qt.AlignLeft)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_image = QLabel(alignment=Qt.AlignTop | Qt.AlignLeft)
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.addWidget(self.detail)
        detail_layout.addWidget(self.detail_image)
        detail_layout.addStretch()
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(detail_page)
        self._detail_width = DETAIL_IMAGE_WIDTH
        splitter = QSplitter()
        splitter.addWidget(tabs)
        splitter.addWidget(detail_scroll)
        splitter.setSizes([700, 460])
        self._show_detail(tables[0][0], -1)

        note = QLabel("Seleziona una riga per vederne il testo completo e l'eventuale figura. Le voci «non più "
                      "presenti» restano nel progetto, a meno di chiederne l'eliminazione qui sotto. Le categorie "
                      "impostate a mano (con nota sulla categoria) non vengono sovrascritte.", objectName="muted")
        note.setWordWrap(True)
        self.delete_missing = QCheckBox(f"Elimina anche le {len(plan.missing)} voci non più presenti "
                                        "(es. voci di una versione precedente dell'import)")
        self.delete_missing.setVisible(bool(plan.missing))
        self.delete_missing.toggled.connect(self._update_import_button)
        self.preview_layout.addWidget(holder)
        self.preview_layout.addWidget(splitter, 1)
        self.preview_layout.addWidget(self.delete_missing)
        self.preview_layout.addWidget(note)

    def _show_detail(self, table, row):
        """Full text, note and figure of the selected row of the preview (before anything is imported)."""
        item = table.item(row, 0) if row is not None and row >= 0 else None
        payload = item.data(Qt.UserRole) if item else None
        if payload is None:
            text = ("Le sotto-voci (a), b), bullet) seguono l'elenco ufficiale del capitolo 9: a parità di numero "
                    "prendono il suo nome, altrimenti quelle che non elenca non diventano voci." if item else
                    "Seleziona una riga per vederne il dettaglio.")
            self.detail.setText(f"<span style='color:#637083'>{text}</span>")
            self.detail_image.clear()
            return
        if hasattr(payload, "values") and hasattr(payload, "image"):  # planned item
            ident, values, image = payload.id, payload.values, payload.image
        else:  # element already in the project
            ident, values = payload.get("id"), payload.values
            image = self.project.asset_data(values.get("figure")) if values.get("figure") else None
        parts = [f"<h3>{escape(ident or '')}</h3>"]
        if values.get("title"):
            parts.append(f"<p><b>{escape(values['title'])}</b></p>")
        if values.get("text"):
            parts.append(f"<p>{escape(values['text']).replace(chr(10), '<br>')}</p>")
        if values.get("category"):
            parts.append(f"<p style='color:#637083'>Categoria: {escape(', '.join(values['category']))}</p>")
        if values.get("import_note"):
            parts.append(f"<p style='color:#9A6700'>{escape(values['import_note'])}</p>")
        self.detail.setText("".join(parts))
        pixmap = QPixmap()
        if image and pixmap.loadFromData(image):
            if pixmap.width() > self._detail_width:
                pixmap = pixmap.scaledToWidth(self._detail_width, Qt.SmoothTransformation)
            self.detail_image.setPixmap(pixmap)
        else:
            self.detail_image.clear()

    # --- apply ---------------------------------------------------------------------------------

    def _apply(self):
        if self.plan is None:
            return
        missing = [e.uuid for e in self.plan.missing] if self._delete_missing_requested() else []
        if missing and not confirm_delete(self, self.project, missing,
                                          f"Eliminare le {len(missing)} voci non più presenti nei PDF importati?"):
            return
        self.created, self.updated = apply_import(self.project, self.plan) if self.plan else (0, 0)
        self.deleted = len(missing)
        self.accept()

    def reject(self):
        """Annulla / closing the window: an analysis in progress is interrupted, nothing is imported."""
        self.cancel_analysis(wait=True)
        super().reject()
