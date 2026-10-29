import os
from pathlib import Path

import pytest

from arcadia_tool.importers.srs_merge import PLACEHOLDER_NOTE, apply_import, plan_import
from arcadia_tool.importers.srs_pdf import (Classification, Line, SrsItem, Word, chapter_of, classify_page,
                                            normalize_id, parse_chapter, parse_lines)
from arcadia_tool.storage.project import Project

BODY = 121.9


def L(text, x=65.2, bold=False, page=1):
    return Line(page, x, 0, text, bold)


SAMPLE = [
    L("3.1 Modification History", bold=True),
    L("3.0.0 990307 All Merge of Basic + Detailed"),
    L("3.3 Introduction", bold=True),
    L("3.14 Supervise train movements", bold=True),
    L("3.14.4 Standstill supervision", bold=True),
    L("3.14.4.1 This function shall prevent the train from moving."),
    L("3.14.4.2 When a movement is detected, the brake command shall be triggered after a distance"),
    L("specified by the national value.", x=BODY),
    L("3.14.4.3 Introduction", bold=True),
    L("3.14.4.3.1 A position report shall be sent when:"),
    L("a) the train reaches standstill;", x=BODY),
    L("b) the mode changes.", x=BODY),
    L("• first bullet text", x=BODY),
]


def test_parse_lines_structure():
    items = {i.id: i for i in parse_lines(SAMPLE, 3)}
    assert "3.0.0" not in items  # modification history table skipped
    assert items["3.14.4"].item_type == "Sezione" and items["3.14.4"].title == "Standstill supervision"
    assert items["3.14"].item_type == "Capitolo"
    assert items["3.14.4.3"].item_type == "Titolo"
    req = items["3.14.4.2"]
    assert req.item_type == "Requisito"
    assert req.text.endswith("specified by the national value.")
    assert items["3.14.4.3.1 a)"].item_type == "Voce"
    assert items["3.14.4.3.1 b)"].text == "the mode changes."
    assert items["3.14.4.3.1 1st bullet"].text == "first bullet text"
    assert items["3.14.4.3.1 a)"].parent_id == "3.14.4.3.1"
    assert not items["3.14.4.3.1"].warnings


def W(x, text, size=10, bold=False):
    return Word(x, text, size, bold)


def LW(top, *words, page=1):
    words = list(words)
    return Line(page, words[0].x, top, " ".join(w.text for w in words), words[0].bold, words)


def test_procedure_table_rows():
    lines = [L("5.11.2.2 Procedure", bold=True),
             L("ID # Requirements", x=68.7, bold=True),
             L("S010 The on-board is in one of the following modes", x=68.7),
             L("modes: FS, LS, OS", x=104.1),
             L("A025 The mode shall change to TR.", x=68.7),
             L("ID # Requirements", x=68.7, bold=True),
             L("A030 The on-board shall report the mode change to the RBC", x=68.7),
             L("5.11.2.3 Something else follows."),
             L("Not part of the table.", x=BODY)]
    items = {i.id: i for i in parse_lines(lines, 5)}
    assert items["5.11.2.2 S010"].text == "The on-board is in one of the following modes modes: FS, LS, OS"
    assert items["5.11.2.2 A025"].parent_id == "5.11.2.2"
    assert "5.11.2.2 A030" in items
    assert items["5.11.2.3"].text == "Something else follows. Not part of the table."


