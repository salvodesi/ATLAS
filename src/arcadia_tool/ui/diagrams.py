"""Graphic views of the SA (see model.diagrams), opened in a tab from «Viste grafiche» in the left panel.

BreakdownPage: the functional breakdown, a block for each domain that opens, in place, on its system functions.
DiagramPage: a view composed by the user (dataflow, functional chain, scenario) with the elements of the model
listed at its side; the view is changed in the page and stored in the model only with «Salva vista».
"""
import math

from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QIcon, QImage, QKeySequence, QPainter,
                           QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QGraphicsItem, QGraphicsLineItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QLineEdit,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from arcadia_tool.model import diagrams as dg
from arcadia_tool.model.element import Element, natural_key
from arcadia_tool.model.identifiers import compute_id
from arcadia_tool.model.schema import (DIAGRAM_BREAKDOWN, DIAGRAM_CHAIN, DIAGRAM_DATAFLOW, DIAGRAM_FUNCTIONS,
                                       DIAGRAM_LEVELS, DIAGRAM_SCENARIO, NATURES)
from arcadia_tool.storage.project import local_change
from arcadia_tool.ui.activity_bar import ActivityBar
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.theme import ACCENT, ACCENT_SOFT, ARROW, BG, BORDER, MUTED, SURFACE, TEXT, icon, kind_icon

BAD, BAD_SOFT = "#B42318", "#FEE4E2"
WARN, WARN_SOFT = "#9A6700", "#FFF8C5"
MIME = "application/x-atlas-view-element"
NORMAL, SELECTED, PROBLEM, ACTOR, BOUNCE = "normal", "selected", "problem", "actor", "bounce"
# The line of an exchange for the nature of its datum: continuous, dashed, dash-dot.
LINES = {"FLOW": Qt.SolidLine, "EVENT": Qt.DashLine, "OPERATION": Qt.DashDotLine}
CONNECTORS = (("FLOW", "Flusso", "dato continuo: il valore esiste sempre"),
              ("EVENT", "Evento", "qualcosa accade in un istante"),
              ("OPERATION", "Operazione", "richiesta o comando"))


def _font(size=9.0, bold=False, mono=False):
    font = QFont("Consolas" if mono else QApplication.font().family())
    font.setPointSizeF(size)
    font.setBold(bold)
    return font


def _style(style):
    """(fill, border, dashed) of an element of a view."""
    return {NORMAL: (SURFACE, BORDER, False), SELECTED: (ACCENT_SOFT, ACCENT, False),
            PROBLEM: (BAD_SOFT, BAD, False), ACTOR: (SURFACE, ARROW, True),
            BOUNCE: (WARN_SOFT, WARN, False)}[style]


def _lines(text, font, width, max_lines):
    """The text wrapped on words in lines of at most width; beyond max_lines the last one ends with «…»."""
    metrics = QFontMetricsF(font)
    lines = []
    for paragraph in (text or "").split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if not line or metrics.horizontalAdvance(candidate) <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max(max_lines, 1)]
        lines[-1] = metrics.elidedText(lines[-1], Qt.ElideRight, width - metrics.horizontalAdvance("…")) + "…"
    return [metrics.elidedText(line, Qt.ElideRight, width) for line in lines]


