"""Figures and tables of the SUBSET-026 PDF, extracted as images.

The figures of the specification are vector drawings (rectangles, lines, curves) or groups of small images;
their caption ("Figure 26: …", "Table 5: …") is always below them. The area of a figure is the group of
graphic objects just above its caption, bounded by the previous caption on the same page; it is rendered to
PNG with pypdfium2. The words inside that area (labels of the drawing) are not part of the clause text.
"""
import io
import re
from dataclasses import dataclass, field

CAPTION = re.compile(r"^(Figure|Table)\s+(\d+[a-z]?)\s*:?\s*(.*)$")
# Vertical gap that separates two groups of graphic objects (points).
GROUP_GAP = 28
# Graphics must end close to the caption to belong to it (labels may sit between the drawing and the caption).
MAX_CAPTION_DISTANCE = 90
LINE_HEIGHT = 12
DELETED = "intentionally deleted"
LABEL_MAX_SIZE = 10        # body text is 11 pt; labels and legends of drawings are smaller
TOP_OF_PAGE = 110          # a caption above this line may belong to a drawing at the end of the previous page
PREVIOUS_PAGE_DISTANCE = 150
MARGIN = 6
RENDER_SCALE = 2.0  # 144 dpi


@dataclass
class PageGraphics:
    width: float
    height: float
    boxes: list = field(default_factory=list)  # (x0, top, x1, bottom) of drawings and images


@dataclass
class Figure:
    kind: str           # "Figure" or "Table"
    number: str         # "26", "2a"
    title: str
    page: int
    caption_top: float
    bbox: tuple | None  # (x0, top, x1, bottom), None when nothing is drawn ("Intentionally deleted")


def page_graphics(page, top_limit, bottom_limit):
    boxes = []
    for obj in list(page.rects) + list(page.lines) + list(page.curves) + list(page.images):
        if top_limit <= obj["top"] and obj["bottom"] <= bottom_limit:
            boxes.append((obj["x0"], obj["top"], obj["x1"], obj["bottom"]))
    return PageGraphics(page.width, page.height, boxes)


def caption_of(line):
    """(kind, number, title) if the line is a figure or table caption (bold, «Figure N: …»)."""
    if not line.bold:
        return None
    m = CAPTION.match(line.text.strip())
    return (m.group(1), m.group(2), m.group(3).strip()) if m else None


def _area_above(boxes, caption_top, upper_limit, max_distance=MAX_CAPTION_DISTANCE):
    """Bounding box of the group of graphics that ends right above the caption."""
    candidates = sorted((b for b in boxes if b[3] <= caption_top + 1 and b[1] >= upper_limit),
                        key=lambda b: b[3], reverse=True)
    if not candidates or caption_top - candidates[0][3] > max_distance:
        return None
    group = [candidates[0]]
    top = candidates[0][1]
    for b in candidates[1:]:
        if b[3] >= top - GROUP_GAP:
            group.append(b)
            top = min(top, b[1])
        else:
            break
    return (min(b[0] for b in group), min(b[1] for b in group), max(b[2] for b in group), max(b[3] for b in group))


def _only_small_text(page_lines, top, bottom):
    """True if every text line between top and bottom is in small type (labels or legend of a drawing)."""
    between = [l for l in page_lines if top < l.top < bottom]
    return all(max((w.size for w in l.words), default=0) < LABEL_MAX_SIZE for l in between)


def _distance_limit(boxes, page_lines, caption_top, upper):
    above = [b[3] for b in boxes if b[3] <= caption_top + 1 and b[1] >= upper]
    if above and _only_small_text(page_lines, max(above), caption_top - 2):
        return float("inf")  # only a legend between drawing and caption
    return MAX_CAPTION_DISTANCE