def test_active_functions_table():
    header1 = LW(400, W(47.3, "ONBOARD-FUNCTIONS", bold=True), W(209.7, "RELATED", bold=True),
                 W(266.7, "N", bold=True), W(281.7, "S", bold=True), W(326.2, "F", bold=True))
    header2 = LW(414, W(218.7, "SRS", bold=True), W(240, "§", bold=True),
                 W(267.0, "P", bold=True), W(281.3, "B", bold=True), W(326.0, "S", bold=True))
    lines = [L("4.5.2 Active Functions Table", bold=True),
             L("4.5.2.1 X = functions shall be active"),
             header1, header2,
             LW(430, W(47.3, "Data", bold=True), W(80, "Consistency", bold=True)),
             LW(450, W(47.3, "Check"), W(75, "linking"), W(215.1, "3.16.2.3"), W(325.9, "X")),
             LW(466, W(47.3, "consistency"), W(222.1, "3.4.4")),
             LW(480, W(47.3, "Standstill"), W(100, "Supervision"), W(215.1, "3.8.2.3"), W(240, "a)"),
                W(281.6, "X"), W(266.5, "O")),
             LW(494, W(215.1, "and"), W(235, "b)")),
             LW(700, W(65.2, "4", size=6.5), W(70, "Footnote"), W(110, "text")),
             L("Figure 1: Active Functions table", bold=True),
             L("4.5.3 Next clause.")]
    items = {i.id: i for i in parse_lines(lines, 4)}
    r1, r2 = items["4.5.2-R01"], items["4.5.2-R02"]
    assert r1.title == "Check linking consistency"
    assert r1.extra == {"srs_refs": ["3.16.2.3", "3.4.4"]}
    assert "Gruppo: Data Consistency" in r1.text and "Attiva in: FS" in r1.text
    assert "Attiva in: SB" in r2.text and "Opzionale in: NP" in r2.text
    assert r2.extra["srs_refs"] == ["3.8.2.3 a) and b)"]
    assert r1.parent_id == "4.5.2.1 Table"
    assert "4.5.3" in items and "Footnote" not in r2.title


def test_language_chapter_keeps_structure():
    lines = [L("7.5 Definitions of Variables", bold=True),
             L("7.5.1.72 M_MODE"),
             L("Name Onboard operating mode", x=65.1),
             L("• not a bullet item here", x=196.6),
             L("Length of variable 4 bits", x=65.1)]
    item = {i.id: i for i in parse_lines(lines, 7)}["7.5.1.72"]
    assert item.title == "M_MODE"
    assert item.text.splitlines() == ["Name Onboard operating mode", "• not a bullet item here",
                                      "Length of variable 4 bits"]


def _ch9_words(rows):
    words = [{"text": "ETCS", "x0": 173.5, "top": 156}, {"text": "on-", "x0": 200, "top": 156},
             {"text": "trackside", "x0": 237.8, "top": 168}, {"text": "Definition", "x0": 302, "top": 168},
             {"text": "Informative", "x0": 354.4, "top": 168}, {"text": "Others", "x0": 414.8, "top": 168}]
    for top, ident, mark_x in rows:
        if ident:
            words.append({"text": ident, "x0": 70.1, "top": top})
        if mark_x:
            words.append({"text": "x", "x0": mark_x, "top": top})
    return words


def test_chapter_9_cells_spanning_several_lines():
    result = {}
    classify_page(_ch9_words([
        (200, "7.4.2.1 Packet Number 2: System", None),
        (212, "Version order", 197.7), (212, None, 261.9),
        (230, "7.5.1.72 M_MODE", 197.7),
        (245, "3.6.5.1.4 a)", 376.6),
        (260, "5.4.3.2 S1", 197.7),
    ]), result)
    assert result["7.4.2.1"].categories == ["Bordo", "Terra"]
    assert result["7.5.1.72"].categories == ["Bordo"]
    assert result["3.6.5.1.4 a)"].categories == ["Informativa"]
    assert "5.4.3.2 S1" in result


def test_normalize_id():
    assert normalize_id("7.5.1.72 M_MODE") == "7.5.1.72"
    assert normalize_id("8.6.3 Message 132: MA request") == "8.6.3"
    assert normalize_id("7..4.2.20.1") == "7.4.2.20.1"  # a typo of chapter 9
    for kept in ("3.6.5.1.4 a)", "5.11.2.2 A030", "4.10.1.3 Table - footnote [1]", "3.10.2.2 1st bullet",
                 "5.10.1.4.1 Figure 7"):
        assert normalize_id(kept) == kept


