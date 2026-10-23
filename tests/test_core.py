import pytest

from arcadia_tool.diff.semantic import ADDED, MODIFIED, REMOVED, diff_models, word_diff
from arcadia_tool.model.element import Element, Model
from arcadia_tool.model.serialization import dumps, loads
from arcadia_tool.storage.project import Project, ProjectError
from arcadia_tool.storage.repository import NothingToSave

AUTHOR = "Tester <tester@example.com>"


def make(project, kind, **values):
    e = project.new_element(kind)
    for k, v in values.items():
        e.set(k, v)
    project.update(e)
    return e


def test_serialization_is_deterministic_and_round_trips():
    e = Element("system_function", values={
        "status": "Proposta", "name": "Supervisionare lo standstill", "id": "SF-DF06-04",
        "description": "Riga 1\nRiga 2", "rows_452": ["4.5.2-R49"], "mode_availability": {"SB": "X"},
        "extra_future_field": "kept", "notes": "",
    })
    text = dumps(e)
    assert text.index("id:") < text.index("name:") < text.index("status:") < text.index("extra_future_field")
    assert "notes" not in text
    assert "description: |" in text
    again = loads(text)
    assert again.values == {k: v for k, v in e.values.items() if v}
    assert dumps(again) == text


def test_numeric_looking_strings_survive():
    e = Element("requirement", values={"id": "3.14", "baseline": "3.6.0"})
    assert loads(dumps(e)).get("id") == "3.14"


def test_edits_stay_in_memory_until_save(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    dom = make(project, "domain", id="DF06")
    assert project.is_modified
    assert not project.element_file(dom).exists()
    project.save()
    assert not project.is_modified
    assert project.element_file(dom).exists()

    project.delete_element(dom.uuid)
    assert project.element_file(dom).exists()
    project.save()
    assert not project.element_file(dom).exists()
    project.close()


def test_unsaved_edits_are_lost_on_reopen(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    make(project, "domain", id="DF06")
    project.close()
    assert len(Project.open(tmp_path / "p").model) == 0


def test_publish_saves_and_records_version(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    dom = make(project, "domain", id="DF06")
    v1 = project.publish("Prima pubblicazione", AUTHOR)
    assert not project.is_modified
    assert not project.has_unpublished_changes()
    with pytest.raises(NothingToSave):
        project.publish("niente di nuovo", AUTHOR)
    project.close()

    reopened = Project.open(tmp_path / "p")
    assert reopened.model.get(dom.uuid).get("id") == "DF06"
    assert not reopened.has_unpublished_changes()
    versions = reopened.versions()
    assert [v.sha for v in versions] == [v1]
    assert versions[0].title == "Prima pubblicazione"
    reopened.close()


def test_open_reads_files_changed_after_publication_from_disk(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    dom = make(project, "domain", name="Originale")
    other = make(project, "domain", name="Invariato")
    project.publish("v1", AUTHOR)
    project.close()
    file = project.element_file(dom)
    file.write_text(file.read_text(encoding="utf-8").replace("Originale", "Modificato a mano"), encoding="utf-8")

    reopened = Project.open(tmp_path / "p")
    assert reopened.model.get(dom.uuid).get("name") == "Modificato a mano"
    assert reopened.model.get(other.uuid).get("name") == "Invariato"
    assert reopened.has_unpublished_changes()
    reopened.close()


def test_open_rejects_non_project(tmp_path):
    with pytest.raises(ProjectError):
        Project.open(tmp_path)


def test_semantic_diff_between_versions(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    df06 = make(project, "domain", id="DF06")
    df07 = make(project, "domain", id="DF07")
    sf = make(project, "system_function", id="SF-DF06-04", name="Supervisionare lo standstill", domain=df06.uuid)
    gone = make(project, "system_function", id="SF-DF06-05", name="Da eliminare", domain=df06.uuid)
    v1 = project.publish("v1", AUTHOR)

    sf.set("name", "Supervisionare lo stato di fermo")
    sf.set("domain", df07.uuid)
    sf.set("rows_452", ["4.5.2-R49"])
    project.update(sf)
    project.delete_element(gone.uuid)
    new = make(project, "system_function", id="SF-DF07-01", name="Determinare il modo", domain=df07.uuid)

    d = diff_models(project.published_model(v1), project.model)
    changes = {c.uuid: c for c in d.changes}
    assert changes[new.uuid].change == ADDED
    assert changes[gone.uuid].change == REMOVED
    mod = changes[sf.uuid]
    assert mod.change == MODIFIED
    assert mod.renamed and mod.significant
    fields = {f.name: f for f in mod.fields}
    assert set(fields) == {"name", "domain", "rows_452"}
    assert d.label_of(fields["domain"].after) == "DF07"
    assert fields["rows_452"].added_items == ["4.5.2-R49"]
    assert d.summary() == {ADDED: 1, REMOVED: 1, MODIFIED: 1}

    v2 = project.publish("v2", AUTHOR)
    d12 = diff_models(project.published_model(v1), project.published_model(v2))
    assert {c.uuid for c in d12.changes} == {new.uuid, gone.uuid, sf.uuid}
    assert not diff_models(project.published_model(v2), project.model)
    project.close()


def test_table_rows_diff(tmp_path):
    project = Project.create(tmp_path / "p", "Prova")
    fc = make(project, "functional_chain", steps=[{"cycle": "C0", "what": "riceve"}, {"cycle": "C0", "what": "verifica"}])
    v1 = project.publish("v1", AUTHOR)
    fc.set("steps", [{"cycle": "C0", "what": "riceve"}, {"cycle": "C1", "what": "verifica"}, {"what": "Attesa"}])
    project.update(fc)
    rows = diff_models(project.published_model(v1), project.model).changes[0].fields[0].rows
    assert [(r.index, r.change, r.columns) for r in rows] == [(1, MODIFIED, ["cycle"]), (2, ADDED, [])]
    project.close()


def test_unnamed_elements_are_labelled_by_reference():
    req = Element("requirement", values={"id": "3.14.4.2"})
    record = Element("trace_record", values={"requirement": req.uuid})
    model = Model([req, record])
    assert model.label(record) == "Esito di tracciatura · 3.14.4.2"
    d = diff_models(Model(), model)
    assert "Esito di tracciatura · 3.14.4.2" in [c.label for c in d.changes]


def test_word_diff_separates_punctuation():
    ops = word_diff("in Stand By.", "in Stand By oltre la distanza.")
    assert ("-", "By.") not in ops
    assert ("+", " oltre la distanza") in ops


def test_word_diff():
    ops = word_diff("il freno è comandato", "il freno di servizio è comandato")
    assert "".join(t for op, t in ops if op != "-") == "il freno di servizio è comandato"
