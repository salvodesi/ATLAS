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
    assert labels[:9] == ["ID voce", "Categoria cap. 9", "Funzioni primarie", "Funzioni secondarie",
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

    def spy(self, *args, **kwargs):  # «Funzioni primarie»: one or more functions, grouped
        real_init(self, *args, **kwargs)
        shown.append(self)
        self._clicked(self.items[logical.uuid], 1)
        self._clicked(self.items[system.uuid], 1)
    monkeypatch.setattr(TickPickerDialog, "__init__", spy)
    monkeypatch.setattr(TickPickerDialog, "exec", lambda self: True)
    editor = ElementEditor()
    editor.edit(p, record, editing=True)
    assert editor.widgets["category"].text() == "Bordo"
    editor.widgets["primary_functions"]._pick()
    picker = shown[0]
    assert not picker.single and picker.items[system.uuid].parent().text(0) == p.model.choice_label(domain)
    assert picker.items[logical.uuid].parent().text(0) == p.model.choice_label(system)
    assert record.get("primary_functions") is None  # in the draft until «Salva»
    editor.save_changes()
    assert set(record.get("primary_functions")) == {logical.uuid, system.uuid}  # both primary
    p.close()


def test_a_record_with_one_primary_function_of_earlier_versions_gets_a_list(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    item = p.new_element("requirement", id="3.4.1.3", item_type="Requisito")
    function = p.new_element("system_function", name="Verifica il gruppo")
    record = p.new_element("trace_record", requirement=item.uuid)
    record.values["primary_function"] = function.uuid  # as saved up to 0.7.0
    p.save()
    p.close()
    again = Project.open(tmp_path / "p")
    record = again.model.get(record.uuid)
    assert record.get("primary_functions") == [function.uuid] and "primary_function" not in record.values
    again.close()


def test_referent_chosen_among_members_and_proposed_to_the_domain(optional_fields, app, tmp_path):
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
    shown = editor.widgets["referent"]  # chosen among the members of the team assigned
    assert shown.value() is None and shown.options(None) == []  # no team yet: nobody to choose
    editor.draft.set("team", team.uuid)  # chosen in its window
    editor._draft_changed()
    shown = editor.widgets["referent"]
    assert shown.value() == "Mario Rossi"  # the referent of the team, proposed
    assert [name for name, _label in shown.options(shown.value())] == ["Anna Bianchi", "Mario Rossi", "Luca Verdi"]
    shown.set_value("Anna Bianchi")  # another member of the team
    editor.save_changes()
    assert domain.get("team") == team.uuid and domain.get("referent") == "Anna Bianchi"

    team.set("referent", "Luca Verdi")  # changed later in the team sheet: the domain keeps its own
    p.update(team)
    assert domain.get("referent") == "Anna Bianchi"
    other = p.new_element("team", name="Radio", members=["Sara Neri"], referent="Sara Neri")
    previous = domain.copy()
    domain.set("team", other.uuid)  # another team: Anna is not one of its members
    p.update(domain, previous)
    assert domain.get("referent") == "Sara Neri"
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


def test_the_open_team_sheet_follows_the_domain_sheet(optional_fields, app, tmp_path):
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
    domain_tab.draft.set("team", team.uuid)  # chosen in its window
    domain_tab._draft_changed()
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
            dialog.account.set_text(account)
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


def test_only_the_design_authority_assigns_the_domains_to_the_teams(optional_fields, app, tmp_path):
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
    assert editor.widgets["team"].isEnabled()
    editor.draft.set("team", team.uuid)  # chosen in its window
    editor._draft_changed()
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
        dialog.account.set_text(MARIO)
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


def test_publish_asks_first_for_the_changes_of_a_sheet_not_saved(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import main_window as mw
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria", members=[{"name": "Mario Rossi", "account": "a" * 32}])
    p.save()
    p.publish("Prima versione", "Prova <prova@example.com>")
    window = mw.MainWindow()
    window._set_project(p)
    window._open_finding(team.uuid)
    editor = window.editors[team.uuid]
    editor.start_editing()
    members = editor.findChild(MembersWidget)
    members.set_value([{"name": "Mario Rossi", "account": "b" * 32}])  # the ID changed, «Salva» of the sheet not
    members.changed.emit()
    asked, seen = [], []
    monkeypatch.setattr(mw, "resolve_unsaved", lambda e, parent: asked.append(e) or e.save_changes() or True)
    monkeypatch.setattr(mw.PublishDialog, "exec", lambda dialog: seen.append(dialog.diff) and False)
    window.publish()
    assert asked == [editor] and seen and seen[0]  # saved when asked: the change is there to publish
    assert team.get("members")[0]["account"] == "b" * 32
    monkeypatch.setattr(mw, "resolve_unsaved", lambda e, parent: False)  # cancelled: nothing is published
    editor.start_editing()
    members = editor.findChild(MembersWidget)  # the page was rebuilt when saved
    members.set_value([{"name": "Mario Rossi", "account": "c" * 32}])
    members.changed.emit()
    seen.clear()
    window.publish()
    assert not seen
    editor.cancel_changes(ask=False)
    p.save()
    window.close()


def test_the_changes_not_published_are_discarded_back_to_the_last_version(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria")
    p.save()
    p.publish("Prima versione", "Prova <prova@example.com>")
    team.set("name", "Localizzazione")
    p.update(team)
    added = p.new_element("team", name="Freno")
    p.save()
    assert p.has_unpublished_changes()
    p.discard_unpublished()
    reopened = Project.open(tmp_path / "p")
    assert reopened.model.get(team.uuid).get("name") == "Odometria" and reopened.model.get(added.uuid) is None
    assert not reopened.has_unpublished_changes()


def test_receive_asks_first_to_publish_or_discard_the_changes_not_published(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import main_window as mw
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria")
    p.save()
    p.publish("Prima versione", "Prova <prova@example.com>")
    window = mw.MainWindow()
    window._set_project(p)
    assert window._ready_to_receive()  # nothing to publish: received at once
    team.set("name", "Localizzazione")
    p.update(team)
    p.save()

    shown = []

    def answer(text):
        def click(box):  # the changes not published are shown, then a button is pressed
            shown.append(box.diff)
            buttons = {"Pubblica…": box.publish_button, "Scarta le modifiche": box.discard_button}
            buttons[text].click() if text in buttons else box.reject()
        monkeypatch.setattr(mw.UnpublishedDialog, "exec", click)

    answer("Annulla")
    assert not window._ready_to_receive() and p.has_unpublished_changes()
    assert any(c.uuid == team.uuid for c in shown[0].changes)  # the team renamed, among the changes shown
    published = []
    monkeypatch.setattr(mw.PublishDialog, "exec", lambda d: published.append(d.diff) or False)
    answer("Pubblica…")
    assert not window._ready_to_receive() and published and published[0]  # not published: not received
    answer("Scarta le modifiche")
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Yes)
    assert window._ready_to_receive()
    assert window.project is not p and window.project.model.get(team.uuid).get("name") == "Odometria"
    assert not window.project.has_unpublished_changes()
    window.close()


def test_the_members_of_a_read_only_team_sheet_ask_to_switch_to_edit_mode(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import element_editor, team_members
    from arcadia_tool.ui.main_window import MainWindow
    p = Project.create(tmp_path / "p", "Prova")
    team = p.new_element("team", name="Odometria", members=[{"name": "Mario Rossi", "account": "0" * 31 + "2"}])
    p.save()
    window = MainWindow()
    window._set_project(p)
    window._open_finding(team.uuid)
    editor = window.editors[team.uuid]
    assert not editor.editing
    asked = []

    def answer(reply):
        monkeypatch.setattr(element_editor.QMessageBox, "question",
                            lambda *a, **k: asked.append(True) or reply)
    opened = []

    def fake_exec(dialog):  # the ID of the account written, «Salva» of the window of the member
        opened.append(True)
        dialog.account.set_text("1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0f9")
        dialog._accept()
        return dialog.result()
    monkeypatch.setattr(team_members.MemberDialog, "exec", fake_exec)
    answer(element_editor.QMessageBox.No)
    members = editor.findChild(MembersWidget)
    members.edit_member(0)  # the pencil, or a double click on the row
    assert asked and not opened and members.value()[0]["account"] == "0" * 31 + "2"  # nothing changed only here
    assert members.add_member() is None and len(members.value()) == 1
    answer(element_editor.QMessageBox.Yes)
    members.edit_member(0)
    app.processEvents()  # the sheet switches to edit mode
    assert editor.editing
    members = editor.findChild(MembersWidget)
    members.edit_member(0)
    assert editor.dirty
    editor.save_changes()
    assert team.get("members")[0]["account"] == "1f2e3d4c5b6a49788695a4b3c2d1e0f9" and not editor.dirty
    window.close()


def test_a_member_working_on_more_pcs_has_an_id_for_each(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from arcadia_tool.model.teams import access_denied, account_ids, accounts_value, is_da_member, memberships
    from arcadia_tool.ui import team_members
    office, laptop, other = "a" * 32, "b" * 32, "c" * 32
    p = Project.create(tmp_path / "p", "Prova")
    da = p.new_element("team", name="DA", design_authority=True,
                       members=[{"name": "Anna Bianchi", "account": [office, laptop]}])
    p.new_element("team", name="Odometria", members=[{"name": "Mario Rossi", "account": other}])
    p.save()
    reopened = Project.open(tmp_path / "p")  # kept as written: a text for one ID, a list for more
    rows = {r["name"]: r for t in reopened.model.of_kind("team") for r in t.get("members")}
    assert rows["Anna Bianchi"]["account"] == [office, laptop] and rows["Mario Rossi"]["account"] == other
    for pc in (office, laptop):  # from either PC: the same member of the DA
        user = SimpleNamespace(id=pc, full_name="Anna Bianchi")
        assert access_denied(reopened.model, user) is None and is_da_member(reopened.model, user)
        assert [t.get("name") for t, _row in memberships(reopened.model, user)] == ["DA"]
    assert access_denied(reopened.model, SimpleNamespace(id="d" * 32, full_name="Anna Bianchi"))
    assert account_ids({"account": f"{office.upper()}, {laptop}; {office}"}) == [office, laptop]
    assert accounts_value([office]) == office and accounts_value([office, laptop]) == [office, laptop]
    assert accounts_value([]) == ""

    # The window of the member: a list of IDs, added (with or without dashes) and removed; invalid ones and those of
    # others refused.
    warned = []
    monkeypatch.setattr(team_members.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    dialog = team_members.MemberDialog(rows["Anna Bianchi"], [rows["Mario Rossi"]])
    accounts = dialog.account
    assert accounts.ids() == [office, laptop] and not accounts.add_button.isEnabled()
    accounts.list.setCurrentRow(1)
    accounts.remove_button.click()
    assert accounts.ids() == [office]
    accounts.entry.setText("non-un-id")
    accounts.add_button.click()
    assert "«non-un-id» non è un ID valido" in warned[-1] and accounts.entry.text() == "non-un-id"
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    accounts.entry.setText(laptop.upper())
    QTest.keyClick(accounts.entry, Qt.Key_Return)  # Invio: the ID added, the window still open
    assert accounts.ids() == [office, laptop] and accounts.entry.text() == "" and not dialog.result()
    accounts.entry.setText(office)  # already in the list: once
    accounts.add()
    assert accounts.ids() == [office, laptop]
    accounts.entry.setText("1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0f8")  # written, not added: taken by «Salva»
    dialog._accept()
    assert dialog.result() and dialog.row["account"] == [office, laptop, "1f2e3d4c5b6a49788695a4b3c2d1e0f8"]
    dialog = team_members.MemberDialog(rows["Anna Bianchi"], [rows["Mario Rossi"]])
    dialog.account.set_text(f"{office}\nnon-un-id\n{other}")
    dialog._accept()
    assert "L'ID «non-un-id» non è valido" in warned[-1] and not dialog.result()
    dialog.account.set_text(f"{office}\n{other}")
    dialog._accept()
    assert "è già di un altro membro del team (Mario Rossi)" in warned[-1]
    third = "1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0f9"
    dialog.account.set_text(f"{office}\n{laptop}\n{third}\n{office}")
    dialog._accept()
    assert dialog.result() and dialog.row["account"] == [office, laptop, "1f2e3d4c5b6a49788695a4b3c2d1e0f9"]
    single = team_members.MemberDialog(rows["Mario Rossi"], [])
    single._accept()
    assert single.row["account"] == other  # one ID: a text, as before

    # The table of the sheet: the first ID and how many more, all of them in the tooltip.
    members = MembersWidget(reopened.model)
    members.set_value([rows["Anna Bianchi"], rows["Mario Rossi"]])
    assert members.table.item(0, 3).text() == f"{office[:8]}… (+1)"
    assert members.table.item(0, 3).toolTip() == f"{office}\n{laptop}"
    assert members.table.item(1, 3).text() == f"{other[:8]}…"

    # The comparison of the versions and the sheets in Excel: the IDs as a list.
    from arcadia_tool.documents.values import table_rows
    from arcadia_tool.model.schema import KINDS_BY_NAME
    from arcadia_tool.ui.diff_view import _cell_text
    field = KINDS_BY_NAME["team"].field("members")
    column = next(c for c in field.columns if c.name == "account")
    assert _cell_text(None, column, rows["Anna Bianchi"]) == f"{office}, {laptop}"
    assert table_rows(reopened.model, reopened.model.get(da.uuid), field)[0][3] == f"{office}, {laptop}"


def srs_project(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    da = p.new_element("team", name="RFI", design_authority=True, members=[{"name": "Anna", "account": ANNA}])
    domain = p.new_element("domain", name="Localizzazione")
    section = p.new_element("requirement", id="3.8.1", item_type="Sezione", title="Una sezione")
    clause = p.new_element("requirement", id="3.8.1.1", item_type="Requisito", parent=section.uuid, text="Una clausola",
                           category=["Bordo"], primary_domain=domain.uuid)
    other = p.new_element("requirement", id="5.1.1.1", item_type="Requisito", text="Un'altra", category=["Terra"])
    p.save()
    return p, da, domain, section, clause, other


def test_only_the_design_authority_changes_the_srs_items(app, tmp_path, monkeypatch):
    from arcadia_tool.model.teams import edit_denied
    from arcadia_tool.ui import main_window as mw

    p, da, domain, section, clause, other = srs_project(tmp_path)
    mario, anna = user("Mario Rossi", MARIO), user("Anna", ANNA)
    assert "voci SRS" in edit_denied(p.model, mario, "requirement")
    assert "voci SRS" in edit_denied(p.model, mario, "requirement", "primary_domain")
    assert edit_denied(p.model, anna, "requirement") is None
    window = mw.MainWindow()
    window._set_project(p)
    window.user = mario
    window._refresh_state()
    mode = window.srs_edit_mode
    # The catalogue: the edit mode cannot be switched on, nothing can be deleted, the domains not allocated.
    window.open_srs_reader()
    reader = window.reader
    assert not reader.edit_mode_button.isEnabled() and "voci SRS" in reader.edit_mode_button.toolTip()
    mode.set_enabled(True)
    assert not mode.enabled and not reader.edit_mode_button.isChecked()
    assert reader.delete_button.isHidden()  # «Elimina selezionate»: only for the Design Authority
    assert not any(a.text().startswith("Elimina") for a in reader.context_menu(clause).actions())
    assert reader.layout().indexOf(reader.commands) == 0  # the commands: a group above the one of the title
    reader.reveal(clause.uuid)
    reader.delete_selected()
    assert p.model.get(clause.uuid) is clause
    said = []
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: said.append(a[2]))
    reader.run_action(section.uuid, "domains")
    assert "voci SRS" in said[-1]
    menu = {a.text(): a for a in reader.context_menu(section).actions()}
    assert not menu["Alloca ai domini funzionali…"].isEnabled()
    # From the tree and the project: not deleted, not imported, not cleaned.
    window.tree.delete_all_requirements()
    assert p.model.get(clause.uuid) is clause and "voci SRS" in said[-1]
    window.import_srs()
    window.clean_project()
    assert len(said) >= 4 and p.model.get(clause.uuid) is clause
    # The sheet of an item: read-only, also the fields of the analysis.
    window._open_finding(clause.uuid)
    editor = window.editors[clause.uuid]
    assert editor.read_only and not editor.edit_mode_button.isEnabled()
    assert not editor.widgets["primary_domain"].property("keepEnabled")
    # The Design Authority: as before; a user who is not any more: the edit mode goes off.
    window.user = anna
    window._refresh_state()
    assert reader.edit_mode_button.isEnabled() and not reader.delete_button.isHidden()
    assert any(a.text().startswith("Elimina") for a in reader.context_menu(clause).actions())
    mode.set_enabled(True)
    assert mode.enabled
    window.user = mario
    window._refresh_state()
    assert not mode.enabled and reader.delete_button.isHidden()
    window._set_project(None)
    window.close()


def test_a_double_click_on_an_srs_item_in_the_tree_goes_to_it_in_the_catalogue(app, tmp_path):
    from arcadia_tool.ui import main_window as mw

    p, da, domain, section, clause, other = srs_project(tmp_path)
    window = mw.MainWindow()
    window._set_project(p)
    tree = window.tree
    tree.tree.setCurrentItem(tree._items[clause.uuid])  # a click: only selected
    assert window.reader is None or window.pages.currentWidget() is not window.reader
    tree.tree.itemDoubleClicked.emit(tree._items[clause.uuid], 0)
    reader = window.reader
    assert reader is not None and window.pages.currentWidget() is reader
    window.show()  # the rows are laid out once it is visible: the item is reached then
    assert reader.selected_elements() == [clause]
    assert clause.uuid not in window.editors  # not its sheet
    # Another chapter, hidden by the search: the catalogue goes there and shows it.
    reader.search.setText("clausola")
    assert all(e.uuid != other.uuid for e in reader.model.elements)
    tree.tree.itemDoubleClicked.emit(tree._items[other.uuid], 0)
    assert reader.selected_elements() == [other] and reader.search.text() == ""
    # A double click in the catalogue, and the links to an item, still open its sheet.
    window._open_from_reader(clause.uuid)
    assert window.pages.currentWidget() is window.editors[clause.uuid]
    window._set_project(None)
    window.close()



def test_the_members_ticked_in_the_teams_are_those_who_change_the_main_branch(app, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from arcadia_tool.model.teams import MAIN_PUSH, main_denied, member_rows
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui import team_members

    p = Project.create(tmp_path / "p", "Prova")
    da = p.new_element("team", name="DA", design_authority=True, members=[{"name": "Anna Bianchi", "account": ANNA}])
    team = p.new_element("team", name="Odometria", members=[{"name": "Mario Rossi", "account": MARIO}])
    anna, mario = user("Anna Bianchi", ANNA), user("Mario Rossi", MARIO)
    # No one ticked: the Design Authority, named in the message with what to do.
    assert main_denied(p.model, anna, "main") is None
    denied = main_denied(p.model, mario, "main")
    assert "Solo la Design Authority" in denied and "Anna Bianchi" in denied and "eseguire l'operazione" in denied
    # Mario ticked in the table of the sheet of his team: only who is ticked, also against the DA.
    editor = ElementEditor()
    editor.edit(p, team, editing=True)
    members = editor.widget().findChildren(MembersWidget)[0]
    assert members.table.horizontalHeaderItem(team_members.MAIN).text() == "Ramo principale"
    members.table.item(0, team_members.MAIN).setCheckState(Qt.Checked)
    assert members.rows[0][MAIN_PUSH] is True
    editor.save_changes()
    assert member_rows(team)[0][MAIN_PUSH] is True
    assert main_denied(p.model, mario, "main") is None
    denied = main_denied(p.model, anna, "main")
    assert "Solo i membri indicati" in denied and "Mario Rossi" in denied
    # The window of a member: the same tick.
    dialog = team_members.MemberDialog(member_rows(team)[0], [])
    assert dialog.main_push.isChecked()
    dialog.main_push.setChecked(False)
    dialog._accept()
    assert MAIN_PUSH not in dialog.row
    dialog.deleteLater()
    # Who may not: «Pubblica» on the main branch is an error, nothing is published.
    p.save()
    p.publish("Prima versione", "Prova <prova@example.com>")
    window = mw.MainWindow()
    window._set_project(p)
    window.user = anna
    assert p.main_branch() == p.current_branch()
    errors, opened = [], []
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a, **k: errors.append(a[2]))
    monkeypatch.setattr(mw.PublishDialog, "exec", lambda d: opened.append(d) and False)
    window.publish()
    assert not opened and "Non hai il permesso di pubblicare" in errors[-1] and "Mario Rossi" in errors[-1]
    window.user = mario
    window.publish()
    assert opened  # he may
    window._set_project(None)
    window.close()
    editor.deleteLater()
