import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from arcadia_tool.model.teams import da_teams, design_authority, is_da_member
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor
from arcadia_tool.ui.team_members import MembersWidget


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
    members = editor.widget().findChildren(MembersWidget)[0]
    members.rows.append({"name": "Luca Verdi", "account": "c" * 32})  # a member added in the sheet
    members.changed.emit()
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


ANNA, MARIO = "a" * 32, "b" * 32  # IDs of local accounts


def user(name, account=""):
    from types import SimpleNamespace
    return SimpleNamespace(full_name=name, id=account, username=name.split()[0].lower(),
                           email=f"{name.split()[0].lower()}@example.org")


def test_members_are_added_changed_and_removed_with_the_id_of_their_account(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.team_members as team_members
    from arcadia_tool.model.teams import member_rows
    from PySide6.QtWidgets import QMessageBox

    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria")
    editor = ElementEditor()
    editor.edit(p, team, editing=True)
    members = editor.widget().findChildren(MembersWidget)[0]
    assert members.empty.isVisibleTo(editor) and members.add_button.text() == "Aggiungi membro…"
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))

    def fill(name, account, email="", role=""):
        def run(dialog):
            dialog.name.setText(name)
            dialog.account.setText(account)
            dialog.email.setText(email)
            dialog.role.setText(role)
            dialog._accept()
            return dialog.result()
        return run
    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("Anna Bianchi", "", "anna@example.org"))
    assert members.add_member() is None and "Indica l'ID" in warnings[-1]  # the ID is required
    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("Anna Bianchi", "non-un-id"))
    assert members.add_member() is None and "non è valido" in warnings[-1]
    dashed = (ANNA[:8] + "-" + ANNA[8:]).upper()  # as typed: normalized
    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("Anna Bianchi", dashed, "anna@example.org", "Analista"))
    anna = members.add_member()
    assert anna == {"name": "Anna Bianchi", "account": ANNA, "email": "anna@example.org", "role": "Analista"}
    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("anna  BIANCHI", MARIO))
    assert members.add_member() is None and "già tra i membri" in warnings[-1]
    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("Mario Rossi", ANNA))
    assert members.add_member() is None and "già di un altro membro" in warnings[-1]
    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("Mario Rossi", MARIO))
    members.add_member()
    assert members.table.rowCount() == 2 and members.table.item(0, 3).text() == f"{ANNA[:8]}…"

    monkeypatch.setattr(team_members.MemberDialog, "exec", fill("Anna Bianchi Verdi", ANNA, "anna@example.org"))
    members.edit_member(0)
    assert members.rows[0]["name"] == "Anna Bianchi Verdi" and members.rows[0]["account"] == ANNA
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    members.remove_member(1)
    editor.save_changes()
    assert [r["name"] for r in member_rows(team)] == ["Anna Bianchi Verdi"]

    team.set("design_authority", True)
    p.update(team)
    assert is_da_member(p.model, user("A. Verdi", ANNA))  # by the ID, also with another name
    assert not is_da_member(p.model, user("Anna Bianchi Verdi", MARIO))  # her name, another account: no
    p.close()


def test_members_of_the_first_versions_are_recognized_by_name_until_their_id_is_written(tmp_path):
    from arcadia_tool.model.serialization import dumps
    from arcadia_tool.model.element import Element
    from arcadia_tool.model.teams import member_of, member_rows

    p = Project.create(tmp_path / "p", "Prova")
    p.close()
    old = Element("team", values={"id": "T1", "name": "DA", "members": [
        "Anna Bianchi", {"code": "M-AAAA-BBBB", "name": "Mario Rossi"}]})  # names, and a code of a test version
    folder = tmp_path / "p" / "model" / "x" / "teams"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{old.uuid}.yaml").write_text(dumps(old), encoding="utf-8")
    opened = Project.open(tmp_path / "p")
    team = opened.model.get(old.uuid)
    assert member_rows(team) == [{"name": "Anna Bianchi"}, {"name": "Mario Rossi"}]
    assert member_of(team, user("anna bianchi", ANNA))["name"] == "Anna Bianchi"  # no ID yet: by name
    team.set("members", [{"name": "Anna Bianchi", "account": ANNA}, {"name": "Mario Rossi"}])
    opened.update(team)
    assert member_of(team, user("Anna Bianchi", MARIO)) is None  # her ID is written: the name is not enough
    opened.close()


