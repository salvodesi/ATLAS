"""Loading screen shown while an existing project is opened (thousands of SRS items take a while)."""
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QProgressBar, QVBoxLayout

from arcadia_tool.storage.project import Project, ProjectError


class LoadWorker(QThread):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            self.done.emit(Project.open(self.path, progress=self.progress.emit))
        except (OSError, ProjectError) as exc:
            self.failed.emit(str(exc))


class LoadingDialog(QDialog):
    """Opens the project at `path`; `finish(project)` runs in the GUI thread before the dialog closes."""

    def __init__(self, path, finish, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apertura del progetto")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint & ~Qt.WindowCloseButtonHint)
        self.setModal(True)
        self.setMinimumWidth(520)
        self.finish = finish
        self.error = None

        title = QLabel(f"Apertura di «{Path(path).name}»", objectName="elementTitle")
        where = QLabel(str(path), objectName="muted")
        where.setWordWrap(True)
        self.action = QLabel("Avvio…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # busy until the number of files is known
        self.bar.setTextVisible(True)
        self.detail = QLabel(objectName="muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        for w in (title, where, self.action, self.bar, self.detail):
            layout.addWidget(w)

        self.worker = LoadWorker(path)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._loaded)
        self.worker.failed.connect(self._failed)

    def exec(self):
        self.worker.start()
        return super().exec()

    def reject(self):
        pass  # Esc does not leave a half-opened project: the dialog closes when loading ends

    def _progress(self, action, done, total):
        self.action.setText(f"{action}…")
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.detail.setText(f"{done} di {total} elementi")
        else:
            self.bar.setRange(0, 0)

    def _loaded(self, project):
        self.worker.wait()
        self._progress("Preparazione dell'albero del modello", 0, 0)
        QApplication.processEvents()
        self.finish(project)
        self.accept()

    def _failed(self, message):
        self.worker.wait()
        self.error = message
        super().reject()
