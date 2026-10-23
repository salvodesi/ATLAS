import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_trace_record_sheet_follows_the_sa3_register(app, tmp_path):
    from PySide6.QtWidgets import QLabel
    from arcadia_tool.model.serialization import dumps

    p = Project.create(tmp_path / "p", "Prova")
    item = p.new_element("requirement", id="3.4.1.3", item_type="Requisito", category=["Bordo"])
    ei = p.new_element("exchange_item", name="NID_BG")
    derived = p.new_element("derived_requirement", parent=item.uuid, obligation="Conta le boe")
    record = p.new_element("trace_record", requirement=item.uuid, exchange_items=[ei.uuid, derived.uuid])
    editor = ElementEditor()
    editor.edit(p, record)
    page = editor.widget()
    captions = [l.text() for l in page.findChildren(QLabel) if l.objectName() == "sectionCaption"]
    assert captions[0] == "ESITO DI TRACCIATURA (SA-3)"
    labels = [l.text() for l in page.findChildren(QLabel) if l.objectName() == "formLabel"]
    assert labels[:9] == ["ID voce", "Categoria cap. 9", "Funzione primaria", "Funzioni secondarie",
                          "Derivati / dizionario", "Domanda B5 decisiva", "Esito", "Note", "ADR"]
    category = editor.widgets["category"]
    assert category.isReadOnly() and category.text() == "Bordo"  # from chapter 9, through the SRS item
    editor.flush()
    record.set("notes", "verificato")
    p.update(record)
    assert "category" not in dumps(record)  # read from the SRS item, never saved twice
    p.close()


def test_trace_record_item_and_primary_function_are_chosen_in_windows(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.ui.srs_trace import PARENT, TickPickerDialog, TraceItemDialog

    p = Project.create(tmp_path / "p", "Prova")
    section = p.new_element("requirement", id="3.4.1", item_type="Sezione", title="Balise groups",
                            category=["Informativa"])
    clause = p.new_element("requirement", id="3.4.1.3", item_type="Requisito", parent=section.uuid,
                           category=["Bordo"], text="A balise group shall consist of 1 to 8 balises.")
    domain = p.new_element("domain", name="Localizzazione")
    system = p.new_element("system_function", name="Verifica il gruppo", domain=domain.uuid)
    logical = p.new_element("logical_function", name="Conta le boe", refines=system.uuid)
    record = p.new_element("trace_record")

    dialog = TraceItemDialog(p, record)  # «ID voce»: one SRS section or clause, with search
    assert dialog.tree.headerItem().text(1) == "Categoria cap. 9"  # right after the SRS item
    assert dialog._items[clause.uuid].text(1) == "Bordo" and dialog._items[section.uuid].text(1) == "Informativa"
    dialog._clicked(dialog._items[section.uuid], 1)  # a click on the category does nothing
    assert not dialog.chosen(PARENT)
    dialog._clicked(dialog._items[section.uuid], 2)  # the box is the next column
    assert dialog.chosen(PARENT) == {section.uuid}
    dialog.category_boxes["Informativa"].setChecked(False)  # filter on the chapter 9 category
    assert not dialog._items[clause.uuid].isHidden()  # Bordo
    assert dialog._items[section.uuid].isExpanded()  # opened to show it, though Informativa itself
    dialog.category_boxes["Bordo"].setChecked(False)
    assert dialog._items[clause.uuid].isHidden() and dialog._items[section.uuid].isHidden()
    for box in dialog.category_boxes.values():
        box.setChecked(True)
    dialog.click(dialog._items[section.uuid], PARENT)
    dialog.click(dialog._items[clause.uuid], PARENT)
    assert dialog.chosen(PARENT) == {clause.uuid}
    dialog.accept()
    assert record.get("requirement") == clause.uuid

    shown = []
    real_init = TickPickerDialog.__init__

    def spy(self, *args, **kwargs):  # «Funzione primaria»: one function, grouped
        real_init(self, *args, **kwargs)
        shown.append(self)
        self.single and self._clicked(self.items[logical.uuid], 1)
    monkeypatch.setattr(TickPickerDialog, "__init__", spy)
    monkeypatch.setattr(TickPickerDialog, "exec", lambda self: True)
    editor = ElementEditor()
    editor.edit(p, record, editing=True)
    assert editor.widgets["category"].text() == "Bordo"
    editor._pick(record.schema.field("primary_function"))
    picker = shown[0]
    assert picker.single and picker.items[system.uuid].parent().text(0) == p.model.choice_label(domain)
    assert picker.items[logical.uuid].parent().text(0) == p.model.choice_label(system)
    assert record.get("primary_function") is None  # in the draft until «Salva»
    editor.save_changes()
    assert record.get("primary_function") == logical.uuid
    assert isinstance(editor.widgets["primary_function"], type(editor.widgets["requirement"]))  # no combo
    p.close()


def test_referent_chosen_among_members_and_copied_to_the_domain(app, tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria", members=["Anna Bianchi", "Mario Rossi"])
    domain = p.new_element("domain", name="Localizzazione")

    editor = ElementEditor()
    editor.edit(p, team, editing=True)
    referent = editor.widgets["referent"]
    assert [referent.itemText(i) for i in range(referent.count())] == ["", "Anna Bianchi", "Mario Rossi"]
    editor.widgets["members"].setText("Anna Bianchi, Mario Rossi, Luca Verdi")  # members added in the sheet
    assert referent.findData("Luca Verdi") > 0
    referent.setCurrentIndex(referent.findData("Mario Rossi"))
    editor.save_changes()
    assert team.get("referent") == "Mario Rossi"

    editor.edit(p, domain, editing=True)
    identification = [f.name for f in domain.schema.fields if f.section == "Identificazione"]
    assert identification == ["team"]
    team_combo, shown = editor.widgets["team"], editor.widgets["referent"]
    assert shown.isReadOnly() and shown.text() == ""
    team_combo.setCurrentIndex(team_combo.findData(team.uuid))
    assert shown.text() == "Mario Rossi"  # chosen automatically
    editor.save_changes()
    assert domain.get("team") == team.uuid and domain.get("referent") == "Mario Rossi"

    team.set("referent", "Anna Bianchi")  # changed later in the team sheet
    p.update(team)
    assert domain.get("referent") == "Anna Bianchi"
    p.close()