def _draw_lines(painter, rect, text, font, color):
    """Text in a rect, wrapped and cut to the lines that fit."""
    painter.setFont(font)
    painter.setPen(QColor(color))
    height = QFontMetricsF(font).height()
    for i, line in enumerate(_lines(text, font, rect.width(), max(int(rect.height() // height), 1))):
        painter.drawText(QRectF(rect.left(), rect.top() + i * height, rect.width(), height),
                         Qt.AlignLeft | Qt.AlignVCenter, line)


# --- items of the scene -----------------------------------------------------------------------------

SNAP = 8  # how near (px) an edge or a centre is aligned to that of a block nearby
GRID = 20  # the dots shown while elements are moved: their top left corner goes on one
# The anchor points of an element, where a connector starts and ends: «R500» is the right side, half way along
# it (thousandths of the side, from the left or the top). Three on each side; when they are all taken by
# connectors, more between them (see side_anchors).
BASE_ANCHORS = (250, 500, 750)
ANCHOR_R = 4.5


def anchor_point(rect, anchor):
    """The point of an anchor on a rect."""
    side, f = anchor[0], int(anchor[1:]) / 1000
    if side in "LR":
        return QPointF(rect.left() if side == "L" else rect.right(), rect.top() + rect.height() * f)
    return QPointF(rect.left() + rect.width() * f, rect.top() if side == "T" else rect.bottom())


def side_anchors(used=()):
    """The points of a side (thousandths): the three of every element and those taken; while every one is taken,
    one more between each two (and between the corners and the first and last)."""
    used = set(used)
    offered = sorted(set(BASE_ANCHORS) | used)
    while all(o in used for o in offered):
        bounds = [0, *offered, 1000]
        offered = sorted(set(offered) | {(x + y) // 2 for x, y in zip(bounds, bounds[1:]) if y - x > 1})
    return offered


def anchor_ids(used=()):
    """The anchors of an element, given those its connectors take («R500»…)."""
    taken = {}
    for anchor in used:
        taken.setdefault(anchor[0], set()).add(int(anchor[1:]))
    return [f"{side}{v}" for side in "LRTB" for v in side_anchors(taken.get(side, ()))]


def anchor_points(rect, ids=None):
    """{anchor: point} of a rect (ids: its anchors, by default the twelve of every element)."""
    return {a: anchor_point(rect, a) for a in (ids if ids is not None else anchor_ids())}


def nearest_anchor(rect, pos, ids=None):
    """The anchor of the rect nearest to a point."""
    return min(anchor_points(rect, ids).items(),
               key=lambda a: (a[1].x() - pos.x()) ** 2 + (a[1].y() - pos.y()) ** 2)[0]


def snap_offset(rect, others, threshold=SNAP):
    """(dx, dy, guides) that align the rect, being moved, with the others: an edge with an edge (left or right,
    top or bottom), the centre with the centre, when nearer than threshold; the nearest wins. guides: the lines
    (x1, y1, x2, y2) that show the alignments."""
    def pairs(r, other, vertical):
        if vertical:
            mine, theirs, centres = (r.left(), r.right()), (other.left(), other.right()), (r.center().x(),
                                                                                         other.center().x())
        else:
            mine, theirs, centres = (r.top(), r.bottom()), (other.top(), other.bottom()), (r.center().y(),
                                                                                         other.center().y())
        return [(m, o) for m in mine for o in theirs] + [centres]

    result, guides = [0, 0], []
    for axis, vertical in ((0, True), (1, False)):
        best = None
        for other in others:
            for mine, theirs in pairs(rect, other, vertical):
                gap = theirs - mine
                if abs(gap) <= threshold and (best is None or abs(gap) < abs(best[0])):
                    best = (gap, theirs, other)
        if best is None:
            continue
        gap, at, other = best
        result[axis] = gap
        if vertical:
            guides.append((at, min(rect.top(), other.top()), at, max(rect.bottom(), other.bottom())))
        else:
            guides.append((min(rect.left(), other.left()), at, max(rect.right(), other.right()), at))
    return result[0], result[1], guides


class Box(QGraphicsItem):
    """An element of a view: its ID, its name, an optional note at the bottom. Moved with the mouse when the view
    can be arranged; a double click opens its sheet."""

    def __init__(self, key, w, h, ident="", text="", note="", style=NORMAL, movable=False, badge="",
                 note_color=MUTED):
        super().__init__()
        self.key, self.w, self.h = key, w, h
        self.ident, self.text, self.note, self.style, self.badge, self.note_color = (
            ident, text, note, style, badge, note_color)
        self.on_move = self.on_open = None
        self.on_menu = None  # a dataflow: (box, where on the screen) → its menu
        self.on_snap = None  # a dataflow, an element on its own: (item, rect) → (dx, dy) aligning it to the others
        self._dragging = False
        self.highlighted = False
        self.hot_anchor = None  # highlighted: the anchor point nearest to the pointer
        self.anchor_ids, self.used_anchors = None, set()  # a dataflow: its anchors, those its connectors take
        self.setFlag(QGraphicsItem.ItemIsSelectable, movable)
        if movable:
            self.setFlag(QGraphicsItem.ItemIsMovable)
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
            self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(" ".join(p for p in (ident, text) if p))

    def rect(self):
        return QRectF(0, 0, self.w, self.h)

    def boundingRect(self):
        return self.rect().adjusted(-5, -5, 5, 5)  # with the halo of a highlight

    def paint(self, painter, _option, _widget=None):
        fill, border, dashed = _style(self.style)
        strong = self.isSelected() or self.highlighted
        pen = QPen(QColor(ACCENT if strong else border), 2.5 if self.highlighted else 2 if strong else 1.2)
        if self.highlighted:  # a halo around it, visible also on the block of its domain
            halo = QColor(ACCENT)
            halo.setAlpha(70)
            painter.setPen(QPen(halo, 7))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect(), 6, 6)
        elif dashed:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(self.rect(), 6, 6)
        y = 8
        if self.ident or self.badge:
            painter.setFont(_font(8.5, bold=True, mono=True))
            painter.setPen(QColor(ACCENT))
            painter.drawText(QRectF(10, y, self.w - 20, 16), Qt.AlignLeft | Qt.AlignVCenter, self.ident)
            if self.badge:
                painter.setFont(_font(8))
                painter.setPen(QColor(MUTED))
                painter.drawText(QRectF(10, y, self.w - 20, 16), Qt.AlignRight | Qt.AlignVCenter, self.badge)
            y += 18
        note_h = 16 if self.note else 0
        _draw_lines(painter, QRectF(10, y, self.w - 20, self.h - y - note_h - 4), self.text, _font(9), TEXT)
        if self.note:
            painter.setFont(_font(8))
            painter.setPen(QColor(self.note_color))
            painter.drawText(QRectF(10, self.h - note_h - 5, self.w - 20, note_h), Qt.AlignLeft | Qt.AlignVCenter,
                             QFontMetricsF(_font(8)).elidedText(self.note, Qt.ElideRight, self.w - 20))
        if self.highlighted:  # its anchor points: where the connector starts or ends filled, those taken pale
            for anchor, point in anchor_points(self.rect(), self.anchor_ids).items():
                hot = anchor == self.hot_anchor
                painter.setPen(QPen(QColor(ACCENT), 1.5))
                painter.setBrush(QColor(ACCENT if hot else ACCENT_SOFT if anchor in self.used_anchors else SURFACE))
                painter.drawEllipse(point, ANCHOR_R + (1 if hot else 0), ANCHOR_R + (1 if hot else 0))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._dragging and self.on_snap is not None and \
                len(self.scene().selectedItems()) <= 1:
            dx, dy = self.on_snap(self, QRectF(value.x(), value.y(), self.w, self.h))
            return QPointF(value.x() + dx, value.y() + dy)
        if change == QGraphicsItem.ItemPositionHasChanged and self.on_move is not None:
            self.on_move(self.key)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        self._dragging = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._dragging = False
        self.setPos(round(self.pos().x()), round(self.pos().y()))
        if self.on_snap is not None:
            self.on_snap(None, None)  # the guides go

    def mouseDoubleClickEvent(self, event):
        if self.on_open is not None:
            self.on_open(self.key)
        event.accept()

    def contextMenuEvent(self, event):
        if self.on_menu is None:
            event.ignore()
            return
        self.scene().clearSelection()
        self.setSelected(True)
        self.on_menu(self, event.screenPos())
        event.accept()


class Block(QGraphicsItem):
    """The block of a domain around its functions in a dataflow; dragged, it moves them with it, and with them
    everything else selected. Selected (a click, Ctrl + click, the rubber band), its functions are selected too."""

    def __init__(self, key, ident, name, members):
        super().__init__()
        self.key, self.ident, self.name, self.members = key, ident, name, members
        self.on_open = self.on_snap = self.on_menu = None
        self._rect = QRectF()
        self._last = None
        self.setZValue(-2)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(f"{ident} {name}".strip())

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            for m in self.members:  # moved with it by a drag of one of them, taken out of the view with it
                m.setSelected(bool(value))
        return super().itemChange(change, value)

    def fit(self):
        rects = [m.mapRectToScene(m.rect()) for m in self.members]
        if not rects:
            return
        left, top = min(r.left() for r in rects), min(r.top() for r in rects)
        right, bottom = max(r.right() for r in rects), max(r.bottom() for r in rects)
        self.prepareGeometryChange()
        self._rect = QRectF(left - dg.PAD, top - dg.HEADER_H, right - left + 2 * dg.PAD,
                            bottom - top + dg.HEADER_H + dg.PAD)
        self.update()

    def rect(self):
        return self._rect

    def boundingRect(self):
        return self._rect.adjusted(-2, -2, 2, 2)

    def paint(self, painter, _option, _widget=None):
        painter.setPen(QPen(QColor(ACCENT), 2.6 if self.isSelected() else 1.2))
        painter.setBrush(QColor(ACCENT_SOFT))
        painter.drawRoundedRect(self._rect, 8, 8)
        r = self._rect
        painter.setFont(_font(8.5, bold=True, mono=True))
        painter.setPen(QColor(ACCENT))
        painter.drawText(QRectF(r.left() + 12, r.top() + 8, 60, 16), Qt.AlignLeft | Qt.AlignVCenter, self.ident)
        painter.setFont(_font(9, bold=True))
        painter.setPen(QColor(TEXT))
        name = QFontMetricsF(_font(9, bold=True)).elidedText(self.name, Qt.ElideRight, r.width() - 24)
        painter.drawText(QRectF(r.left() + 12, r.top() + 24, r.width() - 24, 16), Qt.AlignLeft | Qt.AlignVCenter,
                         name)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                self.setSelected(not self.isSelected())
            elif not self.isSelected():  # a click on a block not selected: that block only
                self.scene().clearSelection()
                self.setSelected(True)
        self._last = event.scenePos()  # where the drag started
        self._start = QRectF(self._rect)
        self._applied = QPointF()
        # What moves: its functions and everything else selected that can be moved.
        moving = list(self.members)
        moving += [i for i in self.scene().selectedItems()
                   if isinstance(i, Box) and i.flags() & QGraphicsItem.ItemIsMovable and i not in moving]
        self._moving = moving
        event.accept()

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        wanted = event.scenePos() - self._last
        if self.on_snap is not None:  # aligned to the blocks nearby
            dx, dy = self.on_snap(self, self._start.translated(wanted))
            wanted += QPointF(dx, dy)
        self.move_members(wanted - self._applied)
        self._applied = wanted

    def move_members(self, delta):
        for m in getattr(self, "_moving", None) or self.members:
            m.moveBy(delta.x(), delta.y())

    def mouseReleaseEvent(self, event):
        self._last = None
        for m in getattr(self, "_moving", None) or self.members:
            m.setPos(round(m.pos().x()), round(m.pos().y()))
        self._moving = None
        if self.on_snap is not None:
            self.on_snap(None, None)  # the guides go

    def mouseDoubleClickEvent(self, event):
        if self.on_open is not None:
            self.on_open(self.key)
        event.accept()

    def contextMenuEvent(self, event):
        if self.on_menu is None:
            event.ignore()
            return
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)
        self.on_menu(self.key, event.screenPos())
        event.accept()


def _clip(rect, inside, outside):
    """Where the segment from the centre of rect towards a point leaves the rect."""
    dx, dy = outside.x() - inside.x(), outside.y() - inside.y()
    if dx == 0 and dy == 0:
        return inside
    tx = (rect.width() / 2) / abs(dx) if dx else math.inf
    ty = (rect.height() / 2) / abs(dy) if dy else math.inf
    t = min(tx, ty, 1)
    return QPointF(inside.x() + dx * t, inside.y() + dy * t)


SIDE_ICONS = ("mdi6.vector-line", "mdi6.playlist-plus")  # the tabs of the panel at the right: tools, elements
HANDLE = 5  # half the side of the handles on the ends of an arrow
HANDLES_KEY = "views/connector_handles"  # the handles of every arrow shown, or only of the one selected


def handles_shown():
    """The choice of the user (right click on the canvas), kept in the settings: by default shown."""
    return str(settings().value(HANDLES_KEY, "true")).lower() == "true"


class Arrow(QGraphicsItem):
    """An exchange: from an element to another (or between two points), with its label; dashed for an EVENT."""

    def __init__(self, ends, lines=(), dashed=False, color=ARROW, key=None, label_color=TEXT, label_above=False,
                 nature=None, exchanges=(), route=None):
        super().__init__()
        self.ends, self.lines, self.dashed, self.color, self.key = ends, list(lines), dashed, color, key
        self.route = route  # a dataflow: the points of its path around the other elements (see orthogonal_route)
        self.label_color, self.label_above = label_color, label_above  # above: the messages of a scenario
        self.nature = nature  # a dataflow: the line of the nature of its data
        self.exchanges = list(exchanges)  # a dataflow: the exchanges it draws (uuids)
        self.on_open = self.on_menu = None
        self.movable_ends = False  # a dataflow: its two ends, shown as handles, moved to other anchor points
        self.handles_always = True  # the handles also when not selected (the choice of the user)
        self.setZValue(-1)
        self._points = [QPointF(), QPointF()]
        self._label = QRectF()
        self.refresh()

    @property
    def _a(self):
        return self._points[0]

    @property
    def _b(self):
        return self._points[-1]

    def refresh(self):
        points = self.route() if self.route is not None else list(self.ends())
        self.prepareGeometryChange()
        self._points = points
        metrics = QFontMetricsF(_font(8))
        width = max((metrics.horizontalAdvance(line) for line in self.lines), default=0) + 10
        height = len(self.lines) * 13 + 4
        # The label in the middle of the longest stretch.
        p, q = max(zip(points, points[1:]), key=lambda s: abs(s[1].x() - s[0].x()) + abs(s[1].y() - s[0].y()))
        mid = (p + q) / 2
        top = mid.y() - height - 1 if self.label_above else mid.y() - height / 2
        self._label = QRectF(mid.x() - width / 2, top, width, height) if self.lines else QRectF()
        self.update()

    def place_label(self, taken):
        """The label on a free place of the path: the middle of its stretches, longest first, or a third of
        them; taken: the rects to keep clear (the elements, the labels already placed)."""
        if not self.lines:
            return
        size = self._label.size()
        stretches = sorted(zip(self._points, self._points[1:]),
                           key=lambda s: -(abs(s[1].x() - s[0].x()) + abs(s[1].y() - s[0].y())))
        for p, q in stretches:
            for f in (0.5, 0.3, 0.7):
                c = p + (q - p) * f
                rect = QRectF(c.x() - size.width() / 2, c.y() - size.height() / 2, size.width(), size.height())
                if not any(rect.intersects(r) for r in taken):
                    self.prepareGeometryChange()
                    self._label = rect
                    self.update()
                    return

    def _path(self):
        path = QPainterPath(self._points[0])
        for point in self._points[1:]:
            path.lineTo(point)
        return path

    def boundingRect(self):
        r = self._path().boundingRect().adjusted(-12, -12, 12, 12)
        return r.united(self._label.adjusted(-2, -2, 2, 2)) if self.lines else r

    def shape(self):
        path = QPainterPath()
        path.addRect(self._label)
        outline = QPainterPathStroker()
        outline.setWidth(8)
        return path.united(outline.createStroke(self._path()))

    def paint(self, painter, _option, _widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = ACCENT if self.isSelected() else self.color
        pen = QPen(QColor(color), 2.4 if self.isSelected() else 1.4)
        if self.nature in LINES:
            pen.setStyle(LINES[self.nature])
        elif self.dashed:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._path())
        last = self._points[-2]
        angle = math.atan2(self._b.y() - last.y(), self._b.x() - last.x())
        head = QPolygonF([self._b, self._b - QPointF(math.cos(angle - 0.4) * 10, math.sin(angle - 0.4) * 10),
                          self._b - QPointF(math.cos(angle + 0.4) * 10, math.sin(angle + 0.4) * 10)])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawPolygon(head)
        if self.lines:
            painter.setBrush(QColor(BG))
            painter.drawRoundedRect(self._label, 3, 3)
            painter.setFont(_font(8))
            for i, line in enumerate(self.lines):
                painter.setPen(QColor(ACCENT if i % 2 else self.label_color))
                painter.drawText(QRectF(self._label.left(), self._label.top() + 2 + i * 13, self._label.width(), 13),
                                 Qt.AlignCenter, line)
        if self._handles():  # the handles of its ends: dragged, to another anchor point
            painter.setPen(QPen(QColor(color), 1.5))
            painter.setBrush(QColor(ACCENT_SOFT if self.isSelected() else SURFACE))
            for point in (self._a, self._b):
                painter.drawRect(QRectF(point.x() - HANDLE, point.y() - HANDLE, 2 * HANDLE, 2 * HANDLE))

    def _handles(self):
        return self.movable_ends and (self.handles_always or self.isSelected())

    def handle_at(self, pos):
        """0 or 1, the end whose handle is under the point of the scene, or None."""
        if not self._handles():
            return None
        for end, point in enumerate((self._a, self._b)):
            if abs(point.x() - pos.x()) <= HANDLE + 3 and abs(point.y() - pos.y()) <= HANDLE + 3:
                return end
        return None

    def mouseDoubleClickEvent(self, event):
        if self.on_open is not None and self.key:
            self.on_open(self.key)
        event.accept()

    def contextMenuEvent(self, event):
        if self.on_menu is None:
            return
        self.scene().clearSelection()
        self.setSelected(True)
        self.on_menu(self, event.screenPos())
        event.accept()


ROUTE_GAP = 16  # the stretch out of an element, before turning
SIDES = {"L": (-1, 0), "R": (1, 0), "T": (0, -1), "B": (0, 1)}


def _side_point(rect, side, offset):
    """(x, y) on a side of a rect (left, top, right, bottom), shifted along it."""
    left, top, right, bottom = rect
    if side in "LR":
        y = min(max((top + bottom) / 2 + offset, top + 6), bottom - 6)
        return (left if side == "L" else right, y)
    x = min(max((left + right) / 2 + offset, left + 6), right - 6)
    return (x, top if side == "T" else bottom)


def _crosses(p, q, rect):
    """True when the stretch p-q (horizontal or vertical, points (x, y)) passes inside the rect (left, top, right,
    bottom; also a QRectF)."""
    if isinstance(rect, QRectF):
        rect = (rect.left(), rect.top(), rect.right(), rect.bottom())
    if isinstance(p, QPointF):
        p, q = (p.x(), p.y()), (q.x(), q.y())
    left, top, right, bottom = rect
    if p[1] == q[1]:
        return top < p[1] < bottom and min(p[0], q[0]) < right and max(p[0], q[0]) > left
    return left < p[0] < right and min(p[1], q[1]) < bottom and max(p[1], q[1]) > top


def _crossings(points, blockers, ends, first=False):
    """How many times the path passes inside the blockers (rects as tuples), and back inside its ends except
    the stretches that leave them; first: stop at the first one (only whether it crosses)."""
    count = 0
    last = len(points) - 2
    for i in range(last + 1):
        (x1, y1), (x2, y2) = points[i], points[i + 1]
        rects = blockers + ends if 0 < i < last else blockers
        if y1 == y2:
            lo, hi = (x1, x2) if x1 < x2 else (x2, x1)
            for left, top, right, bottom in rects:
                if top < y1 < bottom and lo < right and hi > left:
                    count += 1
                    if first:
                        return 1
        else:
            lo, hi = (y1, y2) if y1 < y2 else (y2, y1)
            for left, top, right, bottom in rects:
                if left < x1 < right and lo < bottom and hi > top:
                    count += 1
                    if first:
                        return 1
    return count


def _simplify(points):
    """Without repeated points and points in the middle of a straight stretch."""
    result = []
    for p in points:
        if result and p == result[-1]:
            continue
        if len(result) >= 2 and ((result[-2][0] == result[-1][0] == p[0]) or (result[-2][1] == result[-1][1] == p[1])):
            result[-1] = p
            continue
        result.append(p)
    return result


LANE = 12  # between the middle stretches of two arrows in the same gap


def orthogonal_route(ra, rb, obstacles, offset=0, lane=0, anchors=(None, None)):
    """The path of an arrow from the rect ra to the rect rb in horizontal and vertical stretches, out of a side of
    each: the shortest with the fewest turns that crosses no other element (obstacles: rects), or else the one that
    crosses the fewest. First through the middle of the gap or along the ends; if they all cross something, also
    along the edges of the elements near the two ends, to go around them. offset: shifted along the sides (two
    arrows between the same elements); lane: the middle stretch shifted, so that arrows in the same gap do not
    overlap; anchors: the anchor points it leaves and reaches («R500»), chosen with the connector, or None.
    Returns [QPointF]."""
    a = (ra.left(), ra.top(), ra.right(), ra.bottom())
    b = (rb.left(), rb.top(), rb.right(), rb.bottom())
    region = (min(a[0], b[0]) - 400, min(a[1], b[1]) - 400, max(a[2], b[2]) + 400, max(a[3], b[3]) + 400)
    blockers = [(r.left() - 4, r.top() - 4, r.right() + 4, r.bottom() + 4) for r in obstacles]
    blockers = [r for r in blockers if r[0] < region[2] and r[2] > region[0] and r[1] < region[3] and r[3] > region[1]]
    def ends(rect, tuple_rect, anchor):
        """[(side, point)] where the arrow can leave or reach the rect: its anchor, or the middle of each side."""
        if anchor:
            point = anchor_point(rect, anchor)
            return [(anchor[0], (point.x(), point.y()))]
        return [(side, _side_point(tuple_rect, side, offset)) for side in SIDES]

    stubs = []
    for sa, p0 in ends(ra, a, anchors[0]):
        dxa, dya = SIDES[sa]
        p1 = (p0[0] + dxa * ROUTE_GAP, p0[1] + dya * ROUTE_GAP)
        for sb, q0 in ends(rb, b, anchors[1]):
            dxb, dyb = SIDES[sb]
            stubs.append((p0, p1, (q0[0] + dxb * ROUTE_GAP, q0[1] + dyb * ROUTE_GAP), q0))

    def candidates(xs, ys, simple):
        result = []
        for p0, p1, q1, q0 in stubs:
            for x in ([(p1[0] + q1[0]) / 2 + lane * LANE, p1[0], q1[0]] if simple else []) + xs:
                result.append(_simplify([p0, p1, (x, p1[1]), (x, q1[1]), q1, q0]))
            for y in ([(p1[1] + q1[1]) / 2 + lane * LANE, p1[1], q1[1]] if simple else []) + ys:
                result.append(_simplify([p0, p1, (p1[0], y), (q1[0], y), q1, q0]))
        return result

    def length(points):
        return sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in zip(points, points[1:])) + (len(points) - 2) * 20

    ends = [a, b]
    best, best_count = None, None
    near = (min(a[0], b[0]) - 60, min(a[1], b[1]) - 60, max(a[2], b[2]) + 60, max(a[3], b[3]) + 60)
    edges = [r for r in blockers if r[0] < near[2] and r[2] > near[0] and r[1] < near[3] and r[3] > near[1]]
    for phase in ((([], []), True),
                  (([r[0] - ROUTE_GAP for r in edges] + [r[2] + ROUTE_GAP for r in edges],
                    [r[1] - ROUTE_GAP for r in edges] + [r[3] + ROUTE_GAP for r in edges]), False)):
        (xs, ys), simple = phase
        found = sorted(candidates(xs, ys, simple), key=length)
        for points in found:  # the shortest first: the first that crosses nothing is the one
            if not _crossings(points, blockers, ends, first=True):
                return [QPointF(*p) for p in points]
        for points in found[:40]:  # none: among the shortest, the one that crosses the fewest
            count = _crossings(points, blockers, ends)
            if best_count is None or count < best_count:
                best, best_count = points, count
    return [QPointF(*p) for p in best]


def _routed(source, target, obstacles, offset=0, lane=0, anchors=(None, None)):
    """The route of an arrow between two items, drawn again when they move; obstacles: a function giving the
    other items it goes around; anchors: where it leaves and reaches them (or None)."""
    def route():
        ra = source.mapRectToScene(source.rect())
        rb = target.mapRectToScene(target.rect())
        return orthogonal_route(ra, rb, [i.mapRectToScene(i.rect()) for i in obstacles()], offset, lane, anchors)
    return route


def _between(source, target, offset=0):
    """The ends of an arrow between two items, on their borders, shifted sideways (two arrows between the same
    elements, in opposite directions, do not overlap)."""
    def ends():
        ra = source.mapRectToScene(source.rect())
        rb = target.mapRectToScene(target.rect())
        ca, cb = ra.center(), rb.center()
        length = math.hypot(cb.x() - ca.x(), cb.y() - ca.y()) or 1
        shift = QPointF(-(cb.y() - ca.y()) / length * offset, (cb.x() - ca.x()) / length * offset)
        return _clip(ra, ca + shift, cb + shift), _clip(rb, cb + shift, ca + shift)
    return ends


# --- the canvas ------------------------------------------------------------------------------------------

class Canvas(QGraphicsView):
    """The drawing: zoom with Ctrl + wheel; elements dropped from the list are added where they are dropped. With
    a connector chosen (connecting: which items it links, by key), a drag from an item to another emits connected."""
    dropped = Signal(str, QPointF)
    menu_requested = Signal(object)  # a right click on an empty place of the canvas: where (on the screen)
    connected = Signal(str, str, str, str)  # source, target, their anchors
    end_moved = Signal(object, int, str)  # an arrow, its end (0, 1), the anchor point it goes to
    pressed = Signal()  # the mouse pressed to move elements (the hand)
    released = Signal()  # the mouse released after moving elements
    connecting = None  # None, or a function: key of an item → True when a connector can start or end there
    MARGIN = 1200  # the canvas goes this far beyond its elements: they can be placed out of sight
    EDGE = 30  # dragging an element this near the edge of the view scrolls it
    ZOOM_STEP = 1.2
    ZOOM_RANGE = (0.2, 4.0)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setBackgroundBrush(QColor(SURFACE))
        self.show_grid = False  # while elements are moved: the dots they are placed on
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        for keys, slot in ((QKeySequence.ZoomIn, lambda: self.zoom(self.ZOOM_STEP)),
                           (QKeySequence("Ctrl+="), lambda: self.zoom(self.ZOOM_STEP)),
                           (QKeySequence.ZoomOut, lambda: self.zoom(1 / self.ZOOM_STEP)),
                           (QKeySequence("Ctrl+0"), self.zoom_reset)):
            QShortcut(keys, self, activated=slot, context=Qt.WidgetWithChildrenShortcut)

    def grow(self):
        """The canvas as large as its elements and MARGIN around them, never smaller than it has been: elements
        can be placed out of sight, and the view moved there. The first time, the view on the elements."""
        items = self.scene().itemsBoundingRect()
        if items.isNull():
            items = QRectF(0, 0, 800, 600)
        wanted = items.adjusted(-self.MARGIN, -self.MARGIN, self.MARGIN, self.MARGIN)
        first = getattr(self, "_extent", None) is None
        self._extent = wanted if first else self._extent.united(wanted)
        self.scene().setSceneRect(self._extent)
        if first:
            self._home = items.topLeft()
            self.go_home()

    def go_home(self):
        """The view on the elements: their top left corner near the top left corner of the view."""
        home = getattr(self, "_home", None)
        if home is not None:
            scale = self.transform().m11()  # the scroll bars count in the coordinates of the canvas
            self.horizontalScrollBar().setValue(int((home.x() - 40) * scale))
            self.verticalScrollBar().setValue(int((home.y() - 40) * scale))

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_shown", False):  # only now the scroll bars have their range
            self._shown = True
            self.go_home()

    def set_grid(self, shown):
        if shown != self.show_grid:
            self.show_grid = shown
            self.viewport().update()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        if not self.show_grid:
            return
        painter.setPen(QPen(QColor("#B8C1CD"), 1.6))
        left, top = math.floor(rect.left() / GRID) * GRID, math.floor(rect.top() / GRID) * GRID
        dots = [QPointF(x, y) for x in range(int(left), int(rect.right()) + GRID, GRID)
                for y in range(int(top), int(rect.bottom()) + GRID, GRID)]
        painter.drawPoints(dots)

    def zoom(self, factor, at=None):
        """Zoom in (factor > 1) or out, within ZOOM_RANGE; the point of the view at (by default its centre) stays
        on the same place of the canvas."""
        current = self.transform().m11()
        factor = max(self.ZOOM_RANGE[0], min(self.ZOOM_RANGE[1], current * factor)) / current
        if abs(factor - 1) < 1e-6:
            return
        at = at if at is not None else self.viewport().rect().center()
        fixed = self.mapToScene(at)
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(factor, factor)
        self.setTransformationAnchor(anchor)
        self._pan_by(-(self.mapFromScene(fixed) - at))

    def zoom_reset(self):
        self.zoom(1 / self.transform().m11())

    def zoom_fit(self):
        """All the elements in sight, never larger than their real size."""
        items = self.scene().itemsBoundingRect()
        if items.isNull():
            return
        view = self.viewport().rect()
        wanted = min(view.width() / (items.width() + 60), view.height() / (items.height() + 60), 1)
        self.zoom(max(wanted, self.ZOOM_RANGE[0]) / self.transform().m11())
        self.centerOn(items.center())

    def zoom_actions(self, menu, at=None):
        """The zoom in the menu of a right click (at: where, in the view)."""
        menu.addAction(icon("mdi6.magnify-plus-outline"), "Zoom avanti\tCtrl++",
                       lambda: self.zoom(self.ZOOM_STEP, at))
        menu.addAction(icon("mdi6.magnify-minus-outline"), "Zoom indietro\tCtrl+-",
                       lambda: self.zoom(1 / self.ZOOM_STEP, at))
        menu.addAction(icon("mdi6.magnify"), f"Dimensione reale (ora {round(self.transform().m11() * 100)}%)\tCtrl+0",
                       self.zoom_reset)
        menu.addAction(icon("mdi6.fit-to-screen-outline"), "Adatta alla finestra", self.zoom_fit)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            step = self.ZOOM_STEP if event.angleDelta().y() > 0 else 1 / self.ZOOM_STEP
            self.zoom(step, event.position().toPoint())  # around the pointer
            event.accept()
            return
        super().wheelEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            key = bytes(event.mimeData().data(MIME)).decode()
            event.acceptProposedAction()
            self.dropped.emit(key, self.mapToScene(event.position().toPoint()))

    def box_at(self, pos):
        """The element under the point of the view where a connector can start or end, or None."""
        for item in self.items(pos):
            key = getattr(item, "key", None)
            if isinstance(item, Box) and key and self.connecting(key):
                return item
        return None

    def end_at(self, pos):
        box = self.box_at(pos)
        return box.key if box is not None else None

    def highlight(self, boxes=()):
        """The elements shown as ends of the connector, with their anchor points: the one under the pointer and,
        while dragging, the start. boxes: {box: its anchor to fill} (or boxes, none filled)."""
        boxes = dict(boxes) if isinstance(boxes, dict) else dict.fromkeys(boxes)
        boxes.pop(None, None)
        for box in getattr(self, "_highlighted", set()) - set(boxes):
            box.highlighted, box.hot_anchor = False, None
            box.update()
        for box, anchor in boxes.items():
            box.highlighted, box.hot_anchor = True, anchor
            box.update()
        self._highlighted = set(boxes)

    def _anchor_under(self, box, pos):
        """The anchor of the box nearest to the point of the view (None without a box)."""
        if box is None:
            return None
        return nearest_anchor(box.mapRectToScene(box.rect()), self.mapToScene(pos), box.anchor_ids)

    def _handle_under(self, pos):
        scene_pos = self.mapToScene(pos)
        for item in self.scene().items(QRectF(scene_pos.x() - 10, scene_pos.y() - 10, 20, 20)):
            if isinstance(item, Arrow) and item.handle_at(scene_pos) is not None:
                return item, item.handle_at(scene_pos)
        return None

    def contextMenuEvent(self, event):
        if any(isinstance(i, (Box, Block, Arrow, DomainBlock)) for i in self.items(event.pos())):
            super().contextMenuEvent(event)  # the menu of the element
            return
        self.menu_requested.emit(event.globalPos())
        event.accept()

    def _pan_by(self, delta):
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        empty = not any(isinstance(i, (Box, Block, Arrow, DomainBlock)) for i in self.items(pos))
        if self.dragMode() != QGraphicsView.ScrollHandDrag and (
                event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and empty and
                                                      self.connecting is None and
                                                      not event.modifiers() & Qt.ShiftModifier)):
            # The hand on an empty place (or the middle button): the view moves over the canvas.
            self._pan = event.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            if event.button() == Qt.LeftButton and not event.modifiers() & Qt.ControlModifier:
                self.scene().clearSelection()
            event.accept()
            return
        grabbed = self._handle_under(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if self.connecting is None and grabbed is not None:  # an end of an arrow: to another anchor point
            arrow, end = grabbed
            self._end = (arrow, end, arrow.between[end])
            fixed = arrow._b if end == 0 else arrow._a
            self._line = QGraphicsLineItem(fixed.x(), fixed.y(), fixed.x(), fixed.y())
            self._line.setPen(QPen(QColor(ACCENT), 2, Qt.DashLine))
            self._line.setZValue(10)
            self.scene().addItem(self._line)
            self.highlight({arrow.between[end]: None})
            event.accept()
            return
        if self.connecting is not None and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            self._start_box = self.box_at(pos)
            self._source = self._start_box.key if self._start_box is not None else None
            if self._source is not None:  # from its anchor point nearest to the pointer
                self._start_anchor = self._anchor_under(self._start_box, pos)
                start = anchor_point(self._start_box.mapRectToScene(self._start_box.rect()), self._start_anchor)
                self.highlight({self._start_box: self._start_anchor})
                self._line = QGraphicsLineItem(start.x(), start.y(), start.x(), start.y())
                self._line.setPen(QPen(QColor(ACCENT), 2, Qt.DashLine))
                self._line.setZValue(10)
                self.scene().addItem(self._line)
            event.accept()
            return
        self.pressed.emit()
        super().mousePressEvent(event)

    def _end_anchor(self, box, pos):
        """Dragging an end of an arrow: the anchor point of its element nearest to the pointer, when the pointer
        is on the element or near it (else None)."""
        rect = box.mapRectToScene(box.rect())
        scene_pos = self.mapToScene(pos)
        if not rect.adjusted(-24, -24, 24, 24).contains(scene_pos):
            return None
        return nearest_anchor(rect, scene_pos, box.anchor_ids)

    def mouseMoveEvent(self, event):
        if getattr(self, "_pan", None) is not None:
            self._pan_by(event.position() - self._pan)
            self._pan = event.position()
            event.accept()
            return
        if self.connecting is None and event.buttons() & Qt.LeftButton and self.scene().mouseGrabberItem():
            # An element dragged near the edge: the view follows it, the canvas grows.
            pos, size = event.position(), self.viewport().size()
            step = QPointF(-20 if pos.x() < self.EDGE else 20 if pos.x() > size.width() - self.EDGE else 0,
                           -20 if pos.y() < self.EDGE else 20 if pos.y() > size.height() - self.EDGE else 0)
            if step != QPointF():
                self.grow()
                self._pan_by(-step)
        if getattr(self, "_end", None) is not None:
            arrow, end, box = self._end
            pos = event.position().toPoint()
            anchor = self._end_anchor(box, pos)
            target = anchor_point(box.mapRectToScene(box.rect()), anchor) if anchor else self.mapToScene(pos)
            line = self._line.line()
            self._line.setLine(line.x1(), line.y1(), target.x(), target.y())
            self.highlight({box: anchor})
            event.accept()
            return
        if self.connecting is not None:
            pos = event.position().toPoint()
            under = self.box_at(pos)
            anchor = self._anchor_under(under, pos)
            if getattr(self, "_line", None) is not None:
                line = self._line.line()
                end = self.mapToScene(pos)
                if under is not None and under is not self._start_box:  # on the anchor it will reach
                    end = anchor_point(under.mapRectToScene(under.rect()), anchor)
                self._line.setLine(line.x1(), line.y1(), end.x(), end.y())
                ends = {self._start_box: self._start_anchor}
                if under is not None and under is not self._start_box:
                    ends[under] = anchor
                self.highlight(ends)
            else:
                self.highlight({under: anchor})
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_pan", None) is not None:
            self._pan = None
            self.viewport().setCursor(Qt.CrossCursor if self.connecting else Qt.ArrowCursor)
            event.accept()
            return
        if getattr(self, "_end", None) is not None:
            arrow, end, box = self._end
            self._end = None
            self.scene().removeItem(self._line)
            self._line = None
            anchor = self._end_anchor(box, event.position().toPoint())
            self.highlight()
            if anchor is not None:  # away from its element: it stays where it was
                self.end_moved.emit(arrow, end, anchor)
            event.accept()
            return
        if self.connecting is not None and event.button() == Qt.LeftButton:
            if getattr(self, "_line", None) is not None:
                self.scene().removeItem(self._line)
                self._line = None
                pos = event.position().toPoint()
                box = self.box_at(pos)
                anchor = self._anchor_under(box, pos)
                self.highlight({box: anchor})
                if box is not None and box.key != self._source:
                    self.connected.emit(self._source, box.key, self._start_anchor, anchor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.released.emit()


def export_image(parent, scene, name):
    """Save the drawing as a PNG or SVG image, chosen by the user. Returns the path, or None."""
    path, chosen = QFileDialog.getSaveFileName(parent, "Esporta la vista", f"{name}.png",
                                               "Immagine PNG (*.png);;Disegno SVG (*.svg)")
    if not path:
        return None
    scene.clearSelection()
    source = scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
    if path.lower().endswith(".svg") or "svg" in chosen.lower() and not path.lower().endswith(".png"):
        from PySide6.QtSvg import QSvgGenerator
        if not path.lower().endswith(".svg"):
            path += ".svg"
        generator = QSvgGenerator()
        generator.setFileName(path)
        generator.setSize(source.size().toSize())
        generator.setViewBox(QRectF(0, 0, source.width(), source.height()))
        generator.setTitle(name)
        painter = QPainter(generator)
        scene.render(painter, QRectF(0, 0, source.width(), source.height()), source)
        painter.end()
        return path
    image = QImage((source.size() * 2).toSize(), QImage.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), source)
    painter.end()
    image.save(path)
    return path


def _toolbar_button(text, icon_name, slot, tip=""):
    button = QPushButton(icon(icon_name), text)
    button.setToolTip(tip or text)
    button.clicked.connect(lambda _checked=False: slot())
    return button


# --- functional breakdown ---------------------------------------------------------------------------------

# Every block of a domain as wide as a cell, closed or open (SA-1, SA-2).
COLUMNS, CELL_W, CELL_H, SPACING = 5, 400, 96, 14
# The title bar of a domain (its ID and name, the chevron to open it on the right), the functions under it.
ROW_H, TITLE_H = 38, 56
BLOCK_HEADER = TITLE_H + 14
BODY_H = CELL_H - TITLE_H  # closed: the number of its functions, under the title bar


class DomainBlock(QGraphicsItem):
    """A domain in the breakdown: a title bar with its ID and name and, on the right, the chevron; closed, the number
    of its functions under it; open, the list of its functions. A click on the title bar opens or closes it, on a
    function selects it; a double click opens the sheet of the domain or of the function; a right click on a function
    opens it or deletes it, on the domain shows what can be done on it. Not expandable (the overview of SA-1): as a closed one, without the
    chevron, and its title bar as high as the whole name."""

    def __init__(self, page, domain, w, h, opened, problems, expandable=True):
        super().__init__()
        self.page, self.domain, self.w, self.h, self.opened, self.problems = page, domain, w, h, opened, problems
        self.expandable = expandable  # not in the overview of SA-1: always closed
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{domain.ident} {domain.name}\n" + (
            "Clic sul titolo: apri o chiudi il dominio · clic su una funzione: selezionala · doppio clic: apri la "
            "scheda" if expandable else "Doppio clic: apri la scheda del dominio"))

    def rect(self):
        return QRectF(0, 0, self.w, self.h)

    def boundingRect(self):
        return self.rect().adjusted(-2, -2, 2, 2)

    @property
    def has_chevron(self):
        return self.expandable and self.domain.uuid is not None and not self.domain.partial

    def on_title(self, pos):
        return 0 <= pos.y() < TITLE_H

    def function_at(self, pos):
        if not self.opened:
            return None
        row = int((pos.y() - BLOCK_HEADER) // ROW_H)
        return self.domain.functions[row] if 0 <= row < len(self.domain.functions) and pos.y() >= BLOCK_HEADER \
            else None

    def paint(self, painter, _option, _widget=None):
        d = self.domain
        bad = sum(1 for f in d.functions if f.uuid in self.problems)
        painter.setRenderHint(QPainter.Antialiasing)
        outline = QPainterPath()
        outline.addRoundedRect(self.rect(), 7, 7)
        painter.fillPath(outline, QColor(SURFACE))
        # The title bar: blue when the domain is open.
        painter.save()
        painter.setClipPath(outline)
        bar = self.h - BODY_H if not self.expandable else min(TITLE_H, self.h)  # SA-1: the whole name
        painter.fillRect(QRectF(0, 0, self.w, bar), QColor(ACCENT if self.opened else ACCENT_SOFT))
        painter.restore()
        width = 2.2 if self.isSelected() else 1.4 if self.opened else 1
        painter.setPen(QPen(QColor(ACCENT if self.opened or self.isSelected() else BORDER), width))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(outline)
        on_bar = "white" if self.opened else ACCENT
        right = self.w - (36 if self.has_chevron else 12)
        painter.setFont(_font(8.5, bold=True, mono=True))
        painter.setPen(QColor(on_bar))
        painter.drawText(QRectF(12, 6, right - 12, 16), Qt.AlignLeft | Qt.AlignVCenter, d.ident)
        _draw_lines(painter, QRectF(12, 21, right - 12, bar - 24), d.name, _font(10.5, bold=True),
                    "white" if self.opened else TEXT)
        if self.has_chevron:
            # Drawn, not a character: the same in every font.
            x, y = self.w - 22, TITLE_H / 2
            chevron = QPainterPath()
            if self.opened:
                chevron.moveTo(x - 5, y - 2.5), chevron.lineTo(x, y + 2.5), chevron.lineTo(x + 5, y - 2.5)
            else:
                chevron.moveTo(x - 2.5, y - 5), chevron.lineTo(x + 2.5, y), chevron.lineTo(x - 2.5, y + 5)
            painter.setPen(QPen(QColor(on_bar), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(chevron)
        if not self.opened:
            count = f"{len(d.functions)} funzion{'e' if len(d.functions) == 1 else 'i'}"
            painter.setFont(_font(8))
            painter.setPen(QColor(MUTED))
            body = QRectF(12, bar, self.w - 24, self.h - bar)
            painter.drawText(body, Qt.AlignLeft | Qt.AlignVCenter, count)
            if bad:
                painter.setPen(QColor(BAD))
                painter.drawText(body, Qt.AlignRight | Qt.AlignVCenter, f"{bad} con segnalazioni")
            return
        if not d.functions:
            painter.setFont(_font(8.5))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(16, BLOCK_HEADER, self.w - 32, 20), Qt.AlignLeft | Qt.AlignVCenter,
                             "Nessuna funzione di sistema")
        for i, f in enumerate(d.functions):
            row = QRectF(14, BLOCK_HEADER - 6 + i * ROW_H, self.w - 28, ROW_H - 4)
            problem = f.uuid in self.problems
            chosen = f.uuid == self.page.selected_function
            painter.setPen(QPen(QColor(ACCENT if chosen else BAD if problem else BORDER), 2 if chosen else 1))
            painter.setBrush(QColor(ACCENT_SOFT if chosen else BAD_SOFT if problem else BG))
            painter.drawRoundedRect(row, 4, 4)
            painter.setFont(_font(8, bold=True, mono=True))
            painter.setPen(QColor(ACCENT))
            painter.drawText(QRectF(row.left() + 10, row.top() + 3, 120, 14), Qt.AlignLeft | Qt.AlignVCenter, f.ident)
            painter.setFont(_font(8))
            painter.setPen(QColor(BAD if problem else MUTED))
            note = f"{f.clauses} clausol{'a' if f.clauses == 1 else 'e'}"
            if problem:
                note += " · " + ", ".join(self.problems[f.uuid])
            painter.drawText(QRectF(row.left() + 10, row.top() + 3, row.width() - 20, 14),
                             Qt.AlignRight | Qt.AlignVCenter, note)
            painter.setFont(_font(9))
            painter.setPen(QColor(TEXT))
            name = QFontMetricsF(_font(9)).elidedText(f.name, Qt.ElideRight, row.width() - 20)
            painter.drawText(QRectF(row.left() + 10, row.top() + 17, row.width() - 20, 15),
                             Qt.AlignLeft | Qt.AlignVCenter, name)

    def mousePressEvent(self, event):
        function = self.function_at(event.pos())
        if function is not None:  # a function: selected, the domain stays open
            self.page.select_function(function.uuid)
        else:
            self.page.select_function(None)
            if self.flags() & QGraphicsItem.ItemIsSelectable:  # in a view: selected, to be taken out of it
                super().mousePressEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.has_chevron and self.on_title(event.pos()):
            self.page.toggle_later(self.domain.uuid)  # the title bar, or its chevron

    def contextMenuEvent(self, event):
        menu = QMenu()
        function = self.function_at(event.pos())
        if function is not None:
            self.page.select_function(function.uuid)
            menu.addAction(icon("mdi6.open-in-app"), "Apri la scheda",
                           lambda: self.page.open_requested.emit(function.uuid))
            menu.addSeparator()  # in a view: asked, only from the view or from the model too
            menu.addAction(icon("mdi6.trash-can-outline"), "Elimina la funzione…",
                           lambda: self.page.delete_function(function.uuid))
        elif self.domain.uuid is not None:
            self.page.domain_actions(menu, self.domain.uuid)
        else:
            return
        menu.exec(event.screenPos())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.page.cancel_toggle()
        function = self.function_at(event.pos())
        uuid = function.uuid if function is not None else self.domain.uuid
        if uuid:
            self.page.open_requested.emit(uuid)
        event.accept()


def draw_breakdown(page, scene, domains, opened, problems, selectable=False, expandable=True):
    """The blocks of the domains on the scene: {uuid: DomainBlock}."""
    root = scene.addSimpleText("EVC" if domains else "Nessun dominio funzionale", _font(9, bold=True))
    root.setBrush(QColor(MUTED))
    root.setPos(20, -6)
    blocks = {}
    for d, x, y, w, h in breakdown_layout(domains, opened) if expandable else names_layout(domains):
        block = DomainBlock(page, d, w, h, d.uuid in opened, problems, expandable)
        block.setFlag(QGraphicsItem.ItemIsSelectable, selectable)
        block.setPos(x, y + 14)
        scene.addItem(block)
        blocks[d.uuid] = block
    return blocks


def title_height(domain):
    """The height of the title bar of a block of SA-1: the whole name, on as many lines as it needs."""
    font = _font(10.5, bold=True)
    lines = _lines(domain.name, font, CELL_W - 24, 100)
    return max(TITLE_H, math.ceil(21 + len(lines) * QFontMetricsF(font).height() + 10))


def names_layout(domains):
    """(domain, x, y, w, h) of the blocks of SA-1: five columns; a row as high as its highest name, with the
    number of functions under it."""
    result, y = [], 20
    for start in range(0, len(domains), COLUMNS):
        row = domains[start:start + COLUMNS]
        heights = [title_height(d) + BODY_H for d in row]
        for column, (d, h) in enumerate(zip(row, heights)):
            result.append((d, 20 + column * (CELL_W + SPACING), y, CELL_W, max(heights)))
        y += max(heights) + SPACING
    return result


def breakdown_layout(domains, opened, cell_h=CELL_H):
    """(domain, x, y, w, h) of the blocks: five columns of cells cell_h high; an open block is as high as its
    functions, the others flow around it."""
    taken, result = set(), []
    for d in domains:
        is_open = d.uuid in opened
        span_w = 1
        height = BLOCK_HEADER + max(len(d.functions), 1) * ROW_H + 6 if is_open else cell_h
        span_h = max(1, math.ceil((height + SPACING) / (cell_h + SPACING)))
        row = 0
        while True:
            column = next((c for c in range(COLUMNS - span_w + 1)
                           if all((row + r, c + k) not in taken for r in range(span_h) for k in range(span_w))), None)
            if column is not None:
                break
            row += 1
        taken.update((row + r, column + k) for r in range(span_h) for k in range(span_w))
        w = span_w * CELL_W + (span_w - 1) * SPACING
        h = height  # an open block as high as its functions, not as its rows of cells
        result.append((d, 20 + column * (CELL_W + SPACING), 20 + row * (cell_h + SPACING), w, h))
    return result


class _Toggles:
    """A click on a domain of a breakdown opens or closes it, unless it is the first click of a double click (that
    opens the sheet). The page has toggle(uuid)."""

    def _setup_toggles(self):
        self._pending = None
        self._timer = QTimer(self, singleShot=True, timeout=self._toggle_pending)
        self._timer.setInterval(QApplication.doubleClickInterval())

    def toggle_later(self, uuid):
        self._pending = uuid
        self._timer.start()

    def cancel_toggle(self):
        self._timer.stop()
        self._pending = None

    def _toggle_pending(self):
        if self._pending is not None:
            uuid, self._pending = self._pending, None
            self.toggle(uuid)


class NewFunctionDialog(QDialog):
    """A new system function from a breakdown: its domain and its name (the ID is given by ATLAS)."""

    def __init__(self, model, domain=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuova funzione di sistema")
        self.domain = QComboBox()
        for d in model.of_kind("domain"):
            self.domain.addItem(model.label(d), d.uuid)
        if domain is not None and self.domain.findData(domain) >= 0:
            self.domain.setCurrentIndex(self.domain.findData(domain))
        self.name = QLineEdit(placeholderText="verbo + oggetto, es. Supervisionare lo standstill")
        self.problem = QLabel(objectName="muted", wordWrap=True)
        self.problem.setStyleSheet(f"color: {BAD};")
        form = QFormLayout()
        form.addRow("Dominio", self.domain)
        form.addRow("Nome", self.name)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crea la funzione")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)
        self.resize(QSize(460, 0))

    def accept(self):
        if self.domain.currentData() is None:
            self.problem.setText("Nel modello non ci sono domini funzionali: creane uno in SA-1.")
            return
        if not self.name.text().strip():
            self.problem.setText("Dai un nome alla funzione.")
            return
        super().accept()


class NewDomainDialog(QDialog):
    """A new functional domain from SA-1: its name and mission (the ID, DFnn, is given by ATLAS)."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuovo dominio funzionale")
        ident = compute_id(Element("domain"), model) or ""
        self.name = QLineEdit(placeholderText="es. Supervisione della velocità")
        self.mission = QPlainTextEdit()
        self.mission.setFixedHeight(70)
        self.problem = QLabel(objectName="muted", wordWrap=True)
        self.problem.setStyleSheet(f"color: {BAD};")
        form = QFormLayout()
        form.addRow("ID", QLabel(f"{ident} (assegnato da ATLAS)" if ident else "assegnato da ATLAS"))
        form.addRow("Nome", self.name)
        form.addRow("Missione", self.mission)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crea il dominio")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)
        self.resize(QSize(460, 0))

    def accept(self):
        if not self.name.text().strip():
            self.problem.setText("Dai un nome al dominio.")
            return
        super().accept()


def line_icon(nature):
    """A sample of the line of a nature, for the connectors in the side panel."""
    pixmap = QPixmap(40, 14)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(ARROW), 1.6, LINES[nature]))
    painter.drawLine(2, 7, 31, 7)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(ARROW))
    painter.drawPolygon(QPolygonF([QPointF(38, 7), QPointF(30, 3), QPointF(30, 11)]))
    painter.end()
    return QIcon(pixmap)


NEW_ITEM = "new"
PRODUCTION = ("Sempre", "A ogni variazione", "Su evento", "Su richiesta")
FIXED_PRODUCTION = {"EVENT": "Su evento"}
USUAL_PRODUCTION = {"OPERATION": "Su richiesta"}  # proposed, can be changed


class NewExchangeDialog(QDialog):
    """A connector between two functions (or a function and an external actor): the functional exchange, with its
    datum, an Exchange Item of the dictionary or a new one. The IDs are given by ATLAS."""

    def __init__(self, model, source, target, nature, preferred=None, parent=None):
        super().__init__(parent)
        self.model, self.source, self.target, self.nature = model, source, target, nature
        self.setWindowTitle("Nuovo scambio funzionale")
        probe = Element("functional_exchange")
        probe.set("source", source)
        probe.set("target", target)
        ident = compute_id(probe, model) or ""
        self.item = QComboBox()
        self.item.addItem(icon("mdi6.plus"), "Nuovo dato…", NEW_ITEM)
        used = {fe.get("exchange_item") for fe in model.of_kind("functional_exchange")}
        for i in dg.exchange_items_for(model, nature):
            note = "" if i.uuid in used else "  · non usato da altri scambi"
            if dg.same_exchange(model, source, target, i.uuid) is not None:
                note = "  · già scambiato tra questi elementi"
            self.item.addItem(f"{model.label(i)}{note}", i.uuid)
        if preferred is not None and self.item.findData(preferred) >= 0:  # the datum of a connector deleted here
            self.item.setCurrentIndex(self.item.findData(preferred))
        self.name = QLineEdit(placeholderText="es. Movimento del treno")
        self.meaning = QPlainTextEdit()
        self.meaning.setFixedHeight(56)
        self.condition = QComboBox()
        self.condition.addItem("")
        self.condition.addItems(PRODUCTION)
        if nature in FIXED_PRODUCTION:  # an EVENT is produced when it happens
            self.condition.setCurrentText(FIXED_PRODUCTION[nature])
            self.condition.setEnabled(False)
        elif nature in USUAL_PRODUCTION:
            self.condition.setCurrentText(USUAL_PRODUCTION[nature])
        self.problem = QLabel(objectName="muted", wordWrap=True)
        self.problem.setStyleSheet(f"color: {BAD};")
        form = QFormLayout()
        form.addRow("Produttore", QLabel(model.label(model.get(source))))
        form.addRow("Utilizzatore", QLabel(model.label(model.get(target))))
        form.addRow("ID", QLabel(f"{ident} (assegnato da ATLAS)" if ident else "assegnato da ATLAS"))
        form.addRow("Natura", QLabel(nature))
        form.addRow("Dato di interfaccia", self.item)
        self.name_label, self.meaning_label = QLabel("Nome del dato"), QLabel("Significato")
        form.addRow(self.name_label, self.name)
        form.addRow(self.meaning_label, self.meaning)
        form.addRow("Condizione di produzione", self.condition)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crea lo scambio")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)
        self.item.currentIndexChanged.connect(self._item_changed)
        self._item_changed()
        self.resize(QSize(520, 0))

    def _item_changed(self, _index=0):
        new = self.item.currentData() == NEW_ITEM
        for w in (self.name_label, self.name, self.meaning_label, self.meaning):
            w.setVisible(new)

    def accept(self):
        new = self.item.currentData() == NEW_ITEM
        if new and not self.name.text().strip():
            self.problem.setText("Dai un nome al dato scambiato, o scegline uno del dizionario.")
            return
        same = dg.same_exchange(self.model, self.source, self.target, None if new else self.item.currentData(),
                                self.name.text() if new else None)
        if same is not None:  # the connector is not drawn: the exchange is there already
            message = (f"Tra questi due elementi lo stesso dato è già scambiato da {self.model.label(same)}: uno "
                       "scambio si registra una volta e si riusa. Scegli un altro dato, o annulla.")
            self.problem.setText(message)
            QMessageBox.warning(self, "Scambio già presente", message)
            return
        super().accept()

    def create(self, project):
        """The exchange item (when new) and the exchange, in the model: [elements created]."""
        created = []
        item = self.item.currentData()
        if item == NEW_ITEM:
            new = project.new_element("exchange_item", name=self.name.text().strip(), nature=self.nature,
                                      meaning=self.meaning.toPlainText().strip())
            created.append(new)
            item = new.uuid
        name = self.model.get(item).get("name") or ""  # it recalls the information carried, not the action (B4)
        values = {"name": name, "source": self.source, "target": self.target, "exchange_item": item,
                  "nature": self.nature}
        if self.condition.currentText():
            values["production_condition"] = self.condition.currentText()
        created.append(project.new_element("functional_exchange", **values))
        return created


UNDO_DEPTH = 100


class _Undo:
    """Ctrl+Z and Ctrl+Y in a view: the last changes undone and done again, those of the drawing (moves,
    elements added or taken out, domains opened, «Riordina»…) and those of the model made from the view (elements
    created or deleted). Before a change the page calls remember; it has project, model_edited, _view_state and
    _restore_state."""

    def _setup_undo(self):
        self._undo, self._redo = [], []
        for keys, slot in ((QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo)):
            QShortcut(keys, self, activated=slot, context=Qt.WidgetWithChildrenShortcut)

    def remember(self, remove=(), add=(), state=None):
        """Before a change: the view as it is (or state, taken before); remove, add: the elements of the model to
        delete and to put back to undo it (those created, those deleted)."""
        self._undo.append({"state": self._view_state() if state is None else state,
                           "remove": [e.copy() for e in remove], "add": [e.copy() for e in add]})
        del self._undo[:-UNDO_DEPTH]
        self._redo.clear()

    @local_change
    def undo(self):
        """Ctrl+Z: True when something was undone."""
        return self._step(self._undo, self._redo, "Annullata l'ultima operazione")

    @local_change
    def redo(self):
        """Ctrl+Y: True when something was done again."""
        return self._step(self._redo, self._undo, "Ripetuta l'operazione")

    def _step(self, source, target, message):
        if not source:
            return False
        entry = source.pop()
        target.append({"state": self._view_state(), "remove": entry["add"], "add": entry["remove"]})
        model = self.project.model
        changed = False
        for element in entry["remove"]:
            if model.get(element.uuid) is not None:
                self.project.delete_element(element.uuid)
                changed = True
        for element in entry["add"]:
            self.project.update(element.copy())
            changed = True
        self._restore_state(entry["state"])
        if changed:  # saved with the project, the other views drawn again
            self.model_edited.emit(message)
        return True


class _NewFunctions:
    """Breakdown pages (SA-1, SA-2): a new system function in a domain, put in the model, with the other elements
    that the views use; a new domain (SA-1); the function selected in a domain. The page has project, scene and
    element_created, and may override _function_added and _domain_added."""
    selected_function = None

    def select_function(self, uuid):
        if uuid != self.selected_function:
            self.selected_function = uuid
            if uuid is not None:
                self.scene.clearSelection()  # the function, not its domain
            self.scene.update()

    @local_change
    def new_function(self, domain=None):
        """Returns the function created, or None."""
        dialog = NewFunctionDialog(self.project.model, domain, self)
        if not dialog.exec():
            return None
        state = self._view_state()
        function = self.project.new_element("system_function", name=dialog.name.text().strip(),
                                            domain=dialog.domain.currentData())
        self.remember(remove=[function], state=state)
        self._function_added(function)
        self.element_created.emit(function.uuid)
        return function

    def _function_added(self, function):
        self.opened.add(function.get("domain"))  # its domain open, to show it
        self.refresh()

    @local_change
    def new_domain(self):
        """«Nuovo dominio…» (SA-1): returns the domain created, or None."""
        dialog = NewDomainDialog(self.project.model, self)
        if not dialog.exec():
            return None
        state = self._view_state()
        domain = self.project.new_element("domain", name=dialog.name.text().strip(),
                                          mission=dialog.mission.toPlainText().strip())
        self.remember(remove=[domain], state=state)
        self._domain_added(domain)
        self.element_created.emit(domain.uuid)
        return domain

    def _domain_added(self, domain):
        self.refresh()

    in_view = False  # a view composed by the user: deleted only from it, or from the model too

    def delete_function(self, uuid):
        return self.delete_elements([uuid])

    @local_change
    def delete_elements(self, uuids):
        """«Elimina…» (right click, Canc): asked, with the elements impacted, whether only from the view or from the
        model too (an overview: only from the model). Ctrl+Z puts them back. Returns "view", "model" or None."""
        model = self.project.model
        uuids = list(dict.fromkeys(u for u in uuids if model.get(u) is not None))
        if not uuids:
            return None
        choice, targets = ask_deletion(self, model, uuids, self.in_view)
        if choice == "view":
            self.remove_from_view(uuids)
        elif choice == "model":
            elements = [model.get(u) for u in targets]
            label = model.label(elements[0])
            self.remember(add=elements)
            for uuid in targets:  # gone from the view with them, without the notice of elements gone
                getattr(self, "placed", {}).pop(uuid, None)
                self.opened.discard(uuid)
            self.project.delete_elements(targets)
            self.select_function(None)
            if hasattr(self, "_set_dirty"):
                self._set_dirty(self._view_state() != self._clean)
            self.refresh()
            self.model_edited.emit(f"Eliminato dal modello: {label}" if len(targets) == 1 else
                                   f"Eliminati dal modello: {len(targets)} elementi")
        return choice

    def remove_from_view(self, uuids):
        """An overview shows the whole model: nothing to take out."""

    def domain_actions(self, menu, uuid):
        """Right click on a functional domain, in every view: what can be done on it."""
        domain = self.project.model.get(uuid)
        if domain is None:
            return
        where = f" in {domain.get('id')}" if domain.get("id") else ""
        menu.addAction(icon("mdi6.open-in-app"), "Apri la scheda", lambda: self.open_requested.emit(uuid))
        self._view_actions(menu, uuid)
        menu.addSeparator()
        menu.addAction(icon("mdi6.function-variant"), f"Nuova funzione di sistema{where}…",
                       lambda: self.new_function(uuid))
        menu.addAction(icon("mdi6.view-grid-plus-outline"), "Nuovo dominio funzionale…", self.new_domain)
        menu.addSeparator()
        menu.addAction(icon("mdi6.trash-can-outline"), "Elimina il dominio…", lambda: self.delete_elements([uuid]))

    def _view_actions(self, menu, uuid):
        """The actions of the view on a domain (open, closed, its functions shown)."""

    def domain_menu(self, uuid, pos):
        menu = QMenu()
        self.domain_actions(menu, uuid)
        if menu.actions():
            menu.exec(pos)


def deletion_impacts(model, uuids):
    """What deleting elements from the model touches: the elements that refer to them (their references left
    without a target) and the views that show them (a function also with its whole domain)."""
    uuids = set(uuids)
    shown = uuids | {d for d in (dg.domain_of_function(model, u) for u in uuids) if d}
    views = [v for v in model.of_kind(dg.DIAGRAM) if v.uuid not in uuids and shown & set(dg.positions(v))]
    return model.referencing(uuids), views


def domain_functions(model, uuid):
    return [f for f in model.of_kind("system_function") if f.get("domain") == uuid]


class DeletionDialog(QDialog):
    """Elements deleted from a view (right click, Canc): asks, and shows every element impacted by their deletion
    from the model. From a view composed by the user (in_view): only from the view, or from the model too; from an
    overview of the whole model, only from the model. A domain: its system functions can go with it.
    choice: "view", "model" or None; targets: what goes out of the model."""

    def __init__(self, model, uuids, in_view, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elimina")
        self.model, self.uuids, self.choice = model, list(uuids), None
        elements = [model.get(u) for u in self.uuids]
        if len(elements) == 1:
            what = {"system_function": "la funzione", "domain": "il dominio funzionale"}.get(elements[0].kind, "")
            subject = f"{what} «{model.label(elements[0])}»".strip()
        else:
            subject = f"{len(elements)} elementi"
        layout = QVBoxLayout(self)
        question = f"Eliminare {subject} solo da questa vista o anche dal modello?" if in_view else \
            f"Eliminare {subject} dal modello?"
        layout.addWidget(QLabel(question, objectName="cardTitle", wordWrap=True))
        if in_view:
            layout.addWidget(QLabel("Solo dalla vista: resta nel modello (le funzioni nel catalogo delle funzioni di "
                                    "sistema) e nelle altre viste. Anche dal modello: esce dal modello e da tutte "
                                    "le viste.", objectName="muted", wordWrap=True))
        # The functions of the domains deleted: with them, or left without a domain.
        self.functions = [f for e in elements if e.kind == "domain" for f in domain_functions(model, e.uuid)
                          if f.uuid not in self.uuids]
        self.with_functions = QCheckBox(f"Elimina dal modello anche le {len(self.functions)} funzioni di sistema "
                                        f"del dominio" if len(self.functions) != 1 else
                                        "Elimina dal modello anche la funzione di sistema del dominio")
        self.with_functions.setToolTip("Altrimenti restano nel modello senza dominio")
        self.with_functions.toggled.connect(self._show_impacts)
        if self.functions:
            layout.addWidget(self.with_functions)
        layout.addWidget(QLabel("ELEMENTI IMPATTATI DALL'ELIMINAZIONE DAL MODELLO", objectName="sectionCaption"))
        self.impacts = QTreeWidget()
        self.impacts.setHeaderHidden(True)
        self.none = QLabel("Nessuno: nessun elemento vi fa riferimento e nessun'altra vista lo mostra.",
                           objectName="muted", wordWrap=True)
        layout.addWidget(self.impacts, 1)
        layout.addWidget(self.none)
        layout.addWidget(QLabel("Ctrl+Z annulla l'eliminazione.", objectName="muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        if in_view:
            only = buttons.addButton("Solo dalla vista", QDialogButtonBox.AcceptRole)
            only.clicked.connect(lambda: self._choose("view"))
            only.setDefault(True)
        everywhere = buttons.addButton("Elimina anche dal modello" if in_view else "Elimina dal modello",
                                       QDialogButtonBox.DestructiveRole)
        everywhere.clicked.connect(lambda: self._choose("model"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._show_impacts()
        self.resize(600, 460)

    @property
    def targets(self):
        return self.uuids + ([f.uuid for f in self.functions] if self.with_functions.isChecked() else [])

    def _show_impacts(self):
        model = self.model
        references, views = deletion_impacts(model, self.targets)

        def named(e):  # the kind, once (the label of an element without a name has it already)
            text = model.label(e)
            return text if text.startswith(e.schema.label) else f"{e.schema.label} · {text}"

        by_text = lambda row: natural_key(row[0])  # noqa: E731
        deleted = [model.get(u) for u in self.targets]
        groups = (("Da eliminare", sorted(((named(e), kind_icon(e.kind)) for e in deleted), key=by_text)
                   if len(deleted) > 1 else []),
                  ("Riferimenti che resteranno senza destinazione",
                   sorted(((named(e), kind_icon(e.kind)) for e in references), key=by_text)),
                  ("Viste da cui sparirà" if len(deleted) == 1 else "Viste da cui spariranno",
                   sorted(((v.get("name") or "(vista senza nome)", icon("mdi6.vector-polyline")) for v in views),
                          key=by_text)))
        self.impacts.clear()
        for heading, rows in groups:
            if not rows:
                continue
            group = QTreeWidgetItem([f"{heading} ({len(rows)})"])
            group.setFlags(Qt.ItemIsEnabled)
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            self.impacts.addTopLevelItem(group)
            for text, row_icon in rows:
                item = QTreeWidgetItem([text])
                item.setIcon(0, row_icon)
                group.addChild(item)
            group.setExpanded(True)
        impacted = bool(references or views)
        self.impacts.setVisible(bool(self.impacts.topLevelItemCount()))
        self.none.setVisible(not impacted)

    def _choose(self, choice):
        self.choice = choice
        self.accept()


def ask_deletion(parent, model, uuids, in_view):
    """("view" | "model" | None, the elements to delete from the model)."""
    dialog = DeletionDialog(model, uuids, in_view, parent)
    dialog.exec()
    return dialog.choice, dialog.targets


def _problems(domains, findings_for):
    """{function uuid: codes of its findings} (the last run of the checks)."""
    if findings_for is None:
        return {}
    result = {}
    for d in domains:
        for f in d.functions:
            codes = sorted({finding.code for finding in findings_for(f.uuid)})
            if codes:
                result[f.uuid] = codes
    return result


class BreakdownPage(_Toggles, _NewFunctions, _Undo, QWidget):
    """The overview of the whole model: SA-1 only the domains, SA-2 (with the functions) every domain open on its
    functions, to be closed and opened again."""
    open_requested = Signal(str)
    delete_requested = Signal(str)  # a function, from the model (after a confirmation)
    element_created = Signal(str)  # a new system function: in the model (to be saved), in the views
    model_edited = Signal(str)  # elements deleted, or a creation undone: to be saved

    def __init__(self, project, functions=False, findings_for=None, title="Vista complessiva"):
        super().__init__()
        self.project, self.findings_for, self.title, self.functions = project, findings_for, title, functions
        self.opened = set()
        self._all_open_at_start = functions
        self._setup_toggles()
        self._setup_undo()
        self.scene = QGraphicsScene(self)
        self.canvas = Canvas(self.scene)
        self.canvas.setDragMode(QGraphicsView.ScrollHandDrag)
        self.canvas.menu_requested.connect(self._canvas_menu)
        QShortcut(QKeySequence.Delete, self.canvas, activated=self.delete_selected)
        caption = QLabel(title, objectName="viewTitle")
        hint = QLabel("Clic sul titolo di un dominio: si apre o si chiude · doppio clic: apre la scheda · clic destro "
                      "su una funzione: apri o elimina" if functions else "I domini funzionali · doppio clic: apre "
                      "la scheda · clic destro: nuova funzione di sistema", objectName="muted")
        bar = QHBoxLayout()
        bar.addWidget(caption)
        bar.addWidget(hint, 1)
        if functions:
            bar.addWidget(_toolbar_button("Nuova funzione…", "mdi6.function-variant", self.new_function,
                                          "Nuova funzione di sistema in un dominio (anche: clic destro sul dominio)"))
        else:
            bar.addWidget(_toolbar_button("Nuovo dominio…", "mdi6.view-grid-plus-outline", self.new_domain,
                                          "Nuovo dominio funzionale nel modello"))
        if functions:
            bar.addWidget(_toolbar_button("Apri tutti", "mdi6.arrow-expand-all", self.open_all))
            bar.addWidget(_toolbar_button("Chiudi tutti", "mdi6.arrow-collapse-all", self.close_all))
        bar.addWidget(_toolbar_button("Esporta immagine…", "mdi6.image-outline",
                                      lambda: export_image(self, self.scene, self.title)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 0)  # the canvas down to the bottom of the window
        layout.addLayout(bar)
        layout.addWidget(self.canvas, 1)
        self.refresh()

    def refresh(self):
        self.domains = dg.breakdown(self.project.model)
        if self._all_open_at_start:
            self.opened = {d.uuid for d in self.domains if d.uuid}
            self._all_open_at_start = False
        self.opened &= {d.uuid for d in self.domains}
        self.scene.clear()
        self.blocks = draw_breakdown(self, self.scene, self.domains, self.opened,
                                     _problems(self.domains, self.findings_for), expandable=self.functions)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))

    def _view_actions(self, menu, uuid):
        if self.functions:
            opened = uuid in self.opened
            menu.addAction(icon("mdi6.arrow-collapse-vertical" if opened else "mdi6.arrow-expand-vertical"),
                           "Chiudi il dominio" if opened else "Apri il dominio", lambda: self.toggle(uuid))

    def delete_selected(self):
        """Canc: the function selected, out of the model (asked)."""
        if self.selected_function:
            self.delete_elements([self.selected_function])

    def _canvas_menu(self, pos):
        """Right click on an empty place of the canvas: the zoom."""
        menu = QMenu()
        self.canvas.zoom_actions(menu, self.canvas.viewport().mapFromGlobal(pos))
        menu.exec(pos)

    def toggle(self, uuid):
        self.remember()
        self.opened ^= {uuid}
        self.refresh()

    def _function_added(self, function):
        if self.functions:  # its domain open, to show it
            self.opened.add(function.get("domain"))
        self.refresh()

    def open_all(self):
        self.remember()
        self.opened = {d.uuid for d in self.domains if d.uuid}
        self.refresh()

    def close_all(self):
        self.remember()
        self.opened = set()
        self.refresh()

    def _view_state(self):
        return set(self.opened)

    def _restore_state(self, state):
        self.opened = set(state)
        self.refresh()


# --- views composed by the user ----------------------------------------------------------------------------

class ElementList(QTreeWidget):
    """The elements of the model that can be added: dragged into the view, or with a double click."""

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragOnly)
        self.setIndentation(10)

    def mimeData(self, items):
        data = QMimeData()
        keys = [i.data(0, Qt.UserRole) for i in items if i.data(0, Qt.UserRole)]
        if keys:
            data.setData(MIME, keys[0].encode())
        return data


class DiagramPage(_Toggles, _NewFunctions, _Undo, QWidget):
    """A view composed by the user: the drawing, and at its side the elements of the model to add."""
    open_requested = Signal(str)
    saved = Signal()
    dirty_changed = Signal(bool)
    delete_requested = Signal(str)  # a function of a breakdown, from the model (after a confirmation)
    element_created = Signal(str)  # a new domain, function or exchange, in the model and in the view
    model_edited = Signal(str)  # elements deleted from the view (a dataflow: exchanges, data): to be saved

    def __init__(self, project, view, findings_for=None):
        super().__init__()
        self.project, self.view, self.findings_for = project, view, findings_for
        self.dirty = False
        self.opened = set()  # a breakdown: its domains shown open
        self.anchors = {}  # a dataflow: {exchange: "R500 L250"}, where its arrow leaves and reaches its elements
        self._setup_toggles()
        self._setup_undo()
        self.items = {}
        self.arrows = []
        self.blocks = []
        self.scene = QGraphicsScene(self)
        self.canvas = Canvas(self.scene)
        self.canvas.dropped.connect(self.add)
        self.canvas.connected.connect(self.connect_elements)
        self.canvas.end_moved.connect(self.move_end)
        self.canvas.menu_requested.connect(self._canvas_menu)
        # While elements are dragged, the arrows near them once after each move; all of them when released.
        self._routing = QTimer(self, singleShot=True, interval=0, timeout=lambda: self._refresh_arrows(False))
        self._moving = set()
        self._guides = []  # the lines of an alignment, while a block is dragged
        self.canvas.released.connect(lambda: self._moving and self._refresh_arrows())
        # A drag of elements: one change, from where they were when the mouse was pressed.
        self._gesture = None
        self.canvas.pressed.connect(self._gesture_started)
        self.canvas.released.connect(self._gesture_ended)
        self._freed = {}  # (source, target) → the datum of an exchange deleted here, proposed again

        self.title = QLabel(objectName="viewTitle")
        self.unsaved = QLabel("● modifiche non salvate")
        self.unsaved.setStyleSheet(f"color: {WARN}; font-weight: 600;")
        self.unsaved.hide()
        self.level = QComboBox()
        self.level.addItems(DIAGRAM_LEVELS)
        self.level.setToolTip("Passi e linee di vita per dominio o per funzione di sistema")
        self.level.currentTextChanged.connect(self._level_changed)
        self.arrange_button = _toolbar_button("Riordina", "mdi6.auto-fix", self.arrange,
                                              "Dispone gli elementi in automatico")
        self.function_button = _toolbar_button("Nuova funzione…", "mdi6.function-variant", self.new_function,
                                               "Nuova funzione di sistema in un dominio, aggiunta alla vista e agli "
                                               "elementi del modello (anche: clic destro sul dominio)")
        self.domain_button = _toolbar_button("Nuovo dominio…", "mdi6.view-grid-plus-outline", self.new_domain,
                                             "Nuovo dominio funzionale, aggiunto alla vista e agli elementi del "
                                             "modello")
        export = _toolbar_button("Esporta immagine…", "mdi6.image-outline",
                                 lambda: export_image(self, self.scene, self.view.get("name") or "vista"))
        self.save_button = QPushButton(icon("mdi6.content-save-outline", "white"), "Salva vista")
        self.save_button.setProperty("primary", True)
        self.save_button.setToolTip("Salva la vista nel modello (Ctrl+S)")
        self.save_button.clicked.connect(self.save_view)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 12, 0)
        bar.addWidget(self.title)
        bar.addWidget(self.unsaved)
        bar.addStretch(1)
        for w in (self.level, self.domain_button, self.function_button, self.arrange_button, export,
                  self.save_button):
            bar.addWidget(w)
        self.notice = QLabel(objectName="muted", wordWrap=True)
        self.notice.setStyleSheet(f"color: {WARN};")
        self.notice.hide()

        self.search = QLineEdit(placeholderText="Cerca per ID o nome", objectName="search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.elements = ElementList()
        self.elements.itemDoubleClicked.connect(self._double_clicked)
        hint = QLabel("Trascina un elemento nella vista o fai doppio clic. Ci sono solo elementi già nel modello.",
                      objectName="muted", wordWrap=True)
        # A dataflow: the hand, which moves the elements, and the connectors, one for each nature of the data.
        self.connectors = QFrame()
        connectors_layout = QVBoxLayout(self.connectors)
        connectors_layout.setContentsMargins(8, 10, 8, 8)
        self.connector_buttons = {}
        tools = [(None, "Sposta", "sposta gli elementi e seleziona gli scambi")] + list(CONNECTORS)
        for nature, label, tip in tools:
            if nature is None:
                button = QPushButton(icon("mdi6.hand-back-right-outline"), label)
                button.setToolTip(f"{label}: {tip} (Esc)")
            else:
                button = QPushButton(line_icon(nature), f"{label} ({nature})")
                button.setToolTip(f"{tip}: trascina da una funzione a un'altra per creare lo scambio")
            button.setIconSize(QSize(40, 14))
            button.setCheckable(True)
            button.setStyleSheet(f"QPushButton {{ text-align: left; }} QPushButton:checked {{ background: "
                                 f"{ACCENT_SOFT}; border: 2px solid {ACCENT}; color: {ACCENT}; font-weight: 600; }}")
            button.toggled.connect(lambda on, n=nature: self.set_connector(n if on else None))
            connectors_layout.addWidget(button)
            self.connector_buttons[nature] = button
        connectors_layout.addWidget(QLabel("Con la mano: trascina gli elementi per spostarli, uno spazio vuoto "
                                           "per muoverti sulla tela, Maiusc + trascina per selezionarne più di uno. "
                                           "Scegli un connettore e trascina da una funzione di sistema a un'altra "
                                           "(o a un attore esterno). La mano, o Esc, per tornare a spostare gli "
                                           "elementi.",
                                           objectName="muted", wordWrap=True))
        connectors_layout.addStretch(1)
        # The panel at the side: two tabs, the tools (a dataflow) and the elements of the model.
        listing = QFrame()
        listing_layout = QVBoxLayout(listing)
        listing_layout.setContentsMargins(8, 8, 8, 8)
        listing_layout.addWidget(self.search)
        listing_layout.addWidget(self.elements, 1)
        listing_layout.addWidget(hint)
        self.listing = listing
        self.side_tabs = QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.setUsesScrollButtons(False)
        self.side_tabs.addTab(self.connectors, icon("mdi6.vector-line"), "Strumenti")
        self.side_tabs.setTabToolTip(0, "La mano e i connettori")
        self.side_tabs.addTab(listing, icon("mdi6.playlist-plus"), "Elementi")
        self.side_tabs.setTabToolTip(1, "Gli elementi del modello da aggiungere alla vista")
        self.side_tabs.tabBar().hide()  # chosen from the bar of icons at the right (ActivityBar)
        caption = QLabel(objectName="sectionCaption")
        caption.setContentsMargins(8, 8, 8, 0)
        self.side_tabs.currentChanged.connect(lambda i: caption.setText(self.side_tabs.tabText(i).upper()))
        self.side_caption = caption
        side = QFrame(objectName="panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(caption)
        side_layout.addWidget(self.side_tabs, 1)
        self.side = side
        split = QSplitter()
        split.addWidget(self.canvas)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setSizes([900, 280])
        # The panel closed towards the right and opened again from its icons, as the one at the left of the window.
        self.activity = ActivityBar(side, self.side_tabs, split, SIDE_ICONS, settings(), side="right",
                                    key="views/panel", width=280, shortcut="Ctrl+Alt+B")
        QShortcut(QKeySequence("Ctrl+Alt+B"), self, activated=self.activity.toggle,
                  context=Qt.WidgetWithChildrenShortcut)
        work = QHBoxLayout()
        work.setSpacing(0)
        work.setContentsMargins(0, 0, 0, 0)
        work.addWidget(split, 1)
        work.addWidget(self.activity)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 0, 0)  # the canvas and the panel down to the bottom, the icons to the edge
        layout.addLayout(bar)
        layout.addWidget(self.notice)
        layout.addLayout(work, 1)
        QShortcut(QKeySequence.Delete, self.canvas, activated=self.delete_selected)
        QShortcut(QKeySequence(Qt.Key_Escape), self.canvas, activated=lambda: self.set_connector(None))
        QShortcut(QKeySequence.SelectAll, self, activated=self.select_all, context=Qt.WidgetWithChildrenShortcut)
        self.set_connector(None)  # the hand
        self.discard_changes(remember=False)
        # An empty view starts from the elements to add; one with elements, from the tools.
        self.side_tabs.setCurrentWidget(self.connectors if self.diagram_type == DIAGRAM_DATAFLOW and self.placed
                                        else self.listing)
        self.side_caption.setText(self.side_tabs.tabText(self.side_tabs.currentIndex()).upper())

    # --- state -------------------------------------------------------------------------------------

    @property
    def diagram_type(self):
        return self.view.get("diagram_type")

    def working(self):
        """The view as it is in the page (not saved yet)."""
        view = self.view.copy()
        dg.set_positions(view, self.placed)
        anchors = {k: v for k, v in sorted(self.anchors.items()) if self.project.model.get(k) is not None}
        if anchors or view.get("anchors"):
            view.set("anchors", anchors)
        if self.diagram_type in dg.BREAKDOWN_TYPES:
            view.set("opened", sorted(k for k in self.opened if k in self.placed))
        else:
            view.set("level", self.level.currentText())
        return view

    def _set_dirty(self, dirty):
        if dirty != self.dirty:
            self.dirty = dirty
            self.unsaved.setVisible(dirty)
            self.dirty_changed.emit(dirty)

    def discard_changes(self, remember=True):
        """Back to the view as saved in the model (Ctrl+Z brings the changes back)."""
        if remember:
            self.remember()
        self.placed = dg.positions(self.view)
        self.opened = set(self.view.get("opened") or [])
        self.anchors = dict(self.view.get("anchors") or {})
        self.level.blockSignals(True)
        self.level.setCurrentText(dg.level(self.view))
        self.level.blockSignals(False)
        self._level_shown = self.level.currentText()
        self._set_dirty(False)
        self.refresh()
        self._clean = self._view_state()  # as saved (with the places given to the elements not placed yet)

    @local_change
    def save_view(self):
        """«Salva vista»: what the view shows and where goes into the model, and the project is saved."""
        previous = self.view.copy()
        current = self.working()
        self.view.values = current.values
        self.project.update(self.view, previous)
        self._set_dirty(False)
        self._clean = self._view_state()
        self.saved.emit()

    # --- undo ----------------------------------------------------------------------------------------

    def _view_state(self):
        return dict(self.placed), set(self.opened), self.level.currentText(), dict(self.anchors)

    def _restore_state(self, state):
        placed, opened, level, anchors = state
        self.placed, self.opened, self.anchors = dict(placed), set(opened), dict(anchors)
        self.level.blockSignals(True)
        self.level.setCurrentText(level)
        self.level.blockSignals(False)
        self._level_shown = level
        self.refresh()
        self._set_dirty(self._view_state() != self._clean)

    def _gesture_started(self):
        self._gesture = self._view_state()

    def _gesture_ended(self):
        if self._gesture is not None and self._gesture != self._view_state():
            self.remember(state=self._gesture)
        self._gesture = None

    # --- building ---------------------------------------------------------------------------------

    def refresh(self):
        """Draw the view again from the model (names, exchanges and steps may have changed)."""
        model = self.project.model
        self.title.setText(self.view.get("name") or "(vista senza nome)")
        self.level.setVisible(self.diagram_type in (DIAGRAM_CHAIN, DIAGRAM_SCENARIO))
        self.arrange_button.setVisible(self.diagram_type in (DIAGRAM_DATAFLOW, DIAGRAM_CHAIN))
        self.domain_button.setVisible(self.diagram_type == DIAGRAM_BREAKDOWN)
        self.function_button.setVisible(self.diagram_type == DIAGRAM_FUNCTIONS)
        self.side_tabs.setTabVisible(0, self.diagram_type == DIAGRAM_DATAFLOW)  # the tools: only a dataflow
        self.activity.show_state()
        gone = dg.missing(model, self.working())
        if gone:
            for key in gone:
                self.placed.pop(key, None)
            self._set_dirty(True)
        notes = []
        if gone:
            notes.append(f"{len(gone)} elementi non più nel modello sono stati tolti dalla vista: salvala per "
                         "confermare.")
        if self.diagram_type in (DIAGRAM_CHAIN, DIAGRAM_SCENARIO) and model.get(self.view.get("chain") or "") is None:
            notes.append("La functional chain della vista non è più nel modello.")
        self.notice.setText(" ".join(notes))
        self.notice.setVisible(bool(notes))
        self.canvas._highlighted = set()  # its boxes go with the scene
        self.scene.clear()
        self.items, self.arrows, self.blocks = {}, [], []
        self._moving = set()  # its items go with the scene
        self._guides = []
        if self.diagram_type in dg.BREAKDOWN_TYPES:
            self._draw_breakdown()
        elif self.diagram_type == DIAGRAM_DATAFLOW:
            self._draw_dataflow()
        elif self.diagram_type == DIAGRAM_CHAIN:
            self._draw_chain()
        elif self.diagram_type == DIAGRAM_SCENARIO:
            self._draw_scenario()
        if not self.items and not self.arrows:
            empty = self.scene.addSimpleText("Vista vuota: aggiungi gli elementi dall'elenco a destra, trascinandoli "
                                             "qui o con un doppio clic.", _font(9.5))
            empty.setBrush(QColor(MUTED))
            empty.setPos(30, 30)
        self.canvas.grow()
        self._fill_list()

    def _box(self, key, w, h, pos, **kwargs):
        box = Box(key, w, h, movable=self.diagram_type != DIAGRAM_SCENARIO, **kwargs)
        box.setPos(*pos)
        box.on_move = self._moved  # after it is placed: only the moves of the user change the view
        box.on_open = self._open
        self.scene.addItem(box)
        self.items[key] = box
        return box

    def _has_problems(self, uuid):
        return bool(self.findings_for(uuid)) if self.findings_for is not None and uuid else False

    def _draw_breakdown(self):
        domains = dg.view_breakdown(self.project.model, self.working())
        if not domains:
            return
        opened = self.opened | {d.uuid for d in domains if d.partial}  # functions added alone: always shown
        self.items.update(draw_breakdown(self, self.scene, domains, opened,
                                         _problems(domains, self.findings_for), selectable=True))

    def _domain_added(self, domain):
        """A domain created from the view is in it (the change remembered with its creation)."""
        self.placed[domain.uuid] = None
        self._set_dirty(True)
        self.refresh()

    def _function_added(self, function):
        """A function created from the view is in it: in its domain, if the domain is in the view, else alone."""
        domain = function.get("domain")
        if domain in self.placed:
            self.opened.add(domain)
        else:
            self.placed[function.uuid] = None
        self._set_dirty(True)
        self.refresh()

    def toggle(self, uuid):
        """A click on a domain of a breakdown: open on its functions, or closed (saved with the view)."""
        if uuid not in self.placed:
            return
        self.remember()
        self.opened ^= {uuid}
        self._set_dirty(True)
        self.refresh()

    def _draw_dataflow(self):
        df = dg.dataflow(self.project.model, self.working())
        laid = dg.auto_layout(df, self.placed)
        self.placed.update(laid)  # elements not placed yet (e.g. a view received from a colleague): no change
        self._kinds = {key: node.kind for key, node in df.nodes.items()}
        for key, node in df.nodes.items():
            style = ACTOR if node.kind == "external_actor" else PROBLEM if self._has_problems(key) else NORMAL
            note = f"+{node.outside} scamb{'io' if node.outside == 1 else 'i'} fuori vista" if node.outside else ""
            kind = {"external_actor": "attore esterno", "domain": "dominio"}.get(node.kind, "")
            self._box(key, dg.NODE_W, dg.NODE_H, laid[key], ident=node.ident or kind, text=node.name, note=note,
                      style=style, badge=kind if node.ident else "")
        for c in df.containers.values():
            block = Block(c.key, c.ident, c.name, [self.items[k] for k in c.members])
            block.on_open = self._open
            block.on_snap = self._snap
            block.on_menu = self.domain_menu
            self.scene.addItem(block)
            block.fit()
            self.blocks.append(block)
            self.items.setdefault(c.key, block)  # arrows of the exchanges of the domain end on its block
        pairs = {(e.source, e.target) for e in df.edges}
        for e in df.edges:
            lines = []
            for x in e.exchanges:
                lines += [x.data or "(senza dato)", x.ident or ""]
            source, target = self.items[e.source], self.items[e.target]
            offset = 14 if (e.target, e.source) in pairs else 0
            lane = len(self.arrows) % 5 - 2
            anchors = self._anchors_of(e)
            arrow = Arrow(_between(source, target, offset),
                          [line for line in lines if line != ""] if len(e.exchanges) == 1 else lines,
                          dashed=e.event, key=e.exchanges[0].uuid, nature=e.nature,
                          exchanges=[x.uuid for x in e.exchanges],
                          route=_routed(source, target, lambda s=source, t=target: self._obstacles(s, t), offset,
                                        lane, anchors))
            arrow.setFlag(QGraphicsItem.ItemIsSelectable)  # Canc or right click: deleted from the model
            arrow.on_open = self._open
            arrow.on_menu = self._arrow_menu
            arrow.between = (source, target)
            arrow.handles_always = handles_shown()
            arrow.movable_ends = isinstance(source, Box) and isinstance(target, Box) and any(
                (fe.get("source"), fe.get("target")) == (e.source, e.target)
                for fe in (self.project.model.get(x.uuid) for x in e.exchanges) if fe is not None)
            self.scene.addItem(arrow)
            self.arrows.append(arrow)
        for box in self.items.values():
            if isinstance(box, Box):  # aligned (a domain without functions, an actor) or on the grid
                box.on_snap = self._snap
                box.on_menu = self._box_menu
        taken = {}  # the anchors the connectors take on each element: more are offered when a side is full
        for uuid, text in self.anchors.items():
            fe, ends = self.project.model.get(uuid), text.split()
            if fe is not None and len(ends) == 2:
                taken.setdefault(fe.get("source"), set()).add(ends[0])
                taken.setdefault(fe.get("target"), set()).add(ends[1])
        for key, box in self.items.items():
            if isinstance(box, Box):
                box.used_anchors = taken.get(key, set())
                box.anchor_ids = anchor_ids(box.used_anchors)
        self._refresh_arrows()  # the labels, once every arrow has its path

    def _step_text(self, s):
        by = self.level.currentText()
        if by == dg.BY_DOMAIN and s.domain_ident:
            return s.domain_ident, s.domain_name
        return s.function_ident, s.function_name

    def _draw_chain(self):
        steps = dg.shown_steps(self.project.model, self.working())
        laid = dg.chain_layout(steps, self.placed)
        self.placed.update({s.key: laid[s.key] for s in steps})
        for s in steps:
            ident, name = self._step_text(s)
            data = " · ".join(p for p in (s.data, s.nature) if p)
            style = PROBLEM if self._has_problems(s.function) else BOUNCE if s.bounce else NORMAL
            box = self._box(s.key, dg.STEP_W, dg.STEP_H, laid[s.key], ident=f"{s.index + 1} · {ident}".strip(" ·"),
                            text=f"{name}\n\n{s.what}".strip(), note=data, style=style,
                            badge=f"ciclo {s.cycle}" if s.cycle else "")
            box.setToolTip(f"Passo {s.index + 1}: {s.what}" + ("\nRitorno a un dominio già percorso: rimbalzo "
                                                              "(regola D4)" if s.bounce else ""))
        for a, b in zip(steps, steps[1:]):
            arrow = Arrow(_between(self.items[a.key], self.items[b.key]), dashed=a.nature == "EVENT",
                          color=WARN if b.bounce else ARROW, key=a.exchange)
            arrow.on_open = self._open
            self.scene.addItem(arrow)
            self.arrows.append(arrow)
        if any(s.bounce for s in steps):
            unit = "dominio" if self.level.currentText() == dg.BY_DOMAIN else "funzione"
            legend = self.scene.addSimpleText(f"In giallo: ritorno a un {unit} già percorso dalla catena, dopo "
                                              "un altro (rimbalzo, regola D4).", _font(8.5))
            legend.setBrush(QColor(WARN))
            bottom = max(self.items[s.key].pos().y() for s in steps) + dg.STEP_H + 16
            legend.setPos(min(self.items[s.key].pos().x() for s in steps), bottom)

    def _draw_scenario(self):
        sc = dg.scenario(self.project.model, self.working())
        x0, dx, head_w, head_h, top, dy = 40, 190, 160, 62, 124, 48
        x_of = {l.key: x0 + i * dx + head_w / 2 for i, l in enumerate(sc.lifelines)}
        bottom = top + max(len(sc.messages), 1) * dy + 10
        right = x0 + max(len(sc.lifelines), 1) * dx
        # Cycles: consecutive messages of the same cycle in a band, one band out of two shaded.
        start, bands = 0, 0
        for i in range(1, len(sc.messages) + 1):
            if i == len(sc.messages) or sc.messages[i].cycle != sc.messages[start].cycle:
                if sc.messages[start].cycle:
                    y = top + start * dy - dy / 2 + 6
                    band = self.scene.addRect(QRectF(0, y, right, (i - start) * dy), QPen(Qt.NoPen),
                                              QBrush(QColor(ACCENT_SOFT if bands % 2 == 0 else BG)))
                    band.setZValue(-3)
                    label = self.scene.addSimpleText(f"Ciclo {sc.messages[start].cycle}", _font(8, bold=True))
                    label.setBrush(QColor(MUTED))
                    label.setPos(4, y + 2)
                    bands += 1
                start = i
        for i, l in enumerate(sc.lifelines):
            self._box(l.key, head_w, head_h, (x0 + i * dx, 20), ident=l.ident or ("attore esterno" if l.actor else ""),
                      text=l.name, style=ACTOR if l.actor else NORMAL)
            line = self.scene.addLine(x_of[l.key], 20 + head_h, x_of[l.key], bottom,
                                      QPen(QColor(BORDER), 1.2, Qt.DashLine))
            line.setZValue(-2)
        for i, m in enumerate(sc.messages):
            y = top + i * dy
            a, b = x_of[m.source], x_of[m.target]
            if a == b:  # a step that stays on its lifeline: a short loop
                b = a + 40
            ends = (lambda a=a, b=b, y=y: (QPointF(a, y), QPointF(b, y)))
            arrow = Arrow(ends, [m.label] + ([m.ident] if m.ident else []), dashed=m.nature == "EVENT",
                          key=self._exchange_of(m.step), label_above=True)
            arrow.on_open = self._open
            self.scene.addItem(arrow)
            self.arrows.append(arrow)

    def _exchange_of(self, index):
        steps = dg.chain_steps(self.project.model, self.view)
        return steps[index].exchange if 0 <= index < len(steps) else None

    # --- the list of the elements of the model -----------------------------------------------------

    def _fill_list(self):
        self.elements.clear()
        groups = {}
        for a in dg.addable(self.project.model, self.working()):
            group = groups.get(a.group)
            if group is None:
                group = QTreeWidgetItem(self.elements, [a.group])
                group.setFlags(Qt.ItemIsEnabled)
                font = group.font(0)
                font.setBold(True)
                group.setFont(0, font)
                group.setExpanded(True)
                groups[a.group] = group
            item = QTreeWidgetItem(group, [" ".join(p for p in (a.ident, a.name) if p)])
            item.setData(0, Qt.UserRole, a.key)
            item.setToolTip(0, item.text(0))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        if not groups:
            empty = QTreeWidgetItem(self.elements, ["Tutto è già nella vista"])
            empty.setFlags(Qt.ItemIsEnabled)
        self._filter(self.search.text())

    def _filter(self, text):
        text = text.lower().strip()
        for i in range(self.elements.topLevelItemCount()):
            group = self.elements.topLevelItem(i)
            visible = 0
            for j in range(group.childCount()):
                child = group.child(j)
                hidden = bool(text) and text not in child.text(0).lower()
                child.setHidden(hidden)
                visible += not hidden
            group.setHidden(bool(text) and group.childCount() > 0 and not visible)

    def _double_clicked(self, item, _column):
        key = item.data(0, Qt.UserRole)
        if key:
            self.add(key)

    # --- changes ---------------------------------------------------------------------------------------

    def add(self, key, pos=None):
        """Add an element of the model (or a step of the chain) to the view: where it was dropped, or in a free
        place."""
        if key in self.placed or key not in {a.key for a in dg.addable(self.project.model, self.working())}:
            return
        self.remember()
        movable = self.diagram_type in (DIAGRAM_DATAFLOW, DIAGRAM_CHAIN)  # a breakdown is laid out in its grid
        self.placed[key] = (round(pos.x() - dg.NODE_W / 2), round(pos.y() - dg.NODE_H / 2)) \
            if pos is not None and movable else None
        if self.diagram_type == DIAGRAM_FUNCTIONS:
            self.opened.add(key)  # «Funzioni per dominio» (SA-2): a domain added shows its functions
        self._set_dirty(True)
        self.refresh()

    in_view = True

    def remove_from_view(self, uuids):
        """Elements out of the view, not out of the model: a domain with its functions; a function shown with its
        whole domain (a breakdown): the domain stays with its other functions."""
        model = self.project.model
        keys, others = set(), set()
        for uuid in uuids:
            keys.add(uuid)
            e = model.get(uuid)
            if e is not None and e.kind == "domain":
                keys |= {f.uuid for f in domain_functions(model, uuid)}
        if self.diagram_type in (DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS):
            for uuid in list(keys):
                domain = dg.domain_of_function(model, uuid)
                if domain and domain in self.placed and domain not in keys:
                    keys.add(domain)
                    others |= {f.uuid for f in domain_functions(model, domain)}
        others -= keys
        if not keys & set(self.placed) and not others:
            return
        self.remember()
        for key in keys:
            self.placed.pop(key, None)
            self.opened.discard(key)
        for key in others:
            self.placed.setdefault(key, None)
        self.select_function(None)
        self._set_dirty(True)
        self.refresh()

    def remove_function(self, uuid):
        self.remove_from_view([uuid])

    def _view_actions(self, menu, uuid):
        model = self.project.model
        functions = sorted(domain_functions(model, uuid), key=lambda f: natural_key(f.get("id") or f.label))
        if self.diagram_type == DIAGRAM_DATAFLOW:
            missing = [f for f in functions if f.uuid not in self.placed]
            if missing:
                more = menu.addMenu(icon("mdi6.playlist-plus"), "Aggiungi alla vista una funzione del dominio")
                for f in missing:
                    more.addAction(" ".join(dg.ident_and_name(f)).strip(), lambda u=f.uuid: self.add(u))
                if len(missing) > 1:
                    more.addSeparator()
                    more.addAction("Tutte le funzioni del dominio", lambda: self.add_all([f.uuid for f in missing]))
        elif self.diagram_type in (DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS):
            if uuid not in self.placed:  # only some of its functions, added alone
                if any(f.uuid not in self.placed for f in functions):
                    menu.addAction(icon("mdi6.playlist-plus"), "Mostra tutte le funzioni del dominio",
                                   lambda: self.show_whole_domain(uuid))
            else:
                opened = uuid in self.opened
                menu.addAction(icon("mdi6.arrow-collapse-vertical" if opened else "mdi6.arrow-expand-vertical"),
                               "Chiudi il dominio" if opened else "Apri il dominio", lambda: self.toggle(uuid))

    def add_all(self, keys):
        """Several elements of the model added to the view at once (one change)."""
        addable = {a.key for a in dg.addable(self.project.model, self.working())}
        keys = [k for k in keys if k not in self.placed and k in addable]
        if not keys:
            return
        self.remember()
        for key in keys:
            self.placed[key] = None
        self._set_dirty(True)
        self.refresh()

    def show_whole_domain(self, uuid):
        """A domain of a breakdown with only some of its functions: all of them, the domain in the view."""
        self.remember()
        for f in domain_functions(self.project.model, uuid):
            self.placed.pop(f.uuid, None)
        self.placed[uuid] = None
        self.opened.add(uuid)
        self._set_dirty(True)
        self.refresh()

    def _box_menu(self, box, pos):
        """Right click on an element of a dataflow."""
        kind = self._kinds.get(box.key)
        if kind == "domain":
            self.domain_menu(box.key, pos)
            return
        menu = QMenu()
        menu.addAction(icon("mdi6.open-in-app"), "Apri la scheda", lambda: self._open(box.key))
        menu.addSeparator()
        label = "Elimina la funzione…" if kind == "system_function" else "Elimina…"
        menu.addAction(icon("mdi6.trash-can-outline"), label, lambda: self.delete_elements([box.key]))
        menu.exec(pos)

    def remove(self, keys):
        """Take elements out of the view (not out of the model)."""
        keys = [k for k in keys if k in self.placed]
        if not keys:
            return
        self.remember()
        for key in keys:
            self.placed.pop(key)
        self._set_dirty(True)
        self.refresh()

    # --- connectors of a dataflow ----------------------------------------------------------------------

    def set_connector(self, nature):
        """The connector chosen in the side panel (None: the hand, the elements are moved again)."""
        self.connector = nature
        for n, button in self.connector_buttons.items():
            button.blockSignals(True)
            button.setChecked(n == nature)
            button.blockSignals(False)
        self.canvas.connecting = self._connectable if nature else None
        if not nature:
            self.canvas.highlight()
        self.canvas.setDragMode(QGraphicsView.NoDrag if nature else QGraphicsView.RubberBandDrag)
        self.canvas.viewport().setCursor(Qt.CrossCursor if nature else Qt.ArrowCursor)

    connector = None

    def _connectable(self, key):
        return getattr(self, "_kinds", {}).get(key) in dg.CONNECTABLE

    @local_change
    def connect_elements(self, source, target, source_anchor=None, target_anchor=None):
        """A connector drawn from an element to another (from an anchor point to another): the functional exchange,
        with its datum (asked); the anchors kept in the view. Returns the exchange created, or None."""
        kinds = {self._kinds.get(source), self._kinds.get(target)}
        if self.connector is None or not kinds <= set(dg.CONNECTABLE) or kinds == {"external_actor"}:
            return None
        dialog = NewExchangeDialog(self.project.model, source, target, self.connector,
                                   self._freed.get((source, target)), self)
        if not dialog.exec():
            return None
        state = self._view_state()
        created = dialog.create(self.project)
        self.remember(remove=created, state=state)
        self._freed.pop((source, target), None)
        if source_anchor and target_anchor:
            self.anchors[created[-1].uuid] = f"{source_anchor} {target_anchor}"
            self._set_dirty(True)
        self.refresh()
        for element in created:
            self.element_created.emit(element.uuid)
        return created[-1]

    def _canvas_menu(self, pos):
        """Right click on an empty place of the canvas."""
        menu = QMenu()
        if self.diagram_type == DIAGRAM_DATAFLOW:
            shown = menu.addAction("Mostra i punti di aggancio dei connettori")
            shown.setCheckable(True)
            shown.setChecked(handles_shown())
            shown.setToolTip("I quadratini alle estremità delle frecce, da trascinare su un altro punto di attacco; "
                             "tolta la spunta, solo sulla freccia selezionata")
            shown.toggled.connect(self.show_handles)
            menu.addSeparator()
        menu.addAction(icon("mdi6.select-all"), "Seleziona tutto\tCtrl+A", self.select_all)
        menu.addSeparator()
        self.canvas.zoom_actions(menu, self.canvas.viewport().mapFromGlobal(pos))
        menu.exec(pos)

    def show_handles(self, shown):
        """The handles of every arrow shown, or only of the one selected; kept for the next views and sessions."""
        settings().setValue(HANDLES_KEY, bool(shown))
        for arrow in self.arrows:
            arrow.handles_always = bool(shown)
            arrow.update()

    def move_end(self, arrow, end, anchor):
        """An end of an arrow dragged to another anchor point of its element: kept in the view for its exchanges
        (the other end where it is now). Returns True when it changed."""
        model = self.project.model
        source, target = arrow.between
        ends = [nearest_anchor(source.mapRectToScene(source.rect()), arrow._a, source.anchor_ids),
                nearest_anchor(target.mapRectToScene(target.rect()), arrow._b, target.anchor_ids)]
        exchanges = [u for u in arrow.exchanges if model.get(u) is not None and
                     (model.get(u).get("source"), model.get(u).get("target")) == (source.key, target.key)]
        if not exchanges:
            return False
        current = self.anchors.get(exchanges[0], "").split()
        if len(current) == 2:
            ends = current
        if ends[end] == anchor:
            return False
        self.remember()
        ends[end] = anchor
        for uuid in exchanges:
            self.anchors[uuid] = " ".join(ends)
        self._set_dirty(True)
        self.refresh()
        return True

    def _arrow_menu(self, arrow, pos):
        model = self.project.model
        menu = QMenu()
        for uuid in arrow.exchanges:
            fe = model.get(uuid)
            if fe is not None:
                menu.addAction(icon("mdi6.open-in-app"), f"Apri {model.label(fe)}",
                               lambda _=False, u=uuid: self.open_requested.emit(u))
        menu.addSeparator()
        menu.addAction(icon("mdi6.trash-can-outline"),
                       "Elimina lo scambio…" if len(arrow.exchanges) == 1 else "Elimina gli scambi…",
                       lambda _=False: self.delete_exchanges(arrow.exchanges))
        menu.exec(pos)

    @local_change
    def delete_exchanges(self, uuids):
        """Delete exchanges from the model, after a confirmation; for each datum no other exchange carries, ask
        whether to take it out of the dictionary too (kept, it is proposed again for a new connector). Returns
        True when deleted."""
        model = self.project.model
        exchanges = [model.get(u) for u in dict.fromkeys(uuids) if model.get(u) is not None]
        if not exchanges:
            return False
        names = "\n".join(f"• {model.label(fe)}" for fe in exchanges)
        if QMessageBox.question(self, "Elimina", f"Eliminare dal modello:\n{names}?") != QMessageBox.Yes:
            return False
        state, gone = self._view_state(), [fe.copy() for fe in exchanges]
        for fe in exchanges:
            self.project.delete_element(fe.uuid)
        deleted = len(exchanges)
        for item in dg.unused_items(model, [fe.get("exchange_item") for fe in exchanges]):
            label = model.label(model.get(item))
            answer = QMessageBox.question(self, "Dato scambiato",
                                          f"Il dato «{label}» non è più trasportato da nessuno scambio.\n"
                                          "Toglierlo anche dal dizionario dei dati (SA-6)?")
            if answer == QMessageBox.Yes:
                gone.insert(0, model.get(item).copy())  # put back before the exchanges that carry it
                self.project.delete_element(item)
                deleted += 1
            else:
                for fe in exchanges:  # a connector drawn again between the same ends reuses it
                    if fe.get("exchange_item") == item:
                        self._freed[(fe.get("source"), fe.get("target"))] = item
        self.remember(add=gone, state=state)
        self.refresh()
        self.model_edited.emit(f"Eliminati dal modello: {deleted} elementi")
        return True

    def delete_selected(self):
        """Canc: the exchanges selected out of the model (asked); the elements selected, asked whether only out of
        the view or out of the model too (the steps of a chain: out of the view)."""
        arrows = [i for i in self.scene.selectedItems() if isinstance(i, Arrow) and i.exchanges]
        if arrows:
            self.delete_exchanges([u for a in arrows for u in a.exchanges])
        keys = self._selected_keys()
        model = self.project.model
        elements = [k for k in keys if model.get(k) is not None]
        steps = [k for k in keys if model.get(k) is None]
        if steps:
            self.remove(steps)
        if elements:
            self.delete_elements(elements)

    def select_all(self):
        """Ctrl+A: every element of the view selected, with the arrows."""
        for item in self.scene.items():
            if item.flags() & QGraphicsItem.ItemIsSelectable:
                item.setSelected(True)

    def _selected_keys(self):
        """The elements selected: a domain block stands for its functions (selected with it); the function selected
        in a domain of a breakdown."""
        selected = self.scene.selectedItems()
        in_blocks = {id(m) for b in selected if isinstance(b, Block) for m in b.members}
        keys = []
        for item in selected:
            if isinstance(item, Box) and id(item) not in in_blocks:
                keys.append(item.key)
            elif isinstance(item, DomainBlock) and item.domain.uuid:
                keys.append(item.domain.uuid)
            elif isinstance(item, Block):
                keys.append(item.key)
        if self.selected_function and self.selected_function not in keys:
            keys.append(self.selected_function)
        return list(dict.fromkeys(keys))

    def remove_selected(self):
        """The elements selected out of the view only."""
        self.remove_from_view(self._selected_keys())

    def arrange(self):
        """«Riordina»: every element in place again, automatically."""
        self.remember()
        if self.diagram_type == DIAGRAM_DATAFLOW:
            self.placed = dg.auto_layout(dg.dataflow(self.project.model, self.working()), {})
        else:
            self.placed = dg.chain_layout(dg.shown_steps(self.project.model, self.working()), {})
        self._set_dirty(True)
        self.refresh()

    def _level_changed(self, text):
        state = list(self._view_state())
        state[2] = getattr(self, "_level_shown", dg.level(self.view))  # as it was before the change
        self.remember(state=tuple(state))
        self._level_shown = text
        self._set_dirty(True)
        self.refresh()

    def _snap(self, item, rect):
        """(dx, dy) placing a block (or an element) being dragged: aligned to the blocks nearby, shown with guide
        lines, or else on the dots of the grid, shown while it moves; item None: the drag is over, guides and
        dots go. A function in the block of its domain goes on the grid only."""
        for line in self._guides:
            self.scene.removeItem(line)
        self._guides = []
        self.canvas.set_grid(item is not None)
        if item is None:
            return 0, 0
        held = {m for b in self.blocks for m in b.members}
        others = []
        if item not in held:
            others = [b.rect() for b in self.blocks if b is not item]
            others += [b.mapRectToScene(b.rect()) for b in self.items.values()
                       if isinstance(b, Box) and b is not item and b not in held]
        dx, dy, guides = snap_offset(rect, others)
        if not any(g[0] == g[2] for g in guides):  # not aligned on x: on the grid
            dx = round(rect.left() / GRID) * GRID - rect.left()
        if not any(g[1] == g[3] for g in guides):
            dy = round(rect.top() / GRID) * GRID - rect.top()
        pen = QPen(QColor(ACCENT), 1, Qt.DashLine)
        for x1, y1, x2, y2 in guides:
            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(pen)
            line.setZValue(20)
            self.scene.addItem(line)
            self._guides.append(line)
        return dx, dy

    def _anchors_of(self, edge):
        """The anchor points of an arrow: those chosen with the connector of one of its exchanges, when the arrow
        joins the very elements of that exchange (not the block of a domain standing for a function)."""
        for x in edge.exchanges:
            fe = self.project.model.get(x.uuid)
            text = self.anchors.get(x.uuid, "")
            if fe is not None and len(text.split()) == 2 and (fe.get("source"), fe.get("target")) == (
                    edge.source, edge.target):
                return tuple(text.split())
        return None, None

    def _obstacles(self, source, target):
        """What an arrow between two items goes around: the other elements and blocks, not the blocks that hold
        its ends."""
        around = {source, target}
        holders = {b for b in self.blocks if b in around or around & set(b.members)}
        return [i for i in list(self.items.values()) + self.blocks
                if i not in around and i not in holders and isinstance(i, (Box, Block))]

    def _moved(self, key):
        item = self.items.get(key)
        if item is None:
            return
        self.placed[key] = (item.pos().x(), item.pos().y())
        self._moving.add(item)
        for block in self.blocks:
            if item in block.members:
                block.fit()
                self._moving.add(block)
        if not self._routing.isActive():  # a block moves all its functions: the arrows once, after them
            self._routing.start()
        self._set_dirty(True)

    def _refresh_arrows(self, everything=True):
        """The paths of the arrows, then their labels away from the elements and from one another. Not
        everything: while dragging, only the arrows of the elements moved and those near them. The canvas grows
        with them."""
        self.canvas.grow()
        arrows = self.arrows
        if not everything and self._moving:
            moved = self._moving
            rects = [i.mapRectToScene(i.rect()).adjusted(-30, -30, 30, 30) for i in moved]
            arrows = [a for a in self.arrows if set(getattr(a, "between", ())) & moved or
                      any(a.sceneBoundingRect().intersects(r) for r in rects)]
        else:
            self._moving = set()
        for arrow in arrows:
            arrow.refresh()
        if self.diagram_type == DIAGRAM_DATAFLOW:
            taken = [i.mapRectToScene(i.rect()) for i in self.items.values() if isinstance(i, Box)]
            taken += [a._label for a in self.arrows if a not in arrows]
            for arrow in arrows:
                arrow.place_label(taken)
                taken.append(arrow._label)

    def _open(self, key):
        uuid = key
        index = dg.step_index(key) if key else None
        if index is not None:  # a step: its function
            steps = dg.chain_steps(self.project.model, self.view)
            uuid = steps[index].function if index < len(steps) else None
        if uuid and self.project.model.get(uuid) is not None:
            self.open_requested.emit(uuid)


def resolve_unsaved_view(page, parent):
    """Before a view with changes not saved is closed: save or discard them. False if the user cancels."""
    if not page.dirty:
        return True
    box = QMessageBox(QMessageBox.Question, "Modifiche non salvate",
                      f"La vista «{page.view.get('name') or ''}» ha modifiche non salvate.", parent=parent)
    box.setInformativeText("Salvarle o scartarle?")
    save = box.addButton("Salva vista", QMessageBox.AcceptRole)
    discard = box.addButton("Scarta", QMessageBox.DestructiveRole)
    box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(save)
    box.exec()
    if box.clickedButton() is save:
        page.save_view()
        return True
    if box.clickedButton() is discard:
        page.discard_changes()
        return True
    return False


class NewViewDialog(QDialog):
    """«Nuova vista»: its type (among those of the SA), its name and, for a chain or a scenario, the chain."""

    def __init__(self, model, types, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Nuova vista")
        self.type = QComboBox()
        self.type.addItems(types)
        self.name = QLineEdit(placeholderText="es. Comando dei freni")
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(60)
        self.chain = QComboBox()
        for chain in model.of_kind("functional_chain"):
            self.chain.addItem(model.label(chain), chain.uuid)
        self.level = QComboBox()
        self.level.addItems(DIAGRAM_LEVELS)
        self.problem = QLabel(objectName="muted", wordWrap=True)
        self.problem.setStyleSheet(f"color: {BAD};")
        form = QFormLayout()
        self.type_label = QLabel("Tipo")
        form.addRow(self.type_label, self.type)
        if len(types) == 1:  # created from the group of its SA: the type is that one, not asked
            self.type_label.hide()
            self.type.hide()
            self.setWindowTitle(f"Nuova vista: {types[0]}")
        form.addRow("Nome", self.name)
        form.addRow("Descrizione", self.description)
        self.chain_label, self.level_label = QLabel("Functional chain"), QLabel("Passi e linee di vita")
        form.addRow(self.chain_label, self.chain)
        form.addRow(self.level_label, self.level)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crea la vista")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(buttons)
        self.type.currentTextChanged.connect(self._type_changed)
        self._type_changed(self.type.currentText())
        self.resize(QSize(460, 0))

    def _type_changed(self, diagram_type):
        chain = diagram_type in (DIAGRAM_CHAIN, DIAGRAM_SCENARIO)
        for w in (self.chain_label, self.chain, self.level_label, self.level):
            w.setVisible(chain)

    def values(self):
        diagram_type = self.type.currentText()
        values = {"name": self.name.text().strip(), "diagram_type": diagram_type,
                  "description": self.description.toPlainText().strip()}
        if diagram_type in (DIAGRAM_CHAIN, DIAGRAM_SCENARIO):
            values["chain"] = self.chain.currentData()
            values["level"] = self.level.currentText()
        values["layout"] = dg.new_view_layout(self.model, diagram_type, values.get("chain"))
        return values

    def accept(self):
        if not self.name.text().strip():
            self.problem.setText("Dai un nome alla vista.")
            return
        if self.type.currentText() in (DIAGRAM_CHAIN, DIAGRAM_SCENARIO) and self.chain.currentData() is None:
            self.problem.setText("Nel modello non ci sono functional chain: creane una in SA-7.")
            return
        super().accept()