def test_appendix_of_the_chapter():
    lines = [L("3.20.1.9 Intentionally deleted."),
             L("A C 3 PPENDIX TO HAPTER", bold=True),  # small capitals, as extracted from the PDF
             L("A.3.1 List of Fixed Value Data", bold=True),
             L("A.3.1.1 The fixed values are listed in the table."),
             L("A.3.3 Train data", bold=True),
             L("A.3.3.1 The train data shall be used as follows."),
             L("A.3.4 Stored information", bold=True),
             L("A.3.4.1 Definitions", bold=True),
             L("A.3.4.1.1 Stored information is information received from trackside.")]
    items = {i.id: i for i in parse_lines(lines, 3)}
    assert items["3.20.1.9"].text == "Intentionally deleted."  # the appendix no longer ends up here
    assert items["A.3"].item_type == "Capitolo" and items["A.3"].title == "Appendix to Chapter 3"
    # The sections of the appendix: A.3.1 (one level less than 3.4.1); a bold A.3.4.1 is a heading inside A.3.4.
    assert items["A.3.1"].item_type == "Sezione" and items["A.3.1"].title == "List of Fixed Value Data"
    assert items["A.3.4"].item_type == "Sezione"
    assert items["A.3.3.1"].item_type == "Requisito"  # plain 3-level number in the appendix
    assert items["A.3.4.1"].item_type == "Titolo"
    assert items["A.3.4.1.1"].item_type == "Requisito" and items["A.3.4.1.1"].parent_id == "A.3.4.1"
    assert items["A.3.1"].parent_id == "A.3"
    assert not any(i.warnings for i in items.values())


def test_a_section_without_heading_is_added_before_its_clauses():
    lines = [L("3.20 Juridical Data", bold=True),  # no «3.20.1» heading: the clauses follow the chapter
             L("3.20.1.1 The on-board recording device is not part of the equipment."),
             L("3.20.1.2 The on-board equipment shall transmit the information."),
             L("3.21 Next chapter", bold=True),
             L("3.21.1 A section", bold=True),
             L("3.21.1.1 A clause.")]
    items = parse_lines(lines, 3)
    assert [(i.id, i.item_type) for i in items] == [
        ("3.20", "Capitolo"), ("3.20.1", "Sezione"), ("3.20.1.1", "Requisito"), ("3.20.1.2", "Requisito"),
        ("3.21", "Capitolo"), ("3.21.1", "Sezione"), ("3.21.1.1", "Requisito")]
    added = items[1]
    assert added.title == "Juridical Data" and "senza intestazione" in added.extra["import_note"]
    assert items[2].parent_id == "3.20.1" and [i.sequence for i in items] == sorted(i.sequence for i in items)


def test_appendix_items_in_chapter_9_and_merge(tmp_path):
    from arcadia_tool.importers.srs_pdf import chapter_of_item, table_clauses

    result = {}
    classify_page(_ch9_words([(200, "A.3.3.1", 197.7), (215, "A.3.3.1 Table 17", 376.6), (230, "A.3.1 Table", 376.6)]),
                  result)
    assert result["A.3.3.1"].categories == ["Bordo"] and "A.3.3.1 Table 17" in result
    assert table_clauses(result, 3) == {"A.3.1"}
    assert chapter_of_item("A.3.4.1") == 3 and chapter_of_item("4.5.2-R01") == 4
    # chapter 9 ids that are not plain numbers must not break the placeholders
    odd = {"3.13.9.3.1a)": Classification(["Bordo"]), "A.3.3.1": Classification(["Bordo"])}
    assert {x.id for x in plan_import(Project.create(tmp_path / "q", "Q").model, {3: []}, odd).new} == set(odd)

    chapters = {3: [SrsItem("A.3", "Capitolo", title="Appendix to Chapter 3"),
                    SrsItem("A.3.3", "Capitolo", title="Train data"),
                    SrsItem("A.3.3.1", "Requisito", text="The train data shall be used.")]}
    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, chapters, result))
    by = {e.get("id"): e for e in p.model.of_kind("requirement")}
    assert by["A.3.3.1"].get("category") == ["Bordo"]
    assert p.model.get(by["A.3.3.1"].get("parent")).get("id") == "A.3.3"
    assert "A.3.3.1 Table 17" in by  # placeholder: chapter 3 is in scope
    p.close()


def test_chapter_from_file_name():
    assert chapter_of("SUBSET-026-3 v360.pdf") == 3
    assert chapter_of("altro.pdf") is None


