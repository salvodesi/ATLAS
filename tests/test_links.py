"""Fields of different sheets kept in step when a sheet is saved (model.links, through Project.update)."""
import pytest

from arcadia_tool.storage.project import Project


@pytest.fixture
def p(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    yield project
    project.close()


def save(p, element, **values):
    """A sheet saved: values changed, with the element as it was before."""
    previous = element.copy()
    for name, value in values.items():
        element.set(name, value)
    return {e.uuid for e in p.update(element, previous)}


def test_team_sheet_assigns_its_domains(p):
    d1, d2 = p.new_element("domain", name="Uno"), p.new_element("domain", name="Due")
    t1 = p.new_element("team", name="T1", referent="Anna", members=["Anna"])
    t2 = p.new_element("team", name="T2", domains=[d2.uuid])
    d2.set("team", t2.uuid)
    p.update(d2)

    assert save(p, t1, domains=[d1.uuid, d2.uuid]) == {d1.uuid, d2.uuid, t2.uuid}
    assert d1.get("team") == d2.get("team") == t1.uuid
    assert d1.get("referent") == "Anna"  # the referent follows the team
    assert not t2.get("domains")  # d2 moved from T2: one team per domain
    save(p, t1, domains=[d1.uuid])  # removed in the team sheet: no team any more
    assert d2.get("team") is None and d1.get("team") == t1.uuid


def test_a_domain_with_the_team_but_not_listed_is_added(p):
    """Data written before the link (or by hand): saving the team does not take the domain away from it."""
    t = p.new_element("team", name="T01")
    d = p.new_element("domain", name="DF01")
    d.values["team"] = t.uuid  # assigned without updating the team
    save(p, t, name="T01 UniMib")
    assert t.get("domains") == [d.uuid] and d.get("team") == t.uuid


def test_derived_requirement_and_record_of_its_item(p):
    item = p.new_element("requirement", id="3.4.1.1", item_type="Requisito")
    other = p.new_element("requirement", id="3.4.1.2", item_type="Requisito")
    record = p.new_element("trace_record", requirement=item.uuid, outcome="Scomposta in requisiti derivati")
    derived = p.new_element("derived_requirement", parent=item.uuid, obligation="Uno.")
    assert record.get("exchange_items") == [derived.uuid]  # created with its «Voce madre»: listed in the record

    other_record = p.new_element("trace_record", requirement=other.uuid)
    save(p, derived, parent=other.uuid)  # «Voce madre» changed in the derived sheet
    assert not record.get("exchange_items") and other_record.get("exchange_items") == [derived.uuid]

    save(p, record, exchange_items=[derived.uuid])  # listed in the record of the first item
    assert derived.get("parent") == item.uuid and not other_record.get("exchange_items")
    save(p, record, exchange_items=[])  # removed from the record: no «Voce madre» any more
    assert derived.get("parent") is None


def test_a_new_record_lists_the_derived_requirements_of_its_item(p):
    item = p.new_element("requirement", id="3.4.1.1", item_type="Requisito")
    derived = p.new_element("derived_requirement", parent=item.uuid, obligation="Uno.")
    record = p.new_element("trace_record", requirement=item.uuid)
    assert record.get("exchange_items") == [derived.uuid] and derived.get("parent") == item.uuid


def test_functions_of_a_record_trace_its_item(p):
    section = p.new_element("requirement", id="3.14.4", item_type="Sezione")
    clause = p.new_element("requirement", id="3.14.4.2", item_type="Requisito", parent=section.uuid)
    sf = p.new_element("system_function", name="Supervisionare lo standstill")
    other = p.new_element("system_function", name="Gestire i freni", sections=[section.uuid])
    lf = p.new_element("logical_function", name="Rilevare il movimento", refines=sf.uuid)
    record = p.new_element("trace_record", requirement=clause.uuid)
    changed = save(p, record, primary_function=sf.uuid, secondary_functions=[other.uuid, lf.uuid])
    assert changed == {sf.uuid, lf.uuid}
    assert sf.get("sections") == [clause.uuid] and lf.get("detail_requirements") == [clause.uuid]
    assert other.get("sections") == [section.uuid]  # already traces it through its section


def test_derived_requirement_takes_the_domain_of_its_logical_function(p):
    d1, d2 = p.new_element("domain", name="Uno"), p.new_element("domain", name="Due")
    sf = p.new_element("system_function", name="Funzione", domain=d1.uuid)
    lf = p.new_element("logical_function", name="Logica", refines=sf.uuid)
    child = p.new_element("logical_function", name="Figlia", parent=lf.uuid)
    derived = p.new_element("derived_requirement", obligation="Uno.", domain=d2.uuid)
    save(p, derived, function=child.uuid)
    assert derived.get("domain") == d1.uuid  # from the system function its logical function refines
    assert save(p, sf, domain=d2.uuid) == {derived.uuid}  # the function moves: the derived requirement too
    assert derived.get("domain") == d2.uuid


def test_exchange_takes_the_nature_of_its_item(p):
    item = p.new_element("exchange_item", name="Movimento", nature="FLOW")
    fe = p.new_element("functional_exchange", name="Movimento", exchange_item=item.uuid, nature="EVENT")
    assert fe.get("nature") == "FLOW"
    assert save(p, item, nature="EVENT") == {fe.uuid}
    assert fe.get("nature") == "EVENT"


def test_realization_steps_take_the_allocation_of_their_logical_function(p):
    lc1, lc2 = p.new_element("logical_component", name="A"), p.new_element("logical_component", name="B")
    lf = p.new_element("logical_function", name="Logica", component=lc1.uuid)
    realization = p.new_element("chain_realization", steps=[{"sa_step": "1", "logical_function": lf.uuid}])
    assert realization.get("steps")[0]["component"] == lc1.uuid
    assert save(p, lf, component=lc2.uuid) == {realization.uuid}
    assert realization.get("steps")[0]["component"] == lc2.uuid
