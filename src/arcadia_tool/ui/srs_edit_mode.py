"""Edit mode for imported SRS items.

SRS items come from the specification: they are read-only unless the user explicitly switches the edit mode
on (in the SUBSET-026 page, on the page of a single item or from the model tree). One shared state keeps all
the views in step; it starts off every time a project is opened.
"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton

from arcadia_tool.ui.theme import icon

LOCKED_TEXT = "Sola lettura"
UNLOCKED_TEXT = "Modalità modifica attiva"


class SrsEditMode(QObject):
    changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self._enabled = False

    @property
    def enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled != self._enabled:
            self._enabled = enabled
            self.changed.emit(enabled)


def edit_mode_button(mode):
    """Toggle button bound to the shared edit mode (both ways)."""
    button = QPushButton()
    button.setCheckable(True)
    button.setToolTip("Le voci SRS importate sono in sola lettura: attiva la modalità modifica per cambiarle "
                      "o eliminarle.")

    def show(enabled):
        button.blockSignals(True)
        button.setChecked(enabled)
        button.blockSignals(False)
        button.setIcon(icon("mdi6.lock-open-variant-outline" if enabled else "mdi6.lock-outline",
                            "#9A6700" if enabled else "#637083"))
        button.setText(UNLOCKED_TEXT if enabled else LOCKED_TEXT)
        button.setStyleSheet("QPushButton { background: #FFF8C5; color: #9A6700; border-color: #E8C26B; "
                             "font-weight: 600; }" if enabled else "")

    def disconnect(*_):
        try:
            mode.changed.disconnect(show)
        except (RuntimeError, TypeError):
            pass

    button.toggled.connect(mode.set_enabled)
    mode.changed.connect(show)
    button.destroyed.connect(disconnect)  # pages are rebuilt often: do not call a deleted button
    show(mode.enabled)
    return button
