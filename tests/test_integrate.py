"""Rami › Integra: a branch integrated into the one in use by ATLAS (not by Git): field by field, the automatic
identifiers renumbered, the sheets kept in step; branches with no version in common refused; the merges made outside
ATLAS recognized."""
import pytest
from PySide6.QtWidgets import QApplication

from arcadia_tool.model.schema import KINDS_BY_NAME
from arcadia_tool.storage.merge import THEIRS
from arcadia_tool.storage.project import ATLAS_MERGE, Project, Receive, made_by_atlas

AUTHOR = "Prova <prova@example.com>"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def start(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    t1, t2, t3 = (p.new_element("team", name=n) for n in ("RFI", "FBK", "UniMiB"))
    domain = p.new_element("domain", name="Odometria")
    domain.set("team", t1.uuid)
    p.update(domain)  # the team lists it (kept in step)
    p.save()
    p.publish("v1", AUTHOR)
    return p, (t1, t2, t3), domain


def reopen(p):
    p.close()
    return Project.open(p.path)


def move(p, uuid, team):
    domain = p.model.get(uuid)
    previous = domain.copy()
    domain.set("team", team)
    p.update(domain, previous)


def test_a_branch_is_integrated_field_by_field_with_the_sheets_kept_in_step(tmp_path):
    p, (t1, t2, t3), domain = start(tmp_path)
    v1 = p.repository.head()
    p.switch_branch("att/T2", v1)
    p = reopen(p)
    move(p, domain.uuid, t2.uuid)  # the domain to FBK: FBK lists it
    p.new_element("domain", name="Radio")  # DF02 on this branch
    p.save()
    branch_head = p.publish("odometria a FBK", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    move(p, domain.uuid, t3.uuid)  # meanwhile on master: to UniMiB
    p.new_element("domain", name="Frenatura")  # DF02 on master too
    p.save()
    p.publish("odometria a UniMiB", AUTHOR)
    receive = p.prepare_integration("att/T2", branch_head)
    assert receive.state == Receive.MERGE and receive.into == "master" and not receive.foreign
    conflict = next(c for c in receive.result.conflicts if c.field == "team")
    result = p.apply_receive(receive, {conflict.key: THEIRS}, AUTHOR)  # the choice: FBK
    assert result.resolved and result.renumbered  # one of the two DF02 renumbered
    p = reopen(p)
    teams = {t.get("name"): t for t in p.model.of_kind("team")}
    assert p.model.get(domain.uuid).get("team") == teams["FBK"].uuid
    assert domain.uuid in teams["FBK"].get("domains")
    assert domain.uuid not in (teams["UniMiB"].get("domains") or [])  # kept in step: Git would have left it
    assert domain.uuid not in (teams["RFI"].get("domains") or [])
    assert sorted(d.get("id") for d in p.model.of_kind("domain")) == ["DF01", "DF02", "DF03"]
    last = p.versions()[0]
    assert last.is_merge and made_by_atlas(last) and ATLAS_MERGE in last.message
    assert last.title == "Integrazione del ramo «att/T2» in «master» (1 versione)"
    assert p.current_branch() == "master" and not p.has_unpublished_changes()


def test_a_branch_ahead_is_taken_as_it_is_and_one_already_in_is_up_to_date(tmp_path):
    p, teams, domain = start(tmp_path)
    p.switch_branch("att/T3", p.repository.head())
    p = reopen(p)
    p.new_element("domain", name="Radio")
    p.save()
    ahead = p.publish("radio", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    receive = p.prepare_integration("att/T3", ahead)
    assert receive.state == Receive.FAST_FORWARD
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert p.repository.head() == ahead and p.current_branch() == "master"
    assert p.prepare_integration("att/T3", ahead).state == Receive.UP_TO_DATE
    p.new_element("domain", name="Non pubblicato")
    assert p.prepare_integration("att/T3", ahead).state == Receive.PUBLISH_FIRST


def test_branches_with_no_version_in_common_are_not_integrated(tmp_path):
    p, teams, domain = start(tmp_path)
    other, *_ = start(tmp_path / "altro")  # a project created apart
    heads = p.repository.fetch(str(other.path))
    receive = p.prepare_integration("master", heads["master"])
    assert receive.state == Receive.UNRELATED and receive.result is None


def test_a_merge_made_outside_atlas_is_recognized(tmp_path):
    p, teams, domain = start(tmp_path)
    v1 = p.repository.head()
    p.switch_branch("att/git", v1)
    p = reopen(p)
    p.new_element("domain", name="Radio")
    p.save()
    side = p.publish("radio", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    p.new_element("domain", name="Frenatura")
    p.save()
    p.publish("frenatura", AUTHOR)
    # A merge as Git makes it (a second parent, its own message, no renumbering): then on a branch.
    git_merge = p.repository.save_version("Merge branch 'att/git' into master", AUTHOR, p._version_files(),
                                          merged=side)
    p.switch_branch("att/T1", v1)
    p = reopen(p)
    receive = p.prepare_integration("master", git_merge)
    assert [v.sha for v in receive.foreign] == [git_merge]
    assert not made_by_atlas(receive.foreign[0])


def test_the_window_of_the_branches_integrates_and_only_the_da_into_main(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.branches import BranchesDialog
    from arcadia_tool.ui.receive import ReceiveDialog

    p, (t1, t2, t3), domain = start(tmp_path)
    v1 = p.repository.head()
    p.switch_branch("att/T2", v1)
    p = reopen(p)
    p.new_element("domain", name="Radio")
    p.save()
    p.publish("radio", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    p.new_element("domain", name="Frenatura")
    p.save()
    p.publish("frenatura", AUTHOR)
    # The Design Authority: RFI, with Anna. Mario (FBK) may not integrate into master.
    rfi = p.model.get(t1.uuid)
    rfi.set("design_authority", True)
    rfi.set("members", [{"name": "Anna Bianchi", "account": "a" * 32}])
    p.update(rfi)
    p.save()
    p.publish("DA", AUTHOR)
    mario = SimpleNamespace(id="b" * 32, full_name="Mario Rossi")
    anna = SimpleNamespace(id="a" * 32, full_name="Anna Bianchi")
    dialog = BranchesDialog(p, {}, mario)
    rows = {dialog.table.item(r, 0).text(): r for r in range(dialog.table.rowCount())}
    dialog.table.selectRow(rows["att/T2"])
    assert not dialog.integrate_button.isEnabled() and "Solo la Design Authority" in dialog.integrate_button.toolTip()
    dialog = BranchesDialog(p, {}, anna)
    dialog.table.selectRow(rows["att/T2"])
    assert dialog.integrate_button.isEnabled()
    dialog.integrate()
    assert dialog.request[:2] == ("integrate", "att/T2")
    # The main window: the window of the merge, applied; the project opened again on master.
    window = mw.MainWindow()
    window._set_project(p)
    window.open_project = lambda path, confirmed=False, **_kw: window._set_project(Project.open(path))
    window.user = SimpleNamespace(id="b" * 32, full_name="Mario Rossi", email="m@x.it", username="mario")
    assert window.branch_request(dialog.request) is None  # Mario: not into master, also from here
    window.user = SimpleNamespace(id="a" * 32, full_name="Anna Bianchi", email="a@x.it", username="anna")

    def run(d):  # the preparation in its thread, then «Ricevi» (here: Integra)
        d.start()
        d.worker.wait(20000)
        app.processEvents()
        assert d.receive.state == Receive.MERGE and "Integrazione del ramo «att/T2»" in d.windowTitle() + \
            d.findChildren(type(d.status))[0].text()
        d.apply()
        return True
    monkeypatch.setattr(ReceiveDialog, "exec", run)
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    result = window.branch_request(dialog.request)
    assert result.applied and window.project.current_branch() == "master"
    assert sorted(d.get("name") for d in window.project.model.of_kind("domain")) == ["Frenatura", "Odometria",
                                                                                     "Radio"]
    assert made_by_atlas(window.project.versions()[0])
    window._set_project(None)
    window.close()


def diverged(tmp_path):
    """master and att/T2 from v1: the domain moved to FBK on the branch, to UniMiB on master (a conflict), and a new
    domain on each side (merged by itself)."""
    p, (t1, t2, t3), domain = start(tmp_path)
    p.switch_branch("att/T2", p.repository.head())
    p = reopen(p)
    move(p, domain.uuid, t2.uuid)
    p.new_element("domain", name="Radio")
    p.save()
    branch_head = p.publish("odometria a FBK", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    move(p, domain.uuid, t3.uuid)
    p.new_element("domain", name="Frenatura")
    p.save()
    p.publish("odometria a UniMiB", AUTHOR)
    return p, (t1, t2, t3), domain, branch_head


def test_the_window_of_the_integration_previews_the_result_and_can_be_cancelled(app, tmp_path):
    from arcadia_tool.ui.receive import ReceiveDialog

    p, (t1, t2, t3), domain, branch_head = diverged(tmp_path)
    head = p.repository.head()
    dialog = ReceiveDialog(p, {}, AUTHOR, integrate=("att/T2", branch_head))
    dialog.start()
    dialog.worker.wait(20000)
    app.processEvents()
    assert dialog.apply_button.text() == "Integra" and dialog.close_button.text() == "Annulla integrazione"
    # The versions received: one per row (title, author, date), newest first, under their count.
    incoming = dialog.receive.incoming
    rows = [dialog.version_list.topLevelItem(i) for i in range(dialog.version_list.topLevelItemCount())]
    assert incoming and [r.text(0) for r in rows] == [v.title for v in incoming]
    assert all(r.text(1) and r.text(2) for r in rows) and not dialog.version_list.isHidden()
    assert dialog.versions.text() == f"{len(incoming)} {'versione ricevuta' if len(incoming) == 1 else 'versioni ricevute'}"
    # Merged by itself: Radio (from the branch) is in the preview; only the team of the domain is left to choose.
    assert dialog.conflicts.rowCount() == 1 and "team" in dialog.conflicts.item(0, 0).text().lower()
    names = lambda d: {e.get("name") for e in merged_domains(d)}
    assert names(dialog) == {"Odometria", "Frenatura", "Radio"}
    assert "Unite automaticamente" in dialog.conflicts_title.text() and "1 conflitto" in dialog.conflicts_title.text()
    assert not dialog.apply_button.isEnabled()
    # The choice is followed by the preview: the domain goes to FBK.
    combo = dialog.conflicts.cellWidget(0, 3)
    combo.setCurrentIndex(combo.findData(THEIRS))
    dialog._refresh_preview()
    assert next(e for e in merged_domains(dialog) if e.uuid == domain.uuid).get("team") == t2.uuid
    assert dialog.apply_button.isEnabled()
    # Annulla integrazione: nothing changes.
    dialog.reject()
    assert not dialog.applied and p.repository.head() == head and not p.has_unpublished_changes()
    assert p.model.get(domain.uuid).get("team") == t3.uuid


def merged_domains(dialog):
    from arcadia_tool.storage.merge import merged_model
    return merged_model(dialog.preview_result.files).of_kind("domain")


def test_the_branch_integrated_is_deleted_here_and_on_the_remote_with_the_next_send(tmp_path):
    from dulwich import porcelain
    from arcadia_tool.storage.project import ProjectError
    from arcadia_tool.storage.repository import remote_branches

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    p, (t1, t2, t3), domain, branch_head = diverged(tmp_path)
    p.repository.set_remote_url(url)
    for name in ("att/T2", "master"):  # both branches on the server
        p.switch_branch(name)
        p = reopen(p)
        p.set_local_settings(branch=name)
        p.push()
    receive = p.prepare_integration("att/T2", branch_head)
    conflict = next(c for c in receive.result.conflicts if c.field == "team")
    p.apply_receive(receive, {conflict.key: THEIRS}, AUTHOR)
    p = reopen(p)
    with pytest.raises(ProjectError):
        p.delete_integrated_branch("master")  # the branch in use
    assert p.delete_integrated_branch("att/T2")
    assert "att/T2" not in p.repository.local_heads() and p.branches_to_delete() == ["att/T2"]
    assert "att/T2" not in [b.name for b in p.branches()]  # gone already, also before the send
    assert "att/T2" in remote_branches(url)
    p.push()
    assert p.deleted_branches == ["att/T2"] and not p.branches_to_delete()
    assert set(remote_branches(url)) == {"master"}


def test_a_branch_with_versions_sent_meanwhile_is_not_deleted_from_the_remote(tmp_path):
    from dulwich import porcelain
    from arcadia_tool.storage.project import clone_project
    from arcadia_tool.storage.repository import remote_branches

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    p, teams, domain = start(tmp_path)
    p.repository.set_remote_url(url)
    p.set_local_settings(branch="master")
    p.push()
    p.switch_branch("att/T3", p.repository.head())
    p = reopen(p)
    p.set_local_settings(branch="att/T3")
    p.new_element("domain", name="Radio")
    p.save()
    ahead = p.publish("radio", AUTHOR)
    p.push()
    p.switch_branch("master")
    p = reopen(p)
    p.set_local_settings(branch="master")
    p.apply_receive(p.prepare_integration("att/T3", ahead), None, AUTHOR)
    p = reopen(p)
    assert p.delete_integrated_branch("att/T3")
    # Meanwhile a colleague sends a version to att/T3: it is not integrated, the branch stays on the server.
    colleague = Project.open(clone_project(url, tmp_path / "collega"))
    colleague.switch_branch("att/T3")
    colleague = reopen(colleague)
    colleague.set_local_settings(branch="att/T3")
    colleague.new_element("domain", name="Frenatura")
    colleague.save()
    colleague.publish("frenatura", AUTHOR)
    colleague.push()
    p.repository.set_remote_heads(p.repository.fetch(url))
    p.push()
    assert p.kept_branches == ["att/T3"] and not p.deleted_branches
    assert set(remote_branches(url)) == {"master", "att/T3"} and not p.branches_to_delete()
    colleague.close()


def test_only_the_design_authority_merges_into_the_main_branch_also_when_receiving(app, tmp_path):
    from types import SimpleNamespace
    from dulwich import porcelain
    from arcadia_tool.storage.project import clone_project
    from arcadia_tool.storage.repository import remote_branches
    from arcadia_tool.ui.receive import ReceiveDialog

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    first, (rfi, *_), domain = start(tmp_path)
    da = first.model.get(rfi.uuid)
    da.set("design_authority", True)
    da.set("members", [{"name": "Anna Bianchi", "account": "a" * 32}])
    first.update(da)
    first.save()
    first.publish("DA", AUTHOR)
    first.repository.set_remote_url(url)
    first.set_local_settings(branch="master")
    first.push()
    first.close()
    mario = SimpleNamespace(id="b" * 32, full_name="Mario Rossi")
    anna = SimpleNamespace(id="a" * 32, full_name="Anna Bianchi")
    mine, colleague = (Project.open(clone_project(url, tmp_path / n)) for n in ("mario", "collega"))
    colleague.new_element("domain", name="Frenatura")
    colleague.save()
    colleague.publish("frenatura", AUTHOR)
    colleague.push()
    mine.new_element("domain", name="Radio")
    mine.save()
    mine.publish("radio", AUTHOR)
    assert mine.main_denied(anna) is None and "Solo la Design Authority" in mine.main_denied(mario)

    def receive_as(user):
        dialog = ReceiveDialog(mine, {}, AUTHOR, user=user)
        dialog.start()
        dialog.worker.wait(20000)
        app.processEvents()
        assert dialog.receive.state == Receive.MERGE
        return dialog

    dialog = receive_as(mario)  # Mario, of a team: not merged on master
    assert "Solo la Design Authority" in dialog.status.text()
    assert dialog.apply_button.isHidden() and not dialog.move_button.isHidden()
    head = mine.repository.head()
    dialog.apply()
    assert not dialog.applied and mine.repository.head() == head
    assert not receive_as(anna).apply_button.isHidden()  # Anna, of the DA: the merge is offered
    # Sposta le mie versioni su un nuovo ramo: «radio» on att/mario, to send; master back as on the server.
    mine.move_unsent_to_branch("att/mario")
    mine.close()
    mine = Project.open(mine.path)
    assert mine.current_branch() == "att/mario" and mine.repository.head() == head
    assert mine.repository.local_heads()["master"] == mine.repository.remote_branch_head("master")
    assert [v.title for v in mine.unsent_versions()] == ["radio"]
    mine.push()
    assert set(remote_branches(url)) == {"master", "att/mario"}
    mine.close()
    colleague.close()


def test_on_the_main_branch_a_team_member_publishes_and_sends_only_on_a_new_branch(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from dulwich import porcelain
    from arcadia_tool.storage.repository import remote_branches
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.versions import PublishDialog

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    p, (rfi, *_), domain = start(tmp_path)
    da = p.model.get(rfi.uuid)
    da.set("design_authority", True)
    da.set("members", [{"name": "Anna Bianchi", "account": "a" * 32}])
    p.update(da)
    p.save()
    p.publish("DA", AUTHOR)
    p.repository.set_remote_url(url)
    p.set_local_settings(branch="master")
    p.push()
    mario = SimpleNamespace(id="b" * 32, full_name="Mario Rossi", email="m@x.it", username="mario")
    anna = SimpleNamespace(id="a" * 32, full_name="Anna Bianchi", email="a@x.it", username="anna")
    p.new_element("domain", name="Radio")
    p.save()
    dialog = PublishDialog(p, user=mario)  # Pubblica: on master only the DA; Mario on a new branch
    assert not dialog.on_current.isEnabled() and dialog.on_new.isChecked() and dialog.denied
    dialog = PublishDialog(p, user=anna)
    assert dialog.on_current.isEnabled() and dialog.on_current.isChecked() and not dialog.denied
    # Versions published on master before (e.g. by an older ATLAS): Invia moves them to a new branch first.
    p.publish("radio", AUTHOR)
    window = mw.MainWindow()
    window.user = mario
    window._set_project(p)
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Yes)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", lambda *a, **k: ("att/mario", True))
    monkeypatch.setattr(mw.PushDialog, "exec", lambda d: d.project.push())
    window.send_versions()
    assert window.project.current_branch() == "att/mario"
    assert set(remote_branches(url)) == {"master", "att/mario"}
    repository = window.project.repository  # master as on the server: the version is only on att/mario
    assert repository.local_heads()["master"] == repository.remote_branch_head("master") != repository.head()
    window._set_project(None)
    window.close()


# --- the selective integration ---------------------------------------------------------------------------------------

def two_branches(tmp_path, on_branch, on_master=lambda p: None):
    """master and att/T2 from a common version; on_branch(p), on_master(p) make their changes (and return what they
    want to give back). Returns (project on master, the head of the branch, what they returned)."""
    p, teams, domain = start(tmp_path)
    p.switch_branch("att/T2", p.repository.head())
    p = reopen(p)
    theirs = on_branch(p, teams, domain)
    p.save()
    head = p.publish("sul ramo", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    ours = on_master(p)
    if p.is_modified:
        p.save()
        p.publish("su master", AUTHOR)
    return p, head, theirs, ours


def names(p, kind="domain"):
    return sorted(e.get("name") or e.get("title") for e in p.model.of_kind(kind))


def test_only_the_elements_chosen_come_and_the_rest_can_be_integrated_later(tmp_path):
    def branch(p, teams, domain):
        adr = p.new_element("adr", title="Una decisione", adr_type="Altro / decisione trasversale", status="Proposta")
        other = p.new_element("domain", name="Radio")
        return adr, other

    p, head, (adr, other), _ = two_branches(tmp_path, branch, lambda p: p.new_element("domain", name="Frenatura"))
    before = p.repository.head()
    receive = p.prepare_integration("att/T2", head)
    selection = receive.selection()
    assert {c.uuid for c in selection.diff.changes} == {adr.uuid, other.uuid}  # not what only master has
    receive.only = {adr.uuid}
    result = p.apply_receive(receive, None, AUTHOR)
    assert result.resolved
    p = reopen(p)
    assert names(p, "adr") == ["Una decisione"] and names(p) == ["Frenatura", "Odometria"]
    last = p.versions()[0]
    assert not last.is_merge and last.parents == (before,) and "Integrazione selettiva" in last.title
    assert "att/T2" in last.title and not p.has_unpublished_changes()
    # What was taken is no longer offered; the rest of the branch still comes with a complete integration.
    receive = p.prepare_integration("att/T2", head)
    assert receive.state == Receive.MERGE and {c.uuid for c in receive.selection().diff.changes} == {other.uuid}
    assert not receive.result.conflicts
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert names(p) == ["Frenatura", "Odometria", "Radio"] and names(p, "adr") == ["Una decisione"]


def test_a_branch_ahead_taken_in_part_is_not_fast_forwarded(tmp_path):
    def branch(p, teams, domain):
        return p.new_element("domain", name="Radio"), p.new_element("domain", name="Frenatura")

    p, head, (radio, _other), _ = two_branches(tmp_path, branch)
    receive = p.prepare_integration("att/T2", head)
    assert receive.state == Receive.FAST_FORWARD
    receive.only = {radio.uuid}
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert names(p) == ["Odometria", "Radio"] and p.repository.head() != head and not p.versions()[0].is_merge


def test_what_is_linked_comes_with_the_selection(tmp_path):
    from arcadia_tool.storage.selective import required

    def branch(p, teams, domain):
        radio = p.new_element("domain", name="Radio")
        adr = p.new_element("adr", title="Radio", adr_type="Ridefinizione dello scopo del dominio", domain=radio.uuid,
                            status="Proposta")
        message = p.new_element("message", subject=adr.uuid, text="Ciao")
        alone = p.new_element("domain", name="Solo")
        return radio, adr, message, alone

    p, head, (radio, adr, message, alone), _ = two_branches(tmp_path, branch)
    needs = p.prepare_integration("att/T2", head).selection().needs
    assert required(needs, [adr.uuid]) == {adr.uuid, radio.uuid, message.uuid}  # what it refers to, and its messages
    assert required(needs, [alone.uuid]) == {alone.uuid}


def test_a_reallocation_applied_brings_the_move_of_its_items(tmp_path):
    from arcadia_tool.model.adr import approve_reallocation
    from arcadia_tool.storage.selective import required

    p, teams, domain = start(tmp_path)
    other = p.new_element("domain", name="Radio")
    clause = p.new_element("requirement", id="3.8.1.1", item_type="Requisito", primary_domain=domain.uuid)
    far = p.new_element("requirement", id="3.8.1.2", item_type="Requisito", primary_domain=domain.uuid)
    p.save()
    p.publish("voci", AUTHOR)
    p.switch_branch("att/T2", p.repository.head())
    p = reopen(p)
    decision = p.new_element("adr", title="Sposta", adr_type="Riallocazione di sezione o clausola", status="Proposta",
                             realloc_item=[clause.uuid], primary_proposed=other.uuid)
    approve_reallocation(p, decision)
    open_one = p.new_element("adr", title="Aperta", adr_type="Riallocazione di sezione o clausola", status="Proposta",
                             realloc_item=[far.uuid], primary_proposed=other.uuid)
    moved = p.model.get(far.uuid)
    moved.set("text", "cambiata")
    p.update(moved)
    p.save()
    head = p.publish("sposta", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    p.new_element("team", name="Altro")
    p.save()
    p.publish("master", AUTHOR)
    receive = p.prepare_integration("att/T2", head)
    needs = receive.selection().needs
    assert clause.uuid in required(needs, [decision.uuid])  # the decision and its effect go together
    assert far.uuid not in required(needs, [open_one.uuid])  # not applied: an SRS item only changed does not come
    receive.only = required(needs, [decision.uuid])
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert p.model.get(clause.uuid).get("primary_domain") == other.uuid


def test_identifiers_used_twice_and_a_later_complete_integration(tmp_path):
    kind = "Altro / decisione trasversale"

    def branch(p, teams, domain):
        return p.new_element("adr", title="Dal ramo", adr_type=kind, status="Proposta")

    def master(p):
        return p.new_element("adr", title="Da master", adr_type=kind, status="Proposta")

    p, head, adr, here = two_branches(tmp_path, branch, master)
    assert adr.get("id") == here.get("id")  # the same ID, two ADR
    receive = p.prepare_integration("att/T2", head)
    receive.only = {adr.uuid}
    result = p.apply_receive(receive, None, AUTHOR)
    assert result.renumbered and result.renumbered[0][0] == adr.uuid  # into master: what is approved keeps its number
    p = reopen(p)
    assert p.model.get(here.uuid).get("id") == here.get("id") and p.model.get(adr.uuid).get("id") != here.get("id")
    final = p.model.get(adr.uuid).get("id")
    assert not p.prepare_integration("att/T2", head).selection().diff.changes  # nothing left: not «changed» by its number
    receive = p.prepare_integration("att/T2", head)
    assert not receive.result.conflicts  # the same ID on the two branches: nothing to choose
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert len({a.get("id") for a in p.model.of_kind("adr")}) == 2


def test_the_sheets_kept_in_step_follow_an_element_taken_alone(tmp_path):
    def branch(p, teams, domain):
        move(p, domain.uuid, teams[1].uuid)  # the domain to FBK: FBK lists it (the team is not taken)

    p, head, _none, _ = two_branches(tmp_path, branch)
    domain = next(d for d in p.model.of_kind("domain"))
    teams = {t.get("name"): t for t in p.model.of_kind("team")}
    receive = p.prepare_integration("att/T2", head)
    receive.only = {domain.uuid}
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    teams = {t.get("name"): t for t in p.model.of_kind("team")}
    assert domain.uuid in teams["FBK"].get("domains") and domain.uuid not in (teams["RFI"].get("domains") or [])


def test_a_conflict_of_an_element_chosen_is_chosen_there(tmp_path):
    def branch(p, teams, domain):
        move(p, domain.uuid, teams[1].uuid)

    def master(p):
        d = p.model.of_kind("domain")[0]
        t = next(t for t in p.model.of_kind("team") if t.get("name") == "UniMiB")
        move(p, d.uuid, t.uuid)

    p, head, _none, _ = two_branches(tmp_path, branch, master)
    domain = p.model.of_kind("domain")[0]
    receive = p.prepare_integration("att/T2", head)
    assert domain.uuid in {c.uuid for c in receive.selection().diff.changes}  # listed, with the value it would have
    receive.only = {domain.uuid}
    conflict = next(c for c in receive.merge().conflicts if c.field == "team")
    assert not p.apply_receive(receive, None, AUTHOR).resolved  # not chosen: nothing is written
    p.apply_receive(receive, {conflict.key: THEIRS}, AUTHOR)
    p = reopen(p)
    assert p.model.of_kind("domain")[0].get("team") == next(t.uuid for t in p.model.of_kind("team") if t.get("name") == "FBK")


def test_a_removal_comes_only_with_its_tick_and_not_if_still_used(tmp_path):
    from arcadia_tool.diff.semantic import REMOVED

    p, teams, domain = start(tmp_path)
    free = p.new_element("domain", name="Libero")
    used = p.new_element("domain", name="Usato")
    p.save()
    p.publish("due domini", AUTHOR)
    p.switch_branch("att/T2", p.repository.head())
    p = reopen(p)
    p.delete_element(free.uuid)
    p.delete_element(used.uuid)
    p.save()
    head = p.publish("via", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    function = p.new_element("system_function", name="Rileva", domain=used.uuid)
    p.save()
    p.publish("usa", AUTHOR)
    receive = p.prepare_integration("att/T2", head)
    selection = receive.selection()
    assert {c.change for c in selection.diff.changes} == {REMOVED}
    assert list(selection.blocked) == [used.uuid] and p.model.label(function) in selection.blocked[used.uuid][0]
    receive.only = {free.uuid}
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert names(p) == ["Odometria", "Usato"]


def test_the_destination_marks_what_changes_and_what_goes_away(app, tmp_path):
    from arcadia_tool.storage.selective import integration_selection
    from arcadia_tool.ui.receive import DestinationView

    p, teams, domain = start(tmp_path)
    gone = p.new_element("domain", name="Via")
    p.save()
    p.publish("v2", AUTHOR)
    p.switch_branch("att/T2", p.repository.head())
    p = reopen(p)
    current = p.model.get(domain.uuid)
    before = current.copy()
    current.set("name", "Odometria nuova")
    p.update(current, before)
    p.delete_element(gone.uuid)
    p.save()
    head = p.publish("ramo", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    p.new_element("team", name="Altro")
    p.save()
    p.publish("master", AUTHOR)
    receive = p.prepare_integration("att/T2", head)
    view = DestinationView(receive.selection(), "master")
    assert view.rows[gone.uuid].text(1) == "" and not view.rows[gone.uuid].font(0).strikeOut()  # not ticked: as it is
    view.show_chosen({gone.uuid, domain.uuid})
    assert view.rows[gone.uuid].text(1) and view.rows[gone.uuid].font(0).strikeOut()
    assert view.rows[domain.uuid].text(1) and "1 modificati · 1 rimossi" in view.summary.text()
    view.search.setText("via")
    assert view.rows[domain.uuid].isHidden() and not view.rows[gone.uuid].isHidden()
    p.close()


def test_the_window_of_the_selective_integration(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.receive import ReceiveDialog

    def branch(p, teams, domain):
        radio = p.new_element("domain", name="Radio")
        adr = p.new_element("adr", title="Radio", adr_type="Ridefinizione dello scopo del dominio", domain=radio.uuid,
                            status="Proposta")
        item = p.new_element("requirement", id="9.1.1.1", item_type="Requisito", text="Nuova")
        return radio, adr, item

    p, head, (radio, adr, item), _ = two_branches(tmp_path, branch, lambda p: p.new_element("domain", name="Frenatura"))
    rfi = next(t for t in p.model.of_kind("team") if t.get("name") == "RFI")
    rfi.set("design_authority", True)
    rfi.set("members", [{"name": "Anna", "account": "a" * 32}])
    p.update(rfi)
    p.save()
    p.publish("DA", AUTHOR)
    mario = SimpleNamespace(id="b" * 32, full_name="Mario Rossi", email="m@x.it", username="mario")
    window = mw.MainWindow()
    window._set_project(p)
    window.open_project = lambda path, confirmed=False, **_kw: window._set_project(Project.open(path))
    p.switch_branch("att/T9", p.repository.head())  # a team integrates in a branch of its own
    p = reopen(p)
    window._set_project(p)
    window.user = mario

    def run(d):
        d.start()
        d.worker.wait(20000)
        app.processEvents()
        assert not d.mode_row.isHidden() and d.full_mode.isChecked()
        d.selective_mode.setChecked(True)
        assert d.selective and not d.groups_row.isHidden() and not d.apply_button.isEnabled()  # nothing ticked yet
        view = d.preview_view
        assert item.uuid in view.locked  # an SRS item: for the DA
        d.group_buttons["ADR"].click()
        assert view.chosen == {adr.uuid, radio.uuid} and "Radio" in view.note.text()  # what is linked comes by itself
        # Side by side: on the left only what the sender has changed (no group without changes); on the right the
        # destination.
        left = [view.tree.topLevelItem(i).child(j).text(0) for i in range(view.tree.topLevelItemCount())
                for j in range(view.tree.topLevelItem(i).childCount())]
        assert not any("Odometria" in t or "Frenatura" in t for t in left)  # the same, or only in the destination
        groups = [view.tree.topLevelItem(i).text(0) for i in range(view.tree.topLevelItemCount())]
        assert sorted(groups) == sorted(KINDS_BY_NAME[k].plural for k in ("domain", "adr", "requirement"))
        right = d.destination
        assert right.rows[adr.uuid].text(1) == "In arrivo" and not right.rows[adr.uuid].isHidden()
        assert right.rows[radio.uuid].text(1) == "In arrivo" and right.rows[item.uuid].isHidden()  # not ticked: not there
        assert not right.rows[next(e.uuid for e in window.project.model.of_kind("domain")
                                   if e.get("name") == "Frenatura")].isHidden()  # what it already has
        assert right.summary.text().startswith("2 in arrivo")
        right.only_changes.setChecked(True)
        assert right.groups["domain"].text(1) == "1"  # Radio only
        right.only_changes.setChecked(False)
        view.set_chosen({radio.uuid})  # a tick taken away: it goes from the destination
        assert right.rows[adr.uuid].isHidden() and right.summary.text().startswith("1 in arrivo")
        view.set_chosen({adr.uuid})
        d._selective_update()
        assert d.apply_button.isEnabled() and "2 da aggiungere" in d.conflicts_title.text()
        d.apply()
        return True
    monkeypatch.setattr(ReceiveDialog, "exec", run)
    asked = []
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or mw.QMessageBox.No)
    result = window.integrate_branch("att/T2", head)
    assert result.applied and result.selective and not result.branch_deleted
    assert not any("Cancellarlo" in text for text in asked)  # the rest of the branch is still to integrate
    assert names(window.project) == ["Frenatura", "Odometria", "Radio"] and window.project.model.get(item.uuid) is None
    window._set_project(None)
    window.close()


def test_the_comparison_integrates_what_is_selected(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.versions import CompareDialog, WORKING

    def branch(p, teams, domain):
        p.new_element("domain", name="Radio")
        p.save()
        first = p.publish("prima", AUTHOR)
        p.new_element("domain", name="Dopo")
        return first

    p, head, earlier, _ = two_branches(tmp_path, branch, lambda p: p.new_element("domain", name="Frenatura"))
    master = p.repository.head()

    def compare(**k):
        return CompareDialog(p, integrating=True, **k)

    assert CompareDialog(p).integrate_button.isHidden()  # only where the integration can start from
    same = compare()  # the same branch on both sides
    assert not same.integrate_button.isEnabled() and "stesso ramo" in same.integrate_button.toolTip()
    # «Da» goes into «A», whatever the branch in use: here into a branch that is not.
    into_branch = compare(before=master, after=head, before_branch="master", after_branch="att/T2")
    assert into_branch.integrate_button.text() == "Integra «master» in «att/T2»…"
    assert "passa prima al ramo «att/T2»" in into_branch.integrate_button.toolTip()
    into_branch.integrate()
    assert into_branch.request == ("integrate", "master", master, "att/T2")
    # The version chosen in «Da», not the last one.
    version = compare(before=earlier, after=WORKING, before_branch="att/T2", after_branch="master")
    assert version.integrate_button.text() == f"Integra «att/T2 @ {earlier[:8]}» in «master»…"
    version.integrate()
    assert version.request == ("integrate", "att/T2", earlier, "master")
    # It follows the selection, also the inverted one.
    swapped = compare(before=master, after=head, before_branch="master", after_branch="att/T2")
    swapped._swap()
    assert swapped.integrate_button.text() == "Integra «att/T2» in «master»…"
    # What cannot be integrated says why.
    working = compare(before=WORKING, after=head, before_branch="master", after_branch="att/T2")
    assert not working.integrate_button.isEnabled() and "stato attuale" in working.integrate_button.toolTip()
    old_target = compare(before=master, after=earlier, before_branch="master", after_branch="att/T2")
    assert not old_target.integrate_button.isEnabled() and "ultima versione" in old_target.integrate_button.toolTip()
    # Into the main branch: only the Design Authority.
    rfi = next(t for t in p.model.of_kind("team") if t.get("name") == "RFI")
    rfi.set("design_authority", True)
    rfi.set("members", [{"name": "Anna", "account": "a" * 32}])
    p.update(rfi)
    mario = SimpleNamespace(id="b" * 32, full_name="Mario Rossi", email="m@x.it", username="mario")
    denied = compare(before=head, after=WORKING, before_branch="att/T2", after_branch="master", user=mario)
    assert not denied.integrate_button.isEnabled() and "Solo la Design Authority" in denied.integrate_button.toolTip()
    denied.integrate()
    assert denied.request is None
    # From the main window: it moves to the branch of «A», then integrates there.
    p.save()
    p.publish("DA", AUTHOR)
    window = mw.MainWindow()
    window.open_project = lambda path, confirmed=False, **_kw: window._set_project(Project.open(path))
    window._set_project(p)
    window.user = SimpleNamespace(id="a" * 32, full_name="Anna", email="a@x.it", username="anna")
    done = []
    monkeypatch.setattr(window, "integrate_branch", lambda name, sha: done.append(
        (name, sha, window.project.current_branch())))
    window.branch_request(("integrate", "master", master, "att/T2"))
    assert done == [("master", master, "att/T2")]
    window.branch_request(("integrate", "att/T2", earlier, "att/T2"))  # already on it: it does not move
    assert done[-1][2] == "att/T2"
    window._set_project(None)
    window.close()


# --- integrating with changes not published -----------------------------------------------------------------------

def with_local(tmp_path, on_master=lambda p: None):
    def branch(p, teams, domain):
        return p.new_element("domain", name="Radio"), p.new_element("domain", name="Altro ramo")

    p, head, (radio, other), _ = two_branches(tmp_path, branch, on_master)
    p.new_element("domain", name="Solo locale")
    p.save()
    return p, head, radio, other


def published_names(p):
    return sorted(d.get("name") for d in p.published_model().of_kind("domain"))


@pytest.mark.parametrize("diverged", [False, True])
def test_a_selective_integration_keeps_the_changes_not_published_out_of_the_version(tmp_path, diverged):
    p, head, radio, other = with_local(tmp_path, (lambda q: q.new_element("domain", name="Frenatura")) if diverged
                                       else (lambda q: None))
    assert p.prepare_integration("att/T2", head).state == Receive.PUBLISH_FIRST  # unless asked
    receive = p.prepare_integration("att/T2", head, keep_local=True)
    assert {c.uuid for c in receive.selection().diff.changes} == {radio.uuid, other.uuid}
    receive.only = {radio.uuid}
    assert p.apply_receive(receive, None, AUTHOR).resolved
    p = reopen(p)
    assert "Radio" in names(p) and "Solo locale" in names(p) and "Altro ramo" not in names(p)
    assert "Radio" in published_names(p) and "Solo locale" not in published_names(p)
    assert p.has_unpublished_changes() and not p.versions()[0].is_merge
    assert (p.path / ".arcadia" / "before_receive.zip").is_file()


@pytest.mark.parametrize("diverged", [False, True])
def test_a_complete_integration_keeps_the_changes_not_published(tmp_path, diverged):
    p, head, radio, other = with_local(tmp_path, (lambda q: q.new_element("domain", name="Frenatura")) if diverged
                                       else (lambda q: None))
    receive = p.prepare_integration("att/T2", head, keep_local=True)
    assert receive.state == (Receive.MERGE if diverged else Receive.FAST_FORWARD)
    assert p.apply_receive(receive, None, AUTHOR).resolved
    p = reopen(p)
    assert {"Radio", "Altro ramo", "Solo locale"} <= set(names(p))
    assert {"Radio", "Altro ramo"} <= set(published_names(p)) and "Solo locale" not in published_names(p)
    assert p.has_unpublished_changes()


def test_a_local_change_on_an_element_chosen_is_a_conflict_of_its_own(tmp_path):
    def branch(p, teams, domain):
        move(p, domain.uuid, teams[1].uuid)

    p, head, _none, _ = two_branches(tmp_path, branch, lambda q: q.new_element("domain", name="Frenatura"))
    domain = next(d for d in p.model.of_kind("domain") if d.get("name") == "Odometria")
    t = next(t for t in p.model.of_kind("team") if t.get("name") == "UniMiB")
    move(p, domain.uuid, t.uuid)  # not published: to UniMiB; on the branch: to FBK
    p.save()
    receive = p.prepare_integration("att/T2", head, keep_local=True)
    assert domain.uuid in {c.uuid for c in receive.selection().diff.changes}
    receive.only = {domain.uuid}
    conflict = next(c for c in receive.merge().conflicts if c.field == "team")
    assert conflict.local
    assert not p.apply_receive(receive, None, AUTHOR).resolved  # not chosen: nothing is written
    assert p.apply_receive(receive, {conflict.key: "ours"}, AUTHOR).resolved
    p = reopen(p)
    assert next(d for d in p.model.of_kind("domain") if d.get("name") == "Odometria").get("team") == t.uuid
    assert p.has_unpublished_changes()


def test_the_window_offers_to_integrate_keeping_the_local_changes(app, tmp_path):
    from arcadia_tool.ui.receive import ReceiveDialog

    p, head, radio, other = with_local(tmp_path, lambda q: q.new_element("domain", name="Frenatura"))
    dialog = ReceiveDialog(p, {}, AUTHOR, integrate=("att/T2", head))

    def prepared():
        dialog.start()
        dialog.worker.wait(20000)
        app.processEvents()
    prepared()
    assert dialog.receive.state == Receive.PUBLISH_FIRST
    assert not dialog.keep_button.isHidden() and not dialog.publish_button.isHidden() and dialog.mode_row.isHidden()
    dialog._integrate_keeping()
    dialog.worker.wait(20000)
    app.processEvents()
    assert dialog.receive.state == Receive.MERGE and dialog.keep_button.isHidden() and not dialog.apply_button.isHidden()
    assert not dialog.mode_row.isHidden()  # complete or selective
    dialog.selective_mode.setChecked(True)
    dialog.preview_view.set_chosen({radio.uuid})
    dialog._selective_update()
    assert dialog.apply_button.isEnabled()
    dialog.apply()
    assert dialog.applied and dialog.selective
    p = reopen(p)
    assert "Radio" in names(p) and "Solo locale" in names(p) and "Altro ramo" not in names(p)


def test_a_local_branch_is_deleted_from_the_window_of_the_branches(app, tmp_path, monkeypatch):
    from dulwich import porcelain
    from arcadia_tool.storage.project import ProjectError
    from arcadia_tool.storage.repository import remote_branches
    from arcadia_tool.ui import branches as ui

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    p, teams, domain = start(tmp_path)
    p.repository.set_remote_url(url)
    p.set_local_settings(branch="master")
    p.push()
    p.switch_branch("att/inviato", p.repository.head())
    p = reopen(p)
    p.set_local_settings(branch="att/inviato")
    p.new_element("domain", name="Radio")
    p.save()
    p.publish("inviata", AUTHOR)
    p.push()
    p.switch_branch("att/solo-qui", p.repository.head())
    p = reopen(p)
    p.set_local_settings(branch="att/solo-qui")
    p.new_element("domain", name="Solo qui")
    p.save()
    p.publish("non inviata", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    p.set_local_settings(branch="master")
    with pytest.raises(ProjectError):
        p.delete_local_branch("master")  # the branch in use
    dialog = ui.BranchesDialog(p, {}, None)
    buttons = [dialog.delete_button, dialog.checkout_button]
    layout = dialog.layout().itemAt(1).layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    # Before the checkout, followed by the removal from the repository.
    assert order.index(buttons[0]) + 1 == order.index(dialog.delete_remote_button) == order.index(buttons[1]) - 1

    def select(name):
        rows = {dialog.table.item(r, 0).text().replace("  (in uso)", ""): r for r in range(dialog.table.rowCount())}
        dialog.table.selectRow(rows[name])

    select("master")
    assert not dialog.delete_button.isEnabled() and "in uso" in dialog.delete_button.toolTip()
    asked = []
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or ui.QMessageBox.No)
    select("att/solo-qui")
    assert dialog.delete_button.isEnabled()
    dialog.delete_local()  # «No»: it stays, and the versions that would be lost are said
    assert "att/solo-qui" in p.repository.local_heads() and "andranno perse" in asked[0]
    replies = [ui.QMessageBox.Yes, ui.QMessageBox.No]  # delete it here; «also from the repository?» no
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or replies.pop(0))
    select("att/inviato")
    dialog.delete_local()
    assert "att/inviato" not in p.repository.local_heads() and "andranno perse" not in asked[-2]
    assert "anche dal repository" in asked[-1] and "att/inviato" in remote_branches(url)  # only on this PC
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or ui.QMessageBox.Yes)
    select("att/inviato")  # still listed, from the repository: nothing local to delete
    assert not dialog.delete_button.isEnabled() and "repository" in dialog.delete_button.toolTip()
    select("att/solo-qui")
    dialog.delete_local()
    assert "att/solo-qui" not in p.repository.local_heads()
    assert all(b.name != "att/solo-qui" for b in p.branches())


# --- the numbers: what is in the main branch keeps its own ------------------------------------------------------------

KIND = "Altro / decisione trasversale"


def numbered(tmp_path, count=3):
    def branch(p, teams, domain):
        return [p.new_element("adr", title=f"Dal ramo {i}", adr_type=KIND, status="Proposta") for i in range(count)]

    def master(p):
        return [p.new_element("adr", title=f"Da master {i}", adr_type=KIND, status="Proposta") for i in range(count)]

    return two_branches(tmp_path, branch, master)


@pytest.mark.parametrize("selective", [False, True])
def test_into_master_the_new_elements_continue_the_numbering(tmp_path, selective):
    p, head, arriving, approved = numbered(tmp_path)
    assert [a.get("id") for a in arriving] == [a.get("id") for a in approved]
    numbers = [a.get("id") for a in approved]
    receive = p.prepare_integration("att/T2", head)
    if selective:
        receive.only = {a.uuid for a in arriving}
    result = p.apply_receive(receive, None, AUTHOR)
    assert {r[0] for r in result.renumbered} == {a.uuid for a in arriving}
    p = reopen(p)
    assert [p.model.get(a.uuid).get("id") for a in approved] == numbers
    assert [p.model.get(a.uuid).get("id") for a in arriving] == ["ADR-004", "ADR-005", "ADR-006"]  # in their order


def test_a_team_receiving_master_takes_its_numbers_with_no_conflict(tmp_path):
    p, head, arriving, approved = numbered(tmp_path)
    p.apply_receive(p.prepare_integration("att/T2", head), None, AUTHOR)
    p = reopen(p)
    master = p.repository.head()
    p.switch_branch("att/T2")
    p = reopen(p)
    receive = p.prepare_integration("master", master)
    assert not receive.into_main and not receive.result.conflicts
    p.apply_receive(receive, None, AUTHOR)
    p = reopen(p)
    assert [p.model.get(a.uuid).get("id") for a in arriving] == ["ADR-004", "ADR-005", "ADR-006"]
    assert [p.model.get(a.uuid).get("id") for a in approved] == ["ADR-001", "ADR-002", "ADR-003"]


def test_into_a_branch_of_a_team_what_is_received_keeps_its_number(tmp_path):
    p, head, arriving, approved = numbered(tmp_path, 1)
    master = p.repository.head()
    p.switch_branch("att/T2")
    p = reopen(p)
    result = p.apply_receive(p.prepare_integration("master", master), None, AUTHOR)
    assert [r[0] for r in result.renumbered] == [arriving[0].uuid]  # the number of the team was provisional


def test_the_window_shows_the_final_number(app, tmp_path):
    from arcadia_tool.ui.receive import ReceiveDialog

    p, head, arriving, approved = numbered(tmp_path, 1)
    dialog = ReceiveDialog(p, {}, AUTHOR, integrate=("att/T2", head))
    dialog.start()
    dialog.worker.wait(20000)
    app.processEvents()
    dialog.selective_mode.setChecked(True)
    dialog.preview_view.set_chosen({arriving[0].uuid})
    dialog._selective_update()
    row = dialog.destination.rows[arriving[0].uuid]
    assert row.text(0).startswith("ADR-002") and "(era ADR-001 in att/T2)" in row.text(0)
    assert dialog.destination.rows[approved[0].uuid].text(0).startswith("ADR-001")
    assert "rinumerati" in dialog.conflicts_title.text()
    dialog.preview_view.set_chosen(set())
    dialog._selective_update()  # not chosen any more: its row reads as before
    assert row.text(0).startswith("ADR-001") and "era" not in row.text(0)


# --- the message of the version of an integration --------------------------------------------------------------------

@pytest.mark.parametrize("selective", [False, True])
def test_the_message_of_an_integration_is_written_by_the_user(tmp_path, selective):
    p, head, arriving, approved = numbered(tmp_path, 1)
    receive = p.prepare_integration("att/T2", head)
    if selective:
        receive.only = {arriving[0].uuid}
    assert p.default_message(receive).startswith("Integrazione selettiva" if selective else "Integrazione del ramo")
    p.apply_receive(receive, None, AUTHOR, "Integrate le ADR di T2\n\nDecise nella riunione del 9/11")
    last = reopen(p).versions()[0]
    assert last.title == "Integrate le ADR di T2" and "riunione del 9/11" in last.message
    assert ("Elementi:" in last.message) if selective else made_by_atlas(last)  # what ATLAS records still follows


def test_an_empty_message_is_the_one_of_atlas(tmp_path):
    p, head, arriving, approved = numbered(tmp_path, 1)
    receive = p.prepare_integration("att/T2", head)
    p.apply_receive(receive, None, AUTHOR, "   ")
    assert reopen(p).versions()[0].title.startswith("Integrazione del ramo «att/T2» in «master»")


def test_the_window_asks_the_message(app, tmp_path):
    from arcadia_tool.ui.receive import ReceiveDialog

    p, head, arriving, approved = numbered(tmp_path, 1)
    dialog = ReceiveDialog(p, {}, AUTHOR, integrate=("att/T2", head))
    dialog.start()
    dialog.worker.wait(20000)
    app.processEvents()
    assert not dialog.message_row.isHidden() and dialog.message.text().startswith("Integrazione del ramo")
    dialog.selective_mode.setChecked(True)
    dialog.preview_view.set_chosen({arriving[0].uuid})
    dialog._selective_update()
    assert dialog.message.text() == p.default_message(dialog.receive)  # it follows the choice until written
    assert "(1 elementi)" in dialog.message.text()
    from PySide6.QtTest import QTest

    dialog.message.selectAll()
    QTest.keyClicks(dialog.message, "ADR di T2 approvate")  # typed by the user
    assert dialog.message.text() == "ADR di T2 approvate"
    dialog.description.setPlainText("Come deciso dalla DA")
    dialog._selective_update()
    assert dialog.message.text() == "ADR di T2 approvate"  # written: it stays
    dialog.apply()
    assert dialog.applied
    last = reopen(p).versions()[0]
    assert last.title == "ADR di T2 approvate" and "Come deciso dalla DA" in last.message


def test_no_message_when_no_version_is_recorded(app, tmp_path):
    from arcadia_tool.ui.receive import ReceiveDialog

    p, teams, domain = start(tmp_path)
    p.switch_branch("att/T2", p.repository.head())
    p = reopen(p)
    p.new_element("domain", name="Radio")
    p.save()
    head = p.publish("radio", AUTHOR)
    p.switch_branch("master")
    p = reopen(p)
    dialog = ReceiveDialog(p, {}, AUTHOR, integrate=("att/T2", head))
    dialog.start()
    dialog.worker.wait(20000)
    app.processEvents()
    assert dialog.receive.state == Receive.FAST_FORWARD and dialog.message_row.isHidden()


# --- removing a branch from the repository ---------------------------------------------------------------------------

def test_a_branch_is_removed_from_the_repository(app, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from dulwich import porcelain
    from arcadia_tool.storage.project import ProjectError
    from arcadia_tool.storage.repository import remote_branches
    from arcadia_tool.ui import branches as ui

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    p, teams, domain = start(tmp_path)
    rfi = p.model.get(teams[0].uuid)  # a Design Authority with members, on every branch
    rfi.set("design_authority", True)
    rfi.set("members", [{"name": "Anna", "account": "a" * 32}])
    p.update(rfi)
    p.save()
    p.publish("DA", AUTHOR)
    p.repository.set_remote_url(url)
    p.set_local_settings(branch="master")
    p.push()
    for name, element in (("att/inviato", "Radio"), ("att/solo-remoto", "Solo remoto")):
        p.switch_branch(name, p.repository.head() if name == "att/inviato" else p.repository.local_heads()["master"])
        p = reopen(p)
        p.set_local_settings(branch=name)
        p.new_element("domain", name=element)
        p.save()
        p.publish(element, AUTHOR)
        p.push()
    p.switch_branch("master")
    p = reopen(p)
    p.set_local_settings(branch="master")
    p.delete_local_branch("att/solo-remoto")  # its versions are only in the repository now
    anna = SimpleNamespace(id="a" * 32, full_name="Anna", email="a@x.it", username="anna")
    mario = SimpleNamespace(id="b" * 32, full_name="Mario", email="m@x.it", username="mario")
    # The main branch: only the Design Authority; the branch in use: nobody.
    assert "in uso" in p.remote_delete_denied(anna, "master")
    p.switch_branch("att/inviato")
    p = reopen(p)
    p.set_local_settings(branch="att/inviato")
    assert "Design Authority" in p.remote_delete_denied(mario, "master")
    with pytest.raises(ProjectError):
        p.delete_remote_branch("master", mario)
    p.update_settings(main_branch="att/solo-remoto")  # the main branch of the settings is protected as well
    assert "Design Authority" in p.remote_delete_denied(mario, "att/solo-remoto")
    assert p.remote_delete_denied(anna, "att/solo-remoto") is None
    p.update_settings(main_branch="")
    assert p.remote_delete_denied(mario, "att/solo-remoto") is None  # another branch: anyone
    # From the window: the versions that nobody would have any more are said.
    dialog = ui.BranchesDialog(p, {}, mario)
    rows = {dialog.table.item(r, 0).text().replace("  (in uso)", ""): r for r in range(dialog.table.rowCount())}
    dialog.table.selectRow(rows["master"])
    assert not dialog.delete_remote_button.isEnabled() and "Design Authority" in dialog.delete_remote_button.toolTip()
    dialog.table.selectRow(rows["att/solo-remoto"])
    assert dialog.delete_remote_button.isEnabled()
    asked = []
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or ui.QMessageBox.Yes)
    dialog.delete_remote()
    assert "nessuno le avrà più" in asked[0]
    assert "att/solo-remoto" not in remote_branches(url) and "att/solo-remoto" not in p.repository.remote_heads()
    assert "master" in remote_branches(url) and "att/inviato" in remote_branches(url)
    assert all(b.name != "att/solo-remoto" for b in p.branches())
    # The Design Authority removes the main branch (here from another branch in use).
    p.delete_remote_branch("master", anna)
    assert "master" not in remote_branches(url) and "master" in p.repository.local_heads()  # the copy here stays


def test_deleting_one_copy_asks_about_the_other(app, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from dulwich import porcelain
    from arcadia_tool.storage.repository import remote_branches
    from arcadia_tool.ui import branches as ui

    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    p, teams, domain = start(tmp_path)
    p.repository.set_remote_url(url)
    p.set_local_settings(branch="master")
    p.push()
    for name in ("att/uno", "att/due", "att/tre"):
        p.switch_branch(name, p.repository.local_heads()["master"])
        p = reopen(p)
        p.set_local_settings(branch=name)
        p.new_element("domain", name=name)
        p.save()
        p.publish(name, AUTHOR)
        p.push()
    p.switch_branch("master")
    p = reopen(p)
    p.set_local_settings(branch="master")
    dialog = ui.BranchesDialog(p, {}, SimpleNamespace(id="a" * 32, full_name="Anna", email="a@x.it", username="a"))

    def select(name):
        rows = {dialog.table.item(r, 0).text().replace("  (in uso)", ""): r for r in range(dialog.table.rowCount())}
        dialog.table.selectRow(rows[name])

    def answers(*replies):
        asked, queue = [], list(replies)
        monkeypatch.setattr(ui.QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or queue.pop(0))
        return asked

    yes, no = ui.QMessageBox.Yes, ui.QMessageBox.No
    # The local copy, then the remote one too.
    asked = answers(yes, yes)
    select("att/uno")
    dialog.delete_local()
    assert len(asked) == 2 and "Eliminarlo anche dal repository?" in asked[1]
    assert "att/uno" not in p.repository.local_heads() and "att/uno" not in remote_branches(url)
    # The remote copy, then not the local one: it stays.
    asked = answers(yes, no)
    select("att/due")
    dialog.delete_remote()
    assert "Eliminare anche la copia di questo PC?" in asked[1]
    assert "att/due" not in remote_branches(url) and "att/due" in p.repository.local_heads()
    # The local copy, and «No» to the other one: the repository keeps it (the warning says its versions are there only).
    asked = answers(yes, no)
    select("att/tre")
    dialog.delete_local()
    assert "nessuno le avrà più" in asked[1] and "att/tre" in remote_branches(url)
    # No other copy: no second question.
    asked = answers(yes)
    select("att/due")
    dialog.delete_local()
    assert len(asked) == 1 and "att/due" not in p.repository.local_heads()

