import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidget

from arcadia_tool.importers.srs_figures import PageGraphics, locate_figures, locate_tables
from arcadia_tool.importers.srs_merge import FIGURES_DIR, apply_import, plan_import
from arcadia_tool.importers.srs_pdf import Classification, Line, SrsItem, Word, parse_lines
from arcadia_tool.storage.project import Project

def _png(colour):
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), colour).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = _png("red")
PNG_CHANGED = _png("blue")


def L(text, top, x=121.9, bold=False, page=1, size=11):
    return Line(page, x, top, text, bold, [Word(x, t, size, bold) for t in text.split()], x + 6 * len(text))


def page(*boxes, height=842):
    return PageGraphics(595, height, list(boxes))


def test_figure_area_is_the_drawing_above_the_caption():
    lines = [L("3.4.1.1 A balise group has a co-ordinate system.", 70, x=65.2),
             L("Label inside", 150, size=8),
             L("legend under the drawing", 230, size=8),
             L("Figure 1: Orientation of the balise group", 300, bold=True),
             L("Figure 2: Intentionally deleted", 330, bold=True),
             L("Next paragraph text", 360)]
    graphics = {1: page((120, 100, 450, 200), (130, 140, 300, 210))}
    figures, inside = locate_figures(lines, graphics)
    f1 = figures[id(lines[3])]
    assert (f1.kind, f1.number, f1.title) == ("Figure", "1", "Orientation of the balise group")
    assert f1.bbox[1] == 100 and f1.bbox[3] >= 230  # drawing plus its legend
    assert id(lines[1]) in inside and id(lines[2]) in inside and id(lines[5]) not in inside
    assert figures[id(lines[4])].bbox is None  # intentionally deleted


def test_caption_at_top_of_page_takes_the_drawing_of_the_previous_page():
    lines = [L("3.13.2.2 Deceleration model", 70, x=65.2, page=1),
             L("Figure 30: Speed Dependent Deceleration Model", 73, bold=True, page=2)]
    graphics = {1: page((100, 600, 500, 760)), 2: page()}
    figure = locate_figures(lines, graphics)[0][id(lines[1])]
    assert figure.page == 1 and figure.bbox[1] == 600


def test_parse_lines_creates_figure_items_and_drops_labels():
    lines = [L("3.4.1 Balise groups", 60, x=65.2, bold=True),
             L("3.4.1.1 A balise group has a co-ordinate system.", 70, x=65.2),
             L("Label inside", 150, size=8),
             L("Figure 1: Orientation", 300, bold=True)]
    figures, inside = locate_figures(lines, {1: page((120, 100, 450, 200))})
    items = {i.id: i for i in parse_lines(lines, 3, figures, inside)}
    assert "Label inside" not in items["3.4.1.1"].text
    figure = items["3.4.1.1 Figure 1"]
    assert figure.title == "Figure 1: Orientation" and figure.parent_id == "3.4.1.1"
    assert figure.extra["_figure"] is figures[id(lines[3])]


def test_equations_become_formula_blocks():
    def M(text, top, font="Times New Roman,Italic"):
        words = [Word(121.9 + 20 * i, t, 11, False, "Symbol" if t[0] >= "" else font)
                 for i, t in enumerate(text.split())]
        return Line(1, 121.9, top, text, False, words, 400, top + 10)

    lines = [L("3.13.9.3.5.8 The P speed shall be calculated as follows:", 72, x=65.2),
             M("V ( d ) ", 124), M("P max safefront", 133), M(" V d  V", 160),
             L("With V_delta0 calculated according to 3.13.9.3.2.10", 220),
             M("V ( d )  V d  D", 240),
             L("3.13.9.3.5.9 Next clause.", 300, x=65.2)]
    items = {i.id: i for i in parse_lines(lines, 3)}
    clause = items["3.13.9.3.5.8"]
    assert "" not in clause.text and "safefront" not in clause.text
    assert clause.text.splitlines() == ["The P speed shall be calculated as follows:", "[Formula 1]",
                                        "With V_delta0 calculated according to 3.13.9.3.2.10", "[Formula 2]"]
    blocks = clause.extra["_formulas"]
    assert len(blocks) == 2 and blocks[0]["top"] == 124 and blocks[0]["bottom"] == 170
    assert "_formulas" not in items["3.13.9.3.5.9"].extra


def test_symbol_font_glyphs_become_characters():
    from arcadia_tool.importers.srs_pdf import symbol_text
    assert symbol_text(" position  5  ") == "• position ≥ 5 − λ"
    assert symbol_text("plain text") == "plain text"


