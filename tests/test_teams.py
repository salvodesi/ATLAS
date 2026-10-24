import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from arcadia_tool.model.teams import da_teams, design_authority, is_da_member
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


def test_team_assigned_in_the_domain_sheet_lists_the_domain(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    other_domain = p.new_element("domain", name="Velocità")
    t1 = p.new_element("team", name="Odometria", domains=[other_domain.uuid])
    t2 = p.new_element("team", name="Supervisione")
    domain = p.new_element("domain", name="Protezione")

    domain.set("team", t1.uuid)
    assert p.update(domain) == [t1]  # the team sheet is kept in step
    assert t1.get("domains") == [other_domain.uuid, domain.uuid]
    domain.set("team", t2.uuid)  # moved to another team: one team per domain
    changed = p.update(domain)
    assert {t.uuid for t in changed} == {t1.uuid, t2.uuid}
    assert t1.get("domains") == [other_domain.uuid] and t2.get("domains") == [domain.uuid]
    domain.set("team", None)  # no team any more
    p.update(domain)
    assert not t2.get("domains") and t1.get("domains") == [other_domain.uuid]
    assert p.update(domain) == []  # nothing to keep in step
    p.save()
    reopened = Project.open(tmp_path / "p")  # saved with the domain
    assert reopened.model.get(t1.uuid).get("domains") == [other_domain.uuid]


def test_the_open_team_sheet_follows_the_domain_sheet(app, tmp_path):
    from arcadia_tool.ui.main_window import MainWindow
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Supervisione")
    domain = p.new_element("domain", name="Protezione")
    p.save()
    window = MainWindow()
    window._set_project(p)
    window._open_finding(team.uuid)
    window._open_finding(domain.uuid)
    team_tab, domain_tab = window.editors[team.uuid], window.editors[domain.uuid]
    domain_tab.start_editing()
    combo = domain_tab.widgets["team"]
    combo.setCurrentIndex(combo.findData(team.uuid))
    domain_tab.save_changes()
    assert team.get("domains") == [domain.uuid]
    assert team_tab.draft.get("domains") == [domain.uuid]  # the open team tab shows the domain
    window.close()


def test_da_member_is_recognised_by_name_and_surname(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    da = p.new_element("team", name="Design Authority", design_authority=True,
                       members=["Salvatore De Simone", "Anna Bianchi"])
    p.new_element("team", name="Odometria", members=["Mario Rossi"])
    assert design_authority(p.model) is da
    for name in ("Salvatore De Simone", "salvatore de  simone", "De Simone Salvatore", "Anna Bianchì"):
        assert is_da_member(p.model, name), name
    for name in ("Mario Rossi", "Salvatore", ""):
        assert not is_da_member(p.model, name), name
    da.set("design_authority", False)
    assert design_authority(p.model) is None and not is_da_member(p.model, "Anna Bianchi")


def test_only_one_team_is_the_design_authority(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QCheckBox, QMessageBox
    p = Project.create(tmp_path / "p", "Prova")
    first = p.new_element("team", name="DA", design_authority=True)
    second = p.new_element("team", name="Odometria")
    editor = ElementEditor()
    editor.edit(p, second, editing=True)
    flag = editor.widgets["design_authority"]
    assert isinstance(flag, QCheckBox) and not flag.isChecked()
    flag.setChecked(True)
    editor.save_changes()  # the question is answered «No» (tests): not saved, still in edit mode
    assert editor.editing and not second.get("design_authority") and first.get("design_authority")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    moved = []
    editor.element_changed.connect(moved.append)
    editor.save_changes()  # «Sì»: the DA moves to this team
    assert not editor.editing and second.get("design_authority") and not first.get("design_authority")
    assert first in moved and second in moved
    assert [t.uuid for t in da_teams(p.model)] == [second.uuid]
    p.close()


def test_status_bar_shows_the_da_member(app, tmp_path):
    from arcadia_tool.accounts import Account
    from arcadia_tool.ui.main_window import MainWindow
    p = Project.create(tmp_path / "p", "Prova")
    window = MainWindow()
    window.set_user(Account(first_name="Anna", last_name="Bianchi", username="a.bianchi", email="a@b.it"))
    window._set_project(p)
    assert not window.user_is_da and "Design Authority" not in window.status_user.text()
    assert "Nessun team è indicato come Design Authority" in window.status_user.toolTip()
    p.new_element("team", name="DA", design_authority=True, members=["Anna Bianchi"])
    window._refresh_state()
    assert window.user_is_da and "Design Authority" in window.status_user.text()
    window.close()
