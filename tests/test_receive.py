"""Receiving the versions published by the others on the working branch, with the semantic three-way merge."""
import pytest
from dulwich import porcelain

from arcadia_tool.checks.config import ChecksConfig, Profile
from arcadia_tool.storage.merge import OURS, THEIRS
from arcadia_tool.storage.project import Project, Receive, clone_project

AUTHOR = "Mario Rossi <mario.rossi@example.com>"


@pytest.fixture
def team(tmp_path):
    """A project on a «server» (bare repository), downloaded by me and by a colleague."""
    url = str(tmp_path / "server.git")
    porcelain.init(url, bare=True).close()
    first = Project.create(tmp_path / "first", "EVC")
    first.repository.set_remote_url(url)
    domain = first.new_element("domain", name="Protezione", mission="Proteggere.")
    first.new_element("system_function", name="Supervisionare lo standstill", domain=domain.uuid)
    first.publish("v1", AUTHOR)
    first.push()
    first.close()
    opened = []

    def download(name):
        p = Project.open(clone_project(url, tmp_path / name))
        opened.append(p)
        return p

    def reopen(p):
        p.close()
        again = Project.open(p.path)
        opened.append(again)
        return again

    yield download("mine"), download("colleague"), reopen
    for p in opened:
        p.close()


def receive(p, choices=None):
    plan = p.prepare_receive()
    if plan.state in (Receive.FAST_FORWARD, Receive.MERGE):
        p.apply_receive(plan, choices, AUTHOR)
    return plan


def domain_of(p):
    return p.model.of_kind("domain")[0]


def test_nothing_to_receive(team):
    mine, _colleague, _reopen = team
    assert mine.prepare_receive().state == Receive.UP_TO_DATE


def test_the_versions_of_a_colleague_are_received(team):
    mine, colleague, reopen = team
    colleague.new_element("domain", name="Localizzazione")
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    plan = receive(mine)
    assert plan.state == Receive.FAST_FORWARD and [v.title for v in plan.incoming] == ["del collega"]
    mine = reopen(mine)
    assert sorted(d.get("name") for d in mine.model.of_kind("domain")) == ["Localizzazione", "Protezione"]
    assert mine.unsent_versions() == [] and not mine.has_unpublished_changes()
    assert mine.prepare_receive().state == Receive.UP_TO_DATE


def test_changes_not_yet_published_stay_on_top(team):
    mine, colleague, reopen = team
    colleague.new_element("domain", name="Localizzazione")
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    mine.new_element("domain", name="Odometria")
    mine.save()  # saved, not published
    assert receive(mine).state == Receive.FAST_FORWARD
    mine = reopen(mine)
    assert sorted(d.get("name") for d in mine.model.of_kind("domain")) == [
        "Localizzazione", "Odometria", "Protezione"]
    assert mine.has_unpublished_changes() and [v.title for v in mine.versions()][0] == "del collega"


def test_versions_published_on_both_sides_are_merged_and_can_be_sent(team):
    mine, colleague, reopen = team
    colleague.new_element("domain", name="Localizzazione")
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    d = domain_of(mine)
    d.set("mission", "Impedire i movimenti non autorizzati.")
    mine.update(d)
    mine.publish("mia", AUTHOR)
    plan = receive(mine)
    assert plan.state == Receive.MERGE and plan.result.resolved
    mine = reopen(mine)
    assert {x.get("name") for x in mine.model.of_kind("domain")} == {"Localizzazione", "Protezione"}
    assert any(x.get("mission") == "Impedire i movimenti non autorizzati." for x in mine.model.of_kind("domain"))
    head = mine.repository._repo[mine.repository.head().encode()]
    assert len(head.parents) == 2 and "Integrazione di 1 versione ricevuta" in head.message.decode()
    mine.push()  # now accepted
    assert receive(colleague).state == Receive.FAST_FORWARD  # and the colleague receives it
    colleague = reopen(colleague)
    assert any(x.get("mission") == "Impedire i movimenti non autorizzati." for x in colleague.model.of_kind("domain"))


