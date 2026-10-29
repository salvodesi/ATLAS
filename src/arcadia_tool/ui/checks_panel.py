"""Panel «Verifiche»: the findings of the active checks, grouped as in the settings. Every finding names the
sheet that violates the check and, below it, the other sheets involved; a double click opens the sheet."""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDockWidget, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from arcadia_tool.checks import (CHECKS_BY_CODE, ERROR, GROUP_LABELS, INFO, SEVERITY_LABELS, WAIVED, WARNING, count,
                                 run)
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.theme import ACCENT, BORDER, MUTED, SURFACE, TEXT, icon, kind_icon

UUID_ROLE = Qt.UserRole
FIELD_ROLE = Qt.UserRole + 1
FINDING_ROLE = Qt.UserRole + 2
PINNED_SETTING = "checks/pinned"
EXPANDED_HEIGHT = 340
MIN_EXPANDED_HEIGHT = 160
QWIDGETSIZE_MAX = 16777215  # no maximum height (Qt's QWIDGETSIZE_MAX)
SEVERITY_COLORS = {ERROR: "#B42318", WARNING: "#B54708", INFO: "#1A5FB4"}
SEVERITY_ICONS = {ERROR: "mdi6.close-circle", WARNING: "mdi6.alert", INFO: "mdi6.information"}
SEVERITY_PLURAL = {ERROR: ("errore", "errori"), WARNING: ("avviso", "avvisi"), INFO: ("informazione", "informazioni")}
WAIVED_COLOR = "#5E6B7A"
WAIVED_ICON = "mdi6.shield-check-outline"


def severity_icon(severity):
    if severity == WAIVED:
        return icon(WAIVED_ICON, WAIVED_COLOR)
    return icon(SEVERITY_ICONS[severity], SEVERITY_COLORS[severity])


def summary(counts):
    """«2 errori, 1 avviso, 0 informazioni» (and «, 1 eccezione» if some findings are accepted as exceptions)"""
    parts = []
    for s in (ERROR, WARNING, INFO):
        one, many = SEVERITY_PLURAL[s]
        parts.append(f"{counts[s]} {one if counts[s] == 1 else many}")
    if counts.get(WAIVED):
        parts.append(f"{counts[WAIVED]} {'eccezione' if counts[WAIVED] == 1 else 'eccezioni'}")
    return ", ".join(parts)


class ExceptionDialog(QDialog):
    """«Accetta come eccezione»: the reason is mandatory; it stays in checks.yaml with who and when."""

    def __init__(self, finding, where, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accetta come eccezione")
        self.setMinimumWidth(520)
        check = CHECKS_BY_CODE[finding.code]
        head = QLabel(f"<b>{finding.code}</b> {check.title}<br>{where}: {finding.message}")
        head.setWordWrap(True)
        note = QLabel("La segnalazione non sarà più contata finché la scheda non cambia; la motivazione resta "
                      "registrata nelle impostazioni delle verifiche, condivise con il team.", objectName="muted")
        note.setWordWrap(True)
        self.reason = QPlainTextEdit(placeholderText="Motivazione (obbligatoria): perché la violazione è accettata")
        self.reason.setMinimumHeight(90)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Accetta come eccezione")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.reason.textChanged.connect(self._update)
        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(self.reason)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self._update()

    def _update(self):
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.text()))

    def text(self):
        return " ".join(self.reason.toPlainText().split())


def run_checks(project, progress=None):
    """Findings of the checks of the active profile of the project (none if no check is active)."""
    config = project.checks
    if config is None or not config.profile.enabled:
        return []
    return run(project.model, config, published=project.published_model, progress=progress)


def enabled_count(project):
    config = project.checks if project is not None else None
    return len(config.profile.enabled) if config is not None else 0


def exception_text(exception):
    """«Accettata come eccezione da Mario Rossi il 2026-10-24: motivo»"""
    return (f"Accettata come eccezione da {exception.get('author') or '?'} il {exception.get('date') or '?'}: "
            f"{exception.get('reason') or ''}")


