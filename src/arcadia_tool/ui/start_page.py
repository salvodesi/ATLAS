from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget

from arcadia_tool import APP_FULL_NAME, APP_NAME, __version__
from arcadia_tool.ui.branding import image_label, symbol
from arcadia_tool.ui.element_editor import card
from arcadia_tool.ui.theme import ACCENT, MUTED, icon


class StartPage(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    clone_requested = Signal()  # a project that is only on a Git remote
    recent_requested = Signal(str)
    delete_requested = Signal(str)  # the project folder, to the Recycle Bin
    forget_requested = Signal(str)  # only out of the list of recent projects

    def __init__(self):
        super().__init__()
        self.recent_box, self.recent_layout = card("Progetti recenti")
        self.recent_box.setFixedWidth(580)

        logo = image_label(symbol(), 112)
        title = QLabel(APP_NAME, objectName="heroTitle", alignment=Qt.AlignCenter)
        full_name = QLabel(APP_FULL_NAME, alignment=Qt.AlignCenter)
        full_name.setStyleSheet(f"color: {ACCENT}; font-weight: 600; font-size: 11pt;")
        subtitle = QLabel(f"Software di modellazione ARCADIA · versione {__version__}\nDeveloped by: RFI - Ricerca e Sviluppo - Sviluppo Sistemi", objectName="muted",
                          alignment=Qt.AlignCenter)
        new = QPushButton(icon("mdi6.file-plus-outline", "white"), "Nuovo progetto")
        new.setProperty("primary", True)
        open_ = QPushButton(icon("mdi6.folder-open-outline"), "Apri progetto")
        clone = QPushButton(icon("mdi6.source-branch"), "Scarica da Git")
        clone.setToolTip("Scarica un progetto che non è ancora su questo PC da un repository Git remoto")
        for b in (new, open_, clone):
            b.setMinimumHeight(36)
            b.setMinimumWidth(180)
        new.clicked.connect(self.new_requested)
        open_.clicked.connect(self.open_requested)
        clone.clicked.connect(self.clone_requested)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(new)
        buttons.addWidget(open_)
        buttons.addWidget(clone)
        buttons.addStretch()

        column = QVBoxLayout()
        column.addStretch(2)
        column.addWidget(logo)
        column.addWidget(title)
        column.addWidget(full_name)
        column.addSpacing(4)
        column.addWidget(subtitle)
        column.addSpacing(24)
        column.addLayout(buttons)
        column.addSpacing(28)
        column.addWidget(self.recent_box, 0, Qt.AlignHCenter)
        column.addStretch(3)
        layout = QHBoxLayout(self)
        layout.addStretch()
        layout.addLayout(column)
        layout.addStretch()

    def set_recent(self, paths):
        while self.recent_layout.count() > 1:  # the rows (a project and its delete button) or the empty note
            entry = self.recent_layout.takeAt(1)
            if entry.widget():
                entry.widget().hide()
                entry.widget().deleteLater()  # later: it may be the sender of the signal that clears
                continue
            row = entry.layout()
            while row is not None and row.count():
                widget = row.takeAt(0).widget()
                if widget:
                    widget.hide()
                    widget.deleteLater()  # later: it may be the sender of the signal that clears
        if not paths:
            self.recent_layout.addWidget(QLabel("Nessun progetto aperto di recente.", objectName="muted"))
        for path in paths:
            button = QPushButton()
            button.setProperty("flat", True)
            button.setToolTip(path)
            button.setMinimumHeight(48)
            row = QHBoxLayout(button)
            row.setContentsMargins(8, 4, 8, 4)
            pic = QLabel()
            pic.setPixmap(icon("mdi6.folder-outline", ACCENT).pixmap(20, 20))
            name = QLabel(f"<b>{Path(path).name}</b>")
            location = QLabel(objectName="muted")
            location.setText(location.fontMetrics().elidedText(str(Path(path).parent), Qt.ElideMiddle, 440))
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(name)
            text.addWidget(location)
            row.addWidget(pic)
            row.addLayout(text, 1)
            for label in (pic, name, location):
                label.setAttribute(Qt.WA_TransparentForMouseEvents)
            button.clicked.connect(lambda _=False, p=path: self.recent_requested.emit(p))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, b=button, p=path: self._menu(p).exec(b.mapToGlobal(pos)))
            delete = QToolButton()
            delete.setIcon(icon("mdi6.trash-can-outline", MUTED))
            delete.setAutoRaise(True)
            delete.setCursor(Qt.PointingHandCursor)
            delete.setToolTip("Elimina il progetto (la cartella va nel Cestino)")
            delete.clicked.connect(lambda _=False, p=path: self.delete_requested.emit(p))
            line = QHBoxLayout()
            line.setSpacing(4)
            line.addWidget(button, 1)
            line.addWidget(delete)
            self.recent_layout.addLayout(line)

    def _menu(self, path):
        menu = QMenu(self)
        menu.addAction(icon("mdi6.folder-open-outline"), "Apri", lambda: self.recent_requested.emit(path))
        menu.addSeparator()
        menu.addAction(icon("mdi6.playlist-remove"), "Rimuovi dall'elenco", lambda: self.forget_requested.emit(path))
        menu.addAction(icon("mdi6.trash-can-outline"), "Elimina progetto…", lambda: self.delete_requested.emit(path))
        return menu
