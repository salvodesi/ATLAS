"""Extraction of SRS items from the SUBSET-026 PDF chapters and of the chapter 9 classification.

Layout rules (calibrated on SUBSET-026 v3.6.0):
- clause numbers start at the left margin, the text is indented;
- bold numbers are headings (chapter, section, sub-heading), plain numbers are requirements;
- a 3-level number (3.4.1) is a section, 4+ levels (3.4.1.5) is a requirement clause;
- list items "a)" and bullets inside a clause are separate items, named like chapter 9 ("3.6.5.1.4 a)",
  "3.10.2.2 1st bullet");
- chapters 7 and 8 (language: variables, packets, messages) keep the line structure of their definitions;
- procedure tables of chapter 5 ("ID # | Requirements") give one item per row ("5.4.3.2 S1");
- the active functions table 4.5.2 gives one item per row ("4.5.2-R01"); the modes where the function is
  active are written in the item text;
- chapter 9 is a table: item id + an "x" in the column of its category.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from arcadia_tool.importers.srs_figures import (TableImage, lines_inside, locate_figures, locate_tables,
                                                page_graphics, render_figures)

CATEGORY_COLUMNS = {"onboard": "Bordo", "trackside": "Terra", "definition": "Definizione",
                    "informative": "Informativa", "others": "Altro"}
CATEGORY_ORDER = ["Bordo", "Terra", "Definizione", "Informativa", "Altro"]

HEADER_MARGIN = 55
FOOTER_MARGIN = 65
LEFT_MARGIN_TOLERANCE = 12
LINE_TOLERANCE = 2.5
PARAGRAPH_GAP = 17
SKIPPED_SECTIONS = ("modification history", "table of contents")
TABLE_HEADER_WORDS = {"Clause", "number", "Clause number"}
REPLACED_HEADER = {"Replaced", "clause", "number", "Replacing", "Clause", "classification"}
LANGUAGE_CHAPTERS = (7, 8)

# Clause numbers: 3.14.4.2, and in the appendix of a chapter A.3.4.1 («APPENDIX TO CHAPTER 3»).
APPENDIX = "A."
NUMBER = re.compile(r"^((?:A\.)?\d+(?:\.\d+)+)$")
ITEM_ID = re.compile(r"^(?:A\.)?\d+(?:\.\d+)*\b")
def appendix_chapter(line):
    """Chapter of an «APPENDIX TO CHAPTER n» heading, or None.

    The heading is in small capitals: the PDF text may come out as «A C 3 PPENDIX TO HAPTER».
    """
    if not line.bold:
        return None
    text = line.text.upper()
    if "PPENDIX" not in text or "HAPTER" not in text:
        return None
    numbers = re.findall(r"\d+", text)
    return int(numbers[0]) if len(numbers) == 1 else None
# «b) The mode changes.»: a space and some text must follow, so that «b)).» (the end of a wrapped reference
# such as «see 3.17.3.11 b))») is not taken for a list item.
LETTER_ITEM = re.compile(r"^([a-z]{1,2})\)\s+([^\s).,;].*)$")  # text may start with quotes: a) “valid” …
BULLETS = ("•", "", "▪", "•", "–")
PROCEDURE_ROW = re.compile(r"^([SDAE]\d{1,3})\b\.?\s*(.*)$")
# Suffixes that identify a sub-item of a clause in chapter 9; any other text after the number is a name
# (e.g. "7.5.1.72 M_MODE", "8.6.3 Message 132: ...") and is dropped from the identifier.
SUB_ITEM_SUFFIX = re.compile(r"^(?:[a-z]{1,2}\)|\d+(?:st|nd|rd|th)\s+bul|Table|Figure|[SDAE]\d{1,3}\b|step\b)",
                             re.IGNORECASE)
DICTIONARY_NAME = re.compile(r"^(?:Packet Number|Message)\b|^[A-Z][A-Z0-9]*_[A-Z0-9_()]+$")

ACTIVE_FUNCTIONS_TABLE = "4.5.2.1"
ACTIVE_FUNCTIONS_HEADER = "ONBOARD-FUNCTIONS"
FUNCTION_NAME_MAX_X = 200
MODE_COLUMNS_MIN_X = 260
REFS_MIN_X = 200
SUPERSCRIPT_MAX_SIZE = 7


@dataclass
class Word:
    x: float
    text: str
    size: float
    bold: bool
    font: str = ""


# Fonts of the equations (written with an equation editor): their text is not meaningful once extracted
# (Symbol glyphs in the private Unicode area, sub/superscripts on separate lines) → shown as image.
MATH_FONTS = ("symbol", "times new roman", "timesnewroman", "mt extra", "cambria math", "euclid", "mathtype")
MATH_SHARE = 0.6
FORMULA_GAP = 22  # vertical gap (points) that separates two formula blocks
FORMULA_SHORT_LINE = 4  # words: «if», «or», «for» between the lines of an equation belong to it

# The Symbol font puts its glyphs in the private Unicode area (U+F020–U+F0FF): map them to real characters.
_SYMBOL_GREEK = dict(zip("abgdezhqiklmnxoprstufcywjvJ", "αβγδεζηθικλμνξοπρστυφχψωϕϖϑ"))
_SYMBOL_GREEK.update(zip("ABGDEZHQIKLMNXOPRSTUFCYW", "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"))
_SYMBOL_SPECIAL = {0x2D: "−", 0x2A: "∗", 0xA3: "≤", 0xB3: "≥", 0xB1: "±", 0xB4: "×", 0xB7: "•", 0xB8: "÷",
                   0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xA5: "∞", 0xAE: "→", 0xAC: "←", 0xDE: "⇒", 0xDC: "⇐",
                   0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xE5: "∑", 0xF2: "∫", 0xA7: "▪",
                   0xB0: "°", 0xA2: "′", 0xB2: "″", 0xC6: "∅", 0xCE: "∈", 0xCF: "∉", 0xC7: "∩", 0xC8: "∪"}


def symbol_text(text):
    """Text with the private-area glyphs of the Symbol font replaced by the characters they show."""
    if not any("" <= c <= "" for c in text):
        return text
    out = []
    for c in text:
        if "" <= c <= "":
            code = ord(c) - 0xF000
            out.append(_SYMBOL_SPECIAL.get(code) or _SYMBOL_GREEK.get(chr(code)) or
                       (chr(code) if code < 0x7F else ""))
        else:
            out.append(c)
    return "".join(out)


@dataclass
class Line:
    page: int
    x: float
    top: float
    text: str
    bold: bool
    words: list = field(default_factory=list)
    x1: float = 0
    bottom: float = 0

    @property
    def math(self):
        """True for a line of an equation (mostly in the fonts of an equation editor)."""
        if not self.words:
            return False
        math = sum(len(w.text) for w in self.words if w.font.lower().startswith(MATH_FONTS))
        return math >= MATH_SHARE * sum(len(w.text) for w in self.words)


@dataclass
class SrsItem:
    id: str
    item_type: str
    title: str = ""
    text: str = ""
    page: int = 0
    warnings: list = field(default_factory=list)
    parent: str | None = None
    extra: dict = field(default_factory=dict)
    # «text» also contains the list items (a), b), bullets), which are items of their own: own_text is the text
    # up to the first list item, pieces the text added after it as (list item id or None, piece). The import
    # keeps a list item in the clause text only when it is not an item (see without_sub_items).
    own_text: str | None = None
    pieces: list = field(default_factory=list)
    sequence: int = 0  # position in the document (procedure rows S0, D2, A23… are not in alphabetical order)

    def without_sub_items(self, kept=()):
        """The clause text without its list items, except those in kept (ids as parsed)."""
        if self.own_text is None:
            return self.text
        text = self.own_text + "".join(p for owner, p in self.pieces if owner is None or owner in kept)
        return text.strip()

    @property
    def parent_id(self):
        if self.parent:
            return self.parent
        if " " in self.id:
            return self.id.split(" ", 1)[0]
        return self.id.rsplit(".", 1)[0] if "." in self.id else None


@dataclass
class Classification:
    categories: list
    replaces: str | None = None


def chapter_of(path):
    m = re.search(r"SUBSET-026-(\d+)", Path(path).name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def chapter_of_item(ident):
    """Chapter of an item id: «3.14.4.2» → 3, «A.3.4.1» (appendix to chapter 3) → 3, «4.5.2-R01» → 4."""
    m = re.match(r"(?:A\.)?(\d+)", ident or "")
    return int(m.group(1)) if m else None


def _numeric(number):
    """Levels of a clause number without the appendix prefix: «A.3.4.1» → [3, 4, 1]."""
    return [int(p) for p in number.removeprefix(APPENDIX).split(".")]


def normalize_id(ident):
    """«7.5.1.72 M_MODE» → «7.5.1.72»; sub-items such as «3.6.5.1.4 a)» or «5.4.3.2 S1» are kept; a dot typed
    twice in chapter 9 («7..4.2.20.1») is one."""
    ident = " ".join(ident.split())
    number, _, rest = ident.partition(" ")
    while ".." in number:
        number = number.replace("..", ".")
    ident = f"{number} {rest}".strip()
    if not rest or SUB_ITEM_SUFFIX.match(rest):
        return ident
    return number


def _ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# --- reading ------------------------------------------------------------------------------------

SMALL_CAPS_TOLERANCE = 6


def _join_small_capitals(lines):
    """Join the two halves of a heading in small capitals («A» «PPENDIX» «TO» «C» «HAPTER» «3»).

    Capital and small letters have different sizes, so their tops differ a little more than the usual line
    tolerance; they are bold and their words interleave horizontally.
    """
    joined = []
    for ws in lines:
        if joined:
            prev = joined[-1]
            bold = all("bold" in w["fontname"].lower() for w in prev + ws)
            sizes = {round(w["size"]) for w in prev} != {round(w["size"]) for w in ws}
            close = abs(ws[0]["top"] - prev[0]["top"]) <= SMALL_CAPS_TOLERANCE
            interleaved = min(w["x0"] for w in ws) < max(w["x0"] for w in prev) and \
                min(w["x0"] for w in prev) < max(w["x0"] for w in ws)
            if bold and sizes and close and interleaved:
                joined[-1] = prev + ws
                continue
        joined.append(ws)
    return joined


def _page_lines(page):
    words = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
    for w in words:
        w["text"] = symbol_text(w["text"])
    words = [w for w in words if w["text"]]
    words = [w for w in words if HEADER_MARGIN <= w["top"] <= page.height - FOOTER_MARGIN]
    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines, current = [], []
    for w in words:
        if current and abs(w["top"] - current[0]["top"]) > LINE_TOLERANCE:
            lines.append(current)
            current = []
        current.append(w)
    if current:
        lines.append(current)
    lines = _join_small_capitals(lines)
    out = []
    for ws in lines:
        ws.sort(key=lambda w: w["x0"])
        out.append(Line(page.page_number, ws[0]["x0"], ws[0]["top"], " ".join(w["text"] for w in ws),
                        "bold" in ws[0]["fontname"].lower(),
                        [Word(w["x0"], w["text"], w["size"], "bold" in w["fontname"].lower(),
                              w["fontname"].split("+", 1)[-1]) for w in ws],
                        max(w["x1"] for w in ws), max(w["bottom"] for w in ws)))
    return out


def read_document(path, progress=None):
    """Body lines of a PDF (without headers, footers and table-of-contents pages) and its graphics per page."""
    lines, graphics = [], {}
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for page in pdf.pages:
            page_lines = _page_lines(page)
            if sum("....." in l.text for l in page_lines) <= 5:
                lines.extend(page_lines)
                graphics[page.page_number] = page_graphics(page, HEADER_MARGIN, page.height - FOOTER_MARGIN)
            page.close()
            if progress:
                progress(page.page_number, total)
    return lines, graphics


def read_lines(path, progress=None):
    return read_document(path, progress)[0]


# --- chapters -----------------------------------------------------------------------------------

def _plausible_successor(previous, number):
    if previous is None or previous.startswith(APPENDIX) != number.startswith(APPENDIX):
        return True  # the appendix restarts the numbering
    a, b = _numeric(previous), _numeric(number)
    if len(b) <= 2:
        return True  # chapter headings: the skipped table of contents leaves a gap (x.1 → x.3)
    first = lambda parts: all(p in (0, 1) for p in parts)  # numbering may start at 0 (7.4.2.0, 7.5.0.1)
    if len(b) > len(a) and b[:len(a)] == a and first(b[len(a):]):
        return True  # descends, possibly skipping a level (3.4.2 → 3.4.2.1.1)
    # next sibling at some level, possibly followed by the first sub-levels (7.5.0.5 → 7.5.1.1)
    return any(b[:i] == a[:i] and len(b) > i and b[i] == a[i] + 1 and first(b[i + 1:]) for i in range(len(a)))


def _item_type(number, bold):
    # Count the levels without converting them: chapter 9 has ids such as «3.13.9.3.1a)».
    depth = number.removeprefix(APPENDIX).count(".") + 1
    if number.startswith(APPENDIX):
        # The appendix of a chapter (A.3) has one level less: its sections are A.3.7, a 3-level number is a
        # requirement unless it is a heading inside its section (A.3.3.1 vs A.3.4.1 «Introduction»).
        if depth <= 1:
            return "Capitolo"
        if depth == 2:
            return "Sezione"
        return "Titolo" if bold else "Requisito"
    if depth <= 2:
        return "Capitolo"
    if depth == 3:
        return "Sezione"
    return "Titolo" if bold else "Requisito"


IMPLICIT_SECTION_NOTE = "Sezione senza intestazione nel SRS (le clausole seguono il capitolo): aggiunta da ATLAS"


def _section_of_number(number):
    """The section a clause number belongs to: 3.20.1.2 → 3.20.1, A.3.7.1 → A.3.7; None for a section or a
    chapter, or a number that is not plain (7..4)."""
    appendix = number.startswith(APPENDIX)
    parts = number.removeprefix(APPENDIX).split(".")
    if any(not p for p in parts):
        return None
    levels = 2 if appendix else 3
    if len(parts) <= levels:
        return None
    return (APPENDIX if appendix else "") + ".".join(parts[:levels])


def add_implicit_sections(items):
    """Sections without a heading in the SRS: the clauses of some chapters follow the chapter heading directly
    (3.20 Juridical Data → 3.20.1.1, 6.3 Scope → 6.3.1.1, the variables 7.5 → 7.5.0.1, 7.5.1.1). Their section
    (3.20.1) is added right before its first clause, with the title of the chapter, so that the clauses have a
    section like the others (the domains of the matrix A4 are allocated by section)."""
    present = {i.id for i in items}
    chapters = {i.id: i for i in items if i.item_type == "Capitolo"}
    result = []
    for item in items:
        section = _section_of_number(item.id) if " " not in item.id and item.item_type in ("Requisito", "Titolo") \
            else None
        chapter = chapters.get(section.rsplit(".", 1)[0]) if section else None
        if chapter is not None and section not in present:  # the clauses follow the chapter heading
            result.append(SrsItem(section, "Sezione", title=chapter.title, page=item.page,
                                  extra={"import_note": IMPLICIT_SECTION_NOTE}))
            present.add(section)
        result.append(item)
    return result


def _append(item, text, line, previous_top, structured):
    """Add a line to an item's text: new line for structured content or a new paragraph."""
    item.text = _joined(item.text, text, line, previous_top, structured)