def test_only_the_design_authority_changes_the_teams(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from arcadia_tool.model.teams import edit_denied
    from arcadia_tool.ui.model_tree import ModelTree

    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria")
    anna, mario = user("Anna Bianchi", ANNA), user("Mario Rossi", MARIO)
    assert edit_denied(p.model, mario, "team") is None  # no DA yet: anyone sets it up
    da = p.new_element("team", name="DA", design_authority=True)
    assert edit_denied(p.model, mario, "team") is None  # a DA without members: still anyone
    da.set("members", [{"name": "Anna B.", "account": ANNA}])
    p.update(da)
    assert edit_denied(p.model, anna, "team") is None  # recognized by the ID of her account
    reason = edit_denied(p.model, mario, "team")
    assert "Design Authority" in reason and edit_denied(p.model, mario, "domain") is None

    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    editor = ElementEditor()
    editor.edit_denied = lambda kind, field=None: edit_denied(p.model, mario, kind, field)
    editor.edit(p, team, editing=True)
    assert not editor.editing and not editor.modify_button.isEnabled()
    assert editor.modify_button.toolTip() == reason
    editor.start_editing()
    assert not editor.editing
    editor.ask_to_edit()
    assert shown == [reason]

    tree = ModelTree()
    tree.project = p
    tree.edit_denied = lambda kind: edit_denied(p.model, mario, kind)
    count = len(p.model.of_kind("team"))
    tree.create("team")
    assert len(p.model.of_kind("team")) == count and shown[-1] == reason
    assert not tree.delete_element(team) and p.model.get(team.uuid) is not None

    editor.edit_denied = lambda kind, field=None: edit_denied(p.model, anna, kind, field)
    editor.edit(p, team, editing=True)
    assert editor.editing  # a member of the DA
    p.close()


def test_only_the_design_authority_assigns_the_domains_to_the_teams(app, tmp_path):
    from arcadia_tool.model.teams import edit_denied

    p = Project.create(tmp_path / "p", "Prova")
    p.new_element("team", name="DA", design_authority=True, members=[{"name": "Anna", "account": ANNA}])
    team = p.new_element("team", name="Odometria")
    domain = p.new_element("domain", name="Localizzazione")
    anna, mario = user("Anna", ANNA), user("Mario Rossi", MARIO)
    assert edit_denied(p.model, mario, "domain") is None  # the domain sheet: anyone
    assert "assegnare i domini" in edit_denied(p.model, mario, "domain", "team")
    assert edit_denied(p.model, mario, "domain", "mission") is None

    editor = ElementEditor()
    editor.edit_denied = lambda kind, field=None: edit_denied(p.model, mario, kind, field)
    editor.edit(p, domain, editing=True)
    combo = editor.widgets["team"]
    assert editor.editing and not combo.isEnabled() and "Design Authority" in combo.toolTip()
    editor.draft.set("team", team.uuid)  # even if it were changed: not saved
    editor.draft.set("mission", "Stimare la posizione.")
    editor._set_dirty(True)
    editor.save_changes()
    assert domain.get("team") is None and domain.get("mission") == "Stimare la posizione."
    assert domain.uuid not in (team.get("domains") or [])

    editor.edit_denied = lambda kind, field=None: edit_denied(p.model, anna, kind, field)
    editor.edit(p, domain, editing=True)
    combo = editor.widgets["team"]
    assert combo.isEnabled()
    combo.setCurrentIndex(combo.findData(team.uuid))
    editor.save_changes()
    assert domain.get("team") == team.uuid and domain.uuid in team.get("domains")
    p.close()


def test_the_account_window_shows_the_id_to_tell_the_design_authority(app):
    from arcadia_tool.accounts import Account, AccountStore
    from arcadia_tool.ui.accounts import AccountDialog

    account = Account(first_name="Anna", last_name="Bianchi", username="abianchi", email="anna@example.org")
    store = AccountStore.__new__(AccountStore)
    store.accounts = [account]
    dialog = AccountDialog(store, account)
    assert dialog.ident.text() == account.id and len(account.id) == 32
    assert not hasattr(account, "member_codes")


def test_the_members_are_right_below_the_description_of_the_team(app, tmp_path):
    from PySide6.QtWidgets import QLabel
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria", members=[{"name": "Anna", "account": ANNA}])
    editor = ElementEditor()
    editor.edit(p, team)
    captions = [l.text() for l in editor.widget().findChildren(QLabel) if l.objectName() == "sectionCaption"]
    order = [c.upper() for c in captions]
    assert order.index("MEMBRI DEL TEAM") == order.index("DESCRIZIONE") + 1, order
    p.close()


def test_only_the_members_of_the_teams_open_the_project(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.main_window as main_window
    from arcadia_tool.model.teams import access_denied, locks_out

    p = Project.create(tmp_path / "p", "Prova")
    anna, mario = user("Anna Bianchi", ANNA), user("Mario Rossi", MARIO)
    assert access_denied(p.model, mario) is None  # no ID in the teams yet: anyone, to set them up
    da = p.new_element("team", name="DA", design_authority=True, members=[{"name": "Mario Rossi"}])
    assert access_denied(p.model, mario) is None  # a member by name only: still the setup
    draft = da.copy()
    draft.set("members", [{"name": "Anna Bianchi", "account": ANNA}, {"name": "Mario Rossi"}])
    assert locks_out(p.model, draft, mario) and not locks_out(p.model, draft, anna)  # Mario would be left out
    da.set("members", [{"name": "Anna Bianchi", "account": ANNA}])
    p.update(da)
    assert access_denied(p.model, anna) is None
    assert "Chiedi alla Design Authority" in access_denied(p.model, mario)
    p.save()

    shown = []
    monkeypatch.setattr(main_window, "show_access_denied", lambda parent, reason, who: shown.append(who))
    window = main_window.MainWindow()
    window.set_user(mario)
    window._denied = None
    window._open_loaded(Project.open(tmp_path / "p"))  # what open_project does once the project is loaded
    assert window.project is None and window._denied
    window.set_user(anna)
    window._open_loaded(Project.open(tmp_path / "p"))
    assert window.project is not None and window._denied is None
    window.set_user(mario)  # another user logs in while the project is open: it closes
    assert window.project is None and shown == [mario]

    window.set_user(anna)
    window._open_loaded(Project.open(tmp_path / "p"))
    editor = ElementEditor()
    editor.locks_out = window.locks_out
    team = window.project.model.get(da.uuid)
    editor.edit(window.project, team, editing=True)
    editor.draft.set("members", [{"name": "Mario Rossi", "account": MARIO}])  # Anna removes herself
    editor._set_dirty(True)
    errors = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a[2]))
    editor.save_changes()
    assert errors and editor.editing and team.get("members") == [{"name": "Anna Bianchi", "account": ANNA}]
    assert "non potresti più aprire il progetto" in errors[-1]

    # The error at once, in the table of the members: her own row removed, or her ID changed, by mistake.
    import arcadia_tool.ui.team_members as team_members
    editor.edit(window.project, team, editing=True)
    members = editor.widget().findChildren(MembersWidget)[0]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    members.remove_member(0)
    assert len(errors) == 2 and members.rows == [{"name": "Anna Bianchi", "account": ANNA}]

    def change_id(dialog):
        dialog.account.setText(MARIO)
        dialog._accept()
        return dialog.result()
    monkeypatch.setattr(team_members.MemberDialog, "exec", change_id)
    members.edit_member(0)
    assert len(errors) == 3 and members.rows[0]["account"] == ANNA

    # Removing someone else is fine.
    members.rows.append({"name": "Mario Rossi", "account": MARIO})
    members.remove_member(1)
    assert len(errors) == 3 and len(members.rows) == 1

    # Deleting the team with her ID, from the tree: refused too.
    from arcadia_tool.ui.model_tree import ModelTree
    tree = ModelTree()
    tree.project = window.project
    tree.locks_out = window.locks_out
    assert not tree.delete_element(team) and len(errors) == 4 and window.project.model.get(team.uuid) is not None
    window._set_project(None)
    window.close()
    p.close()
