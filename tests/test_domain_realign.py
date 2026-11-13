"""The deletion of a functional domain leaves no gap in the numbering: the following domains move down, and the
identifiers holding their codes (system and logical functions, functional exchanges) follow, each keeping its own
number. The changes are saved as any other and reach the other branches with the merges."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from arcadia_tool.model.domain_deletion import KEEP, approve_domain_deletion
from arcadia_tool.model.schema import ADR_DELETE_DOMAIN
from arcadia_tool.storage.merge import merge_files, merged_model, renumber_ids
from arcadia_tool.storage.project import Project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    d = {n: p.new_element("domain", name=f"Dominio {n}") for n in (1, 2, 3, 4, 5)}
    assert [d[n].get("id") for n in d] == ["DF01", "DF02", "DF03", "DF04", "DF05"]
    sf = {
        "3a": p.new_element("system_function", name="A", domain=d[3].uuid),
        "4a": p.new_element("system_function", name="B", domain=d[4].uuid),
        "4b": p.new_element("system_function", name="C", domain=d[4].uuid),
        "5a": p.new_element("system_function", name="D", domain=d[5].uuid),
        "2a": p.new_element("system_function", name="E", domain=d[2].uuid),
    }
    p.delete_element(sf["4a"].uuid)  # a gap inside a domain: kept, each function keeps its number
    sf.pop("4a")
    lf = p.new_element("logical_function", name="L", refines=sf["4b"].uuid)
    fe = p.new_element("functional_exchange", name="X", source=sf["5a"].uuid, target=sf["4b"].uuid)
    fe2 = p.new_element("functional_exchange", name="Y", source=sf["2a"].uuid, target=sf["3a"].uuid)
    p.save()
    return p, d, sf, lf, fe, fe2


def ids(*elements):
    return [e.get("id") for e in elements]


def test_the_following_domains_move_down_with_what_depends_on_them(tmp_path):
    p, d, sf, lf, fe, fe2 = build(tmp_path)
    assert ids(sf["4b"], lf, fe, fe2) == ["SF-DF04-02", "LF-DF04-02-01", "FE-DF05-DF04-01", "FE-DF02-DF03-01"]
    p.delete_element(d[3].uuid)
    assert ids(d[1], d[2], d[4], d[5]) == ["DF01", "DF02", "DF03", "DF04"]
    assert ids(sf["4b"], sf["5a"], sf["2a"]) == ["SF-DF03-02", "SF-DF04-01", "SF-DF02-01"]
    assert ids(lf, fe) == ["LF-DF03-02-01", "FE-DF04-DF03-01"]
    # The function of the deleted domain, left without it: no identifier (it would clash with SF-DF03-…)
    assert sf["3a"].get("id") is None
    assert fe2.get("id") is None  # its target has no domain: no identifier either
    changes = {old: new for _e, old, new in p.take_realigned()}
    assert changes["DF04"] == "DF03" and changes["SF-DF04-02"] == "SF-DF03-02" and changes["SF-DF03-01"] is None
    assert p.take_realigned() == []  # told once
    p.save()  # saved as changes of the elements
    again = Project.open(p.path)
    assert sorted(e.get("id") for e in again.model.of_kind("domain")) == ["DF01", "DF02", "DF03", "DF04"]
    # The last domain deleted: nothing else moves.
    again.delete_element(again.model.get(d[5].uuid).uuid)
    assert [(e.kind, old, new) for e, old, new in again.take_realigned()] == [
        ("system_function", "SF-DF04-01", None), ("functional_exchange", "FE-DF04-DF03-01", None)]


def test_the_approved_deletion_moves_the_orphans_into_their_new_domain(tmp_path):
    p, d, sf, lf, fe, fe2 = build(tmp_path)
    adr = p.new_element("adr", title="Via il 3", adr_type=ADR_DELETE_DOMAIN, status="Proposta",
                        deleted_domain=d[3].uuid)
    approve_domain_deletion(p, adr, {sf["3a"].uuid: d[5].uuid})
    # DF05 → DF04, and the function passed to it is numbered after its functions.
    assert d[5].get("id") == "DF04" and ids(sf["5a"], sf["3a"]) == ["SF-DF04-01", "SF-DF04-02"]
    assert fe2.get("id") == "FE-DF02-DF04-01"
    approve_keep = p.take_realigned()
    assert ("DF05", "DF04") in [(old, new) for _e, old, new in approve_keep]
    assert adr.get("deleted_domain_label").startswith("DF03")  # the name it had


def test_the_window_shows_the_impact_and_asks_to_resolve_every_orphan(app, tmp_path):
    from arcadia_tool.model.domain_deletion import DELETE
    from arcadia_tool.ui.domain_deletion import DomainDeletionDialog

    p, d, sf, lf, fe, fe2 = build(tmp_path)
    open_adr = p.new_element("adr", title="Allocare in DF03", adr_type="Riallocazione di sezione o clausola",
                             status="Proposta", primary_proposed=d[3].uuid)
    dialog = DomainDeletionDialog(p, d[3], approving=False)
    assert dialog.windowTitle() == "Elimina il dominio"
    assert set(dialog.choices) == {sf["3a"].uuid, open_adr.uuid}  # the function and the open ADR naming it
    assert not dialog.ok.isEnabled() and "Da risolvere: 2 elementi" in dialog.pending.text()
    # The renumbering shown before deleting, as it would be.
    text = dialog.numbers.toPlainText()
    assert "DF04 → DF03" in text and "SF-DF04-02 → SF-DF03-02" in text and "SF-DF03-01 → (senza ID" in text
    combo = dialog.combos[sf["3a"].uuid]
    combo.setCurrentIndex(combo.findData(d[5].uuid))  # passes to DF05 (DF04 after)
    assert "SF-DF03-01 → SF-DF04-02" in dialog.numbers.toPlainText()
    assert combo.findData(DELETE) < 0  # an exchange uses it: it cannot be deleted
    adr_combo = dialog.combos[open_adr.uuid]
    adr_combo.setCurrentIndex(adr_combo.findData(d[2].uuid))
    assert dialog.ok.isEnabled() and dialog.pending.text() == ""
    from arcadia_tool.model.domain_deletion import delete_domain
    delete_domain(p, d[3], dialog.choices)
    assert open_adr.get("primary_proposed") == d[2].uuid and sf["3a"].get("id") == "SF-DF04-02"
    dialog.deleteLater()


def test_the_tree_asks_through_the_window(app, tmp_path, monkeypatch):
    from arcadia_tool.ui.domain_deletion import DomainDeletionDialog
    from arcadia_tool.ui.model_tree import ModelTree

    p, d, sf, lf, fe, fe2 = build(tmp_path)
    tree = ModelTree()
    tree.set_project(p)
    seen = []
    monkeypatch.setattr(DomainDeletionDialog, "exec", lambda self: seen.append(self) or False)
    assert not tree.delete_element(d[1])  # cancelled: nothing changes
    assert p.model.get(d[1].uuid) is not None and d[2].get("id") == "DF02"

    def resolve(dialog):
        for combo in dialog.combos.values():
            combo.setCurrentIndex(combo.findData(d[3].uuid))
        return True
    monkeypatch.setattr(DomainDeletionDialog, "exec", resolve)
    assert tree.delete_element(d[2])
    assert sf["2a"].get("domain") == d[3].uuid and sf["2a"].get("id") == "SF-DF02-02"  # DF03 → DF02
    assert p.model.get(d[2].uuid) is None and d[5].get("id") == "DF04"
    tree.deleteLater()


def test_the_view_undoes_the_deletion_and_the_numbers(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import diagrams
    from arcadia_tool.ui.domain_deletion import DomainDeletionDialog

    p, d, sf, lf, fe, fe2 = build(tmp_path)

    def resolve(dialog):
        for combo in dialog.combos.values():
            combo.setCurrentIndex(combo.findData(d[1].uuid))
        return True
    monkeypatch.setattr(DomainDeletionDialog, "exec", resolve)
    monkeypatch.setattr(diagrams, "ask_deletion", lambda parent, model, uuids, in_view: ("model", uuids))
    page = diagrams.BreakdownPage(p)
    assert page.delete_elements([d[2].uuid]) == "model"
    assert ids(d[3], d[4], d[5]) == ["DF02", "DF03", "DF04"] and sf["2a"].get("domain") == d[1].uuid
    assert page.undo()
    assert ids(p.model.get(d[2].uuid), p.model.get(d[3].uuid), p.model.get(d[5].uuid)) == ["DF02", "DF03", "DF05"]
    assert p.model.get(sf["4b"].uuid).get("id") == "SF-DF04-02"
    assert p.model.get(sf["2a"].uuid).get("domain") == d[2].uuid  # back in its domain
    assert p.model.get(sf["2a"].uuid).get("id") == "SF-DF02-01"
    assert page.redo()
    assert p.model.get(d[2].uuid) is None and p.model.get(d[5].uuid).get("id") == "DF04"
    assert p.model.get(sf["2a"].uuid).get("domain") == d[1].uuid
    page.deleteLater()


def test_the_merge_brings_the_new_numbers_to_the_other_branches(tmp_path):
    p, d, sf, lf, fe, fe2 = build(tmp_path)
    base = p._version_files()
    # The main branch: DF03 deleted, the following ones moved down.
    p.delete_element(d[3].uuid)
    p.save()
    main = p._version_files()
    # A team branch, from the same base: a new function in DF04 and a new domain (DF06).
    for f in [f for f in main if f not in base]:
        (p.path / f).unlink()
    for f, data in base.items():
        (p.path / f).write_bytes(data)
    team = Project.open(p.path)
    new_sf = team.new_element("system_function", name="Nuova", domain=d[4].uuid)
    new_domain = team.new_element("domain", name="Nuovo")
    assert ids(new_sf, new_domain) == ["SF-DF04-01", "DF06"]  # the first free numbers
    team.save()
    ours = team._version_files()
    # The main branch propagated into the team branch: its numbers arrive, the new elements follow them.
    result = merge_files(base, ours, main)
    assert not result.conflicts
    renumber_ids(result, base, main)
    merged = {e.uuid: e for e in merged_model(result.files)}
    assert merged[d[4].uuid].get("id") == "DF03" and merged[sf["4b"].uuid].get("id") == "SF-DF03-02"
    assert merged[new_sf.uuid].get("id") == "SF-DF03-01"  # in DF03 now: the first free number
    assert merged[new_domain.uuid].get("id") == "DF05"  # no gap: after DF04
    assert d[3].uuid not in merged
