"""Progetto › Impostazioni › Verifiche: the profiles of checks (checks.yaml, shared with the team). A profile has
its active checks (none by default), divided by group as in the methodology, and for each check what differs
from the methodology: its parameters, its severity and its scope (status and domains of the sheets). On the left
the checks, on the right the details of the selected one."""
import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from arcadia_tool.checks import (CHECKS, CHECKS_BY_CODE, ERROR, GROUPS, INFO, SEVERITY_LABELS, WARNING,
                                 checks_of_group)
from arcadia_tool.checks.config import SCOPE_STATUS, ChecksConfig
from arcadia_tool.checks.params import (BOOL, DOMAIN, DOMAINS, INT, MAP_REGEX, MAP_STRINGS, REGEX, STRINGS,
                                        key_label, params_of)
from arcadia_tool.ui.theme import ACCENT, MUTED, icon

CODE_ROLE = Qt.UserRole
SEVERITY_TEXT = {s: "/".join(SEVERITY_LABELS[p] for p in s.split("/")) for s in ("E", "A", "I", "E/A", "A/E")}
PROBLEM_COLOR = "#B42318"


def severity_text(severity):
    return SEVERITY_TEXT.get(severity, severity)


def _split(text):
    return [part.strip() for part in (text or "").split(",") if part.strip()]