def test_changes_not_published_must_be_published_before_a_merge(team):
    mine, colleague, _reopen = team
    colleague.new_element("domain", name="Localizzazione")
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    mine.new_element("domain", name="Odometria")
    mine.publish("mia", AUTHOR)
    mine.new_element("domain", name="Velocità")
    mine.save()
    assert mine.prepare_receive().state == Receive.PUBLISH_FIRST


def test_fields_changed_on_both_sides_are_merged_one_by_one(team):
    mine, colleague, reopen = team
    sf = mine.model.of_kind("system_function")[0]
    sf.set("description", "Mia descrizione.")
    mine.update(sf)
    mine.publish("mia", AUTHOR)
    sf = colleague.model.of_kind("system_function")[0]
    sf.set("name", "Supervisionare lo standstill del treno")
    colleague.update(sf)
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    plan = receive(mine)
    assert plan.state == Receive.MERGE and plan.result.resolved and plan.result.merged
    sf = reopen(mine).model.of_kind("system_function")[0]
    assert sf.get("description") == "Mia descrizione." and sf.get("name") == "Supervisionare lo standstill del treno"


def test_the_same_field_changed_in_two_ways_is_a_conflict_to_resolve(team):
    mine, colleague, reopen = team
    for p, mission in ((mine, "La mia missione."), (colleague, "La missione del collega.")):
        d = domain_of(p)
        d.set("mission", mission)
        p.update(d)
        p.publish("missione", AUTHOR)
    colleague.push()
    plan = mine.prepare_receive()
    [conflict] = plan.result.conflicts
    assert conflict.field == "mission" and conflict.uuid == domain_of(mine).uuid
    assert (conflict.ours, conflict.theirs, conflict.base) == ("La mia missione.", "La missione del collega.",
                                                               "Proteggere.")
    assert not mine.apply_receive(plan, {}, AUTHOR).resolved  # without a choice nothing is written
    assert mine.apply_receive(plan, {conflict.key: THEIRS}, AUTHOR).resolved
    assert domain_of(reopen(mine)).get("mission") == "La missione del collega."


def test_references_added_on_both_sides_are_kept(team):
    mine, colleague, reopen = team
    for p, ident in ((mine, "3.6.1"), (colleague, "3.14.4")):
        section = p.new_element("requirement", id=ident, item_type="Sezione")
        sf = p.model.of_kind("system_function")[0]
        sf.set("sections", [section.uuid])
        p.update(sf)
        p.publish(ident, AUTHOR)
    colleague.push()
    assert receive(mine).result.resolved
    mine = reopen(mine)
    sf = mine.model.of_kind("system_function")[0]
    assert sorted(mine.model.get(u).get("id") for u in sf.get("sections")) == ["3.14.4", "3.6.1"]


def test_deleted_on_one_side_and_changed_on_the_other_is_a_conflict(team):
    mine, colleague, reopen = team
    sf = mine.model.of_kind("system_function")[0]
    mine.delete_element(sf.uuid)
    mine.publish("eliminata", AUTHOR)
    sf = colleague.model.of_kind("system_function")[0]
    sf.set("description", "Ancora utile.")
    colleague.update(sf)
    colleague.publish("modificata", AUTHOR)
    colleague.push()
    plan = mine.prepare_receive()
    [conflict] = plan.result.conflicts
    assert conflict.field is None and conflict.ours is None and conflict.theirs is not None
    mine.apply_receive(plan, {conflict.key: OURS}, AUTHOR)
    assert reopen(mine).model.of_kind("system_function") == []