def locate_figures(lines, pages):
    """Find captions and figure areas; returns (figures by caption line id, ids of lines inside figures)."""
    figures, inside = {}, set()
    by_page = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)
    captions_by_page = {p: [l for l in ls if caption_of(l)] for p, ls in by_page.items()}
    for page_no, page_lines in by_page.items():
        graphics = pages.get(page_no)
        upper = 0
        for line in sorted(page_lines, key=lambda l: l.top):
            caption = caption_of(line)
            if not caption:
                continue
            deleted = caption[2].lower().startswith(DELETED)
            bbox, figure_page, figure_lines = None, page_no, page_lines
            if graphics and not deleted:
                limit = _distance_limit(graphics.boxes, page_lines, line.top, upper)
                bbox = _area_above(graphics.boxes, line.top, upper, limit)
            previous = pages.get(page_no - 1)
            if bbox is None and not deleted and previous and line.top < TOP_OF_PAGE and upper == 0:
                # Caption at the top of the page: the drawing ends the previous page.
                prev_lines = by_page.get(page_no - 1, [])
                prev_upper = max((c.top + 8 for c in captions_by_page.get(page_no - 1, [])), default=0)
                bbox = _area_above(previous.boxes, previous.height, prev_upper, PREVIOUS_PAGE_DISTANCE)
                if bbox:
                    figure_page, figure_lines = page_no - 1, prev_lines
            if bbox:
                # Labels written under the drawing, before the caption, belong to the figure.
                end = line.top - 2 if figure_page == page_no else float("inf")
                labels = [o for o in figure_lines if o is not line and bbox[3] < o.top < end
                          and _only_small_text([o], o.top - 1, o.top + 1)]
                if labels:
                    bbox = (min(bbox[0], *(o.x for o in labels)), bbox[1],
                            max(bbox[2], *(o.x1 for o in labels)), max(o.top for o in labels) + LINE_HEIGHT)
                for other in figure_lines:
                    if other is not line and bbox[1] - 2 <= other.top <= bbox[3] and other.x <= bbox[2]:
                        inside.add(id(other))
            figures[id(line)] = Figure(*caption, page=figure_page, caption_top=line.top, bbox=bbox)
            upper = line.top + 8
    return figures, inside


MIN_TABLE_BOXES = 6


@dataclass
class TableImage:
    """A table without caption («3.5.3.16 Table» in chapter 9), possibly spread over several pages."""
    clause: str
    regions: list  # [(page, (x0, top, x1, bottom))]


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def locate_tables(spans, graphics, clause_ids, taken, header, footer):
    """Tables drawn inside the text of the given clauses.

    spans: clause id → (first page, first top, last page, last top) of its text; taken: page → areas already
    used by captioned figures. A page contributes when it has enough graphic objects to be a table.
    """
    tables = []
    for clause in clause_ids:
        if clause not in spans:
            continue
        first_page, first_top, last_page, last_top = spans[clause]
        regions = []
        for page in range(first_page, last_page + 1):
            g = graphics.get(page)
            if g is None:
                continue
            top = first_top if page == first_page else header
            bottom = last_top if page == last_page else g.height - footer
            boxes = [b for b in g.boxes if b[1] >= top - 2 and b[3] <= bottom + 2
                     and not any(_overlaps(b, t) for t in taken.get(page, ()))]
            if len(boxes) >= MIN_TABLE_BOXES:
                regions.append((page, (min(b[0] for b in boxes), min(b[1] for b in boxes),
                                       max(b[2] for b in boxes), max(b[3] for b in boxes))))
        if regions:
            tables.append(TableImage(clause, regions))
    return tables


def lines_inside(lines, regions):
    """Ids of the text lines that fall inside the given (page, bbox) regions."""
    by_page = {}
    for page, bbox in regions:
        by_page.setdefault(page, []).append(bbox)
    return {id(l) for l in lines for b in by_page.get(l.page, ())
            if b[1] - 2 <= l.top <= b[3] and l.x <= b[2] and l.x1 >= b[0]}


def _render_region(pdf, page_no, bbox):
    page = pdf[page_no - 1]
    try:
        width, height = page.get_size()
        x0, top, x1, bottom = bbox
        crop = (max(x0 - MARGIN, 0), max(height - bottom - MARGIN, 0),
                max(width - x1 - MARGIN, 0), max(top - MARGIN, 0))
        return page.render(scale=RENDER_SCALE, crop=crop).to_pil()
    finally:
        page.close()


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_figures(path, figures, tables=()):
    """PNG bytes of every figure with an area and of every table: {id(figure or table): bytes}.

    A table spread over several pages becomes one image, its pieces stacked from top to bottom.
    """
    import pypdfium2 as pdfium
    from PIL import Image

    images = {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        for figure in figures:
            if figure.bbox is not None:
                images[id(figure)] = _png(_render_region(pdf, figure.page, figure.bbox))
        for table in tables:
            pieces = [_render_region(pdf, page, bbox) for page, bbox in table.regions]
            sheet = Image.new("RGB", (max(p.width for p in pieces), sum(p.height for p in pieces)), "white")
            y = 0
            for piece in pieces:
                sheet.paste(piece, (0, y))
                y += piece.height
            images[id(table)] = _png(sheet)
    finally:
        pdf.close()
    return images