def _items():
    return {3: [SrsItem("3.14", "Capitolo", title="Supervise"),
                SrsItem("3.14.4", "Sezione", title="Standstill supervision"),
                SrsItem("3.14.4.2", "Requisito", text="When a movement is detected"),
                SrsItem("3.14.4.2 a)", "Voce", text="first"),
                SrsItem("3.14.9.9", "Requisito", text="not in chapter 9")]}


CH9 = {"3.14": Classification(["Informativa"]), "3.14.4": Classification(["Informativa"]),
       "3.14.4.2": Classification(["Bordo"]), "3.14.4.2 Table": Classification(["Bordo", "Terra"]),
       "6.5.1.2.2": Classification(["Bordo"], replaces="3.14.4.2")}


def test_plan_and_apply_import(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    plan = plan_import(p.model, _items(), CH9, "SUBSET-026 v3.6.0")
    ids = {x.id for x in plan.new}
    # «3.14.4.2 a)»: chapter 9 classifies 3.14.4.2 but does not list a list item → not an item
    assert ids == {"3.14", "3.14.4", "3.14.4.2", "3.14.9.9", "3.14.4.2 Table"}
    assert plan.discarded == ["3.14.4.2 a)"]
    assert "6.5.1.2.2" not in ids  # chapter 6 is not part of this import
    created, updated = apply_import(p, plan)
    assert (created, updated) == (5, 0)
    by = {e.get("id"): e for e in p.model.of_kind("requirement")}
    assert by["3.14.4.2"].get("category") == ["Bordo"]
    assert by["3.14.4.2 Table"].get("import_note").startswith(PLACEHOLDER_NOTE)
    assert "capitolo 9" in by["3.14.9.9"].get("import_note")
    assert p.model.get(by["3.14.4.2"].get("parent")).get("id") == "3.14.4"
    assert p.model.get(by["3.14.9.9"].get("parent")).get("id") == "3.14"  # missing 3.14.9: nearest ancestor
    assert by["3.14.4.2"].get("baseline") == "SUBSET-026 v3.6.0"

    again = plan_import(p.model, _items(), CH9, "SUBSET-026 v3.6.0")
    assert not again and again.unchanged == 5

    changed = _items()
    changed[3][2].text = "When a movement is detected (rev.)"
    del changed[3][4]
    plan2 = plan_import(p.model, changed, CH9, "SUBSET-026 v3.6.0")
    assert [(e.get("id"), c) for e, _, c in plan2.updates] == [("3.14.4.2", ["text"])]
    assert [e.get("id") for e in plan2.missing] == ["3.14.9.9"]
    p.close()


def test_duplicate_ids_keep_both_texts_and_reimport_is_stable(tmp_path):
    chapters = {3: [SrsItem("3.6.5.1.2", "Requisito", text="Two lists"),
                    SrsItem("3.6.5.1.2 a)", "Voce", text="first list"),
                    SrsItem("3.6.5.1.2 a)", "Voce", text="second list"),
                    SrsItem("6.5.1.6.4", "Requisito", text="v1 rule")]}
    ch9 = {"6.5.1.6.4": Classification(["Bordo"], replaces="8.4.4.4.2")}  # target not in the project
    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, chapters, ch9))
    item = next(e for e in p.model.of_kind("requirement") if e.get("id") == "3.6.5.1.2 a)")
    assert item.get("text") == "first list\nsecond list"
    assert chapters[3][1].text == "first list"  # parsed items are not modified
    again = plan_import(p.model, chapters, ch9)
    assert not again.updates and not again.new
    p.close()


def test_sequence_check_accepts_zero_and_level_changes():
    from arcadia_tool.importers.srs_pdf import _plausible_successor as ok
    assert ok("7.4.2", "7.4.2.0") and ok("7.5", "7.5.0.1") and ok("7.5.0.5", "7.5.1.1")
    assert ok("3.4.2", "3.4.2.1.1") and ok("3.14.4.5", "3.15")
    assert not ok("3.14.4.2", "3.14.4.7")