def _grow(clause, sub, text):
    """Set a clause text, remembering, once it has list items, which one each added piece belongs to."""
    if clause.own_text is not None:
        clause.pieces.append((sub.id if sub is not None else None, text[len(clause.text):]))
    clause.text = text


def _joined(before, text, line, previous_top, structured):
    if not before:
        return text
    if structured or _new_paragraph(line, previous_top):
        return f"{before}\n{text}"
    return _same_paragraph(before, text)


def _same_paragraph(before, text):
    """A wrapped line: «on-» + «board» is «on-board», not «on- board»."""
    if not before:
        return text
    return f"{before}{text}" if re.search(r"[A-Za-z]-$", before) else f"{before} {text}"


def _new_paragraph(line, previous_top):
    gap = line.top - previous_top if previous_top is not None else 0
    return gap > PARAGRAPH_GAP  # a negative gap is a page break, not a paragraph


def parse_chapter(path, progress=None, table_clauses=()):
    """SRS items of one SUBSET-026 chapter, in document order; figures and tables carry their image.

    table_clauses: clauses that chapter 9 lists with a table without caption («4.6.2 Table»): the table drawn
    in their text becomes an item with its image.
    """
    chapter = chapter_of(path)
    lines, graphics = read_document(path, progress)
    figures, inside = locate_figures(lines, graphics)
    tables = []
    if table_clauses:
        spans = {}
        parse_lines(lines, chapter, figures, inside, spans=spans)
        taken = {}
        for f in figures.values():
            if f.bbox:
                taken.setdefault(f.page, []).append(f.bbox)
        tables = locate_tables(spans, graphics, table_clauses, taken, HEADER_MARGIN, FOOTER_MARGIN)
        inside = set(inside) | lines_inside(lines, [r for t in tables for r in t.regions])
    items = parse_lines(lines, chapter, figures, inside)
    with_figure = [i.extra["_figure"] for i in items if i.extra.get("_figure") is not None]
    # Equations of a clause: one image with its blocks one under the other.
    formulas = {}
    for item in items:
        blocks = item.extra.pop("_formulas", None)
        if blocks:
            formulas[item.id] = TableImage(item.id, [(b["page"], (b["x0"], b["top"], b["x1"], b["bottom"]))
                                                    for b in blocks])
    images = render_figures(path, with_figure, tables + list(formulas.values()))
    for item in items:
        figure = item.extra.pop("_figure", None)
        if figure is not None and id(figure) in images:
            item.extra["figure_png"] = images[id(figure)]
        elif item.id in formulas:
            item.extra["figure_png"] = images[id(formulas[item.id])]
    for table in tables:
        item = SrsItem(f"{table.clause} Table", "Voce", title="Tabella", page=table.regions[0][0],
                       parent=table.clause, extra={"figure_png": images[id(table)]})
        position = next((n for n, i in enumerate(items) if i.id == table.clause), len(items) - 1)
        items.insert(position + 1, item)  # right after its clause, like in the document
    _number(items, chapter)
    return items