def test_identifiers_given_on_both_sides_are_renumbered(team):
    mine, colleague, reopen = team
    domain = domain_of(colleague)
    sf = colleague.new_element("system_function", name="Comandare i freni", domain=domain.uuid)
    colleague.publish("del collega", AUTHOR)
    colleague.push()
    domain = domain_of(mine)
    mine_sf = mine.new_element("system_function", name="Rilevare il movimento", domain=domain.uuid)
    lf = mine.new_element("logical_function", name="Calcolare la distanza", refines=mine_sf.uuid)
    assert mine_sf.get("id") == sf.get("id") == "SF-DF01-02" and lf.get("id") == "LF-DF01-02-01"
    mine.publish("mia", AUTHOR)
    plan = receive(mine)
    assert (mine_sf.uuid, "SF-DF01-02", "SF-DF01-03") in plan.result.renumbered
    mine = reopen(mine)
    ids = {e.get("name"): e.get("id") for e in mine.model if e.kind in ("system_function", "logical_function")}
    assert ids["Comandare i freni"] == "SF-DF01-02"  # received: keeps its identifier
    assert ids["Rilevare il movimento"] == "SF-DF01-03" and ids["Calcolare la distanza"] == "LF-DF01-03-01"


def test_settings_of_the_checks_are_merged(team):
    mine, colleague, reopen = team
    mine.update_checks(ChecksConfig({"Predefinito": Profile(["SA2-01"])}))
    mine.publish("verifiche", AUTHOR)
    config = ChecksConfig({"Predefinito": Profile(["SA2-07"]), "Gate LA": Profile(["LA2-02"])})
    config.active = "Predefinito"
    colleague.update_checks(config)
    colleague.publish("verifiche del collega", AUTHOR)
    colleague.push()
    plan = receive(mine)
    assert plan.result.resolved, [c.key for c in plan.result.conflicts]
    checks = reopen(mine).checks
    assert set(checks.profiles["Predefinito"].enabled) == {"SA2-01", "SA2-07"} and "Gate LA" in checks.profiles


def test_the_window_shows_the_conflicts_and_receives_with_the_choices(team):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from arcadia_tool.ui.receive import ReceiveDialog

    app = QApplication.instance() or QApplication([])
    mine, colleague, reopen = team
    for p, mission, name in ((mine, "La mia missione.", "Protezione dei movimenti"), (colleague, "Del collega.", "Protezione ATP")):
        d = domain_of(p)
        d.set("mission", mission)
        d.set("name", name)
        p.update(d)
        p.publish("modifiche", AUTHOR)
    colleague.push()
    dialog = ReceiveDialog(mine, {}, AUTHOR)
    dialog.show_receive(mine.prepare_receive())
    assert dialog.conflicts.rowCount() == 2 and not dialog.apply_button.isEnabled()
    rows = {dialog.conflicts.item(r, 0).text(): r for r in range(2)}
    assert any("Missione" in k for k in rows) and any("Nome" in k for k in rows)
    assert "Del collega." in [dialog.conflicts.item(r, 2).text() for r in range(2)]
    dialog._choose_all(THEIRS)
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    assert dialog.applied and dialog.merged
    d = domain_of(reopen(mine))
    assert (d.get("name"), d.get("mission")) == ("Protezione ATP", "Del collega.")
    app.processEvents()


def test_the_main_window_opens_the_project_again_after_receiving(team, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    import arcadia_tool.ui.main_window as main_window
    from arcadia_tool.ui.receive import ReceiveDialog

    app = QApplication.instance() or QApplication([])
    mine, colleague, _reopen = team
    colleague.new_element("domain", name="Localizzazione")
    colleague.publish("del collega", AUTHOR)
    colleague.push()

    class Immediate(ReceiveDialog):  # no thread and no modal window in the test
        def exec(self):
            self.show_receive(self.project.prepare_receive())
            self.apply()
            return True
    monkeypatch.setattr(main_window, "ReceiveDialog", Immediate)
    window = main_window.MainWindow()
    window._set_project(mine)
    assert window.receive_action.isEnabled()
    window.receive_versions()
    assert window.project is not mine
    assert sorted(d.get("name") for d in window.project.model.of_kind("domain")) == ["Localizzazione", "Protezione"]
    window._set_project(None)
    window.close()
    app.processEvents()
