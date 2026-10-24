"""WYSIWYG editor of the free texts of the sheets: bold, italic, underline, strikethrough, code, bulleted and numbered
lists (nested with the indentation), links.

The text is stored as Markdown (GitHub dialect): the model files and the diffs between versions stay readable.
What is written stays as it is until it is changed (a text saved by earlier versions is not rewritten).
"""
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor, QTextDocument, QTextListFormat
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QTextEdit, QToolButton, QVBoxLayout, QWidget

from arcadia_tool.ui.theme import BORDER, SURFACE, TEXT, icon

DIALECT = QTextDocument.MarkdownDialectGitHub
LINK_COLOR = "#1A5FB4"
MAX_HEIGHT = 520  # a text box grows with its text up to this height, then it scrolls
LINE_START = re.compile(r"^(\s*)([#>+\-]|\d+[.)])(\s)", re.M)  # what would start a heading, quote or list


def _escape_line_start(match):
    mark = match.group(2)
    escaped = f"{mark[:-1]}\\{mark[-1]}" if mark[0].isdigit() else f"\\{mark}"  # «1\.», «\-»
    return f"{match.group(1)}{escaped}{match.group(3)}"


def _escape(text):
    """Characters that Markdown would read as styles; an underscore inside a word (M_MODE) is kept as it is."""
    text = re.sub(r"([\\`*\[\]~])", r"\\\1", text)
    return re.sub(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", r"\\_", text)


def _style(fmt):
    return (fmt.fontWeight() >= QFont.Bold, fmt.fontItalic(), fmt.fontStrikeOut(), fmt.fontFixedPitch(),
            fmt.anchorHref() if fmt.isAnchor() else "", fmt.fontUnderline() and not fmt.isAnchor())


LIST_ITEM = re.compile(r"^\s*([-+*]|\d+[.)])\s")


def prepare(markdown):
    """Markdown to show: a line break of a text written as plain text (earlier versions) stays a line break,
    instead of joining the two lines as Markdown would."""
    lines = (markdown or "").split("\n")
    for i in range(len(lines) - 1):
        line, following = lines[i], lines[i + 1]
        if line.strip() and following.strip() and not line.endswith("  ") and not LIST_ITEM.match(following):
            lines[i] = line + "  "
    return "\n".join(lines)


def _inline(block):
    """The text of a paragraph with its styles, as Markdown."""
    runs = []  # (style, text): fragments with the same style joined (no «**a****b**»)
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid():
            style = _style(fragment.charFormat())
            if runs and runs[-1][0] == style:
                runs[-1] = (style, runs[-1][1] + fragment.text())
            else:
                runs.append((style, fragment.text()))
        it += 1
    parts = []
    for (bold, italic, strike, code, href, underline), text in runs:
        text = text.replace(" ", "\n")  # line break inside a paragraph
        core = text.strip()
        if not core:
            parts.append(text)
            continue
        lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]  # spaces out of the marks
        body = f"`{core}`" if code else _escape(core)
        if underline:  # «_text_»: read back by ATLAS as underlined (elsewhere it shows as emphasis)
            body = f"_{body}_"
        if italic:
            body = f"*{body}*"
        if bold:
            body = f"**{body}**"
        if strike:
            body = f"~~{body}~~"
        if href:
            body = f"[{body}]({href})"
        parts.append(lead + body + trail)
    text = "".join(parts)
    text = "  \n".join(text.split("\n"))  # hard line breaks
    return LINE_START.sub(_escape_line_start, text)


def to_markdown(document):
    """Markdown of the document, written here: the writer of Qt 6.12 loses bold and italic, and it wraps the lines
    (noisy diffs between versions). Paragraphs, bulleted and numbered lists (also nested), and inline styles."""
    lines, previous = [], None  # previous: «list» or «paragraph», for the blank lines between blocks
    previous_top = None  # the list of the previous item at the first level: another list starts after a blank line
    block = document.begin()
    while block.isValid():
        text_list = block.textList()
        content = _inline(block)
        if text_list is not None:
            fmt = text_list.format()
            depth = max(fmt.indent(), 1) - 1
            ordered = fmt.style() in (QTextListFormat.ListDecimal, QTextListFormat.ListLowerAlpha,
                                      QTextListFormat.ListUpperAlpha, QTextListFormat.ListLowerRoman,
                                      QTextListFormat.ListUpperRoman)
            marker = f"{text_list.itemNumber(block) + 1}. " if ordered else "- "
            if previous == "paragraph" or (depth == 0 and previous_top is not None and previous_top != text_list):
                lines.append("")
            if depth == 0:
                previous_top = text_list
            lines.append("   " * depth + marker + content)
            previous = "list"
        else:
            if previous is not None and (content or previous == "list"):
                lines.append("")
            if content:
                lines.append(content)
                previous = "paragraph"
            previous_top = None
        block = block.next()
    return "\n".join(lines).strip()


