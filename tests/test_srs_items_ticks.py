"""Lists of SRS items in the sheets (the items an ADR is about, the clauses of an exchange) chosen with ticks."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import arcadia_tool.ui.srs_trace as srs_trace
from arcadia_tool.checks import run
from arcadia_tool.model.element import Model
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_editor import ElementEditor, RefsWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    section = p.new_element("requirement", id="3.14.4", item_type="Sezione")
    c2 = p.new_element("requirement", id="3.14.4.2", item_type="Requisito", parent=section.uuid)
    c3 = p.new_element("requirement", id="3.14.4.3", item_type="Requisito", parent=section.uuid)
    return p, section, c2, c3


@pytest.fixture
def ticks(monkeypatch):
    """The ticks window, answered: the items in `ticks.wanted` ticked, the others not."""
    windows = []

    def exec_(self):
        windows.append(self)
        for uuid in self.state:
            self.set_state(uuid, srs_trace.PARENT if uuid in ticks.wanted else None)
        return True
    monkeypatch.setattr(srs_trace.TraceItemsDialog, "exec", exec_)
    ticks.windows = windows
    return ticks


@pytest.mark.parametrize("kind, field", [("adr", "srs_items"), ("functional_exchange", "clauses")])
def test_lists_of_srs_items_are_chosen_with_ticks(app, tmp_path, ticks, kind, field):
    p, section, c2, c3 = build(tmp_path)
    element = p.new_element(kind, title="Decisione") if kind == "adr" else p.new_element(kind, name="Scambio")
    editor = ElementEditor()
    editor.edit(p, element, editing=True)
    widget = editor.widgets[field]
    assert isinstance(widget, RefsWidget) and widget.picker is not None
    ticks.wanted = {c3.uuid, section.uuid}
    widget._pick()  # «Seleziona»: the window with chapters, search and ticks
    [window] = ticks.windows
    assert isinstance(window, srs_trace.TraceItemsDialog) and window.count_text() == "2 voci scelte"
    assert widget.value() == [section.uuid, c3.uuid]  # in specification order
    assert element.get(field) is None  # applied with «Salva»
    editor.save_changes()
    assert element.get(field) == [section.uuid, c3.uuid]
    ticks.wanted = {c2.uuid}
    editor.start_editing()
    editor.widgets[field]._pick()  # the window opens with the current choice; another choice replaces it
    assert ticks.windows[1].initial_state(c3) == srs_trace.PARENT
    editor.save_changes()
    assert element.get(field) == [c2.uuid]
    p.close()


def test_relations_come_before_the_description_in_an_adr(app, tmp_path):
    from PySide6.QtWidgets import QLabel
    p, *_ = build(tmp_path)

    def cards(element):
        editor = ElementEditor()
        editor.edit(p, element)
        titles = [l.text() for l in editor.widget().findChildren(QLabel) if l.objectName() == "sectionCaption"]
        return [t for t in titles if t in ("IDENTIFICAZIONE", "DESCRIZIONE", "RELAZIONI")]
    assert cards(p.new_element("adr", title="Decisione")) == ["IDENTIFICAZIONE", "RELAZIONI", "DESCRIZIONE"]
    assert cards(p.new_element("domain", name="Dominio")) == ["IDENTIFICAZIONE", "DESCRIZIONE", "RELAZIONI"]


def test_superseded_by_is_chosen_in_a_window_with_search(app, tmp_path, monkeypatch):
    p, *_ = build(tmp_path)
    old = p.new_element("adr", title="Limiti di velocità nei dati di tratta", status="Superata")
    new = p.new_element("adr", title="MRSP in un dominio autonomo", status="Decisa")
    other = p.new_element("adr", title="Tipo di freno")
    offered = []

    def exec_(self):
        offered.append(sorted(self.items))
        self._clicked(self.items[new.uuid], 1)  # the tick of the ADR that replaces it
        return True
    monkeypatch.setattr(srs_trace.TickPickerDialog, "exec", exec_)
    editor = ElementEditor()
    editor.edit(p, old, editing=True)
    field = old.schema.field("superseded_by")
    assert field.picker
    editor._pick(field)  # «Scegli…»: search and ticks, one ADR
    assert offered == [sorted([new.uuid, other.uuid])]  # every other ADR, not the one being edited
    assert editor.draft.get("superseded_by") == new.uuid
    editor.save_changes()
    assert old.get("superseded_by") == new.uuid
    p.close()


def test_items_cited_in_the_text_of_an_adr_become_its_srs_items(tmp_path):
    p, section, c2, c3 = build(tmp_path)
    adr = p.new_element("adr", title="Decisione")
    adr.values["affected"] = "Voci 3.14.4.3 e 3.14.4.2 (e 9.9.9 non importata); funzione SF-DF06-01."
    p.save()
    reopened = Project.open(tmp_path / "p")
    migrated = reopened.model.get(adr.uuid)
    assert migrated.get("srs_items") == [c3.uuid, c2.uuid]
    assert migrated.get("affected").startswith("Voci 3.14.4.3")  # the text stays as it is


def test_a_new_adr_on_the_item_justifies_a_change_of_domain(tmp_path):
    p, section, c2, c3 = build(tmp_path)
    d1, d2 = p.new_element("domain", name="Uno"), p.new_element("domain", name="Due")
    section.set("primary_domain", d1.uuid)
    published = Model([e.copy() for e in p.model])
    section.set("primary_domain", d2.uuid)
    assert [f.code for f in run(p.model, {"VER-02"}, published=published)] == ["VER-02"]
    p.new_element("adr", title="Sezione spostata", srs_items=[section.uuid])
    assert run(p.model, {"VER-02"}, published=published) == []
