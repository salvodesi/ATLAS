"""Icon, symbol and logo of ATLAS, from the images in arcadia_tool/resources (installed with the tool, see
build.ps1)."""
from functools import cache
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QLabel, QWidget

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
ICON_FILE = RESOURCES / "atlas.ico"  # also the icon of ATLAS.exe and of the installer
ICON_SIZES = (16, 24, 32, 48, 64, 96, 128, 180, 192, 256, 512)
SYMBOL_SIZES = (256, 512, 2048)
LOGO_SIZES = ((1100, 1120), (2200, 2240))  # the vertical logo: symbol, «ATLAS» and the full name
LOGO_SCALE = 0.35  # the logo is drawn at 35% of its smaller image: 385×392


def resource(name):
    return RESOURCES / name


def _images(files):
    """One icon with every size of an image: Qt picks the closest one for the size and the screen."""
    result = QIcon()
    for name, (width, height) in files:
        result.addFile(str(resource(name)), QSize(width, height))
    return result


@cache
def app_icon():
    """Title bars and taskbar."""
    return _images((f"icon_{size}.png", (size, size)) for size in ICON_SIZES)


@cache
def symbol():
    """The symbol alone (login and start page)."""
    return _images((f"symbol_{size}.png", (size, size)) for size in SYMBOL_SIZES)


@cache
def vertical_logo():
    """Symbol with the name below (work area without tabs)."""
    return _images((f"logo_vertical_{w}x{h}.png", (w, h)) for w, h in LOGO_SIZES)


def logo_size():
    width, height = LOGO_SIZES[0]
    return QSize(round(width * LOGO_SCALE), round(height * LOGO_SCALE))


class FittedImage(QWidget):
    """«image» at «size», reduced (keeping its proportions) only when the widget is smaller."""

    def __init__(self, image, size, parent=None):
        super().__init__(parent)
        self.image, self.size_ = image, size
        self.setAccessibleName("ATLAS")

    def sizeHint(self):
        return self.size_

    def paintEvent(self, event):
        size = self.size_.scaled(self.size_.boundedTo(self.size()), Qt.KeepAspectRatio)
        pixmap = self.image.pixmap(size, self.devicePixelRatioF())
        x, y = (self.width() - size.width()) // 2, (self.height() - size.height()) // 2
        QPainter(self).drawPixmap(QRect(x, y, size.width(), size.height()), pixmap)


def image_label(image, size, parent=None):
    """«image» (a QIcon) at «size» logical pixels (an int for a square), sharp also on high-DPI screens."""
    size = size if isinstance(size, QSize) else QSize(size, size)
    label = QLabel(parent, alignment=Qt.AlignCenter)
    # Not squeezed by the layout of a window sized to its minimum (with word-wrapped labels it can overlap).
    label.setFixedHeight(size.height())
    label.setMinimumWidth(size.width())
    label.setPixmap(image.pixmap(size, label.devicePixelRatioF()))
    label.setAccessibleName("ATLAS")
    return label