class RichTextEdit(QWidget):
    """A text box with a toolbar of styles. markdown() gives its content; changed when it is edited."""
    changed = Signal()

    def __init__(self, markdown="", parent=None, height=96):
        super().__init__(parent)
        self._original = markdown or ""
        self.base_height = height  # the box is at least this high, and grows with its text (up to MAX_HEIGHT)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)  # pasted text keeps what Markdown can say (bold, lists…)
        self.editor.setTabChangesFocus(True)
        self.editor.setFixedHeight(height)
        self.editor.document().documentLayout().documentSizeChanged.connect(self._fit_height)
        self._load(self._original)
        self.editor.textChanged.connect(self.changed)
        self.editor.cursorPositionChanged.connect(self._update_buttons)

        self.toolbar = QWidget(objectName="richToolbar")
        self.toolbar.setStyleSheet(f"QWidget#richToolbar {{ background: {SURFACE}; border: 1px solid {BORDER}; "
                                   "border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }"
                                   f"QToolButton {{ border: none; padding: 3px; border-radius: 3px; }}"
                                   f"QToolButton:checked {{ background: #E3EEFB; }}"
                                   f"QToolButton:hover {{ background: #EEF2F7; }}")
        bar = QHBoxLayout(self.toolbar)
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(1)
        self.buttons = {}
        for name, glyph, tip, shortcut, handler, checkable in (
                ("bold", "mdi6.format-bold", "Grassetto", "Ctrl+B", self.toggle_bold, True),
                ("italic", "mdi6.format-italic", "Corsivo", "Ctrl+I", self.toggle_italic, True),
                ("underline", "mdi6.format-underline", "Sottolineato", "Ctrl+U", self.toggle_underline, True),
                ("strike", "mdi6.format-strikethrough", "Barrato", "", self.toggle_strike, True),
                ("code", "mdi6.code-tags", "Codice (testo a spaziatura fissa)", "", self.toggle_code, True),
                (None, None, None, None, None, None),
                ("bullets", "mdi6.format-list-bulleted", "Elenco puntato", "", self.toggle_bullets, True),
                ("numbers", "mdi6.format-list-numbered", "Elenco numerato", "", self.toggle_numbers, True),
                ("outdent", "mdi6.format-indent-decrease", "Riduci rientro", "", lambda: self.indent(-1), False),
                ("indent", "mdi6.format-indent-increase", "Aumenta rientro", "", lambda: self.indent(1), False),
                (None, None, None, None, None, None),
                ("link", "mdi6.link-variant", "Collegamento", "Ctrl+K", self.insert_link, False),
                ("clear", "mdi6.format-clear", "Rimuovi la formattazione", "", self.clear_format, False)):
            if name is None:
                bar.addSpacing(8)
                continue
            b = QToolButton(checkable=checkable)
            b.setIcon(icon(glyph, TEXT))
            b.setToolTip(f"{tip} ({shortcut})" if shortcut else tip)
            b.setFocusPolicy(Qt.NoFocus)  # the cursor stays in the text
            if shortcut:
                b.setShortcut(QKeySequence(shortcut))
            b.clicked.connect(lambda _=False, h=handler: self._apply(h))
            bar.addWidget(b)
            self.buttons[name] = b
        bar.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.editor)
        self._update_buttons()

    # --- content -----------------------------------------------------------------------------

    def _load(self, markdown):
        self.editor.blockSignals(True)
        self.editor.document().setMarkdown(prepare(markdown), DIALECT)
        self.editor.document().setModified(False)
        self.editor.blockSignals(False)
        self._loaded = to_markdown(self.editor.document())  # the original as this editor writes it

    def set_markdown(self, markdown):
        """Show another text (not an edit: changed is not emitted)."""
        self._original = markdown or ""
        self._load(self._original)

    def markdown(self):
        """The text as Markdown: the original one, unchanged, if it was not edited (in any way)."""
        current = to_markdown(self.editor.document())
        return self._original.strip() if current == self._loaded else current

    def plain_text(self):
        return self.editor.toPlainText()

    def _fit_height(self, *_):
        """As high as its text, from the base height up to MAX_HEIGHT (then it scrolls): a text that fills the
        box makes it grow, a shorter one brings it back."""
        margins = self.editor.contentsMargins()
        frame = 2 * self.editor.frameWidth() + margins.top() + margins.bottom()
        needed = int(self.editor.document().size().height()) + frame + 4
        height = max(self.base_height, min(needed, MAX_HEIGHT))
        if height != self.editor.height():
            self.editor.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()  # another width: the text wraps on more or fewer lines

    def setReadOnly(self, read_only):
        """Read-only: the formatted text without the toolbar."""
        self.editor.setReadOnly(read_only)
        self.toolbar.setVisible(not read_only)

    def isReadOnly(self):
        return self.editor.isReadOnly()

    def setPlaceholderText(self, text):
        self.editor.setPlaceholderText(text)

    def setFocus(self):
        self.editor.setFocus()

    # --- styles ------------------------------------------------------------------------------

    def _apply(self, handler):
        if self.editor.isReadOnly():
            return
        handler()
        self.editor.setFocus()
        self._update_buttons()

    def _merge(self, fmt):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)

    def toggle_bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.editor.fontWeight() >= QFont.Bold else QFont.Bold)
        self._merge(fmt)

    def toggle_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.editor.fontItalic())
        self._merge(fmt)

    def toggle_underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.editor.fontUnderline())
        self._merge(fmt)

    def toggle_strike(self):
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.editor.currentCharFormat().fontStrikeOut())
        self._merge(fmt)

    def toggle_code(self):
        fmt = QTextCharFormat()
        on = not self.editor.currentCharFormat().fontFixedPitch()
        fmt.setFontFixedPitch(on)
        fmt.setFontFamilies(["Consolas", "Courier New", "monospace"] if on else [self.editor.font().family()])
        self._merge(fmt)

    def _toggle_list(self, style):
        cursor = self.editor.textCursor()
        current = cursor.currentList()
        if current is not None and current.format().style() == style:
            # Already this list: the paragraphs leave it.
            block = cursor.block()
            current.remove(block)
            fmt = block.blockFormat()
            fmt.setIndent(0)
            cursor.setBlockFormat(fmt)
        elif current is not None:
            fmt = current.format()
            fmt.setStyle(style)
            current.setFormat(fmt)
        else:
            cursor.createList(style)

    def toggle_bullets(self):
        self._toggle_list(QTextListFormat.ListDisc)

    def toggle_numbers(self):
        self._toggle_list(QTextListFormat.ListDecimal)

    def indent(self, step):
        cursor = self.editor.textCursor()
        current = cursor.currentList()
        if current is not None:
            fmt = current.format()
            fmt.setIndent(max(1, fmt.indent() + step))
            cursor.createList(fmt) if step > 0 else current.setFormat(fmt)
        else:
            fmt = cursor.blockFormat()
            fmt.setIndent(max(0, fmt.indent() + step))
            cursor.setBlockFormat(fmt)

    def insert_link(self):
        cursor = self.editor.textCursor()
        href = cursor.charFormat().anchorHref() if cursor.charFormat().isAnchor() else "https://"
        url, ok = QInputDialog.getText(self, "Collegamento", "Indirizzo del collegamento:", text=href)
        if not ok:
            return
        fmt = QTextCharFormat()
        if url.strip() and url.strip() != "https://":
            fmt.setAnchor(True)
            fmt.setAnchorHref(url.strip())
            fmt.setForeground(QColor(LINK_COLOR))
            fmt.setFontUnderline(True)
        else:  # emptied: no longer a link
            fmt.setAnchor(False)
            fmt.setAnchorHref("")
            fmt.setFontUnderline(False)
        if not cursor.hasSelection():
            cursor.insertText(url.strip(), fmt)
        else:
            cursor.mergeCharFormat(fmt)

    def clear_format(self):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.BlockUnderCursor)
        cursor.setCharFormat(QTextCharFormat())
        current = cursor.currentList()
        if current is not None:
            current.remove(cursor.block())
        fmt = cursor.blockFormat()
        fmt.setIndent(0)
        cursor.setBlockFormat(fmt)

    def _update_buttons(self):
        fmt = self.editor.currentCharFormat()
        current = self.editor.textCursor().currentList()
        style = current.format().style() if current is not None else None
        for name, on in (("bold", self.editor.fontWeight() >= QFont.Bold), ("italic", self.editor.fontItalic()),
                         ("underline", fmt.fontUnderline() and not fmt.isAnchor()),
                         ("strike", fmt.fontStrikeOut()), ("code", fmt.fontFixedPitch()),
                         ("bullets", style == QTextListFormat.ListDisc),
                         ("numbers", style == QTextListFormat.ListDecimal)):
            self.buttons[name].setChecked(bool(on))
