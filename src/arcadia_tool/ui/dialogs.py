from pathlib import Path

from PySide6.QtCore import QSettings

from arcadia_tool import DATA_NAME
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QMessageBox, QPushButton, QWidget)


def settings():
    # INI file under %APPDATA%\RFI instead of the registry: portable and easy to inspect. Its name is the one of
    # the first versions (DATA_NAME), so that recent projects and settings are kept.
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "RFI", DATA_NAME)


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuovo progetto")
        self.name = QLineEdit("EVC")
        self.baseline = QLineEdit("SUBSET-026 v3.6.0")
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Cartella vuota o da creare")
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self._browse)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.folder)
        h.addWidget(browse)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crea progetto")
        buttons.button(QDialogButtonBox.Ok).setProperty("primary", True)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setVerticalSpacing(10)
        form.addRow("Nome", self.name)
        form.addRow("Baseline SRS", self.baseline)
        form.addRow("Cartella", row)
        form.addRow(buttons)
        self.resize(600, 0)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Cartella del progetto")
        if folder:
            self.folder.setText(folder)

    def _accept(self):
        path = Path(self.folder.text().strip())
        if not self.name.text().strip() or not self.folder.text().strip():
            QMessageBox.warning(self, "Nuovo progetto", "Indica nome e cartella.")
            return
        if path.exists() and any(path.iterdir()):
            QMessageBox.warning(self, "Nuovo progetto", "La cartella non è vuota.")
            return
        self.accept()
