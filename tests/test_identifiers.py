from arcadia_tool.model.element import Model, natural_key
from arcadia_tool.model.identifiers import camel, missing_context
from arcadia_tool.storage.project import Project

AUTHOR = "Tester <tester@example.com>"


def test_ids_follow_template_conventions(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    df1 = p.new_element("domain")
    df2 = p.new_element("domain")
    assert (df1.get("id"), df2.get("id")) == ("DF01", "DF02")

    sf1 = p.new_element("system_function", domain=df2.uuid)
    sf2 = p.new_element("system_function", domain=df2.uuid)
    other = p.new_element("system_function", domain=df1.uuid)
    assert (sf1.get("id"), sf2.get("id"), other.get("id")) == ("SF-DF02-01", "SF-DF02-02", "SF-DF01-01")

    lf = p.new_element("logical_function", refines=sf2.uuid)
    assert lf.get("id") == "LF-DF02-02-01"

    rbc = p.new_element("external_actor", name="RBC")
    assert rbc.get("id") == "OE-01"
    fe = p.new_element("functional_exchange", source=other.uuid, target=sf1.uuid)
    fe_internal = p.new_element("functional_exchange", source=sf1.uuid, target=lf.uuid)
    fe_actor = p.new_element("functional_exchange", source=rbc.uuid, target=sf1.uuid)
    assert fe.get("id") == "FE-DF01-DF02-01"
    assert fe_internal.get("id") == "FE-DF02-DF02-01"
    assert fe_actor.get("id") == "FE-OE-01-DF02-01"

    lc11, lc12 = p.new_element("logical_component"), p.new_element("logical_component")
    assert (lc11.get("id"), lc12.get("id")) == ("LC-01", "LC-02")
    ce = p.new_element("component_exchange", source=lc11.uuid, target=lc12.uuid)
    assert ce.get("id") == "CE-LC01-LC02-01"

    req = p.new_element("requirement", id="5.11.2.2 A030")
    assert p.new_element("derived_requirement", parent=req.uuid).get("id") == "5.11.2.2 A030-D1"
    assert p.new_element("adr").get("id") == "ADR-001"
    assert p.new_element("clarification").get("id") == "CQ-01"
    assert p.new_element("team").get("id") == "T1"
    assert p.new_element("exchange_item", name="Train Position Report").get("id") == "EI-TrainPositionReport"
    assert p.new_element("exchange_item", name="Train position report").get("id") == "EI-TrainPositionReport-2"
    assert p.new_element("functional_chain", title="Trip").get("id") == "FC-Trip"
    p.close()


def test_id_waits_for_context_and_then_stays_stable(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    df1 = p.new_element("domain")
    df2 = p.new_element("domain")
    sf = p.new_element("system_function")
    assert sf.get("id") is None
    assert missing_context(sf, p.model) == ["Dominio"]
    sf.set("domain", df1.uuid)
    p.update(sf)
    assert sf.get("id") == "SF-DF01-01"

    sf.set("domain", df2.uuid)  # moved: id is kept until the user renumbers
    p.update(sf)
    assert sf.get("id") == "SF-DF01-01"
    assert p.renumber(sf) and sf.get("id") == "SF-DF02-01"
    assert not p.renumber(sf)
    p.close()


def test_the_first_free_number_is_given_also_after_a_deletion(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    first = p.new_element("team", name="UniMib")
    assert first.get("id") == "T1"
    p.publish("v1", AUTHOR)
    p.delete_element(first.uuid)  # the only team, published, deleted
    assert p.new_element("team", name="Nuovo").get("id") == "T1"
    domains = [p.new_element("domain") for _ in range(3)]
    assert [d.get("id") for d in domains] == ["DF01", "DF02", "DF03"]
    p.delete_element(domains[0].uuid)
    assert p.new_element("domain").get("id") == "DF01"  # the gap left by the deleted one
    assert p.new_element("domain").get("id") == "DF04"
    p.close()


def test_requirements_keep_their_clause_number(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    assert p.new_element("requirement").get("id") is None
    p.close()


def test_helpers():
    assert camel("Movimento del treno à") == "MovimentoDelTrenoA"
    assert sorted(["3.10", "3.2", "3.1.5"], key=natural_key) == ["3.1.5", "3.2", "3.10"]
    assert Model().of_kind("domain") == []