SEQUENCE_PER_CHAPTER = 100_000


def _number(items, chapter):
    """Position in the document, used to keep the specification order (e.g. procedure rows S0, S1, D2…)."""
    for n, item in enumerate(items, 1):
        item.sequence = (chapter or 0) * SEQUENCE_PER_CHAPTER + n


def parse_lines(lines, chapter=None, figures=None, inside=(), spans=None):
    """figures: caption line id → Figure; inside: ids of lines drawn inside a figure (labels, table cells);
    spans (filled if given): clause id → (first page, first top, last page, last top) of the clause text."""
    figures = figures or {}
    open_span = None
    if chapter is None:
        firsts = [l.text.split(" ", 1)[0] for l in lines if NUMBER.match(l.text.split(" ", 1)[0])]
        chapter = (chapter_of_item(firsts[0]) or 0) if firsts else 0
    margin = min((l.x for l in lines if NUMBER.match(l.text.split(" ", 1)[0])), default=0)
    prefixes = (f"{chapter}.", f"{APPENDIX}{chapter}.")
    language = chapter in LANGUAGE_CHAPTERS

    items, current, sub, sub_x = [], None, None, 0
    previous_number, previous_top, skipping, bullet_count = None, None, False, 0
    procedure, functions = None, None
    for line in lines:
        head, _, rest = line.text.partition(" ")
        is_clause = (abs(line.x - margin) <= LEFT_MARGIN_TOLERANCE and NUMBER.match(head)
                     and head.startswith(prefixes))
        if is_clause and skipping and not (len(_numeric(head)) == 2 and line.bold):
            continue  # numbers inside the modification history table are not clauses

        if functions is None and appendix_chapter(line) == chapter:
            # «APPENDIX TO CHAPTER 3»: root of the A.3.x items, which follow the same layout as the clauses.
            if spans is not None and open_span:
                spans[open_span[0]] = (*open_span[1:], line.page, line.top)
                open_span = None
            procedure, sub, skipping = None, None, False
            current = SrsItem(f"{APPENDIX}{chapter}", "Capitolo", title=f"Appendix to Chapter {chapter}",
                              page=line.page)
            items.append(current)
            previous_number = None
            continue

        if functions is not None:
            if is_clause or line.text.startswith("Figure"):
                items.extend(functions.finish())
                functions = None
                if not is_clause:
                    continue  # its caption: the table is already split into rows, no image needed
            else:
                functions.add(line)
                continue

        if is_clause:
            if spans is not None:
                if open_span:
                    spans[open_span[0]] = (*open_span[1:], line.page, line.top)
                open_span = (head, line.page, line.top)
            procedure = None
            item_type = _item_type(head, line.bold)
            current = SrsItem(head, item_type, page=line.page)
            if item_type in ("Capitolo", "Sezione", "Titolo") or (language and DICTIONARY_NAME.match(rest.strip())):
                current.title = rest.strip()
            else:
                current.text = rest.strip()
            if not _plausible_successor(previous_number, head):
                current.warnings.append(f"Numerazione non in sequenza dopo {previous_number}")
            previous_number, previous_top = head, line.top
            skipping = item_type == "Capitolo" and rest.strip().lower() in SKIPPED_SECTIONS
            items.append(current)
            sub, bullet_count = None, 0
            continue
        if current is None or skipping:
            continue
        text = line.text.strip()

        figure = figures.get(id(line))
        if figure is not None:
            base = current.id.split(" ", 1)[0]
            label = f"{figure.kind} {figure.number}"
            items.append(SrsItem(f"{base} {label}", "Voce", title=f"{label}: {figure.title}".rstrip(": "),
                                 text="" if figure.bbox else figure.title, page=line.page, parent=base,
                                 extra={"_figure": figure if figure.bbox else None}))
            continue

        if current.id == ACTIVE_FUNCTIONS_TABLE and text.startswith(ACTIVE_FUNCTIONS_HEADER):
            functions = ActiveFunctionsTable(current.id, line)
            continue
        if text.startswith("ID #"):
            procedure, sub = current, None  # header of a procedure table, repeated on every page
            continue
        if procedure is not None:
            row = PROCEDURE_ROW.match(text) if line.x <= margin + LEFT_MARGIN_TOLERANCE else None
            if row:
                sub = SrsItem(f"{procedure.id} {row.group(1)}", "Voce", text=row.group(2), page=line.page)
                items.append(sub)
            elif sub is not None:
                _append(sub, text, line, previous_top, structured=False)
            previous_top = line.top
            continue
        if id(line) in inside:
            # A label or a cell of a figure or table: it is part of the image, not of the clause text.
            # (Checked after the tables read row by row: 4.5.2 and procedures keep their text.)
            continue
        target = sub if sub is not None else current
        blocks = target.extra.get("_formulas") or []
        last = blocks[-1] if blocks else None
        next_to_formula = (last is not None and last["page"] == line.page
                           and line.top - last["bottom"] <= FORMULA_GAP)
        if line.math or (next_to_formula and len(line.words) <= FORMULA_SHORT_LINE):
            # An equation: its extracted text is meaningless, it becomes an image («[Formula 1]» in the text).
            blocks = target.extra.setdefault("_formulas", [])
            if next_to_formula:
                last.update(x0=min(last["x0"], line.x), x1=max(last["x1"], line.x1),
                            bottom=max(last["bottom"], line.bottom))
            else:
                blocks.append({"page": line.page, "x0": line.x, "top": line.top, "x1": line.x1,
                               "bottom": line.bottom})
                marker = f"[Formula {len(blocks)}]"
                _grow(current, sub, _joined(current.text, marker, line, previous_top, structured=True))
                if sub is not None:
                    _append(sub, marker, line, previous_top, structured=True)
            previous_top = line.top
            continue

        letter = LETTER_ITEM.match(text)
        bullet = text[:1] in BULLETS and not language
        if current.item_type == "Requisito" and (letter or bullet):
            if letter:
                sub_id, body = f"{current.id} {letter.group(1)})", letter.group(2)
            else:
                bullet_count += 1
                sub_id, body = f"{current.id} {_ordinal(bullet_count)} bullet", text[1:].strip()
            sub = SrsItem(sub_id, "Voce", text=body, page=line.page)
            # Continuation lines of a list item are aligned with its text, not with its letter or bullet.
            sub_x = line.words[1].x if len(line.words) > 1 else line.x
            items.append(sub)
            if current.own_text is None:
                current.own_text = current.text
            _grow(current, sub, f"{current.text}\n{text}".strip())
            previous_top = line.top
            continue
        if current.item_type in ("Capitolo", "Sezione", "Titolo") and line.bold and not current.text and not language:
            current.title = f"{current.title} {text}".strip()
            continue
        if sub is not None and _new_paragraph(line, previous_top) and line.x < sub_x - LEFT_MARGIN_TOLERANCE:
            sub = None  # a paragraph after the list: it belongs to the clause only
        _grow(current, sub, _joined(current.text, text, line, previous_top, structured=language))
        if sub is not None:
            sub.text = _same_paragraph(sub.text, text)
        previous_top = line.top
    if functions is not None:
        items.extend(functions.finish())
    if spans is not None and open_span and lines:
        spans[open_span[0]] = (*open_span[1:], lines[-1].page, float("inf"))
    items = add_implicit_sections(items)
    _number(items, chapter)
    return items


