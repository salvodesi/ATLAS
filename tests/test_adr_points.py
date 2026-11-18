"""The points of a clause (list items «3.6.2.2.2 a)», bullets «3.6.2.2.2 a) 1st bullet», table rows) in the ADR of
reallocation, exclusion and sharing: chosen on their own, they get domains of their own and their clause is mixed. The
ADR of clauses mapped to no domain stays on whole clauses."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from arcadia_tool.checks import run
from arcadia_tool.checks.config import ChecksConfig, Profile
from arcadia_tool.model.adr import (approve_reallocation, approve_sharing, item_domains, mixed_points, principal_of,
                                    reallocation_problems)
from arcadia_tool.model.schema import ADR_EXCLUSION, ADR_SECTION, ADR_SHARED, ADR_UNMAPPED
from arcadia_tool.storage.project import Project
from arcadia_tool.ui import srs_trace


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    df1, df4, df7 = (p.new_element("domain", name=n) for n in ("Uno", "Quattro", "Sette"))
    section = p.new_element("requirement", id="3.6.2", item_type="Sezione", primary_domain=df1.uuid)
    clause = p.new_element("requirement", id="3.6.2.2", item_type="Requisito", parent=section.uuid,
                           text="Una clausola")
    a = p.new_element("requirement", id="3.6.2.2 a)", item_type="Voce", parent=clause.uuid, text="Il punto a")
    b = p.new_element("requirement", id="3.6.2.2 b)", item_type="Voce", parent=clause.uuid, text="Il punto b")
    bullet = p.new_element("requirement", id="3.6.2.2 a) 1st bullet", item_type="Voce", parent=a.uuid,
                           text="Il primo bullet di a")
    return p, dict(df1=df1, df4=df4, df7=df7, section=section, clause=clause, a=a, b=b, bullet=bullet)


def findings(p, code):
    return [f for f in run(p.model, ChecksConfig({"Predefinito": Profile([code], {})})) if f.code == code]


def test_a_point_passes_to_another_domain_and_its_clause_is_mixed(tmp_path):
    p, e = build(tmp_path)
    decision = p.new_element("adr", title="Punto", adr_type=ADR_SECTION, status="Proposta", id="ADR-001",
                             realloc_item=[e["a"].uuid], primary_proposed=e["df4"].uuid)
    assert reallocation_problems(p.model, decision) == []  # no longer only whole clauses
    approve_reallocation(p, decision)
    assert e["a"].get("primary_domain") == e["df4"].uuid
    assert principal_of(p.model, e["bullet"]) == e["df4"].uuid  # its bullets follow it
    assert principal_of(p.model, e["b"]) == e["df1"].uuid and principal_of(p.model, e["clause"]) == e["df1"].uuid
    assert mixed_points(p.model) == {e["clause"].uuid: [e["a"]]}
    assert not findings(p, "A4-04")  # an exception decided by the Design Authority
    e["b"].set("primary_domain", e["df7"].uuid)  # by hand, without an ADR: found by the check
    p.update(e["b"])
    assert [f.element for f in findings(p, "A4-04")] == [e["b"].uuid]


def test_a_point_excluded_and_a_point_shared(tmp_path):
    p, e = build(tmp_path)
    exclusion = p.new_element("adr", title="Esclusione", adr_type=ADR_EXCLUSION, status="Proposta")
    previous = exclusion.copy()
    exclusion.set("excluded_item", [e["b"].uuid])
    exclusion.set("excluding_domain", e["df1"].uuid)
    p.update(exclusion, previous)
    assert e["df1"].uuid not in item_domains(p.model, e["b"])
    assert e["df1"].uuid in item_domains(p.model, e["a"])  # only the point chosen
    sharing = p.new_element("adr", adr_type=ADR_SHARED, status="Proposta", shared_items=[e["bullet"].uuid],
                            shared_with=[e["df7"].uuid])
    approve_sharing(p, sharing)
    assert e["bullet"].get("contributing_domains") == [e["df7"].uuid]
    assert e["df7"].uuid in item_domains(p.model, e["bullet"]) and e["df7"].uuid not in item_domains(p.model, e["a"])
    assert set(map(lambda i: i.uuid, mixed_points(p.model)[e["clause"].uuid])) == {e["b"].uuid, e["bullet"].uuid}


def test_the_points_are_chosen_under_their_clause_in_four_kinds_of_adr(app, tmp_path):
    p, e = build(tmp_path)
    points = {e["a"].uuid, e["b"].uuid, e["bullet"].uuid}
    realloc = srs_trace.TraceReallocItemsDialog(p, p.new_element("adr", adr_type=ADR_SECTION), "realloc_item")
    assert points <= set(realloc.state) and "3.6.2.2.2 a)" in realloc.HINT
    row = realloc._items[e["bullet"].uuid]
    assert row.parent() is realloc._items[e["a"].uuid] and row.parent().parent() is realloc._items[e["clause"].uuid]
    assert row.text(0).startswith("3.6.2.2 a) 1st bullet – Il primo bullet")
    realloc.click(row, srs_trace.PARENT)
    assert realloc.selected == [e["bullet"].uuid]
    exclusion = srs_trace.TraceExclusionItemsDialog(
        p, p.new_element("adr", adr_type=ADR_EXCLUSION, excluding_domain=e["df1"].uuid), "excluded_item")
    exclusion.click(exclusion._items[e["b"].uuid], srs_trace.PARENT)
    assert exclusion.selected == [e["b"].uuid]
    shared = srs_trace.TraceClausesDialog(p, p.new_element("adr", adr_type=ADR_SHARED), "shared_items")
    assert points <= set(shared.state)
    unmapped = srs_trace.TraceClausesDialog(p, p.new_element("adr", adr_type=ADR_UNMAPPED), "unmapped_items")
    assert points <= set(unmapped.state) and e["clause"].uuid in unmapped.state  # a point not mapped on its own
    unmapped.click(unmapped._items[e["bullet"].uuid], srs_trace.PARENT)
    assert unmapped.selected == [e["bullet"].uuid]
    for dialog in (realloc, exclusion, shared, unmapped):
        dialog.reject()


def test_the_srs_list_shows_the_domains_of_a_point_and_the_mixed_clause(app, tmp_path):
    from arcadia_tool.ui.srs_reader import SrsReader

    p, e = build(tmp_path)
    e["a"].set("primary_domain", e["df4"].uuid)
    e["b"].set("excluded_domains", [e["df1"].uuid])
    reader = SrsReader(p)
    reader._rebuild_links()
    a_badges = reader._link_badges(e["a"])
    assert a_badges[0][1] is True and "Quattro" in a_badges[0][0] and "proprio del punto" in a_badges[0][2]
    assert reader._link_badges(e["b"])[0][1] == "excluded"
    mixed = [b for b in reader._link_badges(e["clause"]) if b[1] == "mixed"]
    assert mixed and mixed[0][0] == "Punti in altri domini (2)"
    assert "3.6.2.2 a): " in mixed[0][2] and "(principale)" in mixed[0][2] and "escluso da" in mixed[0][2]
    assert not [b for b in reader._link_badges(e["section"]) if b[1] == "mixed"]
    reader.deleteLater()


def test_the_sheets_of_the_adrs_name_the_points_also_a_bullet(tmp_path):
    from arcadia_tool.storage.adr_sheets import Resolver

    p, e = build(tmp_path)
    r = Resolver(p.model)
    items, _written, problems = r.requirements("3.6.2.2 a) 1st bullet e 3.6.2.2 b)")
    assert items == [e["bullet"], e["b"]] and problems == []
    items, _written, problems = r.requirements("3.6.2.2 3rd bullet")  # not in the project: its clause, told
    assert items == [e["clause"]] and problems


def test_a_point_is_shared_or_not_mapped_from_its_row(app, tmp_path):
    from arcadia_tool.ui.srs_reader import QUICK_ACTIONS

    names = [a[0] for a in QUICK_ACTIONS["item"] if a]
    assert "share" in names and "exclude" in names
