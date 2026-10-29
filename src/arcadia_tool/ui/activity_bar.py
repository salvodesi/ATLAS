"""The bar of icons beside a side panel, as in VS Code: always shown, an icon for each tab of the panel. A click on
the icon of the tab shown closes the panel, which goes away towards the bar; a click on an icon with the panel
closed (or on another one) opens it on that tab. The panel also closes when its divider is dragged to the edge.
Open or closed, and its width, are kept in the settings. Used by the left panel of the window (the model and the
views) and by the panel at the right of the canvas of a view (the tools and the elements)."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QFrame, QToolButton, QVBoxLayout

from arcadia_tool.ui.theme import ACCENT, ACCENT_SOFT, BORDER, SURFACE, icon


class ActivityBar(QFrame):
    """panel: the widget closed and opened, in splitter; tabs: its tabs (a QTabBar or a QTabWidget, their bar
    hidden); icons: one for each tab. side: "left" or "right", where the bar is, next to the panel. key: the group
    of the settings."""

    def __init__(self, panel, tabs, splitter, icons, store=None, side="left", key="panel", width=340,
                 shortcut="Ctrl+Maiusc+B"):
        super().__init__(objectName="activityBar")
        self.panel, self.tabs, self.splitter, self.store, self.key = panel, tabs, splitter, store, key
        self.setFixedWidth(40)
        inner, outer = ("left", "right") if side == "left" else ("right", "left")
        self.setStyleSheet(f"QFrame#activityBar {{ background: {SURFACE}; border-{outer}: 1px solid {BORDER}; }}"
                           f"QToolButton {{ border: none; border-{inner}: 3px solid transparent; padding: 8px 0; }}"
                           f"QToolButton:checked {{ background: {ACCENT_SOFT}; border-{inner}-color: {ACCENT}; }}"
                           f"QToolButton:hover {{ background: {ACCENT_SOFT}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(2)
        self.buttons = []
        for index, name in enumerate(icons):
            button = QToolButton(icon=icon(name, "#3D4B5C"), iconSize=QSize(22, 22), checkable=True)
            button.setFixedWidth(40)
            button.setToolTip(f"{tabs.tabText(index)} (clic di nuovo: chiude il pannello · {shortcut})")
            button.clicked.connect(lambda _=False, i=index: self.choose(i))
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addStretch(1)
        self._width = width
        tabs.currentChanged.connect(lambda _index: self.show_state())
        splitter.splitterMoved.connect(self._moved)
        if store is not None:
            self._width = int(store.value(f"{key}/width", width) or width)
            if str(store.value(f"{key}/collapsed", "false")).lower() == "true":
                self.panel.hide()
        self.show_state()

    @property
    def _index(self):
        return self.splitter.indexOf(self.panel)

    @property
    def open(self):
        return self.panel.isVisible() or (not self.panel.isHidden() and self.splitter.sizes()[self._index] > 0)

    def choose(self, index):
        """A click on an icon."""
        if self.open and self.tabs.currentIndex() == index:
            self.collapse()
        else:
            self.tabs.setCurrentIndex(index)
            self.expand()

    def toggle(self):
        """The shortcut: the panel closed, or opened again on its tab."""
        self.collapse() if self.open else self.expand()

    def collapse(self):
        sizes = self.splitter.sizes()
        if sizes and sizes[self._index] > 40:
            self._width = sizes[self._index]
        self.panel.hide()
        self._save()

    def expand(self):
        self.panel.show()
        total = sum(self.splitter.sizes()) or self._width * 4
        sizes = [max(total - self._width, 200)] * self.splitter.count()
        sizes[self._index] = self._width
        self.splitter.setSizes(sizes)
        self._save()

    def _moved(self, _pos, _index):
        size = self.splitter.sizes()[self._index]
        if size == 0 and not self.panel.isHidden():  # dragged to the edge: closed
            self.panel.hide()
            self._save()
        elif size > 40:
            self._width = size
            self._save()

    def _save(self):
        if self.store is not None:
            self.store.setValue(f"{self.key}/collapsed", self.panel.isHidden())
            self.store.setValue(f"{self.key}/width", self._width)
        self.show_state()

    def show_state(self):
        """The icon of the tab shown checked (none with the panel closed); those of the tabs hidden, hidden."""
        for index, button in enumerate(self.buttons):
            button.setVisible(self.tabs.isTabVisible(index))
            button.setChecked(not self.panel.isHidden() and self.tabs.currentIndex() == index)