def test_tables_without_caption_over_several_pages():
    boxes = [(60, 100 + 10 * i, 500, 108 + 10 * i) for i in range(8)]
    spans = {"4.6.2": (1, 90, 2, 300), "4.6.3": (2, 300, 2, 700)}
    graphics = {1: page(*boxes), 2: page(*[(60, 70 + 10 * i, 500, 78 + 10 * i) for i in range(8)])}
    tables = locate_tables(spans, graphics, {"4.6.2"}, {}, 55, 65)
    assert [t.clause for t in tables] == ["4.6.2"]
    assert [p for p, _ in tables[0].regions] == [1, 2]


def figure_chapter(png=PNG):
    return {3: [SrsItem("3.5.3", "Sezione", title="Session"),
                SrsItem("3.5.3.7", "Requisito", text="The session is established."),
                SrsItem("3.5.3.7 Figure 3", "Voce", title="Figure 3: Establishment", parent="3.5.3.7",
                        extra={"figure_png": png})]}


def test_figures_are_saved_published_and_stable(tmp_path):
    ch9 = {"3.5.3.8 Figure 3": Classification(["Informativa"]), "3.5.3.7": Classification(["Bordo"])}
    p = Project.create(tmp_path / "p", "Prova")
    plan = plan_import(p.model, figure_chapter(), ch9)
    ids = {x.id for x in plan.new}
    assert "3.5.3.8 Figure 3" in ids and "3.5.3.7 Figure 3" not in ids  # aligned with chapter 9
    apply_import(p, plan)
    figure = next(e for e in p.model.of_kind("requirement") if e.get("id") == "3.5.3.8 Figure 3")
    rel = figure.get("figure")
    assert rel.startswith(FIGURES_DIR) and p.asset_data(rel) == PNG
    assert not (p.path / rel).exists()  # written at save
    p.save()
    assert (p.path / rel).read_bytes() == PNG
    p.publish("v1", "T <t@x.it>")
    assert not p.has_unpublished_changes()
    assert not plan_import(p.model, figure_chapter(), ch9)  # same image: nothing to update

    changed = figure_chapter(PNG_CHANGED)
    plan2 = plan_import(p.model, changed, ch9)
    assert [c for _, _, c in plan2.updates] == [["figure"]]
    apply_import(p, plan2)
    p.save()
    assert not (p.path / rel).exists()  # the old image is no longer used
    assert p.asset_data(figure.get("figure")) == PNG_CHANGED
    p.delete_element(figure.uuid)
    p.save()
    assert list((p.path / FIGURES_DIR).iterdir()) == []
    p.close()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_reader_shows_and_highlights(app, tmp_path):
    from arcadia_tool.ui.srs_reader import SrsReader

    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, figure_chapter(), None))
    reader = SrsReader(p)
    reader.show()
    reader.search.setText("establish")
    delegate = reader.view.itemDelegate()
    assert delegate.highlight == "establish"
    shown = [e for e in reader.model.elements if e.get("item_type") == "Requisito"]
    doc = delegate._highlighted("text", "#000", shown[0].get("text"), 400)
    assert doc is not None and "background-color" in doc.toHtml()
    assert delegate._highlighted("text", "#000", "nothing here", 400) is None
    figure = next(e for e in reader.model.elements if e.get("figure"))
    assert delegate._pixmap(figure) is not None and not delegate._pixmap(figure).isNull()
    p.close()


def test_back_to_catalogue_and_preview_image(app, tmp_path):
    from arcadia_tool.ui.import_srs import ImportSrsDialog
    from arcadia_tool.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    p = window.project

    dialog = ImportSrsDialog(p, window)
    dialog._on_done(figure_chapter(), None)
    new_table, row = next((t, r) for t in dialog.findChildren(QTableWidget) for r in range(t.rowCount())
                          if t.item(r, 0).text().endswith("Figure 3"))
    new_table.setCurrentCell(row, 0)
    assert dialog.detail_image.pixmap() is not None and not dialog.detail_image.pixmap().isNull()
    assert "Figure 3" in dialog.detail.text()
    dialog._apply()
    window.tree.reload()  # done by the main window after an import

    window.open_srs_reader()
    target = next(e for e in p.model.of_kind("requirement") if e.get("id") == "3.5.3.7")
    window.reader.open_element.emit(target.uuid)
    assert window.pages.currentWidget() is window.editor and window.editor.back_label
    assert window.editor.element is target
    window.editor.back_requested.emit(target.uuid)
    assert window.pages.currentWidget() is window.reader
    assert window.reader.view.currentIndex().data(Qt.UserRole) is target
    other = next(e for e in p.model.of_kind("requirement") if e.get("id") == "3.5.3")
    window.tree.select(other.uuid)  # opened from the tree: no back button
    assert window.editor.back_label is None
    window.save()
    window.close()