class CheckProgress(QDialog):
    """Window of a run of the checks: which check of how many is running. «Interrompi» stops the run after the
    current check (closing the window too); at the end it stays open with the outcome until «Chiudi»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verifica modello")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(560)
        self.steps = []
        self.stopped = self.finished_run = False
        self.label = QLabel("Verifica del modello in corso…", alignment=Qt.AlignLeft | Qt.AlignTop)
        self.label.setWordWrap(True)
        # Room for the longest text (4 lines, with a long title wrapped): the window does not jump while it runs.
        self.label.setMinimumHeight(self.label.fontMetrics().lineSpacing() * 5 + 4)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.stop_button = QPushButton(icon("mdi6.stop-circle-outline"), "Interrompi")
        self.stop_button.setToolTip("Ferma la verifica dopo il controllo in corso")
        self.stop_button.clicked.connect(self.stop)
        self.close_button = QPushButton(icon("mdi6.check", "white"), "Chiudi")
        self.close_button.setProperty("primary", True)
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addLayout(buttons)

    def step(self, done, total, check):
        """Progress of the run (see checks.run): False when the user stopped it."""
        if check is not None:
            self.steps.append((done, total, check.code))
            self.bar.setMaximum(max(total, 1))
            self.bar.setValue(done)
            self.label.setText(f"Verifica del modello in corso…\n\nControllo {done + 1} di {total}: {check.code}\n"
                               f"{check.title}")
        else:
            self.steps.append((done, total, None))
        QApplication.processEvents()
        return not self.stopped

    def stop(self):
        self.stopped = True
        self.stop_button.setEnabled(False)
        self.label.setText("Interruzione della verifica dopo il controllo in corso…")

    def finish(self, done, total, counts):
        """The run ended (or was stopped): the outcome stays shown until «Chiudi»; the window no longer blocks
        the rest, so the findings can be read at once."""
        self.finished_run = True
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        if done < total:
            self.label.setText(f"Verifica interrotta: eseguiti {done} controlli su {total}.\n\n{summary(counts)}.")
        else:
            self.label.setText(f"Verifica del modello completata: {total} controlli eseguiti.\n\n{summary(counts)}.")
        self.stop_button.hide()  # nothing left to stop
        self.close_button.setEnabled(True)
        self.close_button.setDefault(True)
        if self.isVisible():
            self.hide()
            self.setWindowModality(Qt.NonModal)
            self.show()

    def closeEvent(self, event):
        if not self.finished_run:  # closed while running: the run stops
            self.stop()
        super().closeEvent(event)

    def reject(self):
        if not self.finished_run:  # Esc while running: stop
            self.stop()
            return
        super().reject()


class ChecksPanel(QWidget):
    open_requested = Signal(str, str)  # uuid of a sheet to open, field with the problem ("": the sheet)
    settings_requested = Signal()
    ran = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.findings = []
        self.has_run = False
        self._by_element = {}
        self.progress = None  # window of the last run
        self.stopped_at = None  # (checks run, checks active) when the last run was stopped
        # Who may accept a finding as an exception: the Design Authority (set by the main window: () → name of the
        # user if a member of the DA, else None).
        self.design_authority = lambda: None

        self.filters = {}
        for s in (ERROR, WARNING, INFO, WAIVED):
            b = QPushButton(severity_icon(s), "")
            b.setCheckable(True)
            b.setChecked(s != WAIVED)  # the exceptions are hidden until asked for
            b.setToolTip("Mostra o nasconde le segnalazioni accettate come eccezioni dalla Design Authority"
                         if s == WAIVED else f"Mostra o nasconde: {SEVERITY_PLURAL[s][1]}")
            b.toggled.connect(self._fill)
            self.filters[s] = b
        self.search = QLineEdit(placeholderText="Cerca nelle segnalazioni…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        settings = QPushButton(icon("mdi6.cog-outline"), "Impostazioni verifiche…")
        settings.clicked.connect(self.settings_requested)
        self.status = QLabel(objectName="muted")
        bar = QHBoxLayout()  # the checks are run only from «Verifica modello», in the toolbar of the window
        for b in self.filters.values():
            bar.addWidget(b)
        bar.addWidget(self.search, 1)
        bar.addWidget(settings)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Segnalazione", "Codice", "Scheda", "Regola"])
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.resizeSection(2, 260)
        header.resizeSection(3, 180)
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.itemActivated.connect(self._open)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.empty = QLabel(alignment=Qt.AlignCenter, objectName="muted")
        self.empty.setWordWrap(True)
        self.empty_settings = QPushButton(icon("mdi6.cog-outline"), "Scegli i controlli")
        self.empty_settings.clicked.connect(self.settings_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addLayout(bar)
        layout.addWidget(self.status)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.empty, 1)
        layout.addWidget(self.empty_settings, 0, Qt.AlignHCenter)
        self.set_project(None)

    # --- project and runs --------------------------------------------------------------------

    def set_project(self, project):
        self.project = project
        self.findings, self.has_run, self._by_element = [], False, {}
        self._fill()

    def enabled_count(self):
        return enabled_count(self.project)

    def run(self, show_progress=True):
        """Run the active checks. show_progress: the window with the check running, «Interrompi» and, at the
        end, the outcome until «Chiudi» («Verifica modello»); not for the runs after a save."""
        if self.project is None:
            return
        if self.progress is not None and show_progress:
            self.progress.close()  # the window of the previous run
        QApplication.setOverrideCursor(Qt.WaitCursor)  # a couple of seconds on thousands of SRS items
        progress = CheckProgress(self.window()) if show_progress else None
        steps = []
        if progress is not None:
            self.progress = progress
            progress.show()
        try:
            self.findings = run_checks(self.project, progress.step if progress is not None else
                                       lambda done, total, c: steps.append((done, total, c)))
        finally:
            QApplication.restoreOverrideCursor()
        last = (progress.steps if progress is not None else steps) or [(0, 0, None)]
        done, total, _ = last[-1]
        self.stopped_at = (done, total) if done < total else None
        if progress is not None:
            progress.finish(done, total, count(self.findings))
        self.has_run = True
        self._ran_at = datetime.now()
        self._findings_changed()

    def _findings_changed(self):
        self._by_element = defaultdict(list)
        for f in self.findings:
            if f.element and not f.waived:
                self._by_element[f.element].append(f)
        self._fill()
        self.ran.emit()

    # --- exceptions of the Design Authority ----------------------------------------------------

    def accept_exception(self, finding, reason, author):
        """Record the finding as accepted (checks.yaml, shared): it is no longer counted while its sheet does
        not change."""
        config = self.project.checks.copy()
        config.add_exception(finding, self.project.model.get(finding.element), reason, author)
        self.project.update_checks(config)
        self._set_exception(finding, self.project.checks.exception_of(finding))

    def revoke_exception(self, finding):
        config = self.project.checks.copy()
        config.remove_exception(finding)
        self.project.update_checks(config)
        self._set_exception(finding, None)

    def _set_exception(self, finding, exception):
        key = (finding.code, finding.element, finding.message)
        self.findings = [replace(f, exception=exception) if (f.code, f.element, f.message) == key else f
                         for f in self.findings]
        self._findings_changed()

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        finding = item.data(0, FINDING_ROLE) if item is not None else None
        if finding is None:
            return
        menu = QMenu(self)
        menu.addAction(icon("mdi6.open-in-app"), "Apri la scheda", lambda: self._open(item))
        menu.addSeparator()
        author = self.design_authority()
        if finding.waived:
            action = menu.addAction(icon("mdi6.shield-off-outline"), "Revoca eccezione",
                                    lambda: self.revoke_exception(finding))
        else:
            action = menu.addAction(icon(WAIVED_ICON), "Accetta come eccezione…", lambda: self._ask_exception(finding))
            action.setEnabled(bool(finding.element) and self.project.model.get(finding.element) is not None)
        if author is None:
            action.setEnabled(False)
            action.setToolTip("Solo i membri della Design Authority accettano o revocano le eccezioni")
            menu.setToolTipsVisible(True)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _ask_exception(self, finding):
        author = self.design_authority()
        if author is None:
            QMessageBox.information(self, "Accetta come eccezione",
                                    "Solo i membri della Design Authority possono accettare una segnalazione come "
                                    "eccezione.")
            return
        element = self.project.model.get(finding.element)
        dialog = ExceptionDialog(finding, self.project.model.label(element), self)
        if dialog.exec():
            self.accept_exception(finding, dialog.text(), author)

    def refresh(self):
        """The settings of the checks changed: run them again if they had been run, else update the view."""
        if self.has_run:
            self.run(show_progress=False)
        else:
            self._fill()

    def findings_for(self, uuid):
        """Findings whose sheet is the element (shown at the top of its sheet), but those accepted as
        exceptions."""
        return list(self._by_element.get(uuid, []))

    def counts(self):
        return count(self.findings)

    # --- view --------------------------------------------------------------------------------

    def _fill(self):
        self.tree.clear()
        active = self.enabled_count()
        message = None
        if self.project is None:
            message = "Apri un progetto per verificarne il modello."
        elif not active:
            message = ("Nessun controllo attivo. Scegli quelli da eseguire in Progetto › Impostazioni › Verifiche: "
                       "la scelta resta salvata nel progetto.")
        elif not self.has_run:
            message = f"{active} controlli attivi. Usa «Verifica modello» nella barra in alto (F7) per controllare il modello."
        elif not self.findings:
            message = f"Nessuna violazione nei {active} controlli attivi."
        elif all(f.waived for f in self.findings) and not self.filters[WAIVED].isChecked():
            message = (f"Nessuna violazione nei {active} controlli attivi, a parte quelle accettate come eccezioni "
                       "(mostrale con il filtro accanto agli altri).")
        counts = count(self.findings)
        for s, b in self.filters.items():
            b.setText(str(counts[s]) if self.has_run else "")
        self.filters[WAIVED].setVisible(bool(counts[WAIVED]))
        if self.has_run and self.project is not None:
            stopped = (f" · verifica interrotta dopo {self.stopped_at[0]} controlli su {self.stopped_at[1]}"
                       if self.stopped_at else "")
            self.status.setText(f"{active} controlli attivi · {summary(self.counts())} · eseguiti alle "
                                f"{self._ran_at:%H:%M:%S}{stopped}")
        else:
            self.status.setText("")
        self.tree.setVisible(message is None)
        self.empty.setVisible(message is not None)
        self.empty.setText(message or "")
        self.empty_settings.setVisible(self.project is not None and not active)
        if message is not None:
            return
        words = self.search.text().lower().split()
        model = self.project.model
        groups = {}
        for f in self.findings:
            if not self.filters[WAIVED if f.waived else f.severity].isChecked():
                continue
            check = CHECKS_BY_CODE[f.code]
            element = model.get(f.element) if f.element else None
            where = model.label(element) if element is not None else "Progetto"
            waived = exception_text(f.exception) if f.waived else ""
            haystack = " ".join((f.message, f.code, check.title, where, check.ref, waived)).lower()
            if words and not all(w in haystack for w in words):
                continue
            group = groups.get(f.group)
            if group is None:
                group = groups[f.group] = QTreeWidgetItem([GROUP_LABELS[f.group]])
                font = group.font(0)
                font.setBold(True)
                group.setFont(0, font)
                group.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(group)
            item = QTreeWidgetItem([f.message, f.code, where, check.ref])
            item.setIcon(0, severity_icon(WAIVED if f.waived else f.severity))
            item.setToolTip(0, f"{SEVERITY_LABELS[f.severity]} · {f.code} {check.title}\n{f.message}" +
                            (f"\n\n{waived}" if waived else ""))
            item.setToolTip(1, check.title)
            item.setData(0, FINDING_ROLE, f)
            if f.waived:
                item.setForeground(0, QBrush(QColor(WAIVED_COLOR)))
                note = QTreeWidgetItem([waived, "", "", ""])
                note.setIcon(0, icon("mdi6.comment-text-outline", WAIVED_COLOR))
                note.setForeground(0, QBrush(QColor(MUTED)))
                item.addChild(note)
            if element is not None:
                item.setIcon(2, kind_icon(element.kind))
                item.setData(0, UUID_ROLE, element.uuid)
                item.setData(0, FIELD_ROLE, f.field)  # a double click opens the sheet at that field
            group.addChild(item)
            for uuid in f.related:
                other = model.get(uuid)
                if other is None:
                    continue
                child = QTreeWidgetItem([f"Scheda coinvolta: {model.label(other)}", "", other.schema.label, ""])
                child.setIcon(0, kind_icon(other.kind))
                child.setForeground(0, QBrush(QColor(MUTED)))
                child.setData(0, UUID_ROLE, uuid)
                item.addChild(child)
        for group in groups.values():
            group.setText(1, str(group.childCount()))
            group.setExpanded(True)
            for i in range(group.childCount()):
                child = group.child(i)
                child.setExpanded(child.data(0, FINDING_ROLE).waived)  # the reason of an exception at sight
        if not groups:
            self.tree.setVisible(False)
            self.empty.setVisible(True)
            self.empty.setText("Nessuna segnalazione con i filtri scelti.")

    def _open(self, item, _column=0):
        uuid = item.data(0, UUID_ROLE)
        if uuid and self.project is not None and self.project.model.get(uuid) is not None:
            self.open_requested.emit(uuid, item.data(0, FIELD_ROLE) or "")

    def headline(self):
        """Text of the title bar of the panel, also when it is collapsed."""
        if self.project is None:
            return "Verifiche"
        if not self.has_run:
            return "Analisi del modello"
        stopped = " · interrotta" if self.stopped_at else ""
        return f"Verifiche · {summary(self.counts())} · {self._ran_at:%H:%M}{stopped}"


class _TitleBar(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ChecksDock(QDockWidget):
    """The panel of the findings at the bottom of the window: always there, collapsed to its title bar until a
    run of the checks opens it. Not pinned, it collapses again when the user goes back to work in the rest of the
    window; pinned (the pin next to the ×), it stays open. The pin is kept on this PC."""

    def __init__(self, panel, parent=None):
        super().__init__("Verifiche", parent, objectName="checksDock")
        self.panel = panel
        self.expanded = False
        self.pinned = settings().value(PINNED_SETTING, False, bool)
        self._height = EXPANDED_HEIGHT

        bar = _TitleBar(objectName="dockTitle")
        bar.setStyleSheet(f"QFrame#dockTitle {{ background: {SURFACE}; }}")  # the line above: the separator
        bar.setCursor(Qt.PointingHandCursor)
        bar.setToolTip("Mostra o nasconde le segnalazioni delle verifiche")
        bar.clicked.connect(self.toggle)
        self.arrow = QToolButton(autoRaise=True)
        self.arrow.clicked.connect(self.toggle)
        self.title = QLabel(objectName="cardTitle")
        self.pin_button = QToolButton(autoRaise=True, checkable=True)
        self.pin_button.toggled.connect(self.set_pinned)
        close = QToolButton(autoRaise=True)
        close.setIcon(icon("mdi6.close", MUTED))
        close.setToolTip("Chiudi il pannello (resta disponibile, ridotto, in fondo alla finestra)")
        close.clicked.connect(self.close_panel)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 2, 4, 2)
        row.addWidget(self.arrow)
        row.addWidget(self.title, 1)
        row.addWidget(self.pin_button)
        row.addWidget(close)
        self.bar = bar
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setTitleBarWidget(bar)
        # The content stays visible (empty when collapsed): a dock without visible content would be laid out at
        # the width of its title, not across the window.
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(panel)
        self.setWidget(holder)
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.setAllowedAreas(Qt.BottomDockWidgetArea)
        panel.ran.connect(self.update_title)
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self.pin_button.setChecked(self.pinned)
        self._apply()

    def update_title(self):
        self.title.setText(self.panel.headline())

    def expand(self):
        if not self.expanded:
            self.expanded = True
            self._apply()

    def collapse(self):
        if self.expanded:
            self._height = max(self.height(), MIN_EXPANDED_HEIGHT)
            self.expanded = False
            self._apply()

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    def close_panel(self):
        self.set_pinned(False)
        self.collapse()

    def set_pinned(self, pinned):
        self.pinned = pinned
        settings().setValue(PINNED_SETTING, pinned)
        if self.pin_button.isChecked() != pinned:
            self.pin_button.setChecked(pinned)
        if pinned:
            self.expand()
        self._apply()

    def reset(self):
        """A project was opened or closed: open only if pinned."""
        self.expanded = self.pinned and self.panel.project is not None
        self._apply()

    def _apply(self):
        self.panel.setVisible(self.expanded)
        if self.expanded:
            self.setMinimumHeight(MIN_EXPANDED_HEIGHT)
            self.setMaximumHeight(QWIDGETSIZE_MAX)
            if self.parent() is not None:
                self.parent().resizeDocks([self], [self._height], Qt.Vertical)
        else:
            height = self.bar.sizeHint().height()
            self.setMinimumHeight(height)
            self.setMaximumHeight(height)
        self.arrow.setIcon(icon("mdi6.chevron-down" if self.expanded else "mdi6.chevron-up", TEXT))
        self.arrow.setToolTip("Riduci il pannello" if self.expanded else "Apri il pannello")
        self.pin_button.setIcon(icon("mdi6.pin" if self.pinned else "mdi6.pin-outline",
                                     ACCENT if self.pinned else MUTED))
        self.pin_button.setToolTip("Pannello fisso: resta aperto (clic per sbloccarlo)" if self.pinned else
                                   "Rendi fisso il pannello: resta aperto anche quando lavori nel resto della "
                                   "finestra")
        self.update_title()

    def _focus_changed(self, old, new):
        """Not pinned: the focus going, inside the window, from one of its widgets to one outside the panel is
        back to work, and the panel collapses. The focus coming back from another application (Alt+Tab: no old
        widget) or from a dialog (old widget in another window) leaves it as it is."""
        if old is None or new is None or old.window() is not self.window():
            return
        self.clicked_outside(new)

    def clicked_outside(self, widget):
        if not self.expanded or self.pinned or widget is self or self.isAncestorOf(widget):
            return
        if widget.window() is self.window():
            self.collapse()