def test_reimport_removes_obsolete_mode_availability(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, _items(), CH9))
    req = next(e for e in p.model.of_kind("requirement") if e.get("id") == "3.14.4.2")
    req.set("mode_availability", {"SB": "X"})  # written by a previous version of the import
    p.update(req)
    plan = plan_import(p.model, _items(), CH9)
    assert [(e.get("id"), c) for e, _, c in plan.updates] == [("3.14.4.2", ["mode_availability"])]
    apply_import(p, plan)
    assert req.get("mode_availability") is None
    p.close()


def test_import_can_delete_items_no_longer_present(tmp_path, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    import arcadia_tool.ui.srs_reader as srs_reader
    from arcadia_tool.ui.import_srs import ImportSrsDialog

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(srs_reader.QMessageBox, "exec", lambda self: QMessageBox.Yes)
    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, _items(), CH9))
    fewer = _items()
    del fewer[3][4]  # 3.14.9.9 is no longer in the PDF
    dialog = ImportSrsDialog(p)
    dialog._on_done(fewer, CH9)
    assert dialog.delete_missing.text().startswith("Elimina anche le 1 ")
    assert "elimina" not in dialog.import_button.text()  # off by default: nothing is deleted
    dialog.delete_missing.setChecked(True)
    assert dialog.import_button.isEnabled() and "elimina 1" in dialog.import_button.text()
    dialog._apply()
    assert dialog.deleted == 1
    assert "3.14.9.9" not in {e.get("id") for e in p.model.of_kind("requirement")}
    p.close()


def test_preview_lists_items_in_specification_order(tmp_path):
    chapters = {
        3: [SrsItem("3.5.3.7", "Requisito", text="Establishment"),
            SrsItem("3.5.3.7 Figure 3", "Voce", title="Figure 3: Establishment", parent="3.5.3.7"),
            SrsItem("3.10", "Capitolo", title="Emergency"),
            SrsItem("A.3.1", "Capitolo", title="Fixed values"),
            SrsItem("3.5.3.8", "Requisito", text="Next")],
        8: [SrsItem("8.4.3.1", "Requisito", text="Header"),
            SrsItem("8.4.4", "Sezione", title="Next section"),
            SrsItem("8.4.3.1 Table", "Voce", title="Tabella", parent="8.4.3.1")],
    }
    ch9 = {"3.5.3.8 Figure 3": Classification(["Informativa"])}  # realigned: was appended at the end
    p = Project.create(tmp_path / "p", "Prova")
    order = [x.id for x in plan_import(p.model, chapters, ch9).new]
    assert order == ["3.5.3.7", "3.5.3.8", "3.5.3.8 Figure 3", "3.10", "A.3.1",
                     "8.4.3.1", "8.4.3.1 Table", "8.4.4"]
    p.close()


def test_sub_items_follow_chapter_9(tmp_path):
    chapters = {3: [
        SrsItem("3.4.4.1.1", "Requisito", text="Three cases:\n• one\n• two\n• three"),
        SrsItem("3.4.4.1.1 1st bullet", "Voce", text="one"),     # chapter 9 counts letters here
        SrsItem("3.4.4.1.1 2nd bullet", "Voce", text="two"),
        SrsItem("3.4.4.1.1 3rd bullet", "Voce", text="three"),
        SrsItem("3.5.3.7", "Requisito", text="Steps"),
        SrsItem("3.5.3.7 d)", "Voce", text="When"),
        SrsItem("3.5.3.7 1st bullet", "Voce", text="nested"),    # chapter 9 nests it under d)
        SrsItem("8.4.4.1.1", "Requisito", text="refer to section 3.17.3.11\nb))."),
        SrsItem("8.4.4.1.1 b)", "Voce", text=")."),              # a wrapped reference, not a list item
    ]}
    ch9 = {k: Classification(["Bordo"]) for k in (
        "3.4.4.1.1", "3.4.4.1.1 a)", "3.4.4.1.1 b)", "3.4.4.1.1 c)",
        "3.5.3.7", "3.5.3.7 d)", "3.5.3.7 d) 1st bullet", "8.4.4.1.1")}
    p = Project.create(tmp_path / "p", "Prova")
    plan = plan_import(p.model, chapters, ch9)
    ids = {x.id for x in plan.new}
    assert {"3.4.4.1.1 a)", "3.4.4.1.1 b)", "3.4.4.1.1 c)", "3.5.3.7 d) 1st bullet"} <= ids
    assert not any("bullet" in i and i.startswith("3.4.4.1.1") for i in ids)
    assert "8.4.4.1.1 b)" not in ids and plan.discarded == ["8.4.4.1.1 b)"]
    assert plan.renamed["3.5.3.7 1st bullet"] == "3.5.3.7 d) 1st bullet"
    texts = {x.id: x.values["text"] for x in plan.new}
    assert texts["3.4.4.1.1 b)"] == "two" and "b))." in texts["8.4.4.1.1"]  # text kept in the clause
    assert not plan.warnings
    apply_import(p, plan)
    assert not plan_import(p.model, chapters, ch9)  # stable
    p.close()


