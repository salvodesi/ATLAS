from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from arcadia_tool.ui.branding import (ICON_FILE, ICON_SIZES, LOGO_SIZES, SYMBOL_SIZES, FittedImage, app_icon,
                                      image_label, logo_size, resource, symbol, vertical_logo)


def test_images_are_resources_of_the_package():
    assert ICON_FILE.is_file() and resource("atlas.svg").is_file()
    assert all(resource(f"icon_{size}.png").is_file() for size in ICON_SIZES)
    assert all(resource(f"symbol_{size}.png").is_file() for size in SYMBOL_SIZES)
    assert all(resource(f"logo_vertical_{w}x{h}.png").is_file() for w, h in LOGO_SIZES)


def test_icon_symbol_and_logo_are_loaded():
    QApplication.instance() or QApplication([])
    assert QSize(256, 256) in app_icon().availableSizes()
    assert not symbol().isNull() and not vertical_logo().isNull()
    assert logo_size() == QSize(385, 392)  # 35% of the logo
    logo = FittedImage(vertical_logo(), logo_size())
    logo.resize(800, 600)
    assert not logo.grab().isNull()  # reduced to fit, without errors
    assert image_label(symbol(), 112).pixmap().deviceIndependentSize().toSize() == QSize(112, 112)
