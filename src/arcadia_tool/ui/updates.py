"""«Aiuto › Verifica aggiornamenti…» and the check at the start (at most once a day): the window of a new version,
with its notes, and its download with a progress bar, before ATLAS closes and the new version is installed."""
from datetime import date

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar, QTextBrowser,
                               QVBoxLayout)

from arcadia_tool import APP_NAME, __version__
from arcadia_tool import updates
from arcadia_tool.ui.dialogs import settings

AUTO_KEY = "updates/check_at_start"
LAST_KEY = "updates/last_check"
SKIPPED_KEY = "updates/skipped"


def checks_at_start():
    return settings().value(AUTO_KEY, True, type=bool)


def set_checks_at_start(on):
    settings().setValue(AUTO_KEY, bool(on))


def due_today(today=None):
    """The check at the start: on, and not done yet today."""
    return checks_at_start() and settings().value(LAST_KEY, "") != (today or date.today()).isoformat()


class CheckWorker(QThread):
    found = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.found.emit(updates.latest_release())
        except updates.UpdateError as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QThread):
    progress = Signal(int, int)
    done = Signal(object)  # the path of the file, None if cancelled
    failed = Signal(str)

    def __init__(self, release):
        super().__init__()
        self.release = release
        self.stop = False

    def run(self):
        try:
            self.done.emit(updates.download(self.release, self.progress.emit, lambda: self.stop))
        except updates.UpdateError as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """A new version: its notes and «Aggiorna ora» (download, then the installation), «Più tardi», «Salta questa
    versione». Accepted with `path`, the file downloaded and checked, to install after ATLAS closes."""

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.path = None
        self.worker = None
        self.setWindowTitle("Aggiornamento di ATLAS")
        self.setMinimumSize(640, 480)
        title = QLabel(f"È disponibile {APP_NAME} {release.version}", objectName="elementTitle")
        current = QLabel(f"Versione in uso: {__version__}", objectName="muted")
        notes = QTextBrowser(objectName="releaseNotes")
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "Nessuna nota per questa versione.")
        self.blocked = updates.can_install() if release.url else "La release non ha il file per questo sistema."
        self.info = QLabel(objectName="muted")
        self.info.setWordWrap(True)
        self.info.setText(
            f"{self.blocked} Puoi scaricare la nuova versione dalla pagina della release." if self.blocked else
            "«Aggiorna ora» scarica la nuova versione e ne verifica l'integrità; poi ATLAS si chiude, dopo aver "
            "chiesto di salvare le modifiche, e si riapre aggiornato. I tuoi progetti, account e impostazioni restano.")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.buttons = QDialogButtonBox()
        if self.blocked:
            self.update_button = self.buttons.addButton("Apri la pagina della release", QDialogButtonBox.AcceptRole)
        else:
            self.update_button = self.buttons.addButton("Aggiorna ora", QDialogButtonBox.AcceptRole)
        self.update_button.setDefault(True)
        self.skip_button = self.buttons.addButton("Salta questa versione", QDialogButtonBox.DestructiveRole)
        self.later_button = self.buttons.addButton("Più tardi", QDialogButtonBox.RejectRole)
        self.update_button.clicked.connect(self._update)
        self.skip_button.clicked.connect(self._skip)
        self.later_button.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        for w in (title, current, notes, self.info, self.bar, self.buttons):
            layout.addWidget(w, 1 if w is notes else 0)

    def _skip(self):
        settings().setValue(SKIPPED_KEY, self.release.version)  # not offered again at the start
        self.reject()

    def _update(self):
        if self.blocked:
            QDesktopServices.openUrl(QUrl(self.release.page))
            self.reject()
            return
        self.update_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.later_button.setText("Annulla")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.info.setText("Download della nuova versione…")
        self.worker = DownloadWorker(self.release)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._downloaded)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, done, total):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.info.setText(f"Download della nuova versione… {done / 1048576:.1f}"
                          + (f" di {total / 1048576:.1f} MB" if total else " MB"))

    def _downloaded(self, path):
        self.worker.wait()
        if path is None:  # cancelled
            super().reject()
            return
        self.path = path
        self.accept()

    def _failed(self, message):
        self.worker.wait()
        QMessageBox.warning(self, "Aggiornamento di ATLAS", message)
        super().reject()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():  # «Annulla» during the download
            self.worker.stop = True
            self.info.setText("Annullamento…")
            return  # closed when the worker stops (_downloaded with None)
        super().reject()


class UpdateChecker:
    """The check of the main window: `start(manual)` in the background; a new version shows the window (at the
    start, not the version skipped); asked from the menu, the user is also told when there is none, or why the
    check failed. `install(path)` is the main window's: it closes ATLAS and starts the installation."""

    def __init__(self, parent, install):
        self.parent = parent
        self.install = install
        self.worker = None
        self.manual = False

    def start(self, manual=False):
        if self.worker is not None and self.worker.isRunning():
            self.manual = self.manual or manual
            return
        self.manual = manual
        self.worker = CheckWorker()
        self.worker.found.connect(self._found)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _found(self, release):
        self.worker.wait()
        settings().setValue(LAST_KEY, date.today().isoformat())
        if not updates.is_newer(release.version):
            if self.manual:
                QMessageBox.information(self.parent, "Aggiornamento di ATLAS",
                                        f"Stai usando l'ultima versione di {APP_NAME} ({__version__}).")
            return
        if not self.manual and settings().value(SKIPPED_KEY, "") == release.version:
            return
        if not self.manual and QApplication.activeModalWidget() is not None:  # the user is busy in a window
            QTimer.singleShot(30000, lambda: self._offer(release))
            return
        self.show(release)

    def _offer(self, release):
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(30000, lambda: self._offer(release))
        else:
            self.show(release)

    def show(self, release):
        dialog = UpdateDialog(release, self.parent)
        if dialog.exec() and dialog.path is not None:
            self.install(dialog.path)

    def _failed(self, message):
        self.worker.wait()
        if self.manual:  # at the start, without network: nothing is said
            QMessageBox.warning(self.parent, "Aggiornamento di ATLAS",
                                f"{message}\n\nLe nuove versioni sono anche su {updates.RELEASES_PAGE}")