def T(top, text, x=65.2, body=None):
    """A line at a given height; body: x of the text after a list letter or bullet."""
    head, _, rest = text.partition(" ")
    words = [Word(x, head, 10, False)] + ([Word(body or x + 20, rest, 10, False)] if rest else [])
    return Line(1, x, top, text, False, words)


def test_clause_text_does_not_repeat_its_list_items(tmp_path):
    lines = [T(100, "3.4.4.2.1 The on-board shall check that:"),
             T(114, "a) the first condition is met,", x=BODY, body=140),
             T(126, "continued on a second line;", x=140),
             T(140, "b) the second condition is met.", x=BODY, body=140),
             T(170, "The check shall be repeated.", x=BODY),
             T(200, "3.4.4.2.2 Next clause.")]
    items = {i.id: i for i in parse_lines(lines, 3)}
    assert items["3.4.4.2.1 a)"].text == "the first condition is met, continued on a second line;"
    wrapped = parse_lines([T(100, "3.5.7.2 The ERTMS/ETCS on-"), T(112, "board equipment shall", x=BODY)], 3)
    assert wrapped[0].text == "The ERTMS/ETCS on-board equipment shall"
    assert items["3.4.4.2.1 b)"].text == "the second condition is met."  # the last paragraph is not in b)
    p = Project.create(tmp_path / "p", "Prova")
    texts = {x.id: x.values["text"] for x in plan_import(p.model, {3: list(items.values())}).new}
    assert texts["3.4.4.2.1"] == "The on-board shall check that:\nThe check shall be repeated."
    # With chapter 9, list items that are not items (here b)) stay in the clause text.
    ch9 = {k: Classification(["Bordo"]) for k in ("3.4.4.2.1", "3.4.4.2.1 a)", "3.4.4.2.1 c)", "3.4.4.2.2")}
    lines.insert(4, T(150, "c) a third one.", x=BODY, body=140))
    texts = {x.id: x.values["text"] for x in plan_import(p.model, {3: parse_lines(lines, 3)}, ch9).new}
    assert texts["3.4.4.2.1"] == ("The on-board shall check that:\nb) the second condition is met.\n"
                                  "The check shall be repeated.")
    p.close()


def test_procedure_rows_keep_the_document_order(tmp_path):
    from arcadia_tool.ui.srs_reader import document_order

    rows = ["S0", "S1", "D2", "A23", "E10", "A5"]
    lines = [L("5.4.3.2 Procedure", bold=True), L("ID # Requirements", x=68.7, bold=True)]
    lines += [L(f"{r} Row {r}", x=68.7) for r in rows]
    items = parse_lines(lines, 5)
    ch9 = {f"5.4.3.2 {r}": Classification(["Bordo"]) for r in rows + ["A7"]}  # A7 only in chapter 9
    p = Project.create(tmp_path / "p", "Prova")
    plan = plan_import(p.model, {5: items}, ch9)
    assert [x.id.split()[-1] for x in plan.new if " " in x.id] == rows + ["A7"]
    apply_import(p, plan)
    order = [e.get("id").split()[-1] for e in document_order(p.model) if " " in e.get("id")]
    assert order == rows + ["A7"]
    assert not plan_import(p.model, {5: parse_lines(lines, 5)}, ch9)  # stable
    p.close()


