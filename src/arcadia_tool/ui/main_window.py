from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox,
                               QProgressDialog, QPushButton, QSplitter, QStackedWidget, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from arcadia_tool import APP_NAME, __version__
from arcadia_tool.accounts import git_credentials
from arcadia_tool.storage.project import (Project, ProjectError, describe_project, forget_local_changes,
                                          local_changes, read_recovery_info, recovery_file)
from arcadia_tool.storage.repository import PROJECT_FILE
from arcadia_tool.storage.trash import move_to_trash

TAB_TITLE_LENGTH = 48
from arcadia_tool.ui.dialogs import NewProjectDialog, settings
from arcadia_tool.ui.accounts import AccountDialog, account_store, require_login
from arcadia_tool.ui.branding import FittedImage, logo_size, vertical_logo
from arcadia_tool.checks import problems as check_problems
from arcadia_tool.model.schema import KINDS_BY_NAME
from arcadia_tool.model.teams import (access_denied, design_authority, edit_denied, is_da_member, locks_out,
                                      memberships)
from arcadia_tool.ui.checks_panel import ChecksDock, ChecksPanel, summary
from arcadia_tool.ui.clone import CloneDialog
from arcadia_tool.ui.diagrams import BreakdownPage, DiagramPage, resolve_unsaved_view
from arcadia_tool.ui.migrate import MigrationDialog, ReloadDialog
from arcadia_tool.ui.push import PushDialog
from arcadia_tool.ui.receive import ReceiveDialog
from arcadia_tool.ui.element_editor import ElementEditor, ElementWindow, resolve_unsaved
from arcadia_tool.ui.element_list import ElementListPage
from arcadia_tool.ui.project_settings import ProjectSettingsDialog, recovery_minutes
from arcadia_tool.ui.import_srs import ImportSrsDialog
from arcadia_tool.ui.loading import LoadingDialog
from arcadia_tool.ui.activity_bar import ActivityBar
from arcadia_tool.ui.model_tree import TAB_ICONS, ModelTree
from arcadia_tool.ui.srs_edit_mode import SrsEditMode
from arcadia_tool.ui.srs_reader import SrsReader, SrsReaderWindow
from arcadia_tool.ui.start_page import StartPage
from arcadia_tool.ui.theme import ACCENT, CHANGE_COLORS, TEXT, icon, kind_icon
from arcadia_tool.ui.branches import BranchesDialog
from arcadia_tool.ui.versions import CompareDialog, HistoryDialog, PublishDialog

MAX_RECENT = 8


def show_check_problems(parent, problems):
    """Error message of «Verifica modello» when the checks cannot run. Returns True to open their settings."""
    box = QMessageBox(QMessageBox.Critical, "Verifica modello", "Non è possibile verificare il modello.",
                      parent=parent)
    box.setInformativeText("\n".join(f"• {p}" for p in problems))
    open_settings = box.addButton("Apri impostazioni verifiche", QMessageBox.AcceptRole)
    box.addButton("Chiudi", QMessageBox.RejectRole)
    box.setDefaultButton(open_settings)
    box.exec()
    return box.clickedButton() is open_settings


def show_access_denied(parent, reason, user):
    """The project is not opened: the user is not among the members of its teams. Their ID can be copied, to send
    it to the Design Authority."""
    box = QMessageBox(QMessageBox.Warning, "Apri progetto", "Non puoi accedere a questo progetto.", parent=parent)
    ident = getattr(user, "id", "") if user is not None else ""
    box.setInformativeText(reason + (f"\n\nID del tuo account: {ident}" if ident else ""))
    copy = box.addButton("Copia l'ID e chiudi", QMessageBox.AcceptRole) if ident else None
    box.addButton("Chiudi", QMessageBox.RejectRole)
    box.exec()
    if copy is not None and box.clickedButton() is copy:
        QApplication.clipboard().setText(ident)