class ActiveFunctionsTable:
    """Table 4.5.2 (functions active per mode): one item per row, 4.5.2-R01, R02, …"""

    def __init__(self, table_id, header_line):
        self.table_id = table_id
        self.columns = {}
        self.rows = []
        self.group, self.group_open = "", False
        self._header_top = None
        self._header(header_line)

    def _header(self, line):
        """Mode names are written vertically on two header lines (N/P = NP, S/B = SB, …)."""
        self._top_letters = [(w.x, w.text) for w in line.words if w.x >= MODE_COLUMNS_MIN_X]
        self._header_top = line.top

    def _complete_header(self, line):
        bottom = [(w.x, w.text) for w in line.words if w.x >= MODE_COLUMNS_MIN_X]
        self.columns = {}
        for x, top in self._top_letters:
            match = min(bottom, key=lambda b: abs(b[0] - x), default=None)
            if match and abs(match[0] - x) < 6:
                self.columns[x] = f"{top}{match[1]}".strip()
        self._header_top = None

    def _mode(self, x):
        nearest = min(self.columns, key=lambda c: abs(c - x), default=None)
        return self.columns[nearest] if nearest is not None and abs(nearest - x) < 8 else None

    def add(self, line):
        text = line.text.strip()
        if text.startswith(ACTIVE_FUNCTIONS_HEADER):
            self._header(line)
            return
        if self._header_top is not None:
            self._complete_header(line)
            return
        name = " ".join(w.text for w in line.words if w.x < FUNCTION_NAME_MAX_X and w.size > SUPERSCRIPT_MAX_SIZE)
        refs = " ".join(w.text for w in line.words if REFS_MIN_X <= w.x < MODE_COLUMNS_MIN_X)
        marks = {}
        for w in line.words:
            if w.x >= MODE_COLUMNS_MIN_X and w.text in ("X", "O") and w.size > SUPERSCRIPT_MAX_SIZE:
                mode = self._mode(w.x)
                if mode:
                    marks[mode] = w.text
        if line.x >= FUNCTION_NAME_MAX_X and not name:
            if self.rows and refs:
                self.rows[-1]["refs"].append(refs)
            if self.rows:
                self.rows[-1]["modes"].update(marks)
            return
        if line.x > 60 and not marks:
            return  # footnotes and captions start at the text margin, not in the name column
        if line.bold and name:
            self.group = f"{self.group} {name}".strip() if self.group_open else name
            self.group_open = True
            return
        self.group_open = False
        if marks or not self.rows:
            self.rows.append({"name": name, "refs": [refs] if refs else [], "modes": marks, "group": self.group,
                              "page": line.page})
        else:
            row = self.rows[-1]
            row["name"] = f"{row['name']} {name}".strip()
            if refs:
                row["refs"].append(refs)
            row["modes"].update(marks)

    def finish(self):
        items = []
        for n, row in enumerate(self.rows, 1):
            name = row["name"].rstrip(":").strip()
            active = [m for m, v in row["modes"].items() if v == "X"]
            optional = [m for m, v in row["modes"].items() if v == "O"]
            refs = []
            for r in (r.strip() for chunk in row["refs"] for r in chunk.split(",")):
                if r and refs and not re.match(r"\d|None|Chapter", r):
                    refs[-1] = f"{refs[-1]} {r}"  # a reference wrapped onto the next line («3.8.2.3 a)» «and b)»)
                elif r:
                    refs.append(r)
            lines = [f"Gruppo: {row['group'].rstrip(':')}" if row["group"] else "",
                     f"Riferimenti SRS: {', '.join(refs) or '—'}",
                     f"Attiva in: {', '.join(active) or '—'}"]
            if optional:
                lines.append(f"Opzionale in: {', '.join(optional)}")
            items.append(SrsItem(f"4.5.2-R{n:02d}", "Voce", title=name, text="\n".join(l for l in lines if l),
                                 page=row["page"], parent=f"{self.table_id} Table",
                                 extra={"srs_refs": refs}))
        return items