class ChecksSettingsPage(QWidget):
    changed = Signal()

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = project
        self.config = project.checks.copy() if project.checks is not None else ChecksConfig()
        self.current = None  # code of the check shown on the right
        self.icons = {True: icon("mdi6.checkbox-marked", ACCENT), False: icon("mdi6.checkbox-blank-outline", MUTED),
                      None: icon("mdi6.minus-box", ACCENT)}
        self.custom_icon = icon("mdi6.pencil-circle", ACCENT)

        note = QLabel("Condivise con il team: salvate nel progetto (checks.yaml) e pubblicate con le versioni; "
                      "restano attive finché non le cambi. Di default nessun controllo è attivo. Gli errori non "
                      "bloccano la pubblicazione.", objectName="muted")
        note.setWordWrap(True)

        # Profiles: «Verifica modello» runs the active one.
        self.profile = QComboBox()
        self.profile.setMinimumWidth(220)
        self.profile.setToolTip("Il profilo che «Verifica modello» esegue, per tutto il team (salvato nel progetto)")
        self.profile.currentTextChanged.connect(self._profile_chosen)
        new = QPushButton(icon("mdi6.plus"), "Nuovo…")
        new.setToolTip("Nuovo profilo, copia di quello scelto")
        new.clicked.connect(self._new_profile)
        rename = QPushButton(icon("mdi6.rename-outline"), "Rinomina…")
        rename.clicked.connect(self._rename_profile)
        self.remove = QPushButton(icon("mdi6.delete-outline"), "Elimina")
        self.remove.clicked.connect(self._remove_profile)
        profiles = QHBoxLayout()
        profiles.addWidget(QLabel("Profilo"))
        profiles.addWidget(self.profile)
        profiles.addWidget(new)
        profiles.addWidget(rename)
        profiles.addWidget(self.remove)
        profiles.addStretch()

        self.search = QLineEdit(placeholderText="Cerca per codice, descrizione o regola…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        all_on = QPushButton(icon("mdi6.checkbox-multiple-marked-outline"), "Attiva tutti")
        all_on.clicked.connect(lambda: self._set_all(True))
        all_off = QPushButton(icon("mdi6.checkbox-multiple-blank-outline"), "Disattiva tutti")
        all_off.clicked.connect(lambda: self._set_all(False))
        self.counter = QLabel(objectName="muted")
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(all_on)
        bar.addWidget(all_off)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Controllo", "Gravità", "Regola"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.resizeSection(2, 110)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.currentItemChanged.connect(lambda item, _old: self._show(item))
        self.groups, self.items = {}, {}
        for key, label in GROUPS:
            group = QTreeWidgetItem([label])
            group.setData(0, CODE_ROLE, None)
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            self.tree.addTopLevelItem(group)
            self.groups[key] = group
            for c in checks_of_group(key):
                item = QTreeWidgetItem([f"{c.code}   {c.title}", "", c.ref])
                item.setData(0, CODE_ROLE, c.code)
                for column in range(3):
                    item.setToolTip(column, c.title)
                group.addChild(item)
                self.items[c.code] = item
        self.tree.collapseAll()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(bar)
        left_layout.addWidget(self.tree, 1)
        left_layout.addWidget(self.counter)

        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QFrame.NoFrame)
        self.detail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.detail.setMinimumWidth(380)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([540, 420])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(note)
        layout.addLayout(profiles)
        layout.addWidget(splitter, 1)
        self._fill_profiles()
        self._refresh()
        self._show(None)

    @property
    def enabled(self):
        return set(self.config.profile.enabled)

    # --- profiles ----------------------------------------------------------------------------

    def _fill_profiles(self):
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItems(list(self.config.profiles))
        self.profile.setCurrentText(self.config.active)
        self.profile.blockSignals(False)
        self.remove.setEnabled(len(self.config.profiles) > 1)

    def _profile_chosen(self, name):
        if name and name in self.config.profiles and name != self.config.active:
            self.config.active = name
            self._refresh()
            self._show(self.tree.currentItem())
            self.changed.emit()

    def _ask_name(self, title, current=""):
        name, ok = QInputDialog.getText(self, title, "Nome del profilo", text=current)
        name = " ".join((name or "").split())
        if not ok or not name or name == current:
            return None
        if name in self.config.profiles:
            QMessageBox.warning(self, title, f"Esiste già un profilo «{name}».")
            return None
        return name

    def _new_profile(self):
        name = self._ask_name("Nuovo profilo")
        if name:
            self.config.add_profile(name)
            self._profile_changed()

    def _rename_profile(self):
        name = self._ask_name("Rinomina profilo", self.config.active)
        if name:
            self.config.rename_profile(self.config.active, name)
            self._profile_changed()

    def _remove_profile(self):
        if len(self.config.profiles) > 1 and QMessageBox.question(
                self, "Elimina profilo", f"Eliminare il profilo «{self.config.active}»?") == QMessageBox.Yes:
            self.config.remove_profile(self.config.active)
            self._profile_changed()

    def _profile_changed(self):
        self._fill_profiles()
        self._refresh()
        self._show(self.tree.currentItem())
        self.changed.emit()

    # --- the list of checks ------------------------------------------------------------------

    def _refresh(self):
        profile = self.config.profile
        enabled = self.enabled
        for key, group in self.groups.items():
            codes = [c.code for c in checks_of_group(key)]
            on = sum(1 for c in codes if c in enabled)
            group.setIcon(0, self.icons[True if on == len(codes) else False if on == 0 else None])
            group.setText(1, f"{on} di {len(codes)}")
        for code, item in self.items.items():
            item.setIcon(0, self.icons[code in enabled])
            custom = profile.customized(code)
            item.setIcon(1, self.custom_icon if custom else icon("mdi6.circle-small", "transparent"))
            item.setText(1, severity_text(profile.severity.get(code) or CHECKS_BY_CODE[code].severity))
            item.setToolTip(1, "Personalizzato rispetto alla metodologia" if custom else "Come da metodologia")
        customized = sum(1 for c in CHECKS if profile.customized(c.code))
        self.counter.setText(f"{len(enabled)} controlli attivi su {len(CHECKS)}"
                             + (f" · {customized} personalizzati" if customized else "")
                             + (f" · {len(self.config.exceptions)} eccezioni registrate"
                                if self.config.exceptions else ""))

    def _clicked(self, item, column=0):
        """A click on the box (or on a group) turns the check on or off; elsewhere it shows its details."""
        code = item.data(0, CODE_ROLE)
        profile = self.config.profile
        if code is None:  # a group: all its checks on, or all off if they are all on already
            codes = {item.child(i).data(0, CODE_ROLE) for i in range(item.childCount())
                     if not item.child(i).isHidden()}
            enabled = self.enabled
            profile.enabled = sorted(enabled - codes if codes <= enabled else enabled | codes)
        elif column == 0 and self._on_box(item):
            self._toggle(code)
            return
        else:
            return
        self._refresh()
        self._show(self.tree.currentItem())
        self.changed.emit()

    def _on_box(self, item):
        """The click was on the box of the check (its icon), not on its text."""
        pos = self.tree.viewport().mapFromGlobal(self.cursor().pos())
        rect = self.tree.visualItemRect(item)
        return pos.x() < rect.left() + self.tree.iconSize().width() + 10 if rect.contains(pos) else True

    def _toggle(self, code, on=None):
        enabled = self.enabled
        on = code not in enabled if on is None else on
        self.config.profile.enabled = sorted(enabled | {code} if on else enabled - {code})
        self._refresh()
        if code == self.current and hasattr(self, "active_box"):
            self.active_box.blockSignals(True)
            self.active_box.setChecked(on)
            self.active_box.blockSignals(False)
        self.changed.emit()

    def _set_all(self, on):
        self.config.profile.enabled = [c.code for c in CHECKS] if on else []
        self._refresh()
        self._show(self.tree.currentItem())
        self.changed.emit()

    def _filter(self, text):
        words = text.lower().split()
        for group in self.groups.values():
            shown = 0
            for i in range(group.childCount()):
                child = group.child(i)
                haystack = " ".join(child.text(c) for c in range(3)).lower()
                hidden = bool(words) and not all(w in haystack for w in words)
                child.setHidden(hidden)
                shown += not hidden
            group.setHidden(shown == 0)
            group.setExpanded(bool(words) and shown > 0)

    # --- the details of a check --------------------------------------------------------------

    def _show(self, item):
        code = item.data(0, CODE_ROLE) if item is not None else None
        self.current = code
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 4, 8, 8)
        layout.setSpacing(10)
        if code is None:
            hint = QLabel("Scegli un controllo a sinistra per vederne i dettagli e personalizzarlo: parametri, "
                          "gravità e ambito (stato e domini delle schede). Il riquadro accanto al controllo lo "
                          "attiva o disattiva.", objectName="muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            layout.addStretch()
            self.detail.setWidget(page)
            return
        check = CHECKS_BY_CODE[code]
        profile = self.config.profile
        title = QLabel(f"<b>{code}</b> · {check.title}")
        title.setWordWrap(True)
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        ref = QLabel(f"Regola della metodologia: {check.ref} · gravità della metodologia: "
                     f"{severity_text(check.severity)}", objectName="muted")
        ref.setWordWrap(True)
        layout.addWidget(ref)
        self.active_box = QCheckBox(f"Attivo nel profilo «{self.config.active}»")
        self.active_box.setChecked(code in self.enabled)
        self.active_box.toggled.connect(lambda on: self._toggle(code, on))
        layout.addWidget(self.active_box)

        form = self._form()
        severity = self._combo()
        severity.addItem(f"Come da metodologia ({severity_text(check.severity)})", "")
        for s in (ERROR, WARNING, INFO):
            severity.addItem(SEVERITY_LABELS[s], s)
        severity.setCurrentIndex(max(0, severity.findData(profile.severity.get(code) or "")))
        severity.currentIndexChanged.connect(lambda _i: self._set(profile.severity, code, severity.currentData()))
        form.addRow("Gravità", severity)
        scope = dict(profile.scope.get(code) or {})
        status = self._combo()
        for key, label in SCOPE_STATUS.items():
            status.addItem(label, key)
        status.setCurrentIndex(max(0, status.findData(scope.get("status") or "all")))
        status.setToolTip("Le schede senza stato sono sempre controllate")
        form.addRow("Ambito: schede", status)
        domains = QListWidget()
        domains.setFixedHeight(110)
        domains.setToolTip("Nessun dominio spuntato: tutti. Le schede che non appartengono a un dominio sono sempre "
                           "controllate.")
        for d in self.project.model.of_kind("domain"):
            row = QListWidgetItem(self.project.model.label(d))
            row.setData(Qt.UserRole, d.uuid)
            row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked if d.uuid in (scope.get("domains") or []) else Qt.Unchecked)
            domains.addItem(row)

        def scope_changed(*_args):
            value = {}
            if status.currentData() != "all":
                value["status"] = status.currentData()
            chosen = [domains.item(i).data(Qt.UserRole) for i in range(domains.count())
                      if domains.item(i).checkState() == Qt.Checked]
            if chosen:
                value["domains"] = chosen
            self._set(profile.scope, code, value)

        status.currentIndexChanged.connect(scope_changed)
        domains.itemChanged.connect(scope_changed)
        form.addRow("Ambito: domini", domains)
        layout.addWidget(self._card("GRAVITÀ E AMBITO", form))

        params = params_of(code)
        if params:
            pform = self._form()
            for p in params:
                widget, problem = self._param_widget(code, p)
                box = QVBoxLayout()
                box.setSpacing(2)
                box.addWidget(widget)
                if p.hint:
                    hint = QLabel(p.hint, objectName="muted")
                    hint.setWordWrap(True)
                    box.addWidget(hint)
                box.addWidget(problem)
                holder = QWidget()
                holder.setLayout(box)
                box.setContentsMargins(0, 0, 0, 0)
                pform.addRow(p.label + (" *" if p.required else ""), holder)
            layout.addWidget(self._card("PARAMETRI", pform))
        else:
            none = QLabel("Questo controllo non ha parametri.", objectName="muted")
            layout.addWidget(none)

        reset = QPushButton(icon("mdi6.restore"), "Ripristina valori della metodologia")
        reset.setEnabled(profile.customized(code))
        reset.clicked.connect(lambda: self._reset(code))
        layout.addWidget(reset, 0, Qt.AlignLeft)
        self.reset_button = reset
        layout.addStretch()
        self.detail.setWidget(page)

    @staticmethod
    def _form():
        """Labels above their fields: the pane of the details stays narrow."""
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setVerticalSpacing(4)
        return form

    @staticmethod
    def _combo():
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        return combo

    @staticmethod
    def _card(caption, inner):
        card = QFrame(objectName="card")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 10, 14, 12)
        box.addWidget(QLabel(caption, objectName="sectionCaption"))
        box.addLayout(inner)
        return card

    def _param_widget(self, code, p):
        """The widget of a parameter, already showing its value, and the label of its problem."""
        profile = self.config.profile
        value = profile.param(code, p.name)
        problem = QLabel(styleSheet=f"color: {PROBLEM_COLOR};")
        problem.setWordWrap(True)

        def store(new):
            stored = dict(profile.params.get(code) or {})
            if new == p.default or (new in (None, "", [], {}) and p.default in (None, "", [], {})):
                stored.pop(p.name, None)
            else:
                stored[p.name] = new
            self._set(profile.params, code, stored)
            show_problem(new)

        def show_problem(new):
            text = p.problem(new, self.project.model) or ""
            problem.setText(text)
            problem.setVisible(bool(text))

        if p.type == INT:
            widget = QSpinBox(minimum=p.minimum if p.minimum is not None else 0,
                              maximum=p.maximum if p.maximum is not None else 9999)
            widget.setValue(value if isinstance(value, int) else p.default)
            widget.valueChanged.connect(store)
        elif p.type == BOOL:
            widget = QCheckBox("Sì")
            widget.setChecked(bool(value))
            widget.toggled.connect(store)
        elif p.type in (STRINGS, REGEX):
            text = ", ".join(value or []) if p.type == STRINGS else (value or "")
            widget = QLineEdit(text)
            if p.type == STRINGS:
                widget.setPlaceholderText("Valori separati da virgola")
                widget.textChanged.connect(lambda t: store(_split(t)))
            else:
                widget.textChanged.connect(lambda t: store(t.strip()))
        elif p.type == DOMAIN:
            widget = self._combo()
            widget.addItem("— nessuno —", "")
            for d in self.project.model.of_kind("domain"):
                widget.addItem(self.project.model.label(d), d.uuid)
            widget.setCurrentIndex(max(0, widget.findData(value or "")))
            widget.currentIndexChanged.connect(lambda _i: store(widget.currentData() or None))
        elif p.type == DOMAINS:
            widget = QListWidget()
            widget.setFixedHeight(110)
            for d in self.project.model.of_kind("domain"):
                row = QListWidgetItem(self.project.model.label(d))
                row.setData(Qt.UserRole, d.uuid)
                row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                row.setCheckState(Qt.Checked if d.uuid in (value or []) else Qt.Unchecked)
                widget.addItem(row)
            widget.itemChanged.connect(lambda _row: store(
                [widget.item(i).data(Qt.UserRole) for i in range(widget.count())
                 if widget.item(i).checkState() == Qt.Checked]))
        else:  # MAP_STRINGS, MAP_REGEX: one row per key
            current = copy.deepcopy(value or {})
            widget = QTableWidget(len(p.keys), 1)
            widget.setHorizontalHeaderLabels(["Espressione regolare" if p.type == MAP_REGEX else
                                              "Valori separati da virgola"])
            widget.setVerticalHeaderLabels([key_label(p, k) for k in p.keys])
            widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            widget.setMinimumHeight(min(360, 30 + 26 * len(p.keys)))
            for row, key in enumerate(p.keys):
                cell = current.get(key)
                text = ", ".join(cell or []) if p.type == MAP_STRINGS else (cell or "")
                widget.setItem(row, 0, QTableWidgetItem(text))

            def map_changed(cell):
                key = p.keys[cell.row()]
                text = cell.text().strip()
                if text:
                    current[key] = _split(text) if p.type == MAP_STRINGS else text
                elif p.type == MAP_STRINGS:
                    current[key] = []
                else:
                    current[key] = ""  # a kind without format is not checked
                store(copy.deepcopy(current))

            widget.itemChanged.connect(map_changed)
        show_problem(value)
        return widget, problem

    def _set(self, mapping, code, value):
        if value:
            mapping[code] = value
        else:
            mapping.pop(code, None)
        self._refresh()
        if getattr(self, "reset_button", None) is not None and code == self.current:
            self.reset_button.setEnabled(self.config.profile.customized(code))
        self.changed.emit()

    def _reset(self, code):
        self.config.profile.reset(code)
        self._refresh()
        self._show(self.items[code])
        self.changed.emit()

    # --- result ------------------------------------------------------------------------------

    def value(self):
        """What to save in checks.yaml (a ChecksConfig)."""
        return self.config.copy()
