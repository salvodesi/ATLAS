"""X-1 and X-2 as tables: a double click on the kind in the model tree opens a tab with the architectural decisions
or the requests for clarification, from which they are opened, created and deleted."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import arcadia_tool.ui.model_tree as model_tree
from arcadia_tool.storage.project import Project
from arcadia_tool.ui.element_list import ElementListPage
from arcadia_tool.ui.main_window import MainWindow
from arcadia_tool.ui.theme import apply_theme


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def recipients_asked(monkeypatch):
    """The window that asks the recipient of a new request: answered with the first one offered."""
    asked = []

    class Picker:
        def __init__(self, choices, selected, parent=None, single=False, title=""):
            asked.append((choices, set(selected)))
            self.choices = choices

        def exec(self):
            return True

        def selected(self):
            return [self.choices[0][0]]
    monkeypatch.setattr(model_tree, "RefPicker", Picker)
    return asked


def teams(p):
    t2 = p.new_element("team", name="Odometria")
    da = p.new_element("team", name="Architettura", design_authority=True)
    return da, t2


def buttons(page, row):
    return {b.text(): b for b in page.table.cellWidget(row, page.table.columnCount() - 1).findChildren(QPushButton)}


def test_double_click_on_x2_opens_the_table_of_the_requests(app, tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    da, t2 = teams(p)
    second = p.new_element("clarification", problem="Classificazione mancante", recipient=t2.uuid, status="Aperta")
    first = p.new_element("clarification", problem="Testo ambiguo", recipient=da.uuid, status="Chiusa")
    first.set("id", "CQ-01")
    second.set("id", "CQ-02")
    window = MainWindow()
    window.show()
    window._set_project(p)
    kind_item = window.tree._kind_items["clarification"]
    window.tree._double_clicked(kind_item, 0)
    page = window.list_pages["clarification"]
    assert window.pages.currentWidget() is page and not kind_item.isExpanded()  # a tab, not the branch
    table = page.table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["ID", "Destinatario della richiesta", "Stato", ""]
    rows = [[table.item(r, c).text() for c in range(3)] for r in range(table.rowCount())]
    assert rows == [["CQ-01", f"{da.get('id')} Architettura (Design Authority)", "Chiusa"],
                    ["CQ-02", f"{t2.get('id')} Odometria", "Aperta"]]
    assert "Testo ambiguo" in table.item(0, 0).toolTip()
    # The buttons are never cut: their column is as wide as they are.
    assert table.columnWidth(3) >= table.cellWidget(0, 3).sizeHint().width()

    buttons(page, 1)["Apri"].click()  # the sheet of the request in its tab
    assert window.pages.currentWidget() is window.editors[second.uuid]
    page._double_clicked(0, 1)  # a double click on the row too
    assert window.pages.currentWidget() is window.editors[first.uuid]

    first.set("status", "Aperta")  # changed in its sheet: the table follows
    p.update(first)
    window._element_changed(first)
    assert table.item(0, 2).text() == "Aperta"
    page.search.setText("odometria")
    assert table.isRowHidden(0) and not table.isRowHidden(1) and page.count.text() == "1 di 2"

    window.tree._double_clicked(kind_item, 0)  # opened again: the same tab
    assert list(window.list_pages.values()) == [page]
    window._set_project(None)  # closed with the project
    assert window.list_pages == {}
    window.close()


def test_requests_are_created_with_their_recipient_and_deleted(app, tmp_path, monkeypatch, recipients_asked):
    p = Project.create(tmp_path / "p", "Prova")
    window = MainWindow()
    window.show()
    window._set_project(p)
    window.open_element_list("clarification")
    page = window.list_pages["clarification"]
    # Empty: a message in the middle of the page with the button to create the first request, no search.
    assert page.body.currentWidget() is page.empty and page.search.isHidden()
    assert page.empty_text.text() == "Nessuna richiesta di chiarimento" and page.count.text() == "0 richieste"
    first = next(b for b in page.empty.findChildren(QPushButton))
    assert first.text() == "Nuova richiesta di chiarimento"
    first.click()  # no team yet: a recipient is needed first
    assert not p.model.of_kind("clarification") and not recipients_asked

    da, t2 = teams(p)
    first.click()  # the recipient is asked: the Design Authority first (and proposed), then the teams
    [(choices, proposed)] = recipients_asked
    assert [label for _, label in choices] == [p.model.label(da), p.model.label(t2)] and proposed == {da.uuid}
    [request] = p.model.of_kind("clarification")
    assert request.get("id") == "CQ-01" and request.get("recipient") == da.uuid
    assert window.editors[request.uuid].editing  # its sheet opened in edit mode
    assert page.body.currentWidget() is page.table and page.table.item(0, 1).text().endswith("(Design Authority)")
    page.new_button.click()  # «Nuova richiesta», always in the header
    assert len(p.model.of_kind("clarification")) == 2 and page.count.text() == "2 richieste"
    window.pages.setCurrentWidget(page)  # back to the table

    assert set(buttons(page, 0)) == {"Apri", "Elimina"}  # two buttons of the same kind (same style)
    buttons(page, 0)["Elimina"].click()  # asked to confirm: «No» (tests)
    assert len(p.model.of_kind("clarification")) == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    buttons(page, 0)["Elimina"].click()
    assert [e.get("id") for e in p.model.of_kind("clarification")] == ["CQ-02"]
    assert page.table.rowCount() == 1 and window.pages.currentWidget() is page
    assert request.uuid not in window.editors  # its open sheet closed with it
    window.close()


def test_the_clause_of_a_request_is_chosen_with_ticks(app, tmp_path, monkeypatch):
    import arcadia_tool.ui.srs_trace as srs_trace
    from arcadia_tool.ui.element_editor import ElementEditor
    p = Project.create(tmp_path / "p", "Prova")
    section = p.new_element("requirement", id="3.15.1", item_type="Sezione")
    clause = p.new_element("requirement", id="3.15.1.3.9", item_type="Requisito", parent=section.uuid)
    request = p.new_element("clarification", problem="Nessuna categoria")
    assert request.schema.field("clause").picker  # like the other references to the specification
    used = []

    class Ticks(srs_trace.TraceClauseDialog):
        def exec(self):
            used.append(type(self))
            self.set_state(clause.uuid, srs_trace.PARENT)  # the clause ticked
            self.changed = self.apply()
            return True
    monkeypatch.setitem(srs_trace.ITEM_DIALOGS, "clause", Ticks)
    editor = ElementEditor()
    editor.edit(p, request, editing=True)
    editor._pick(request.schema.field("clause"))
    assert used == [Ticks] and editor.draft.get("clause") == clause.uuid
    editor.save_changes()
    assert request.get("clause") == clause.uuid


def test_recipients_written_as_text_become_teams(tmp_path):
    from arcadia_tool.model.serialization import dumps
    p = Project.create(tmp_path / "p", "Prova")
    da, t2 = teams(p)
    texts = ["DA", t2.get("id"), "odometria", "ERA / UNISIG"]
    requests = [p.new_element("clarification", problem=f"P{i}") for i in range(4)]
    for request, text in zip(requests, texts):
        request.values["recipient"] = text  # as earlier versions saved it
    p.save()
    reopened = Project.open(tmp_path / "p")
    recipients = [reopened.model.get(r.uuid).get("recipient") for r in requests]
    assert recipients == [da.uuid, t2.uuid, t2.uuid, None]
    assert reopened.model.get(requests[3].uuid).get("recipient_text") == "ERA / UNISIG"  # kept, shown in the table
    page = ElementListPage(reopened, "clarification")
    row = next(r for r in range(page.table.rowCount()) if page.table.item(r, 1).text() == "ERA / UNISIG")
    assert row is not None


def test_x1_lists_the_architectural_decisions(app, tmp_path, monkeypatch):
    p = Project.create(tmp_path / "p", "Prova")
    adr = p.new_element("adr", title="MRSP in un dominio autonomo", date_decider="12/10/2026 · DA",
                        status="Decisa", context="La catena rimbalza tra DF03 e DF04.")
    window = MainWindow()
    window.show()
    window._set_project(p)
    window.tree._double_clicked(window.tree._kind_items["adr"], 0)
    page = window.list_pages["adr"]
    table = page.table
    assert [table.horizontalHeaderItem(c).text() for c in range(4)] == ["ID", "Titolo", "Data e decisore", "Stato"]
    assert [table.item(0, c).text() for c in range(4)] == ["ADR-001", "MRSP in un dominio autonomo",
                                                           "12/10/2026 · DA", "Decisa"]
    assert "rimbalza" in table.item(0, 0).toolTip() and page.count.text() == "1 ADR"
    page.new_button.click()  # created (no context to ask) and opened
    new = next(e for e in p.model.of_kind("adr") if e.uuid != adr.uuid)
    assert new.get("id") == "ADR-002" and window.editors[new.uuid].editing
    window.pages.setCurrentWidget(page)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    buttons(page, 1)["Elimina"].click()
    assert [e.get("id") for e in p.model.of_kind("adr")] == ["ADR-001"]
    window.close()


@pytest.mark.parametrize("kind, text", [("clarification", "0 richieste"), ("adr", "0 ADR")])
def test_empty_list(app, tmp_path, kind, text):
    p = Project.create(tmp_path / "p", "Prova")
    page = ElementListPage(p, kind)
    assert page.table.rowCount() == 0 and page.body.currentWidget() is page.empty
    assert page.count.text() == text