def test_sections_only_in_chapter_9_keep_their_place(tmp_path):
    from arcadia_tool.ui.srs_reader import document_order

    lines = [L("5.1 Modification History", bold=True), L("5.3 Introduction", bold=True),
             L("5.3.1.1 Text."), L("5.20 Track conditions", bold=True), L("5.20.8.9 Last clause.")]
    ch9 = {k: Classification(["Bordo"]) for k in ("5.2", "5.3.1.1", "5.20.8.9")}
    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, {5: parse_lines(lines, 5)}, ch9))
    order = [e.get("id") for e in document_order(p.model)]
    assert order.index("5.1") < order.index("5.2") < order.index("5.3")
    p.close()


def test_list_items_of_a_procedure_row(tmp_path):
    lines = [L("5.11.2.2 Procedure", bold=True), L("ID # Requirements", x=68.7, bold=True),
             Line(1, 68.7, 100, "S140 The driver selects:", False),
             Line(1, 104.1, 130, "a) start in level 1 ( E150 ), go to S150", False),
             Line(1, 104.1, 160, "b) SH ( E145 ), continue", False),
             Line(1, 68.7, 190, "S150 Wait", False)]
    ch9 = {k: Classification(["Bordo"]) for k in ("5.11.2.2", "5.11.2.2 S140", "5.11.2.2 S140 a)",
                                                    "5.11.2.2 S140 b)", "5.11.2.2 S150")}
    p = Project.create(tmp_path / "p", "Prova")
    plan = plan_import(p.model, {5: parse_lines(lines, 5)}, ch9)
    new = {x.id: x for x in plan.new}
    assert new["5.11.2.2 S140"].values["text"] == "The driver selects:"
    assert new["5.11.2.2 S140 a)"].values["text"] == "start in level 1 ( E150 ), go to S150"
    assert new["5.11.2.2 S140 b)"].parent_id == "5.11.2.2 S140" and not plan.warnings
    apply_import(p, plan)
    assert not plan_import(p.model, {5: parse_lines(lines, 5)}, ch9)
    p.close()


def test_letter_items_need_text_after_the_parenthesis():
    items = {i.id for i in parse_lines([L("8.4.4.1.1 Exception (refer to section 3.17.3.11"), L("b)).", x=BODY),
                                       L("8.4.4.1.2 The list:"), L("a) first", x=BODY),
                                       L("b) “Invalid” (the stored value may be wrong)", x=BODY)], 8)}
    assert "8.4.4.1.1 b)" not in items and {"8.4.4.1.2 a)", "8.4.4.1.2 b)"} <= items


def test_manual_category_is_not_overwritten(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    apply_import(p, plan_import(p.model, _items(), CH9))
    req = next(e for e in p.model.of_kind("requirement") if e.get("id") == "3.14.4.2")
    req.set("category", ["Terra"])
    req.set("category_note", "Interpretazione concordata con la DA")
    p.update(req)
    assert "category" not in [c for e, _, cs in plan_import(p.model, _items(), CH9).updates for c in cs]
    p.close()


def test_classification_links_version_1_clauses(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    chapters = {**_items(), 6: [SrsItem("6.5.1.2.2", "Requisito", text="For system version 1 ...")]}
    apply_import(p, plan_import(p.model, chapters, CH9))
    by = {e.get("id"): e for e in p.model.of_kind("requirement")}
    assert p.model.get(by["6.5.1.2.2"].get("replaces")).get("id") == "3.14.4.2"
    p.close()


PDF_DIR = os.environ.get("ARCADIA_SRS_PDF_DIR")


@pytest.mark.skipif(not PDF_DIR, reason="imposta ARCADIA_SRS_PDF_DIR per il test sui PDF reali")
def test_real_chapter_4():
    items = {i.id: i for i in parse_chapter(Path(PDF_DIR) / "SUBSET-026-4 v360.pdf")}
    assert items["4.4.1"].item_type == "Sezione"
    assert len([i for i in items.values() if i.item_type == "Requisito"]) > 250
