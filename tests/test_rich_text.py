"""Free texts with styles: a WYSIWYG editor, the text stored as Markdown."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor
from arcadia_tool.ui.rich_text import DIALECT, RichTextEdit, prepare, to_markdown
from arcadia_tool.ui.theme import apply_theme


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.mark.parametrize("text", [
    "Testo **grassetto**, *corsivo*, _sottolineato_, ~~barrato~~ e `codice` con M_MODE e 3.14.4.2.",
    "Intro:\n\n- uno\n- **due**\n   - annidato\n\n1. a\n2. b\n\nCon [collegamento](https://example.com).",
    "Prezzo 5 \\* 3 e \\[nota\\]",
])
def test_markdown_round_trip(app, text):
    document = QTextDocument()
    document.setMarkdown(prepare(text), DIALECT)
    assert to_markdown(document) == text  # written back the same: styles are kept, no line wrapping


def test_text_not_edited_stays_as_it_is(app):
    legacy = "Prima riga\nseconda riga *non* enfasi?"  # plain text of an earlier version
    box = RichTextEdit(legacy)
    assert box.plain_text() == "Prima riga\nseconda riga non enfasi?"  # its line break is kept on screen
    assert box.markdown() == legacy  # not rewritten until it is edited
    box.editor.moveCursor(QTextCursor.End)
    box.editor.insertPlainText(" Sì.")
    assert box.markdown() != legacy and box.markdown().endswith("Sì.")


def test_toolbar_styles(app):
    box = RichTextEdit("")
    box.editor.setPlainText("parola")
    box.editor.selectAll()
    box.toggle_bold()
    assert box.markdown() == "**parola**" and box.editor.fontWeight() >= QFont.Bold
    box.editor.selectAll()
    box.clear_format()
    box.toggle_bullets()
    assert box.markdown() == "- parola"
    box.toggle_bullets()  # again: no longer a list
    assert box.markdown() == "parola"


def test_the_box_grows_with_its_text(app):
    from arcadia_tool.ui.rich_text import MAX_HEIGHT
    box = RichTextEdit("Una riga.", height=96)
    box.resize(500, 200)
    box.show()
    app.processEvents()
    assert box.editor.height() == 96  # short text: the base height
    box.editor.setPlainText("\n".join(f"Riga {n}." for n in range(8)))
    app.processEvents()
    grown = box.editor.height()
    assert 96 < grown < MAX_HEIGHT  # the text fills the box: it grows to show all of it
    assert box.editor.verticalScrollBar().maximum() == 0  # nothing to scroll
    box.editor.setPlainText("\n".join(f"Riga {n}." for n in range(200)))
    app.processEvents()
    assert box.editor.height() == MAX_HEIGHT  # up to the maximum, then it scrolls
    box.editor.setPlainText("Corta.")
    app.processEvents()
    assert box.editor.height() == 96  # back to the base height
    box.close()


def test_sheet_texts_have_styles_and_srs_items_stay_plain(app, tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    domain = p.new_element("domain", name="Protezione", mission="Impedire i **movimenti**.")
    item = p.new_element("requirement", id="3.14.4.2", item_type="Requisito", text="Spec text")
    editor = ElementEditor()
    editor.edit(p, domain)
    mission = editor.widgets["mission"]
    assert isinstance(mission, RichTextEdit) and mission.isReadOnly() and mission.toolbar.isHidden()
    assert mission.plain_text() == "Impedire i movimenti."  # shown formatted, not with the marks

    editor.start_editing()
    mission = editor.widgets["mission"]
    assert not mission.isReadOnly() and not mission.toolbar.isHidden()
    mission.editor.moveCursor(QTextCursor.End)
    mission.editor.insertPlainText(" Sempre")
    mission.editor.moveCursor(QTextCursor.WordLeft, QTextCursor.KeepAnchor)
    mission.toggle_italic()
    editor.save_changes()
    assert domain.get("mission") == "Impedire i **movimenti**. *Sempre*"

    editor.edit(p, item)  # the text of the specification: plain, no toolbar
    assert isinstance(editor.widgets["text"], QPlainTextEdit)
    p.close()