SAVE_PROGRESS_THRESHOLD = 300


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = None
        self.user = None  # the logged-in account (see app.main): author of the published versions
        self.resize(1440, 880)
        # Unsaved edits are copied to the project's recovery file, restored after an unexpected interruption.
        self._recovery_pending = False
        self.recovery_timer = QTimer(self, interval=recovery_minutes() * 60_000, timeout=self.write_recovery)
        self.recovery_timer.start()

        self.start = StartPage()
        self.start.new_requested.connect(self.new_project)
        self.start.open_requested.connect(self.open_project_dialog)
        self.start.clone_requested.connect(self.clone_project_dialog)
        self.start.recent_requested.connect(self.open_project)
        self.start.delete_requested.connect(self.delete_project)
        self.start.forget_requested.connect(self.forget_project)
        self.srs_edit_mode = SrsEditMode()
        self.tree = ModelTree(self.srs_edit_mode)
        # One tab per opened element, closed only by the user (or when its element is deleted).
        self.editors = {}  # element uuid → ElementEditor in a tab
        self._idle_editor = ElementEditor(self.srs_edit_mode)  # «editor» when no element tab is shown
        self._last_editor = None
        self.reader = None
        self.pages = QTabWidget()
        self.pages.setDocumentMode(True)
        self.pages.setTabsClosable(True)
        # No tab until an element is opened: its tab is named after it (see _show_editor).
        self.pages.tabCloseRequested.connect(self._close_page)
        self.pages.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)  # close this tab, the others, all of them
        self.pages.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.pages.currentChanged.connect(self._page_changed)
        # With no tab open the vertical logo (it has the name too) is shown in place of the empty tab area.
        self.no_pages = QWidget()
        empty = QVBoxLayout(self.no_pages)
        empty.addWidget(FittedImage(vertical_logo(), logo_size()))  # its size, reduced only to fit the area
        self.work_area = QStackedWidget()
        self.work_area.addWidget(self.no_pages)
        self.work_area.addWidget(self.pages)
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.work_area)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 1100])
        # At its left the bar of icons: the tabs of the panel, and the panel closed to the left and opened again.
        self.activity = ActivityBar(self.tree, self.tree.tabs, splitter, TAB_ICONS, settings())
        workspace = QWidget()
        row = QHBoxLayout(workspace)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.activity)
        row.addWidget(splitter, 1)
        QShortcut(QKeySequence("Ctrl+Shift+B"), self, activated=self.activity.toggle)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(workspace)
        self.setCentralWidget(self.stack)

        self.tree.edit_denied = self.edit_denied
        self._just_created = set()  # elements created with «Nuovo…» whose sheet has not opened yet
        self.tree.element_created.connect(self._just_created.add)
        self.tree.locks_out = self.locks_out
        self.tree.element_selected.connect(self._select)
        self.tree.model_changed.connect(self._model_changed)
        self.tree.srs_reader_requested.connect(self.open_srs_reader)
        self.tree.srs_window_requested.connect(self.open_srs_window)
        self.tree.import_requested.connect(self.import_srs)
        self.tree.list_requested.connect(self.open_element_list)
        self.tree.breakdown_requested.connect(self.open_breakdown)
        self.tree.view_created.connect(lambda _uuid: self._diagram_saved("Vista creata"))
        self.list_pages = {}  # kind → tab with its elements as a table (e.g. X-2, the requests for clarification)
        # Graphic views in a tab: uuid of a view → DiagramPage; «breakdown:<kind>» → the functional breakdown.
        self.diagram_pages = {}
        self.reader_window = None  # the SRS catalogue in its own window («Apri in altra finestra»)
        self.item_window = None  # separate window for an element linked to the page (e.g. a traced SRS item)

        # Checks of the methodology: findings in a panel at the bottom, and in the header of the sheets.
        self.checks = ChecksPanel()
        self.checks.open_requested.connect(self._open_finding)
        self.checks.settings_requested.connect(lambda: self.project_settings("Verifiche"))
        self.checks.ran.connect(self._findings_updated)
        self.checks.design_authority = lambda: self.user.full_name if self.user_is_da else None
        self.checks_dock = ChecksDock(self.checks, self)  # always there with a project: collapsed until a run
        self.verify_button = QPushButton(icon("mdi6.clipboard-check-outline", "white"), "Verifica modello")
        self.verify_button.setProperty("primary", True)
        self.verify_button.setMinimumHeight(34)
        self.verify_button.clicked.connect(self.verify_model)
        self.tree.add_footer(self.verify_button)  # below the model tree, enabled with valid settings only
        self.addDockWidget(Qt.BottomDockWidgetArea, self.checks_dock)
        self.checks_dock.hide()  # no project yet

        self._build_actions()
        self._build_status_bar()
        self._refresh_recent()
        self._refresh_state()

    def _action(self, text, icon_name, slot, shortcut=None, tip=None):
        action = QAction(icon(icon_name, TEXT), text, self)
        action.triggered.connect(lambda _checked=False: slot())
        if shortcut:
            action.setShortcut(shortcut)
        action.setToolTip(f"{tip or text}" + (f" ({QKeySequence(shortcut).toString()})" if shortcut else ""))
        return action

    def _build_actions(self):
        self.new_action = self._action("Nuovo", "mdi6.file-plus-outline", self.new_project, QKeySequence.New,
                                       "Nuovo progetto")
        self.open_action = self._action("Apri", "mdi6.folder-open-outline", self.open_project_dialog,
                                        QKeySequence.Open, "Apri progetto")
        self.save_action = self._action("Salva", "mdi6.content-save-outline", self.save,
                                        QKeySequence("Ctrl+Shift+S"), "Salva tutte le modifiche del modello, "
                                        "anche quelle delle schede e delle viste aperte")
        # Ctrl+S: only the tab shown, as its own «Salva».
        QShortcut(QKeySequence.Save, self, activated=self.save_tab)
        self.publish_action = self._action("Pubblica…", "mdi6.cloud-upload-outline", self.publish,
                                           QKeySequence("Ctrl+Shift+P"), "Pubblica una nuova versione del modello")
        self.compare_action = self._action("Confronta…", "mdi6.compare-horizontal", self.compare, None,
                                           "Confronta due versioni del modello")
        self.history_action = self._action("Cronologia", "mdi6.history", self.history, None,
                                           "Cronologia delle pubblicazioni")
        self.branches_action = self._action("Rami…", "mdi6.source-branch", self.show_branches, None,
                                            "Rami del progetto e del repository: nuovo ramo, cambio di ramo, "
                                            "cronologia e confronto")
        self.close_action = self._action("Chiudi progetto", "mdi6.close", self.close_project)
        self.import_action = self._action("Importa SRS…", "mdi6.file-import-outline", self.import_srs, None,
                                          "Importa le voci SRS dai PDF del SUBSET-026")
        self.clean_action = self._action("Pulisci progetto…", "mdi6.broom", self.clean_project, None,
                                         "Rimuove gli elementi del progetto (anche mantenendo le voci SRS)")
        self.remove_srs_action = self._action("Rimuovi tutte le voci SRS…", "mdi6.delete-sweep-outline",
                                              self.remove_all_srs, None, "Rimuove tutte le voci SRS importate")
        self.send_action = self._action("Invia al repository", "mdi6.cloud-upload", self.send_versions, None,
                                        "Invia al repository remoto le versioni pubblicate e non ancora inviate")
        self.clone_action = self._action("Scarica progetto da Git…", "mdi6.source-branch", self.clone_project_dialog,
                                         None, "Scarica un progetto da un repository Git remoto e lo apre")
        self.receive_action = self._action("Ricevi dal repository…", "mdi6.cloud-download", self.receive_versions,
                                           None, "Riceve le versioni pubblicate dai colleghi sul ramo di lavoro e le "
                                           "integra con le tue")
        self.reload_action = self._action("Ricarica dal repository…", "mdi6.cloud-download-outline",
                                          self.reload_from_remote, None,
                                          "Sostituisce il contenuto locale con il ramo di lavoro del repository")
        self.migrate_action = self._action("Migra repository…", "mdi6.transfer", self.migrate_repository, None,
                                           "Copia la storia del progetto (tutti i rami o alcuni) in un altro Git")
        self.settings_action = self._action("Impostazioni…", "mdi6.cog-outline", self.project_settings, None,
                                            "Nome, repository Git, verifiche e altri parametri del progetto")
        self.check_action = self._action("Verifica modello", "mdi6.clipboard-check-outline", self.verify_model,
                                         QKeySequence("F7"), "Esegue i controlli della metodologia attivi sul modello")
        self.check_settings_action = self._action("Impostazioni verifiche…", "mdi6.clipboard-edit-outline",
                                                  lambda: self.project_settings("Verifiche"), None,
                                                  "Sceglie i controlli da eseguire e i loro parametri")
        self.account_action = self._action("Modifica account…", "mdi6.account-edit-outline", self.edit_account,
                                           None, "Dati dell'utente e accesso ai repository Git")
        self.switch_user_action = self._action("Cambia utente…", "mdi6.account-switch-outline", self.switch_user,
                                               None, "Accedi con un altro account locale")

        bar = QToolBar("Principale", movable=False)
        bar.setIconSize(QSize(18, 18))
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.new_action, self.open_action, self.save_action):
            bar.addAction(a)
        bar.addSeparator()  # «Importa SRS…» is in the menu of «Voci SRS» in the tree (and in File)
        bar.addAction(self.check_action)
        # The profile of checks «Verifica modello» runs (the profiles are in the settings of the checks).
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Profilo di verifiche eseguito da «Verifica modello» (salvato nel progetto e "
                                      "pubblicato per tutto il team)")
        self.profile_combo.setMinimumContentsLength(12)
        self.profile_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.profile_combo.currentTextChanged.connect(self._profile_chosen)
        self.profile_action = bar.addWidget(self.profile_combo)
        bar.addAction(self.check_settings_action)
        bar.addSeparator()
        for a in (self.branches_action, self.publish_action, self.receive_action, self.compare_action,
                  self.history_action):
            bar.addAction(a)
        self.addToolBar(bar)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.clone_action)
        self.recent_menu = file_menu.addMenu("Progetti recenti")
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.import_action)
        file_menu.addSeparator()
        file_menu.addAction("Esci", self.close, QKeySequence.Quit)
        project_menu = self.menuBar().addMenu("&Progetto")
        project_menu.addAction(self.close_action)
        project_menu.addSeparator()
        project_menu.addAction(self.clean_action)
        project_menu.addAction(self.remove_srs_action)
        project_menu.addSeparator()
        project_menu.addAction(self.reload_action)
        project_menu.addAction(self.migrate_action)
        project_menu.addSeparator()
        project_menu.addAction(self.check_action)
        project_menu.addAction(self.check_settings_action)
        project_menu.addSeparator()
        project_menu.addAction(self.settings_action)
        versions_menu = self.menuBar().addMenu("&Versioni")
        for a in (self.publish_action, self.send_action, self.receive_action, self.compare_action,
                  self.history_action, self.branches_action):
            versions_menu.addAction(a)
        user_menu = self.menuBar().addMenu("&Utente")
        user_menu.addAction(self.account_action)
        user_menu.addAction(self.switch_user_action)

    def _build_status_bar(self):
        self.status_user = QLabel()
        self.status_project = QLabel()
        self.status_modified = QLabel()
        self.statusBar().addWidget(self.status_user)
        self.statusBar().addWidget(self.status_project, 1)
        self.statusBar().addPermanentWidget(self.status_modified)

    # --- user ----------------------------------------------------------------------------------

    def set_user(self, account):
        self.user = account
        denied = access_denied(self.project.model, account) if self.project is not None else None
        if denied is not None and self._confirm_discard():  # another user, not a member: the project closes
            self._set_project(None)
            show_access_denied(self, denied, account)
        self._refresh_state()
        for editor in self.editors.values():  # who may change the teams depends on the user
            if editor.element is not None and not editor.editing:
                editor._build()

    def da_name(self):
        """The name of the logged-in user if a member of the Design Authority (who approves the ADR), else None."""
        return self.user.full_name if self.user_is_da else None

    def locks_out(self, draft):
        """Saving the sheet (a team) would leave the logged-in user outside the project."""
        return draft.kind == "team" and self.project is not None and locks_out(self.project.model, draft, self.user)

    def edit_denied(self, kind, field=None):
        """Why the logged-in user may not change sheets of this kind, or that field of them (the teams and the
        team of a domain: only the DA), or None."""
        return edit_denied(self.project.model, self.user, kind, field) if self.project is not None else None

    @property
    def user_is_da(self):
        """The logged-in user is a member of the Design Authority team of the open project (by member code, else
        by name and surname): the only one who integrates the branches into main."""
        return bool(self.project and self.user and is_da_member(self.project.model, self.user))

    def edit_account(self):
        if self.user is None:
            return self.switch_user()
        dialog = AccountDialog(account_store(), self.user, self)
        if dialog.exec():
            self.set_user(dialog.account)

    def switch_user(self):
        account = require_login(self, current=self.user)
        if account is not None:
            self.set_user(account)

    def project_settings(self, section="Generale"):
        if not self.project:
            return
        dialog = ProjectSettingsDialog(self.project, self.user, self, section=section)
        if dialog.exec():
            self.recovery_timer.setInterval(recovery_minutes() * 60_000)
            self._refresh_state()
            self.statusBar().showMessage("Impostazioni del progetto salvate", 3000)
            if dialog.checks_changed:
                self.checks.refresh()
            if dialog.remote_changed:
                self._remote_changed()

    # --- checks of the methodology -------------------------------------------------------------

    def verify_model(self):
        """Progetto › Verifica modello: runs the active checks and opens the panel with the findings. Without
        checks chosen, or with settings that are not correct, says what the problem is instead."""
        if not self.project:
            return
        found = check_problems(self.project.checks, self.project.model)
        if found:
            if show_check_problems(self, found):
                self.project_settings("Verifiche")
            return
        self._flush_editors()
        self.checks.run()
        self.checks_dock.expand()
        self.statusBar().showMessage(f"Verifica del modello: {summary(self.checks.counts())}", 6000)

    def _refresh_profiles(self):
        """The profiles of checks in the toolbar: shown only when there are more than one."""
        config = self.project.checks if self.project is not None else None
        names = list(config.profiles) if config is not None else []
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        if config is not None:
            self.profile_combo.setCurrentText(config.active)
        self.profile_combo.blockSignals(False)
        self.profile_action.setVisible(len(names) > 1)

    def _profile_chosen(self, name):
        if self.project is None or self.project.checks is None or not name or name == self.project.checks.active:
            return
        self.project.choose_checks_profile(name)
        self._refresh_state()
        self.statusBar().showMessage(f"Profilo di verifiche «{name}»: salvato nel progetto, condiviso con il team alla "
                                     "prossima pubblicazione", 5000)
        if self.checks.has_run:
            self.checks.run(show_progress=False)
        else:
            self.checks.refresh()

    def _findings_updated(self):
        for editor in self.editors.values():
            editor.update_findings()
        if self.item_window is not None:
            self.item_window.editor.update_findings()

    def _open_finding(self, uuid, field=""):
        """A double click on a finding: its sheet, at the field with the problem."""
        element = self.project.model.get(uuid) if self.project else None
        if element is None:
            return
        self.tree.select(uuid)
        self._select(element)
        editor = self.editors.get(uuid)
        if editor is not None and field:
            editor.reveal(field)

    def _after_save(self):
        """Saved: the findings follow the model, once the checks have been run."""
        if self.checks.has_run:
            self.checks.run(show_progress=False)

    def _remote_changed(self):
        """The address of the repository changed: keep the project as it is, or reload it from there."""
        box = QMessageBox(QMessageBox.Question, "Indirizzo del repository cambiato",
                          f"Il progetto ora usa il repository {self.project.remote()}.", parent=self)
        box.setInformativeText("Ricaricare il progetto dal nuovo repository (ramo di lavoro), o usare il nuovo "
                               "indirizzo solo per i prossimi invii?")
        reload = box.addButton("Ricarica dal nuovo repository", QMessageBox.AcceptRole)
        box.addButton("Usa solo il nuovo indirizzo", QMessageBox.RejectRole)
        box.setDefaultButton(reload)
        box.exec()
        if box.clickedButton() is reload:
            self.reload_from_remote()

    def reload_from_remote(self):
        """Progetto › Ricarica dal repository: the working branch of the remote replaces the local content (what
        was there stays in the Git history of the folder); the project is then opened again."""
        if not self.project:
            return
        url = self.project.remote()
        if not url:
            QMessageBox.information(self, "Ricarica dal repository", "Nessun repository remoto: indica l'URL in "
                                    "Progetto › Impostazioni › Repository Git.")
            return
        if not self._confirm_discard():  # changes not saved: saved or discarded first
            return
        unsent = self.project.unsent_versions()
        if unsent and QMessageBox.question(
                self, "Ricarica dal repository",
                f"{len(unsent)} versioni pubblicate non sono state inviate al repository: dopo il ricaricamento non "
                "saranno più sul ramo di lavoro (restano nella storia locale del progetto). Continuare?"
        ) != QMessageBox.Yes:
            return
        path, branch = self.project.path, self.project.local_settings().get("branch")
        credentials = git_credentials(self.user, url)
        self._set_project(None)  # its files are about to change
        dialog = ReloadDialog(path, url, branch, credentials, self)
        dialog.exec()
        self.open_project(str(path), confirmed=True)  # reloaded, or as it was if the download failed
        if dialog.branch and self.project is not None:
            self.statusBar().showMessage(f"Progetto ricaricato dal ramo «{dialog.branch}» di {url}", 6000)

    def migrate_repository(self):
        """Progetto › Migra repository: the history of the project (all its branches or some) to another Git."""
        if not self.project:
            return
        dialog = MigrationDialog(self.project, self.user, self)
        dialog.exec()
        if dialog.use_destination:
            target = dialog.target.text().strip()
            self.project.update_settings(remote=target)
            self.project.repository.set_remote_url(target)
            self.statusBar().showMessage(f"Il progetto ora usa il repository {target}", 6000)

    # --- state -------------------------------------------------------------------------------

    def _refresh_state(self):
        has_project = self.project is not None
        modified = has_project and self.project.is_modified
        if modified:
            self._recovery_pending = True  # written by the timer
        for a in (self.save_action, self.publish_action, self.compare_action, self.history_action,
                  self.close_action, self.import_action, self.settings_action, self.send_action,
                  self.reload_action, self.migrate_action, self.check_action, self.check_settings_action,
                  self.receive_action, self.branches_action):
            a.setEnabled(has_project)
        user = self.user.full_name if self.user else "nessuno"
        da = design_authority(self.project.model) if has_project else None
        teams = memberships(self.project.model, self.user) if has_project and self.user else []
        role = (f" <span style='color:{ACCENT}; font-weight:600'>· Design Authority</span>"
                if self.user_is_da else
                f" · {', '.join(self.project.model.label(t) for t, _row in teams)}" if teams else "")
        self.status_user.setText(f"Utente: <b>{user}</b>{role}   ·")
        tip = f"Utente collegato: {self.user.username} · {self.user.email}" if self.user else "Nessun utente collegato"
        if has_project:
            tip += ("\nMembro della Design Authority" if self.user_is_da else
                    "\nNessun team è indicato come Design Authority" if da is None else
                    f"\nNon è tra i membri della Design Authority ({self.project.model.label(da)})")
            for t, row in teams:
                tip += f"\nMembro di {self.project.model.label(t)}" + (
                    "" if row.get("account") else " (riconosciuto dal nome: la DA non ha ancora indicato il tuo ID)")
            if not teams:
                tip += "\nNon sei tra i membri di nessun team del progetto"
            tip += ("\n(riconosciuto dall'ID del tuo account, che la DA indica aggiungendoti al team: lo trovi in "
                    "Utente › Modifica account)")
        self.status_user.setToolTip(tip)
        self._update_save()
        found = check_problems(self.project.checks, self.project.model) if has_project else []
        self._refresh_profiles()
        self.verify_button.setEnabled(has_project and not found)
        self.verify_button.setToolTip(
            "Esegue i controlli della metodologia attivi sul modello (F7)" if not found else
            "Verifiche non configurate correttamente:\n" + "\n".join(f"• {p}" for p in found) +
            "\n\nScegli i controlli in «Impostazioni verifiche».")
        self.clean_action.setEnabled(has_project and len(self.project.model) > 0)
        self.remove_srs_action.setEnabled(has_project and bool(self.project.model.of_kind("requirement")))
        name = f" — {self.project.name}" if has_project else ""
        self.setWindowTitle(f"{'● ' if modified else ''}{APP_NAME} {__version__}{name}")
        self.stack.setCurrentIndex(1 if has_project else 0)
        if has_project:
            self.status_project.setText(f"{self.project.name}   ·   ramo «{self.project.current_branch()}»   ·   "
                                        f"{self.project.baseline}   ·   {len(self.project.model)} elementi   ·   "
                                        f"{self.project.path}")
            color = CHANGE_COLORS["modified"] if modified else CHANGE_COLORS["added"]
            text = "● Modifiche non salvate" if modified else "✓ Salvato"
            self.status_modified.setText(f"<span style='color:{color}; font-weight:600'>{text}</span>")
        else:
            self.status_project.setText("Nessun progetto aperto")
            self.status_modified.clear()

    def _refresh_recent(self):
        # Projects moved or deleted (e.g. a temporary folder) are not offered any more.
        recent = [p for p in (settings().value("recent", [], list) or []) if (Path(p) / PROJECT_FILE).exists()]
        self.recent_menu.clear()
        for path in recent:
            self.recent_menu.addAction(path, lambda _checked=False, p=path: self.open_project(p))
        self.recent_menu.setEnabled(bool(recent))
        self.start.set_recent(recent)

    def _remember(self, path):
        s = settings()
        recent = [p for p in (s.value("recent", [], list) or []) if p != str(path)]
        s.setValue("recent", [str(path)] + recent[:MAX_RECENT - 1])
        self._refresh_recent()

    def forget_project(self, path):
        """Out of the list of recent projects; the folder stays where it is."""
        s = settings()
        s.setValue("recent", [p for p in (s.value("recent", [], list) or []) if p != str(path)])
        self._refresh_recent()

    def delete_project(self, path):
        """The folder of a project to the Recycle Bin of Windows, after a confirmation that says what would be
        lost (versions never sent to a remote exist only on this PC)."""
        path = Path(path)
        if self.project is not None and Path(self.project.path).resolve() == path.resolve():
            QMessageBox.information(self, "Elimina progetto", "Il progetto è aperto: chiudilo prima di eliminarlo.")
            return
        try:
            info = describe_project(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Elimina progetto", f"{path} non è leggibile come progetto: {exc}")
            return
        details = [f"Cartella: {path}",
                   "La cartella viene spostata nel Cestino di Windows: puoi ancora recuperarla da lì."]
        if not info["remote"]:
            details.append("Il progetto non è su un repository remoto: tutto il suo contenuto, comprese le "
                           f"{info['versions']} versioni pubblicate, esiste solo su questo PC.")
        elif info["unsent"]:
            details.append(f"Attenzione: {info['unsent']} versioni pubblicate non sono state inviate al repository "
                           f"{info['remote']} ed esistono solo su questo PC.")
        else:
            details.append(f"Tutte le versioni pubblicate sono sul repository {info['remote']}; le modifiche non "
                           "pubblicate andrebbero perse.")
        box = QMessageBox(QMessageBox.Warning, "Elimina progetto", f"Eliminare il progetto «{info['name']}»?",
                          parent=self)
        box.setInformativeText("\n\n".join(details))
        delete = box.addButton("Sposta nel Cestino", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not delete:
            return
        try:
            move_to_trash(path)
        except OSError as exc:
            QMessageBox.warning(self, "Elimina progetto", str(exc))
            return
        self.forget_project(path)
        self.statusBar().showMessage(f"Progetto «{info['name']}» spostato nel Cestino", 6000)

    # --- project lifecycle ---------------------------------------------------------------------

    def _resolve_unsaved_views(self):
        """Graphic views with changes not saved: saved or discarded. False if the user cancels."""
        for page in [p for p in self.diagram_pages.values() if isinstance(p, DiagramPage) and p.dirty]:
            self.pages.setCurrentWidget(page)
            if not resolve_unsaved_view(page, self):
                return False
        return True

    def _confirm_discard(self):
        """Ask what to do with unsaved edits. Returns False if the user cancels."""
        if not self._resolve_unsaved_views():
            return False
        self._flush_editors()
        for editor in self._unsaved_editors():  # sheets in edit mode with changes not saved
            if editor in self.editors.values():
                self._show_editor(editor)
            if not resolve_unsaved(editor, self):
                return False
        for editor in [e for e in self.editors.values() if e.unsaved_new and e.element is not None]:
            self._abandon_new(editor.element)  # created and never saved: not saved with the project either
        if not self.project:
            return True
        if not self.project.is_modified:
            # Nothing to save: a copy for the recovery written earlier (edits undone since, e.g. a new element
            # cancelled) is not left behind, or the next start would offer it as an interrupted session.
            self.project.discard_recovery()
            return True
        answer = QMessageBox.question(
            self, "Modifiche non salvate", f"Salvare le modifiche a «{self.project.name}»?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            self.project.save()
        elif answer == QMessageBox.Discard:
            self.project.discard_recovery()
        return answer != QMessageBox.Cancel

    def new_project(self):
        if not self._confirm_discard():
            return
        dialog = NewProjectDialog(self)
        if not dialog.exec():
            return
        try:
            project = Project.create(dialog.folder.text().strip(), dialog.name.text().strip(),
                                     dialog.baseline.text().strip())
        except (OSError, ProjectError) as exc:
            QMessageBox.critical(self, "Nuovo progetto", str(exc))
            return
        self._set_project(project)

    def open_project_dialog(self):
        if not self._confirm_discard():
            return
        folder = QFileDialog.getExistingDirectory(self, "Apri progetto")
        if folder:
            self.open_project(folder, confirmed=True)

    def clone_project_dialog(self):
        """A project that is not on this PC yet: downloaded from a Git remote, then opened."""
        if not self._confirm_discard():
            return
        dialog = CloneDialog(self.user, self)
        if dialog.exec() and dialog.path is not None:
            self.open_project(str(dialog.path), confirmed=True)
            if self.project is not None:
                self.statusBar().showMessage(f"Progetto scaricato in {dialog.path}", 6000)

    def open_project(self, path, confirmed=False, restore=None):
        if not confirmed and not self._confirm_discard():
            return
        self._denied = None
        loading = LoadingDialog(path, self._open_loaded, self)
        if loading.exec() and self._denied is None:
            self.offer_recovery(restore)
        elif self._denied is not None:
            show_access_denied(self, self._denied, self.user)
        elif loading.error:
            QMessageBox.critical(self, "Apri progetto", loading.error)

    def _open_loaded(self, project):
        """A project loaded: opened only if the user is among the members of its teams (see access_denied)."""
        self._denied = access_denied(project.model, self.user)
        if self._denied is None:
            self._set_project(project)
        else:
            project.close()

    # --- recovery after an unexpected interruption ---------------------------------------------------

    def write_recovery(self):
        if not self.project or not self._recovery_pending:
            return
        self._flush_editors()
        try:
            self.project.write_recovery()
            self._recovery_pending = False
        except OSError:
            pass  # retried at the next tick; the project files are not affected

    def _ask_recovery(self, name, info):
        when = (info.get("saved_at") or "").replace("T", " alle ")
        changes = info.get("modified", 0) + len(info.get("deleted", []))
        box = QMessageBox(QMessageBox.Warning, "Ripristino della sessione",
                          f"Il tool si è chiuso in modo imprevisto mentre il progetto «{name}» aveva "
                          "modifiche non salvate.", parent=self)
        box.setInformativeText(f"Sono state recuperate {changes} modifiche (ultima copia del {when}).\n\n"
                               "Ripristina: le modifiche tornano nel progetto come non salvate.\n"
                               "Elimina: le modifiche recuperate vengono cancellate definitivamente.")
        restore = box.addButton("Ripristina", QMessageBox.AcceptRole)
        box.addButton("Elimina", QMessageBox.DestructiveRole)
        box.setDefaultButton(restore)
        box.exec()
        return box.clickedButton() is restore

    def offer_recovery(self, restore=None):
        """After opening a project: restore or delete the edits of an interrupted session.

        restore: the user already chose (at start-up); None asks."""
        info = self.project.recovery_info() if self.project else None
        if info is None:
            return
        if restore is None:
            restore = self._ask_recovery(self.project.name, info)
        if restore:
            restored = self.project.restore_recovery()
            self.tree.reload()
            self._refresh_state()
            self.statusBar().showMessage(f"Ripristinate {restored} modifiche non salvate: salva per conservarle.",
                                         10000)
        else:
            self.project.discard_recovery()

    def check_interrupted_sessions(self):
        """At start-up: a recent project with a recovery file was not closed normally."""
        for path in settings().value("recent", [], list) or []:
            info = read_recovery_info(path)
            if info is None or not (Path(path) / PROJECT_FILE).exists():
                continue
            name = Path(path).name
            if self._ask_recovery(name, info):
                self.open_project(path, confirmed=True, restore=True)
            else:
                recovery_file(path).unlink(missing_ok=True)
            return

    def clean_project(self):
        """Remove the elements of the project: all of them, or all but the imported SRS items."""
        if not self.project:
            return
        self._flush_editors()
        model = self.project.model
        srs = len(model.of_kind("requirement"))
        others = len(model) - srs
        box = QMessageBox(QMessageBox.Warning, "Pulisci progetto", f"Pulire il progetto «{self.project.name}»?",
                          parent=self)
        details = [f"Il progetto contiene {len(model)} elementi, di cui {srs} voci SRS importate."]
        if srs:
            details.append("«Mantieni le voci SRS» rimuove tutto il resto (domini, funzioni, esiti di tracciatura, "
                           "requisiti derivati…) e azzera l'allocazione delle voci ai domini.")
        details.append("La pulizia diventa definitiva al salvataggio; le versioni già pubblicate restano nella "
                       "cronologia.")
        box.setInformativeText("\n\n".join(details))
        remove_all = box.addButton(f"Rimuovi tutto ({len(model)})", QMessageBox.DestructiveRole)
        keep_srs = box.addButton(f"Mantieni le voci SRS (rimuove {others})", QMessageBox.AcceptRole) if srs else None
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked not in (remove_all, keep_srs):
            return  # «Annulla» or the window closed
        removed = self.project.clean(keep_srs=clicked is keep_srs)
        self._close_item_window()
        self._model_changed()
        self.statusBar().showMessage(f"Progetto pulito: {removed} elementi rimossi. Salva per renderlo definitivo.",
                                     10000)

    def remove_all_srs(self):
        self._flush_editors()
        self.tree.delete_all_requirements()  # asks to confirm (and to switch to the SRS edit mode)

    def close_project(self):
        if self._confirm_discard():
            self._set_project(None)

    def _set_project(self, project):
        for editor in list(self.editors.values()):
            self._hide_editor(editor)
        self._close_item_window()
        self._close_reader()
        for page in list(self.list_pages.values()):
            self._close_list(page)
        for page in list(self.diagram_pages.values()):
            self._close_diagram(page)
        self.srs_edit_mode.set_enabled(False)  # imported SRS items start read-only in every session
        if self.project:
            self.project.close()
        self.project = project
        if project:
            self._remember(Path(project.path).resolve())
        self.tree.set_project(project)
        self.checks.set_project(project)
        self.checks_dock.setVisible(project is not None)
        self.checks_dock.reset()
        self._refresh_state()

    # --- editing -------------------------------------------------------------------------------

    @property
    def editor(self):
        """Editor of the element tab shown (or last shown); an empty one when no element tab is open."""
        current = self.pages.currentWidget()
        if isinstance(current, ElementEditor):
            return current
        if self._last_editor is not None and self._last_editor in self.editors.values():
            return self._last_editor
        return self._idle_editor

    def _update_save(self):
        """«Salva» of the toolbar: enabled when the model, a sheet or a view has changes not saved."""
        self.save_action.setEnabled(bool(self.project) and (self.project.is_modified or bool(self._dirty_pages())))

    def _page_changed(self, _index):
        # Emitted also when the first tab is added (index 0) and when the last one is closed (index -1).
        self.work_area.setCurrentWidget(self.pages if self.pages.count() else self.no_pages)
        self._update_save()
        if isinstance(self.pages.currentWidget(), ElementEditor):
            self._last_editor = self.pages.currentWidget()

    def _new_editor(self):
        editor = ElementEditor(self.srs_edit_mode)
        editor.element_changed.connect(self._element_changed)
        editor.back_requested.connect(self._back_to_reader)
        editor.open_requested.connect(self.open_in_window)
        editor.elements_created.connect(self._model_changed)
        editor.dirty_changed.connect(lambda _dirty, e=editor: self._show_editor(e, activate=False))
        editor.dirty_changed.connect(lambda _dirty: self._update_save())
        editor.saved.connect(lambda e=editor: self._sheet_saved(e))
        editor.abandoned.connect(self._abandon_new)
        editor.findings_for = self.checks.findings_for
        editor.edit_denied = self.edit_denied
        editor.locks_out = self.locks_out
        editor.approver = self.da_name
        return editor

    def _save_local(self, page):
        """The «Salva» of a page (a sheet, a view): only what it changed is written, the other changes of the
        project stay to be saved (the «Salva» of the toolbar saves everything)."""
        own = getattr(page, "element", None) or getattr(page, "view", None)  # the sheet's element, the view
        only = local_changes(page, self.project) | ({own.uuid} if own is not None else set())
        self.project.save(only=only)
        forget_local_changes(page)

    def _sheet_saved(self, editor):
        """«Salva» of a sheet: its changes are in the model and on disk, only them."""
        self._save_local(editor)
        self._refresh_state()
        self.statusBar().showMessage("Scheda salvata", 3000)
        self._after_save()

    def _unsaved_editors(self):
        editors = [e for e in self.editors.values() if e.dirty]
        if self.item_window is not None and self.item_window.editor.dirty:
            editors.append(self.item_window.editor)
        return editors

    def _select(self, element):
        """Open an element in its tab (a new one, or the one already open). Selecting something that is not an
        element (a group of the tree) leaves the open tabs as they are."""
        if element is None:
            return
        if element.kind == "diagram":  # a graphic view: its drawing, not a sheet
            self.open_diagram(element)
            return
        editor = self.editors.get(element.uuid)
        if editor is None:
            editor = self._new_editor()
            # A new element (never saved) opens directly in edit mode; the others (also imported SRS items not
            # saved yet) read-only.
            new = self.project.is_new(element) and element.kind != "requirement"
            editor.edit(self.project, element, editing=new)
            # Created with «Nuovo…»: if its sheet is never saved, the element goes away (see _abandon_new).
            editor.unsaved_new = new and element.uuid in self._just_created
            self._just_created.discard(element.uuid)
            self.editors[element.uuid] = editor
        elif editor.back_label:
            editor.set_back(None)  # opened again from the model tree: nothing to go back to
        self._show_editor(editor)

    def _show_editor(self, editor=None, activate=True):
        """The tab of an element, named after it, with its kind icon and a close button."""
        editor = editor or self.editor
        element = editor.element
        if element is None:
            return
        index = self.pages.indexOf(editor)
        if index < 0:
            index = self.pages.insertTab(self._element_tab_count(), editor, "")
        label = self.project.model.label(element)
        short = label if len(label) <= TAB_TITLE_LENGTH else label[:TAB_TITLE_LENGTH - 1] + "…"
        self.pages.setTabText(index, f"● {short}" if editor.dirty else short)  # ●: changes not saved
        self.pages.setTabIcon(index, kind_icon(element.kind))
        self.pages.setTabToolTip(index, f"{element.schema.label}: {label}")
        if activate:
            self.pages.setCurrentWidget(editor)

    def _element_tab_count(self):
        """Element tabs come before the SUBSET-026 catalogue."""
        return sum(1 for i in range(self.pages.count()) if isinstance(self.pages.widget(i), ElementEditor))

    def _hide_editor(self, editor=None):
        editor = editor or self.editor
        if editor is self._idle_editor:
            return
        editor.flush()
        uuid = next((u for u, e in self.editors.items() if e is editor), None)
        self.editors.pop(uuid, None)
        index = self.pages.indexOf(editor)
        if index >= 0:
            self.pages.removeTab(index)
        editor.clear()
        editor.deleteLater()
        if self._last_editor is editor:
            self._last_editor = None

    # --- SRS reading view ---------------------------------------------------------------------------

    def open_srs_reader(self):
        if not self.project:
            return
        self._flush_editors()
        if self.reader is None:
            self.reader = SrsReader(self.project, self.srs_edit_mode)
            self.reader.open_element.connect(self._open_from_reader)
            self.reader.derive_requested.connect(self._derive_from_reader)
            self.reader.elements_deleted.connect(self._model_changed)
            self.reader.window_toggled.connect(self._toggle_reader_window)
            self.reader.elements_changed.connect(self._reader_changed)
            self.reader.elements_created.connect(self._model_changed)
            self._reader_to_tab()
        self._show_reader()

    def open_element_list(self, kind):
        """Double click on a kind in the model tree (e.g. X-2): its elements as a table in a tab."""
        if not self.project:
            return
        page = self.list_pages.get(kind)
        if page is None:
            page = ElementListPage(self.project, kind)
            page.edit_denied = self.edit_denied
            page.reload()  # its states, chosen on the rows, as the user may change them
            # Queued: the table is drawn again after the change, not while its drop-down list is changing.
            page.status_changed.connect(self._status_from_list, Qt.QueuedConnection)
            page.open_requested.connect(self._open_finding)
            page.create_requested.connect(self.tree.create)  # its sheet opens, in edit mode
            page.delete_requested.connect(self._delete_from_list)
            self.list_pages[kind] = page
            schema = KINDS_BY_NAME[kind]
            index = self.pages.addTab(page, kind_icon(kind), schema.plural)
            self.pages.setTabToolTip(index, f"{schema.template} · {schema.plural}" if schema.template
                                     else schema.plural)
        self.pages.setCurrentWidget(page)

    # --- graphic views ---------------------------------------------------------------------------------

    def open_breakdown(self, kind):
        """The overview of the whole model: SA-1 (only the domains) or SA-2 (every domain open on its functions)."""
        from arcadia_tool.model.diagrams import BREAKDOWN_VIEWS
        if not self.project or kind not in BREAKDOWN_VIEWS:
            return
        key = f"breakdown:{kind}"
        page = self.diagram_pages.get(key)
        if page is None:
            name, functions, _type = BREAKDOWN_VIEWS[kind]
            title = f"{KINDS_BY_NAME[kind].template} {name}"  # «Vista complessiva» under SA-1 and SA-2
            page = BreakdownPage(self.project, functions, self.checks.findings_for, title)
            page.open_requested.connect(self._open_finding)
            page.element_created.connect(lambda uuid, p=page: self._element_created(uuid, p))
            page.model_edited.connect(lambda message, p=page: self._diagram_edited(message, p))
            page.delete_requested.connect(self._delete_from_list)
            self.diagram_pages[key] = page
            index = self.pages.addTab(page, icon("mdi6.view-grid-outline", ACCENT), title)
            self.pages.setTabToolTip(index, title)
        self.pages.setCurrentWidget(page)

    def open_diagram(self, view):
        """A graphic view composed by the user, in its tab."""
        page = self.diagram_pages.get(view.uuid)
        if page is None:
            page = DiagramPage(self.project, view, self.checks.findings_for)
            page.open_requested.connect(self._open_finding)
            page.element_created.connect(lambda uuid, p=page: self._element_created(uuid, p))
            page.model_edited.connect(lambda message, p=page: self._diagram_edited(message, p))
            page.delete_requested.connect(self._delete_from_list)
            page.saved.connect(lambda p=page: self._diagram_saved("Vista salvata", p))
            page.dirty_changed.connect(lambda _dirty, p=page: self._diagram_title(p))
            page.dirty_changed.connect(lambda _dirty: self._update_save())
            self.diagram_pages[view.uuid] = page
            self.pages.addTab(page, icon("mdi6.vector-polyline", ACCENT), "")
            self._diagram_title(page)
        self.pages.setCurrentWidget(page)

    def _diagram_title(self, page):
        index = self.pages.indexOf(page)
        if index < 0:
            return
        name = page.view.get("name") or "(vista senza nome)"
        short = name if len(name) <= TAB_TITLE_LENGTH else name[:TAB_TITLE_LENGTH - 1] + "…"
        self.pages.setTabText(index, f"● {short}" if page.dirty else short)  # ●: changes not saved
        self.pages.setTabToolTip(index, f"{page.view.get('diagram_type') or 'Vista'}: {name}")

    def _diagram_saved(self, message, page=None):
        """A view created (the project saved), or saved with «Salva vista» (only the view written)."""
        if page is None:
            self._save_with_progress()
        else:
            self._save_local(page)
        self._refresh_state()
        self.statusBar().showMessage(message, 3000)
        self._after_save()

    def _element_created(self, uuid, page=None):
        """An element created from a view (a domain, a system function, an exchange and its datum): saved with the
        project, in the model tree and among the elements of every view."""
        element = self.project.model.get(uuid)
        label = self.project.model.label(element) if element is not None else ""
        self._diagram_edited(f"Aggiunto al modello: {KINDS_BY_NAME[element.kind].label} {label}"
                             if element is not None else "", page)

    def _diagram_edited(self, message, page=None):
        """Elements created or deleted from a view: written at once (only them), the other views drawn again."""
        if page is None:
            self._save_with_progress()
        else:
            self._save_local(page)
        self._model_changed()
        if message:
            self.statusBar().showMessage(message, 5000)

    def _close_diagram(self, page):
        key = next((k for k, p in self.diagram_pages.items() if p is page), None)
        self.diagram_pages.pop(key, None)
        index = self.pages.indexOf(page)
        if index >= 0:
            self.pages.removeTab(index)
        page.deleteLater()

    def _refresh_diagrams(self):
        """The model changed: the views are drawn again; those of a view deleted are closed."""
        for key, page in list(self.diagram_pages.items()):
            if isinstance(page, DiagramPage):
                if self.project.model.get(key) is None:
                    self._close_diagram(page)
                    continue
                self._diagram_title(page)
            page.refresh()

    def _status_from_list(self, uuid, status):
        """The status of an element chosen on its row of a table (SA-1): in the model and on disk at once, only it."""
        element = self.project.model.get(uuid) if self.project else None
        if element is None or (element.get("status") or "") == status:
            return
        page = self.list_pages.get(element.kind)
        reason = self.edit_denied(element.kind, "status")
        editor = self.editors.get(uuid)
        if reason is None and editor is not None and editor.dirty:
            reason = (f"La scheda di «{self.project.model.label(element)}» ha modifiche in corso: salvale o "
                      "annullale prima di cambiarne lo stato dalla tabella.")
        if reason:
            QMessageBox.information(self, "Stato", reason)
            if page is not None:
                QTimer.singleShot(0, page.reload)  # its old status again (not while its list is changing)
            return
        previous = element.copy()
        element.set("status", status)
        others = self.project.update(element, previous) or []
        self.project.save(only={uuid, *(o.uuid for o in others)})
        for changed in [element, *others]:
            self._element_changed(changed)
        self._refresh_state()
        label = self.project.model.label(element)
        self.statusBar().showMessage(f"Stato di {label}: {status or 'nessuno'} (salvato)", 4000)

    def _delete_from_list(self, uuid):
        element = self.project.model.get(uuid) if self.project else None
        page = self.sender()  # the table or the view the deletion comes from
        if element is not None and self.tree.delete_element(element) and \
                (page in self.list_pages.values() or page in self.diagram_pages.values()):
            self.pages.setCurrentWidget(page)  # the table or the view stays shown

    def _close_list(self, page):
        kind = next((k for k, p in self.list_pages.items() if p is page), None)
        self.list_pages.pop(kind, None)
        index = self.pages.indexOf(page)
        if index >= 0:
            self.pages.removeTab(index)
        page.deleteLater()

    def _reload_lists(self):
        for page in self.list_pages.values():
            page.reload()

    def open_srs_window(self):
        """Voci SRS › Apri in altra finestra: the catalogue directly in a separate window."""
        if not self.project:
            return
        self.open_srs_reader()
        if self.reader_window is None:
            self._toggle_reader_window()

    def _reader_to_tab(self):
        self.reader.set_detached(False)
        self.pages.addTab(self.reader, icon("mdi6.book-open-page-variant-outline"), "SUBSET-026")

    def _toggle_reader_window(self):
        """«Apri in altra finestra» / «Riporta nelle schede»: the catalogue between a tab and its own window."""
        if self.reader is None:
            return
        if self.reader_window is None:
            self.pages.removeTab(self.pages.indexOf(self.reader))
            self.reader_window = SrsReaderWindow(self.reader, f"Voci SRS · SUBSET-026 — {self.project.name}", self)
            self.reader_window.setWindowIcon(self.windowIcon())
            self.reader_window.closed.connect(self._close_reader)
            self.reader.set_detached(True)
            self.reader_window.show()
        else:
            window, self.reader_window = self.reader_window, None
            window.release()
            window.deleteLater()
            self._reader_to_tab()
        self._show_reader()

    def _show_reader(self):
        if self.reader_window is not None:
            self.reader_window.show()
            self.reader_window.raise_()
            self.reader_window.activateWindow()
        elif self.reader is not None:
            self.pages.setCurrentWidget(self.reader)

    def _open_from_reader(self, uuid):
        element = self.project.model.get(uuid)
        if element is None:
            return
        self.tree.select(uuid)
        self._select(element)  # also when it is not (yet) in the tree
        editor = self.editors[uuid]
        editor.set_back("Torna al catalogo SUBSET-026")
        self._show_editor(editor)
        if self.reader_window is not None:  # the sheet opens in the main window, brought to the front
            self.raise_()
            self.activateWindow()

    def _derive_from_reader(self, uuid):
        """New derived requirement (SA-4) whose «Voce madre» is the SRS item; its ID is <voce>-Dn."""
        self.tree.create("derived_requirement", {"parent": uuid})
        self.editor.set_back("Torna al catalogo SUBSET-026")
        self._show_editor()

    def open_in_window(self, uuid):
        """Show an element in its own window, leaving the page that links to it as it is."""
        element = self.project.model.get(uuid) if self.project else None
        if element is None:
            return
        if self.item_window is None:
            self.item_window = ElementWindow(self.srs_edit_mode, self)
            self.item_window.editor.element_changed.connect(self._window_element_changed)
            self.item_window.editor.saved.connect(lambda e=self.item_window.editor: self._sheet_saved(e))
            self.item_window.editor.findings_for = self.checks.findings_for
            self.item_window.editor.edit_denied = self.edit_denied
            self.item_window.editor.locks_out = self.locks_out
            self.item_window.editor.approver = self.da_name
        self.item_window.show_element(self.project, element)

    def _reader_changed(self, elements):
        """Allocations made from the rows of the SRS catalogue: the open sheets (the domain, the function, the SA-3
        record…) show them."""
        for element in elements:
            self._window_element_changed(element)
        self._refresh_state()

    def _window_element_changed(self, element):
        self._element_changed(element)
        if element.kind not in ("requirement", "derived_requirement"):
            return
        for editor in self.editors.values():  # e.g. the allocation changed: refresh the traced lists
            page = editor.element
            if page is not None and page.kind in ("domain", "system_function", "logical_function"):
                editor.refresh()

    def _close_item_window(self):
        if self.item_window is not None:
            self.item_window.editor.flush()
            self.item_window.editor.clear()
            self.item_window.close()

    def _flush_editors(self):
        """Apply the pending edits of the tabs and of the separate window (before saving, publishing…)."""
        for editor in self.editors.values():
            editor.flush()
        if self.item_window is not None:
            self.item_window.editor.flush()

    def _back_to_reader(self, uuid):
        if self.reader is None:
            return
        element = self.project.model.get(uuid)
        if element is not None and element.kind == "derived_requirement":
            uuid = element.get("parent") or uuid  # back to the SRS item it was derived from
        self._show_reader()  # its tab, or its own window
        self.reader.reveal(uuid)

    def _tab_menu(self, pos):
        """Right click on a tab."""
        index = self.pages.tabBar().tabAt(pos)
        if index < 0:
            return
        menu = QMenu(self)
        self.tab_actions(menu, index)
        menu.exec(self.pages.tabBar().mapToGlobal(pos))

    def tab_actions(self, menu, index):
        page = self.pages.widget(index)
        others = [self.pages.widget(i) for i in range(self.pages.count()) if i != index]
        menu.addAction(icon("mdi6.close"), "Chiudi", lambda: self.close_pages([page]))
        menu.addAction(icon("mdi6.tab-remove"), "Chiudi le altre", lambda: self.close_pages(others)).setEnabled(
            bool(others))
        menu.addAction(icon("mdi6.close-box-multiple-outline"), "Chiudi tutte",
                       lambda: self.close_pages([page, *others]))

    def close_pages(self, pages):
        """Close these tabs one after the other; each asks about its changes not saved (cancelled: it stays)."""
        for page in pages:
            index = self.pages.indexOf(page)
            if index >= 0:
                self._close_page(index)

    def _close_page(self, index):
        if self.pages.widget(index) is self.reader:
            self._close_reader()
        elif self.pages.widget(index) in self.list_pages.values():
            self._close_list(self.pages.widget(index))
        elif self.pages.widget(index) in self.diagram_pages.values():
            page = self.pages.widget(index)
            if isinstance(page, DiagramPage) and not resolve_unsaved_view(page, self):
                return
            self._close_diagram(page)
        elif isinstance(self.pages.widget(index), ElementEditor):
            editor = self.pages.widget(index)
            if not resolve_unsaved(editor, self):  # changes in progress: save or discard them
                return
            if editor.unsaved_new and editor.element is not None:  # created, never saved: it goes away
                self._abandon_new(editor.element)
                return
            current = self.tree.current_element()
            if current is not None and current is editor.element:
                self.tree.clear_selection()  # a click on the same element opens it again
            self._hide_editor(editor)

    def _abandon_new(self, element):
        """An element created with «Nuovo…» whose sheet was not saved («Annulla», or its tab closed): removed
        from the model and from the tree, as if it had never been created."""
        editor = self.editors.get(element.uuid)
        if editor is not None:
            editor.unsaved_new = False
            self._hide_editor(editor)
        if self.project is not None and self.project.discard_new(element.uuid):
            self._model_changed()  # the tree, the lists
            if not self.project.is_modified:
                self.project.discard_recovery()  # its copy for the recovery, if written meanwhile
        self._refresh_state()

    def _close_reader(self):
        if self.reader_window is not None:  # closed from its own window, or with the project
            window, self.reader_window = self.reader_window, None
            window.releasing = True
            window.close()
            window.deleteLater()
        if self.reader is not None:
            index = self.pages.indexOf(self.reader)
            if index >= 0:
                self.pages.removeTab(index)
            self.reader.deleteLater()
            self.reader = None

    def _model_changed(self):
        """Elements were created or deleted: refresh the views that list them."""
        for uuid, editor in list(self.editors.items()):
            if self.project.model.get(uuid) is None:  # its element was deleted: its pending edits too
                editor.discard_pending()
                self._hide_editor(editor)
        if self.sender() is not self.tree:
            self.tree.reload()
        if self.reader is not None:
            self.reader.reload()
        self._reload_lists()
        self._refresh_diagrams()
        self._refresh_state()

    def _element_changed(self, element):
        self.tree.refresh_label(element)
        editor = self.editors.get(element.uuid)
        if editor is not None:
            self._show_editor(editor, activate=False)  # the name may have changed
            if editor is not self.sender() and not editor.dirty:
                # Changed from another sheet (e.g. the domains of a team, when a domain is assigned to it): its
                # open tab shows the new values; a tab with changes in progress keeps them.
                editor.refresh()
        if self.reader is not None:
            self.reader.element_changed(element)
        if element.kind in self.list_pages:
            self.list_pages[element.kind].reload()
        if self.diagram_pages:
            self._refresh_diagrams()  # e.g. a name or an exchange changed in a sheet
        self._refresh_state()

    def _dirty_pages(self):
        """The sheets and the views with changes not saved yet."""
        pages = [e for e in self.editors.values() if e.dirty]
        if self.item_window is not None and self.item_window.editor.dirty:
            pages.append(self.item_window.editor)
        return pages + [p for p in self.diagram_pages.values() if isinstance(p, DiagramPage) and p.dirty]

    def save(self):
        """«Salva» of the toolbar (Ctrl+Maiusc+S): every change of the model, those of every sheet and view open
        included."""
        if not self.project:
            return
        self._flush_editors()
        for page in self._dirty_pages():
            page.save_view() if isinstance(page, DiagramPage) else page.save_changes()
        left = self._dirty_pages()  # e.g. a sheet that could not be saved: it says why
        self._save_with_progress()
        self._refresh_state()
        self.statusBar().showMessage(f"Modifiche salvate; non salvate: {len(left)} schede o viste" if left else
                                     "Tutte le modifiche salvate", 5000)
        self._after_save()

    def save_tab(self):
        """Ctrl+S: only the changes of the tab shown (a sheet, a view), as its own «Salva»."""
        if not self.project:
            return
        current = self.pages.currentWidget()
        if isinstance(current, DiagramPage) and current.dirty:
            current.save_view()
        elif isinstance(current, ElementEditor) and current.dirty:
            current.save_changes()
        elif isinstance(current, ElementEditor) and local_changes(current, self.project):
            self._sheet_saved(current)  # e.g. the SRS items traced from the sheet, outside its edit mode
        elif self.project.is_modified or self._dirty_pages():
            self.statusBar().showMessage("Nessuna modifica in questa tab: «Salva» nella barra in alto "
                                         "(Ctrl+Maiusc+S) salva tutte le modifiche del modello", 6000)

    def _save_with_progress(self):
        if self.project.pending_count < SAVE_PROGRESS_THRESHOLD:
            self.project.save()
            return
        dialog = QProgressDialog("Salvataggio delle modifiche…", None, 0, self.project.pending_count, self)
        dialog.setWindowTitle("Salva")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)

        def progress(done, total):
            dialog.setValue(done)
            QApplication.processEvents()

        self.project.save(progress)
        dialog.close()

    def import_srs(self):
        if not self.project:
            return
        self._flush_editors()
        dialog = ImportSrsDialog(self.project, self)
        if dialog.exec():
            self._model_changed()
            deleted = f", {dialog.deleted} eliminate" if dialog.deleted else ""
            self.statusBar().showMessage(
                f"Import completato: {dialog.created} voci nuove, {dialog.updated} aggiornate{deleted}. "
                "Salva per scriverle su disco.", 8000)

    # --- versions (the only places where a diff is computed) ------------------------------------

    def publish(self):
        if not self.project:
            return
        self._flush_editors()
        dialog = PublishDialog(self.project, self, user=self.user)
        if dialog.exec():
            if dialog.sha:
                self.statusBar().showMessage(f"Pubblicata la versione {dialog.sha[:8]}", 5000)
            if self.project.remote():
                self.send_versions()  # the new version (or those recorded before) to the remote
        self._refresh_state()

    def send_versions(self):
        """Versioni › Invia al repository: the versions published here and not sent yet, to the working branch."""
        if not self.project:
            return
        if not self.project.remote():
            QMessageBox.information(self, "Invia al repository", "Nessun repository remoto: indica l'URL in "
                                    "Progetto › Impostazioni › Repository Git.")
            return
        if not self.project.unsent_versions() and self.project.branch_on_remote():
            QMessageBox.information(self, "Invia al repository", "Tutte le versioni pubblicate sono già state "
                                    "inviate al repository.")
            return
        dialog = PushDialog(self.project, git_credentials(self.user, self.project.remote()), self)
        dialog.exec()
        if dialog.sent:
            self.statusBar().showMessage(f"Versioni inviate al ramo «{self.project.push_branch()}»", 5000)
        elif dialog.receive_requested:  # the remote has versions of the others: received first
            self.receive_versions()

    def receive_versions(self):
        """Versioni › Ricevi dal repository: the versions of the others on the working branch, merged with those
        of this PC; the project is then opened again. A merge is a new version: it is offered to send it."""
        if not self.project:
            return
        if not self.project.remote():
            QMessageBox.information(self, "Ricevi dal repository", "Nessun repository remoto: indica l'URL in "
                                    "Progetto › Impostazioni › Repository Git.")
            return
        self._flush_editors()
        if self.project.is_modified:
            self.save()
        author = f"{self.user.full_name} <{self.user.email}>" if self.user else None
        dialog = ReceiveDialog(self.project, git_credentials(self.user, self.project.remote()), author, self)
        dialog.exec()
        if dialog.publish_first:
            self.publish()
            return
        if not dialog.applied:
            return
        path, result = self.project.path, dialog.result
        self._set_project(None)  # its files changed
        self.open_project(str(path), confirmed=True)
        if self.project is None:
            return
        if result.renumbered:
            lines = "\n".join(f"• {old} → {new}" for _uuid, old, new in result.renumbered)
            QMessageBox.information(self, "Ricevi dal repository",
                                    "Alcuni identificativi dati qui erano già usati nelle versioni ricevute e sono "
                                    f"stati rinumerati:\n\n{lines}")
        self.statusBar().showMessage(f"Versioni ricevute dal ramo «{self.project.push_branch()}»", 6000)
        if dialog.merged and QMessageBox.question(
                self, "Ricevi dal repository", "Le versioni sono state integrate in una nuova versione. Inviarla "
                "ora al repository?") == QMessageBox.Yes:
            self.send_versions()

    def compare(self):
        if self.project:
            self._flush_editors()
            credentials = git_credentials(self.user, self.project.remote()) if self.project.remote() else None
            CompareDialog(self.project, parent=self, credentials=credentials).exec()

    def history(self):
        if self.project:
            self._flush_editors()
            dialog = HistoryDialog(self.project, self, user=self.user)
            dialog.exec()
            if dialog.request is not None:
                self.branch_request(dialog.request)

    def show_branches(self):
        """Versioni › Rami: the branches of the project; a new one, or another one, is then taken here."""
        if not self.project:
            return
        self._flush_editors()
        credentials = git_credentials(self.user, self.project.remote()) if self.project.remote() else {}
        dialog = BranchesDialog(self.project, credentials, self.user, self)
        dialog.exec()
        if dialog.request is not None:
            self.branch_request(dialog.request)

    def branch_request(self, request):
        """("switch", name) or ("create", name, sha, send): the project moves to that branch and is opened
        again. The changes not yet published are published first, or discarded, if the user wants."""
        if not self._ready_to_leave_branch():
            return
        path = self.project.path
        try:
            if request[0] == "create":
                _kind, name, sha, send = request
                self.project.switch_branch(name, sha)
            else:
                _kind, name = request
                send = False
                self.project.switch_branch(name)
        except Exception as exc:
            QMessageBox.critical(self, "Rami", f"Cambio di ramo non riuscito: {exc}")
            return
        self._set_project(None)  # its files changed
        self.open_project(str(path), confirmed=True)
        if self.project is None:
            return
        self.statusBar().showMessage(f"Ora lavori sul ramo «{name}»", 6000)
        if send:
            dialog = PushDialog(self.project, git_credentials(self.user, self.project.remote()), self)
            dialog.exec()

    def _ready_to_leave_branch(self):
        """The edits are saved; the changes not yet published are published, or discarded, or the user cancels."""
        if not self._resolve_unsaved_views():
            return False
        self._flush_editors()
        for editor in self._unsaved_editors():
            if not resolve_unsaved(editor, self):
                return False
        if self.project.is_modified:
            self.save()
        if not self.project.has_unpublished_changes():
            return True
        box = QMessageBox(QMessageBox.Question, "Cambio di ramo",
                          "Ci sono modifiche salvate ma non ancora pubblicate su questo ramo.", parent=self)
        box.setInformativeText("Pubblicale prima di cambiare ramo, oppure scartale: il nuovo ramo riparte dalla "
                               "sua versione.")
        publish = box.addButton("Pubblica…", QMessageBox.AcceptRole)
        discard = box.addButton("Scarta le modifiche", QMessageBox.DestructiveRole)
        box.addButton("Annulla", QMessageBox.RejectRole)
        box.setDefaultButton(publish)
        box.exec()
        if box.clickedButton() is publish:
            self.publish()
            return not self.project.has_unpublished_changes()
        return box.clickedButton() is discard

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        if self.project:
            self.project.close()
        super().closeEvent(event)
