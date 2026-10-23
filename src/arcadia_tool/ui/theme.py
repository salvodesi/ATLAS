"""Visual theme: palette, stylesheet, fonts and icons."""
import tempfile
from pathlib import Path

import qtawesome as qta
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#2457A6"
ACCENT_HOVER = "#1D4889"
ACCENT_SOFT = "#E8EFFA"
BG = "#F3F5F8"
SURFACE = "#FFFFFF"
BORDER = "#DCE1E8"
TEXT = "#1F2933"
MUTED = "#637083"
ARROW = "#3E4A5B"  # arrows of combo and spin boxes: darker than MUTED, they must be noticed

CHANGE_COLORS = {"added": "#1A7F37", "removed": "#CF222E", "modified": "#9A6700"}
CHANGE_BG = {"added": "#DAFBE1", "removed": "#FFEBE9", "modified": "#FFF8C5"}

# Status chip colours by keyword of the state name, one per stage of a sheet: (text, background), dark text on a
# light background so that every state is readable. Checked in order («non eseguibile» before «eseguibile»).
STATUS_STYLES = (
    (("non eseguibile", "superata"), "#B42318", "#FEE4E2"),
    (("approvat", "decisa", "chiusa", "eseguibile"), "#166534", "#DCFCE7"),
    (("concordat",), "#0F766E", "#CCFBF1"),
    (("revision", "rivist"), "#92400E", "#FEF3C7"),
    (("propost",), "#1E40AF", "#DBEAFE"),
    (("analizzare",), "#5B21B6", "#EDE9FE"),
    (("aperta",), "#9A3412", "#FFEDD5"),
    (("bozza",), "#334155", "#E2E8F0"),
)
NO_STATUS = ("#374151", "#E5E7EB")

KIND_ICONS = {
    "requirement": "mdi6.file-document-outline",
    "trace_record": "mdi6.link-variant",
    "derived_requirement": "mdi6.call-split",
    "domain": "mdi6.shape-outline",
    "system_function": "mdi6.function-variant",
    "external_actor": "mdi6.account-outline",
    "exchange_item": "mdi6.package-variant-closed",
    "functional_exchange": "mdi6.swap-horizontal",
    "functional_chain": "mdi6.transit-connection-variant",
    "logical_function": "mdi6.function",
    "logical_component": "mdi6.cube-outline",
    "component_exchange": "mdi6.connection",
    "chain_realization": "mdi6.check-network-outline",
    "team": "mdi6.account-group-outline",
    "adr": "mdi6.gavel",
    "clarification": "mdi6.help-circle-outline",
}

GROUP_ICONS = {
    "Requisiti": "mdi6.text-box-search-outline",
    "System Analysis": "mdi6.sitemap-outline",
    "Logical Architecture": "mdi6.layers-outline",
    "Trasversali": "mdi6.vector-intersection",
}


def icon(name, color=MUTED):
    try:
        return qta.icon(name, color=color)
    except Exception:
        return qta.icon("mdi6.circle-small", color=color)


def kind_icon(kind, color=ACCENT):
    return icon(KIND_ICONS.get(kind, "mdi6.circle-small"), color)


def status_colors(status):
    s = (status or "").lower()
    for keywords, fg, bg in STATUS_STYLES:
        if any(k in s for k in keywords):
            return fg, bg
    return NO_STATUS


STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; }}
QToolBar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px 8px; spacing: 2px; }}
QToolBar QToolButton {{ padding: 5px 9px; border-radius: 4px; }}
QToolBar QToolButton:hover {{ background: {ACCENT_SOFT}; }}
QToolBar QToolButton:disabled {{ color: #A9B2BF; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 6px; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QFrame#panel {{ background: {SURFACE}; border: none; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; }}
QLabel#cardTitle {{ font-weight: 600; color: {TEXT}; font-size: 10.5pt; }}
QLabel#sectionCaption {{ color: {MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#elementTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#kindLabel {{ color: {ACCENT}; font-weight: 600; }}
QLabel#badge {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-radius: 9px; padding: 1px 8px; font-size: 8.5pt; font-weight: 600; }}
QLabel#heroTitle {{ font-size: 20pt; font-weight: 600; }}
QLabel#formLabel {{ color: {MUTED}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 6px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#search {{ padding-left: 8px; background: {BG}; }}
QLineEdit#readonly {{ background: {BG}; color: {TEXT}; font-weight: 600; }}
QComboBox {{ padding-right: 26px; selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QComboBox:hover, QSpinBox:hover {{ border-color: #A9B8CC; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 24px;
    border: none; border-left: 1px solid {BORDER};
}}
QComboBox::down-arrow {{ image: url(@ARROWS@/down.png); width: 18px; height: 18px; }}
QComboBox::down-arrow:disabled {{ image: url(@ARROWS@/down-disabled.png); }}
/* Open list: white rows with dark text; the row under the mouse dark on light blue (Qt's default highlight is
   dark blue, unreadable with the dark text of the theme). */
QComboBox QAbstractItemView {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; outline: none; padding: 4px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: 4px; color: {TEXT}; }}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT_SOFT}; color: {TEXT};
}}
QSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; border-left: 1px solid {BORDER}; }}
QSpinBox::up-arrow {{ image: url(@ARROWS@/up.png); width: 13px; height: 13px; }}
QSpinBox::down-arrow {{ image: url(@ARROWS@/down.png); width: 13px; height: 13px; }}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {{ image: url(@ARROWS@/up-disabled.png); }}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {{ image: url(@ARROWS@/down-disabled.png); }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #A9B2BF; border-color: {BORDER}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; color: white; }}
QPushButton[primary="true"]:disabled {{ background: #9FB4D6; border-color: #9FB4D6; color: white; }}
QPushButton[flat="true"] {{ border: none; background: transparent; color: {ACCENT}; text-align: left; padding: 4px 6px; }}
QPushButton[flat="true"]:hover {{ background: {ACCENT_SOFT}; }}

QTreeWidget, QListWidget, QTableWidget, QTreeView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; outline: none;
    alternate-background-color: #F8FAFC;
}}
QTreeWidget#navigator {{ border: none; }}
QTreeWidget::item, QListWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: #F0F4FA; }}
QHeaderView::section {{ background: #F6F8FA; border: none; border-bottom: 1px solid {BORDER}; padding: 5px 6px; color: {MUTED}; font-weight: 600; }}
QTableWidget {{ gridline-color: #EEF1F5; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget#qt_scrollarea_viewport > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #C9D1DC; border-radius: 4px; min-height: 24px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #C9D1DC; border-radius: 4px; min-width: 24px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QTextBrowser {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; padding: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 3px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QMenuBar {{ background: {SURFACE}; }}
QMenuBar::item:selected {{ background: {ACCENT_SOFT}; }}
"""


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    # Highlighted rows of lists drawn by Qt itself (the open list of a combo box): dark text on light blue, like
    # the selections styled by the sheet. Selected text in inputs stays white on blue (selection-* below).
    palette.setColor(QPalette.Highlight, QColor(ACCENT_SOFT))
    palette.setColor(QPalette.HighlightedText, QColor(TEXT))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET.replace("@ARROWS@", _arrow_images()))


def _arrow_images():
    """Folder with the arrows of combo and spin boxes: a style sheet draws them only from image files (once
    the drop-down is styled, Qt no longer paints its own arrow)."""
    folder = Path(tempfile.gettempdir()) / "atlas-theme"
    folder.mkdir(exist_ok=True)
    for name, glyph, color in (("down", "mdi6.chevron-down", ARROW), ("down-disabled", "mdi6.chevron-down", "#C3CAD4"),
                               ("up", "mdi6.chevron-up", ARROW), ("up-disabled", "mdi6.chevron-up", "#C3CAD4")):
        icon(glyph, color).pixmap(48, 48).save(str(folder / f"{name}.png"))
    return folder.as_posix()