# --- chapter 9 ----------------------------------------------------------------------------------

def table_clauses(classification, chapter=None):
    """Clauses that chapter 9 lists with a table without caption («4.6.2 Table»)."""
    clauses = set()
    for ident in classification or ():
        number, _, rest = ident.partition(" ")
        if rest == "Table" and (chapter is None or chapter_of_item(number) == chapter):
            clauses.add(number)
    return clauses


def parse_classification(path, progress=None):
    """Chapter 9: item id → categories (and, for chapter 6, the nominal clause it replaces)."""
    result = {}
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        for page in pdf.pages:
            words = [w for w in page.extract_words(keep_blank_chars=False)
                     if HEADER_MARGIN <= w["top"] <= page.height - FOOTER_MARGIN]
            classify_page(words, result)
            page.close()
            if progress:
                progress(page.page_number, total)
    return result


def classify_page(words, result):
    columns, replaced_x = [], None
    for i, w in enumerate(words):
        t = w["text"]
        if t == "on-" and i and words[i - 1]["text"] == "ETCS":
            columns.append(("onboard", words[i - 1]["x0"]))
        elif t == "trackside":
            columns.append(("trackside", w["x0"]))
        elif t in ("Definition", "Informative", "Others"):
            columns.append((t.lower(), w["x0"]))
        elif t == "Replaced":
            replaced_x = w["x0"]
    if len(columns) < 5:
        return
    columns.sort(key=lambda c: c[1])
    first_group = columns[:5]
    id_limit = first_group[0][1] - 5
    # Chapter 6 tables: "Replaced clause number" sits between the two groups of classification columns.
    replaced_end = columns[5][1] - 5 if len(columns) > 5 else float("inf")

    lines = {}
    for w in words:
        key = round(w["top"])
        line = next((lines[k] for k in (key - 1, key, key + 1) if k in lines), None)
        if line is None:
            line = lines[key] = {"id": [], "marks": [], "replaced": []}
        if w["x0"] < id_limit:
            line["id"].append(w["text"])
        elif w["text"] == "x":
            column = None
            for name, x in columns:
                if w["x0"] + 3 >= x:
                    column = (name, x)
            if column and column in first_group:
                line["marks"].append(CATEGORY_COLUMNS[column[0]])
        elif replaced_x is not None and replaced_x - 10 <= w["x0"] < replaced_end and w["text"] not in REPLACED_HEADER:
            line["replaced"].append(w["text"])

    # A cell of the id column may span several lines; its marks can be on any of them (often the last).
    pending = None

    def flush():
        if pending and pending["marks"]:
            marks = sorted(set(pending["marks"]), key=CATEGORY_ORDER.index)
            result[normalize_id(" ".join(pending["id"]))] = Classification(
                marks, " ".join(pending["replaced"]) or None)

    for top in sorted(lines):
        line = lines[top]
        ident = " ".join(line["id"]).strip()
        if ident in TABLE_HEADER_WORDS:
            flush()
            pending = None
            continue
        if ident and ITEM_ID.match(ident):
            flush()
            pending = {"id": [ident], "marks": [], "replaced": []}
        elif ident and pending is not None:
            pending["id"].append(ident)
        if pending is not None:
            pending["marks"].extend(line["marks"])
            pending["replaced"].extend(line["replaced"])
    flush()
