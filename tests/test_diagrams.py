"""Graphic views of the SA: the functional breakdown (SA-1, SA-2) and the views composed by the user (dataflow
under SA-5, chain and scenario under SA-7), in the model tree under their SA and saved with «Salva vista»."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QPushButton

from arcadia_tool.model import diagrams as dg
from arcadia_tool.model.schema import DIAGRAM_CHAIN, DIAGRAM_DATAFLOW, DIAGRAM_SCENARIO
from arcadia_tool.storage.project import Project
from arcadia_tool.ui import model_tree
from arcadia_tool.ui.diagrams import CELL_H, CELL_W, TITLE_H, BreakdownPage, DiagramPage, breakdown_layout


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(tmp_path):
    """DF02, DF05, DF06, DF11 with their functions, the RBC, the exchanges of the braking and a chain that goes
    back to DF06 after DF11."""
    p = Project.create(tmp_path / "p", "Prova")
    d = {n: p.new_element("domain", id=f"DF{n:02d}", name=f"Dominio {n}") for n in (2, 5, 6, 11)}
    f = {}
    for n, k, name in ((2, 1, "Determinare la velocità"), (5, 1, "Supervisionare sull'MRSP"),
                       (6, 4, "Supervisionare lo standstill"), (6, 6, "Comandare la frenatura"),
                       (11, 1, "Gestire i comandi di frenatura"), (11, 2, "Acquisire gli ingressi")):
        f[(n, k)] = p.new_element("system_function", id=f"SF-DF{n:02d}-{k:02d}", name=name, domain=d[n].uuid)
    alone = p.new_element("system_function", id="SF-X", name="Senza dominio")
    rbc = p.new_element("external_actor", name="RBC")

    def exchange(ident, s, t, data, nature):
        item = p.new_element("exchange_item", id=f"EI-{data}", name=data, nature=nature)
        return p.new_element("functional_exchange", id=ident, source=s.uuid, target=t.uuid,
                             exchange_item=item.uuid, nature=nature)

    x = {
        "speed": exchange("FE-DF02-DF06-01", f[(2, 1)], f[(6, 4)], "Velocità", "FLOW"),
        "brake_request": exchange("FE-DF05-DF06-01", f[(5, 1)], f[(6, 6)], "Richiesta di frenatura", "EVENT"),
        "brake": exchange("FE-DF06-DF11-01", f[(6, 6)], f[(11, 1)], "Comando dei freni", "FLOW"),
        "inputs": exchange("FE-DF11-DF06-01", f[(11, 2)], f[(6, 4)], "Ingressi dal treno", "FLOW"),
        "ma": exchange("FE-RBC-DF05-01", rbc, f[(5, 1)], "MA", "EVENT"),
    }
    chain = p.new_element("functional_chain", id="FC-FRENI", title="Frenatura", steps=[
        {"cycle": "1", "function": f[(5, 1)].uuid, "what": "Chiede la frenatura", "data": "Richiesta",
         "nature": "EVENT", "exchange": x["brake_request"].uuid},
        {"cycle": "1", "function": f[(6, 6)].uuid, "what": "Comanda i freni", "data": "Comando", "nature": "FLOW",
         "exchange": x["brake"].uuid},
        {"cycle": "2", "function": f[(11, 2)].uuid, "what": "Legge gli ingressi", "data": "Ingressi",
         "nature": "FLOW", "exchange": x["inputs"].uuid},
        {"cycle": "2", "function": f[(6, 4)].uuid, "what": "Verifica lo standstill", "data": "Standstill"},
    ])
    section = p.new_element("requirement", id="3.11", item_type="Sezione", sequence=1)
    c1, c2 = (p.new_element("requirement", id=f"3.11.{n}", item_type="Requisito", parent=section.uuid, sequence=n + 1)
              for n in (1, 2))
    p.new_element("trace_record", requirement=c1.uuid, primary_function=f[(6, 4)].uuid)
    p.new_element("trace_record", requirement=c2.uuid, primary_function=f[(6, 6)].uuid,
                  secondary_functions=[f[(6, 4)].uuid])
    # Allocated from its sheet (or the import of SA-2), without SA-3 records: its clauses are counted too.
    f[(11, 1)].set("sections", [section.uuid])
    p.update(f[(11, 1)])
    p.new_element("trace_record", requirement=c1.uuid, primary_function=f[(11, 1)].uuid)  # within its section
    return p, d, f, x, chain, rbc, alone


def view(p, diagram_type, keys=(), chain=None, name="Vista"):
    layout = dg.new_view_layout(p.model, diagram_type, chain.uuid) if chain else {k: "" for k in keys}
    return p.new_element("diagram", name=name, diagram_type=diagram_type, layout=layout,
                         **({"chain": chain.uuid} if chain else {}))


def test_the_breakdown_has_the_domains_with_their_functions_and_traced_items(tmp_path):
    p, d, f, *_, alone = build(tmp_path)
    domains = dg.breakdown(p.model)
    assert [x.ident for x in domains] == ["DF02", "DF05", "DF06", "DF11", ""]
    df06 = domains[2]
    assert [(g.ident, g.clauses) for g in df06.functions] == [("SF-DF06-04", 2), ("SF-DF06-06", 1)]
    assert [(g.ident, g.clauses) for g in domains[3].functions] == [("SF-DF11-01", 1), ("SF-DF11-02", 0)]
    # Only allocated, never in an SA-3 record (as after the import of SA-2).
    f[(2, 1)].set("sections", [p.model.of_kind("requirement")[1].uuid, p.model.of_kind("requirement")[2].uuid])
    assert [g.clauses for g in dg.breakdown(p.model)[0].functions] == [2]
    assert domains[-1].name == "Funzioni senza dominio" and domains[-1].functions[0].uuid == alone.uuid
    # An open domain is as wide as the others and higher; the others flow around it.
    blocks = breakdown_layout(domains, {d[5].uuid})
    sizes = {x[0].ident: x[3:] for x in blocks}
    assert sizes["DF05"][0] == sizes["DF02"][0] == CELL_W and sizes["DF05"][1] > sizes["DF02"][1]


def test_a_breakdown_of_the_user_shows_the_domains_and_the_functions_added(app, tmp_path):
    from arcadia_tool.model.schema import DIAGRAM_BREAKDOWN
    p, d, f, *_ = build(tmp_path)
    v = view(p, DIAGRAM_BREAKDOWN, [d[6].uuid, f[(11, 2)].uuid])
    shown = dg.view_breakdown(p.model, v)
    # DF06 added: all its functions; SF-DF11-02 added alone: in the block of DF11, with only it.
    assert [(x.ident, [g.ident for g in x.functions], x.partial) for x in shown] == [
        ("DF06", ["SF-DF06-04", "SF-DF06-06"], False), ("DF11", ["SF-DF11-02"], True)]
    keys = [a.key for a in dg.addable(p.model, v)]
    assert d[2].uuid in keys and d[11].uuid in keys and f[(11, 1)].uuid in keys
    assert d[6].uuid not in keys and f[(6, 4)].uuid not in keys and f[(11, 2)].uuid not in keys
    page = DiagramPage(p, v)
    assert page.items[d[11].uuid].opened and not page.items[d[6].uuid].opened  # added alone: always open
    page.toggle(d[6].uuid)  # a click on the domain
    assert page.dirty and page.items[d[6].uuid].opened
    page.save_view()
    assert v.get("opened") == [d[6].uuid]  # the domains open are saved with the view
    page.items[d[11].uuid].setSelected(True)
    page.remove_selected()  # the block and its function added alone
    assert set(page.placed) == {d[6].uuid}
    # Created from the group of SA-1: the type is not asked.
    from arcadia_tool.ui.diagrams import NewViewDialog
    dialog = NewViewDialog(p.model, [DIAGRAM_BREAKDOWN])
    assert dialog.type.isHidden() and dialog.values()["diagram_type"] == DIAGRAM_BREAKDOWN
    assert not NewViewDialog(p.model, list(dg.BREAKDOWN_TYPES)).type.isHidden()  # «+ Nuova vista…»: asked
    # «Funzioni per dominio» (SA-2): a domain added shows its functions at once.
    from arcadia_tool.model.schema import DIAGRAM_FUNCTIONS
    by_function = p.new_element("diagram", name="Funzioni", diagram_type=DIAGRAM_FUNCTIONS)
    page = DiagramPage(p, by_function)
    page.add(d[2].uuid)
    assert page.items[d[2].uuid].opened


def test_the_breakdowns_create_system_functions_for_all_the_views(app, tmp_path, monkeypatch):
    from arcadia_tool.model.schema import DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.diagrams import NewFunctionDialog

    p, d, f, *_ = build(tmp_path)
    p.save()
    names = iter(["Supervisionare il roll away", "Supervisionare il moto indietro", "Leggere la cabina",
                  "Gestire le uscite"])

    def fill(dialog):
        dialog.name.setText(next(names))
        return True

    monkeypatch.setattr(NewFunctionDialog, "exec", fill)
    # From the overview of SA-1: in the domain asked (right click on its block), which shows only its name.
    page = BreakdownPage(p)
    created = page.new_function(d[6].uuid)
    assert created.get("domain") == d[6].uuid and created.get("id") == "SF-DF06-01"  # the first free ID of DF06
    assert not page.opened and created.uuid in {g.uuid for g in page.blocks[d[6].uuid].domain.functions}
    # From the overview of SA-2: its domain open on it.
    page = BreakdownPage(p, functions=True)
    page.close_all()
    page.new_function(d[6].uuid)
    assert page.opened == {d[6].uuid}
    # From a view of the user (SA-2) whose domain is not in it: the function is added to the view by itself.
    v = view(p, DIAGRAM_FUNCTIONS, [d[6].uuid])
    page = DiagramPage(p, v)
    alone = page.new_function(d[2].uuid)
    assert alone.uuid in page.placed and page.dirty
    inside = page.new_function(d[6].uuid)  # its domain is in the view: it shows it
    assert inside.uuid not in page.placed and inside.uuid in {g.uuid for g in page.items[d[6].uuid].domain.functions}
    # Among the elements of the other views.
    flow = view(p, DIAGRAM_DATAFLOW)
    assert {created.uuid, alone.uuid, inside.uuid} <= {a.key for a in dg.addable(p.model, flow)}
    # In the main window: saved with the project and in the model tree.
    names = iter(["Comandare le uscite"])
    window = mw.MainWindow()
    window._set_project(p)
    window.open_breakdown("system_function")
    sa2 = window.pages.currentWidget()
    made = sa2.new_function(d[11].uuid)
    assert made.uuid in window.tree._items
    # Written at once, only it: the changes made before elsewhere (here without a window) are still to be saved.
    assert made.uuid not in p.changes_since(0) and alone.uuid in p.changes_since(0)
    assert DIAGRAM_BREAKDOWN in dg.BREAKDOWN_TYPES


def test_the_views_of_sa1_create_functional_domains(app, tmp_path, monkeypatch):
    from arcadia_tool.model.schema import DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.diagrams import NewDomainDialog

    p, d, *_ = build(tmp_path)
    p.save()
    names = iter(["Gestire l'odometria", "Gestire la cabina"])

    def fill(dialog):
        dialog.name.setText(next(names))
        return True

    monkeypatch.setattr(NewDomainDialog, "exec", fill)
    window = mw.MainWindow()
    window._set_project(p)
    # The overview of SA-1: «Nuovo dominio…» in place of «Nuova funzione…»; saved, in the tree and in the view.
    window.open_breakdown("domain")
    sa1 = window.pages.currentWidget()
    buttons = [b.text() for b in sa1.findChildren(mw.QPushButton)]
    assert "Nuovo dominio…" in buttons and "Nuova funzione…" not in buttons
    made = sa1.new_domain()
    assert made.get("id") == "DF01" and made.get("name") == "Gestire l'odometria"  # the first free ID
    assert not p.is_modified and made.uuid in window.tree._items and made.uuid in sa1.blocks
    # A view of SA-1 of the user: the domain is added to it; in a view of SA-2 the button is «Nuova funzione…».
    page = DiagramPage(p, view(p, DIAGRAM_BREAKDOWN, [d[6].uuid]))
    assert not page.domain_button.isHidden() and page.function_button.isHidden()
    other = page.new_domain()
    assert other.uuid in page.placed and other.uuid in page.items and page.dirty
    page = DiagramPage(p, view(p, DIAGRAM_FUNCTIONS, [d[6].uuid]))
    assert page.domain_button.isHidden() and not page.function_button.isHidden()


def test_a_dataflow_draws_the_exchanges_between_the_elements_added(tmp_path):
    p, d, f, x, *_ = build(tmp_path)
    v = view(p, DIAGRAM_DATAFLOW, [f[(5, 1)].uuid, f[(6, 4)].uuid, f[(6, 6)].uuid, d[11].uuid])
    df = dg.dataflow(p.model, v)
    # The functions in the block of their domain; DF11 added alone is a block that stands for its functions.
    assert set(df.containers) == {d[5].uuid, d[6].uuid} and df.containers[d[6].uuid].members == [
        f[(6, 4)].uuid, f[(6, 6)].uuid]
    assert df.nodes[d[11].uuid].kind == "domain"
    edges = {(e.source, e.target): e for e in df.edges}
    assert set(edges) == {(f[(5, 1)].uuid, f[(6, 6)].uuid), (f[(6, 6)].uuid, d[11].uuid),
                          (d[11].uuid, f[(6, 4)].uuid)}
    request = edges[(f[(5, 1)].uuid, f[(6, 6)].uuid)]
    assert request.event and request.exchanges[0].data == "Richiesta di frenatura"
    assert request.exchanges[0].ident == "FE-DF05-DF06-01"
    # Exchanges with elements not in the view: counted on the element (DF02 → standstill, RBC → MRSP).
    assert df.nodes[f[(6, 4)].uuid].outside == 1 and df.nodes[f[(5, 1)].uuid].outside == 1
    # Placed from the producers to the users; the exchanges both ways (DF06 ⇄ DF11) do not push the columns.
    placed = dg.auto_layout(df)
    assert placed[f[(5, 1)].uuid][0] < placed[f[(6, 4)].uuid][0] < placed[d[11].uuid][0]
    assert placed[f[(6, 4)].uuid][0] == placed[f[(6, 6)].uuid][0]
    # What is placed stays where it is; the others are put next to it.
    again = dg.auto_layout(df, {f[(5, 1)].uuid: (500, 300)})
    assert again[f[(5, 1)].uuid] == (500, 300) and len(again) == len(df.nodes)


def test_a_connector_between_two_functions_creates_the_exchange_and_its_datum(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import diagrams as ui
    from arcadia_tool.ui.diagrams import Arrow, NewExchangeDialog

    p, d, f, *_ = build(tmp_path)
    a, b = f[(2, 1)].uuid, f[(5, 1)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b, d[11].uuid]))
    assert page.side_tabs.isTabVisible(0) and page.connector_buttons[None].isChecked()  # the hand, at first
    assert page.side_tabs.currentWidget() is page.connectors  # a view with elements: on the tools
    assert [page.side_tabs.tabText(i) for i in range(2)] == ["Strumenti", "Elementi"]
    empty = DiagramPage(p, view(p, DIAGRAM_DATAFLOW))
    assert empty.side_tabs.currentWidget() is empty.listing  # an empty view: on the elements to add
    from arcadia_tool.model.schema import DIAGRAM_BREAKDOWN
    other = DiagramPage(p, view(p, DIAGRAM_BREAKDOWN, [d[6].uuid]))
    assert not other.side_tabs.isTabVisible(0) and other.side_tabs.currentWidget() is other.listing  # no tools
    # The tabs chosen from the bar of icons at the right, as the panel of the window: no tools icon without tools.
    assert page.side_tabs.tabBar().isHidden() and len(page.activity.buttons) == 2
    assert page.side_caption.text() == "STRUMENTI" and other.side_caption.text() == "ELEMENTI"
    assert not other.activity.buttons[0].isVisibleTo(other) and other.activity.buttons[1].isChecked()
    assert not hasattr(page, "add_button") and not hasattr(page, "remove_button") and not hasattr(page, "undo_button")
    page.activity.choose(1)
    assert page.side_tabs.currentWidget() is page.listing and page.activity.buttons[1].isChecked()
    page.activity.choose(1)  # the icon of the tab shown: the panel closed, kept for the views opened next
    assert page.side.isHidden() and not any(b.isChecked() for b in page.activity.buttons)
    assert DiagramPage(p, page.view).side.isHidden()
    page.activity.choose(0)
    assert not page.side.isHidden() and page.side_tabs.currentWidget() is page.connectors
    created = []
    page.element_created.connect(created.append)
    chosen = []

    def fill(dialog):
        chosen.append(dialog.item.currentData())
        if dialog.item.currentData() == ui.NEW_ITEM:
            dialog.name.setText("Richiesta di posizione")
        return True

    monkeypatch.setattr(NewExchangeDialog, "exec", fill)
    assert page.connect_elements(a, b) is None  # no connector chosen: the elements are moved
    page.connector_buttons["OPERATION"].setChecked(True)
    assert page.connector == "OPERATION" and page.canvas.connecting is not None
    assert page.connect_elements(a, d[11].uuid) is None  # a domain alone is not an end
    fe = page.connect_elements(a, b)
    item = p.model.get(fe.get("exchange_item"))
    assert fe.get("id") == "FE-DF02-DF05-01" and fe.get("nature") == "OPERATION" and fe.get("name") == item.get("name")
    assert item.get("id") == "EI-RichiestaDiPosizione" and item.get("nature") == "OPERATION"
    assert created == [item.uuid, fe.uuid]
    arrow = next(i for i in page.scene.items() if isinstance(i, Arrow) and fe.uuid in i.exchanges)
    assert arrow.nature == "OPERATION"
    # Canc on the arrow: out of the model; the datum, no more carried, kept in the dictionary (asked).
    yes, no = ui.QMessageBox.Yes, ui.QMessageBox.No
    answers = iter([yes, no])
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *args, **kwargs: next(answers))
    edited = []
    page.model_edited.connect(edited.append)
    arrow.setSelected(True)
    page.delete_selected()
    assert p.model.get(fe.uuid) is None and p.model.get(item.uuid) is not None and edited
    # Drawn again between the same functions: the datum is proposed again.
    again = page.connect_elements(a, b)
    assert chosen[-1] == item.uuid and again.get("exchange_item") == item.uuid
    # Deleted with its datum.
    answers = iter([yes, yes])
    page.delete_exchanges([again.uuid])
    assert p.model.get(again.uuid) is None and p.model.get(item.uuid) is None
    # The same datum again between the same functions: an error, the connector not drawn.
    warned = []
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[2]))
    first = page.connect_elements(a, b)  # «Nuovo dato…» «Richiesta di posizione»
    dialog = NewExchangeDialog(p.model, a, b, "OPERATION")
    dialog.item.setCurrentIndex(dialog.item.findData(first.get("exchange_item")))
    assert "già scambiato tra questi elementi" in dialog.item.currentText()
    dialog.accept()
    assert dialog.result() == 0 and warned and "FE-DF02-DF05-" in warned[-1]
    dialog = NewExchangeDialog(p.model, a, b, "OPERATION")  # a new datum with the same name
    dialog.name.setText("richiesta di posizione")
    dialog.accept()
    assert dialog.result() == 0 and len(warned) == 2
    other = NewExchangeDialog(p.model, b, a, "OPERATION")  # the other way: another exchange
    other.item.setCurrentIndex(other.item.findData(first.get("exchange_item")))
    other.accept()
    assert len(warned) == 2
    count = len(p.model.of_kind("functional_exchange"))
    monkeypatch.setattr(NewExchangeDialog, "exec", lambda dialog: dialog.name.setText("Richiesta di posizione")
                        or dialog.accept() or dialog.result() == 1)
    assert page.connect_elements(a, b) is None and len(p.model.of_kind("functional_exchange")) == count
    # The data proposed for a connector: of its nature, those no exchange carries first.
    spare = p.new_element("exchange_item", name="Libero", nature="EVENT")
    assert dg.exchange_items_for(p.model, "EVENT")[0].uuid == spare.uuid
    assert all(i.get("nature") == "EVENT" for i in dg.exchange_items_for(p.model, "EVENT"))
    page.connector_buttons[None].click()  # the hand: the elements are moved again
    assert page.canvas.connecting is None and not page.connector_buttons["OPERATION"].isChecked()
    assert page.connector_buttons[None].isChecked()
    page.connector_buttons[None].click()  # clicked again, it stays
    assert page.connector_buttons[None].isChecked() and page.connector is None
    # An EVENT is produced on an event: not to be chosen; an OPERATION is proposed on request.
    event = NewExchangeDialog(p.model, a, b, "EVENT")
    assert event.condition.currentText() == "Su evento" and not event.condition.isEnabled()
    operation = NewExchangeDialog(p.model, a, b, "OPERATION")
    assert operation.condition.currentText() == "Su richiesta" and operation.condition.isEnabled()


def test_a_connector_is_drawn_with_the_mouse_from_a_function_to_another(app, tmp_path):
    from PySide6.QtTest import QTest

    p, d, f, *_ = build(tmp_path)
    a, b = f[(2, 1)].uuid, f[(5, 1)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b]))
    page.resize(1300, 600)
    page.show()
    app.processEvents()
    page.canvas.connected.disconnect()  # the drag only, not the window of the exchange
    got = []
    page.canvas.connected.connect(lambda s, t, sa, ta: got.append((s, t, sa, ta)))
    page.connector_buttons["FLOW"].setChecked(True)

    def at(key):
        item = page.items[key]
        return page.canvas.mapFromScene(item.mapToScene(item.rect().center()))

    button = page.connector_buttons["FLOW"]
    assert button.isChecked() and "checked" in button.styleSheet()  # shown as chosen in the side panel
    before = page.items[a].pos()
    viewport = page.canvas.viewport()
    QTest.mouseMove(viewport, at(a))  # the pointer on a function: it can be an end
    assert page.items[a].highlighted and not page.items[b].highlighted
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, at(a))
    QTest.mouseMove(viewport, at(b))
    assert page.items[a].highlighted and page.items[b].highlighted  # the start and the end
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, at(b))
    assert [g[:2] for g in got] == [(a, b)] and page.items[a].pos() == before and not page.dirty  # not moved
    assert all(anchor[0] in "LRTB" and anchor[1:].isdigit() for anchor in got[0][2:])  # anchor to anchor
    page.set_connector(None)
    assert not page.items[b].highlighted
    page.close()


def test_the_arrows_of_a_dataflow_go_around_the_elements_and_follow_the_blocks(app, tmp_path):
    from PySide6.QtCore import QRectF
    from arcadia_tool.ui.diagrams import Arrow, Block, _crosses, orthogonal_route

    # In line: one straight stretch; an element in between: around it, in horizontal and vertical stretches.
    a, b, wall = QRectF(0, 0, 100, 60), QRectF(400, 0, 100, 60), QRectF(200, -20, 100, 100)
    assert len(orthogonal_route(a, b, [])) == 2
    around = orthogonal_route(a, b, [wall])
    stretches = list(zip(around, around[1:]))
    assert all(p.x() == q.x() or p.y() == q.y() for p, q in stretches)
    assert not any(_crosses(p, q, wall) for p, q in stretches)
    assert around[0].x() in (0, 100) or around[0].y() in (0, 60)  # out of a side of a, into a side of b
    # In the view: moving the block of a domain draws the arrows again around the others, once after the move.
    p, d, f, x, *_ = build(tmp_path)
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid, f[(6, 4)].uuid, f[(6, 6)].uuid]))
    arrow = next(i for i in page.arrows if x["speed"].uuid in i.exchanges)
    block = next(b for b in page.blocks if b.key == d[2].uuid)
    before = list(arrow._points)
    for member in block.members:
        member.moveBy(0, 400)
    assert page._routing.isActive() and arrow._points == before  # not at every function moved
    page._routing.timeout.emit()
    after = arrow._points
    assert after != before and all(p.x() == q.x() or p.y() == q.y() for p, q in zip(after, after[1:]))
    others = [i.mapRectToScene(i.rect()) for i in page._obstacles(page.items[f[(2, 1)].uuid],
                                                                  page.items[f[(6, 4)].uuid])]
    assert not any(_crosses(p, q, r.adjusted(-3, -3, 3, 3)) for p, q in zip(after, after[1:]) for r in others)
    assert isinstance(block, Block) and isinstance(arrow, Arrow)


class _Drag:
    def __init__(self, x, y, modifiers=Qt.NoModifier):
        self._pos, self._modifiers = QPointF(x, y), modifiers

    def scenePos(self):
        return self._pos

    def button(self):
        return Qt.LeftButton

    def modifiers(self):
        return self._modifiers

    def accept(self):
        pass


def test_a_connector_goes_from_an_anchor_point_to_another_and_its_arrow_keeps_them(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QRectF
    from arcadia_tool.ui.diagrams import NewExchangeDialog, anchor_point, anchor_points, nearest_anchor

    from arcadia_tool.ui.diagrams import anchor_ids, side_anchors

    rect = QRectF(0, 0, 200, 80)
    assert len(anchor_points(rect)) == 12 and anchor_point(rect, "R500") == QPointF(200, 40)
    assert nearest_anchor(rect, QPointF(195, 18)) == "R250" and nearest_anchor(rect, QPointF(150, 90)) == "B750"
    # Twelve; a side with its three taken offers more between them, and so on.
    assert side_anchors() == [250, 500, 750] and side_anchors({500}) == [250, 500, 750]
    assert side_anchors({250, 500, 750}) == [125, 250, 375, 500, 625, 750, 875]
    assert len(anchor_ids({"R250", "R500", "R750"})) == 3 * 3 + 7
    p, d, f, *_ = build(tmp_path)
    a, b = f[(2, 1)].uuid, f[(5, 1)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b]))
    monkeypatch.setattr(NewExchangeDialog, "exec", lambda dialog: dialog.name.setText("Posizione") or True)
    page.set_connector("FLOW")
    fe = page.connect_elements(a, b, "B500", "T250")
    arrow = next(i for i in page.arrows if fe.uuid in i.exchanges)
    ra, rb = (page.items[k].mapRectToScene(page.items[k].rect()) for k in (a, b))
    assert arrow._points[0] == anchor_point(ra, "B500") and arrow._points[-1] == anchor_point(rb, "T250")
    assert page.dirty  # the anchors are part of the view: saved with it
    page.save_view()
    assert page.view.get("anchors") == {fe.uuid: "B500 T250"}
    assert page.items[a].used_anchors == {"B500"} and page.items[b].used_anchors == {"T250"}
    # Moved, the arrow still leaves and reaches the same anchor points.
    page.items[b].moveBy(300, 200)
    page._refresh_arrows()
    rb = page.items[b].mapRectToScene(page.items[b].rect())
    assert arrow._points[-1] == anchor_point(rb, "T250")
    # The pointer on a function with a connector chosen: highlighted with its anchor points, the nearest filled.
    box = page.items[a]
    page.canvas.highlight({box: "R750"})
    assert box.highlighted and box.hot_anchor == "R750"
    page.canvas.highlight()
    assert not box.highlighted and box.hot_anchor is None


def test_an_end_of_an_arrow_is_moved_to_another_anchor_point_of_its_element(app, tmp_path):
    from PySide6.QtTest import QTest
    from arcadia_tool.ui.diagrams import anchor_point

    p, d, f, x, *_ = build(tmp_path)
    a, b = f[(2, 1)].uuid, f[(6, 4)].uuid  # FE-DF02-DF06-01, «Velocità»
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b]))
    page.resize(1300, 700)
    page.show()
    app.processEvents()
    arrow = next(i for i in page.arrows if x["speed"].uuid in i.exchanges)
    assert arrow.movable_ends
    viewport = page.canvas.viewport()

    def on_screen(point):
        return page.canvas.mapFromScene(point)

    # Its handles shown even when not selected (the choice of the right click on the canvas: only when selected).
    assert not arrow.isSelected() and arrow.handle_at(arrow._b) == 1
    page.show_handles(False)
    assert arrow.handle_at(arrow._b) is None
    arrow.setSelected(True)
    assert arrow.handle_at(arrow._b) == 1
    arrow.setSelected(False)
    assert not DiagramPage(p, page.view).arrows[0].handles_always  # kept for the views opened next
    page.show_handles(True)
    # The choice is in the menu of a right click on an empty place of the canvas (not on an element).
    from PySide6.QtGui import QContextMenuEvent
    asked = []
    page.canvas.menu_requested.disconnect()
    page.canvas.menu_requested.connect(asked.append)
    empty = on_screen(page.scene.itemsBoundingRect().bottomRight() + QPointF(100, 100))
    QApplication.sendEvent(viewport, QContextMenuEvent(QContextMenuEvent.Mouse, empty, viewport.mapToGlobal(empty)))
    assert len(asked) == 1
    page.canvas.menu_requested.disconnect()
    page.canvas.menu_requested.connect(page._canvas_menu)
    # Its end on DF06 dragged to the bottom of the box.
    rb = page.items[b].mapRectToScene(page.items[b].rect())
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, on_screen(arrow._b))
    QTest.mouseMove(viewport, on_screen(anchor_point(rb, "B750")))
    assert page.items[b].highlighted and page.items[b].hot_anchor == "B750"
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, on_screen(anchor_point(rb, "B750")))
    assert page.anchors[x["speed"].uuid].split()[1] == "B750" and page.dirty
    arrow = next(i for i in page.arrows if x["speed"].uuid in i.exchanges)
    assert arrow._points[-1] == anchor_point(rb, "B750")
    assert not page.items[b].highlighted
    # Released away from its element: nothing changes. Ctrl+Z: the end back where it was.
    arrow.setSelected(True)
    before = dict(page.anchors)
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, on_screen(arrow._b))
    QTest.mouseMove(viewport, on_screen(arrow._b + QPointF(0, 300)))
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, on_screen(arrow._b + QPointF(0, 300)))
    assert page.anchors == before
    assert page.undo() and x["speed"].uuid not in page.anchors
    page.close()


def test_ctrl_z_undoes_the_changes_of_a_view_and_ctrl_y_does_them_again(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import diagrams as ui
    from arcadia_tool.ui.diagrams import NewDomainDialog, NewExchangeDialog

    p, d, f, x, *_ = build(tmp_path)
    a, b = f[(2, 1)].uuid, f[(5, 1)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a]))
    assert not page.undo()  # nothing to undo
    edited = []
    page.model_edited.connect(edited.append)
    # An element added, then a drag (one change, however many steps): undone in reverse order.
    page.add(b)
    box = page.items[b]
    start = box.pos()
    page.canvas.pressed.emit()
    box.moveBy(40, 0)
    box.moveBy(40, 30)
    page.canvas.released.emit()
    assert page.placed[b] == (start.x() + 80, start.y() + 30) and page.dirty
    assert page.undo() and page.placed[b] == (start.x(), start.y())  # the drag
    assert page.undo() and b not in page.placed and not page.dirty  # the element added: as saved
    assert page.redo() and b in page.placed and page.dirty
    assert page.redo() and page.placed[b] == (start.x() + 80, start.y() + 30)
    # A change after an undo: nothing left to do again.
    page.undo()
    page.arrange()
    assert not page.redo()
    # An exchange created with a connector: undone, out of the model with its new datum; done again, back.
    monkeypatch.setattr(NewExchangeDialog, "exec", lambda dialog: dialog.name.setText("Posizione") or True)
    page.set_connector("FLOW")
    fe = page.connect_elements(a, b)
    item = fe.get("exchange_item")
    assert page.undo() and p.model.get(fe.uuid) is None and p.model.get(item) is None and edited
    assert page.redo() and p.model.get(fe.uuid) is not None and p.model.get(item) is not None
    assert any(fe.uuid in arrow.exchanges for arrow in page.arrows)
    # Deleted with its datum: undone, both back.
    monkeypatch.setattr(ui.QMessageBox, "question", lambda *args, **kwargs: ui.QMessageBox.Yes)
    page.delete_exchanges([fe.uuid])
    assert p.model.get(fe.uuid) is None and p.model.get(item) is None
    assert page.undo() and p.model.get(fe.uuid).get("exchange_item") == item and p.model.get(item) is not None
    # The overview of SA-1: a domain created, undone; of SA-2: a domain closed, undone.
    monkeypatch.setattr(NewDomainDialog, "exec", lambda dialog: dialog.name.setText("Odometria") or True)
    sa1 = BreakdownPage(p)
    made = sa1.new_domain()
    assert sa1.undo() and p.model.get(made.uuid) is None and made.uuid not in sa1.blocks
    sa2 = BreakdownPage(p, functions=True)
    sa2.toggle(d[6].uuid)
    assert d[6].uuid not in sa2.opened and sa2.undo() and d[6].uuid in sa2.opened
    # «Elimina la funzione…» from a domain: Ctrl+Z puts it back.
    from arcadia_tool.ui import diagrams as ui
    monkeypatch.setattr(ui, "ask_deletion", lambda parent, model, uuids, in_view: ("model", uuids))
    gone = f[(6, 4)].uuid
    assert sa2.delete_function(gone) and p.model.get(gone) is None
    assert sa2.undo() and p.model.get(gone) is not None


def test_ctrl_a_selects_every_element_of_the_view(app, tmp_path):
    from PySide6.QtTest import QTest
    from arcadia_tool.ui.diagrams import Arrow, Block, Box

    p, d, f, *_ = build(tmp_path)
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid, f[(6, 4)].uuid, d[11].uuid]))
    page.show()
    app.processEvents()
    page.canvas.setFocus()
    QTest.keyClick(page.canvas, Qt.Key_A, Qt.ControlModifier)
    shown = [i for i in page.scene.items() if isinstance(i, (Box, Block, Arrow))]
    assert shown and all(i.isSelected() for i in shown)
    assert any(isinstance(i, Arrow) for i in shown) and any(isinstance(i, Block) for i in shown)
    page.close()


def test_the_canvas_goes_beyond_the_view_and_is_moved_with_the_hand(app, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    p, d, f, *_ = build(tmp_path)
    a, b = f[(2, 1)].uuid, f[(6, 4)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b]))
    page.resize(1200, 700)
    page.show()
    app.processEvents()
    canvas, viewport = page.canvas, page.canvas.viewport()
    # Larger than its elements: there is room beyond the view, and the view starts on the elements.
    items = page.scene.itemsBoundingRect()
    assert page.scene.sceneRect().contains(items.adjusted(-1000, -1000, 1000, 1000))
    assert viewport.rect().contains(canvas.mapFromScene(items.topLeft()))
    # The hand on an empty place: the view moves, the elements do not.
    empty = canvas.mapFromScene(items.bottomRight() + QPointF(150, 150))
    before = (canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value())
    where = page.items[a].pos()
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, empty)
    QTest.mouseMove(viewport, empty - QPoint(200, 120))
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, empty - QPoint(200, 120))
    after = (canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value())
    assert after == (before[0] + 200, before[1] + 120) and page.items[a].pos() == where and not page.dirty
    # Shift + drag on an empty place: the rubber band selects.
    start = canvas.mapFromScene(items.topLeft() - QPointF(20, 20))
    end = canvas.mapFromScene(items.bottomRight() + QPointF(20, 20))
    QTest.mousePress(viewport, Qt.LeftButton, Qt.ShiftModifier, start)
    QTest.mouseMove(viewport, (start + end) / 2)
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.ShiftModifier, end)
    assert all(b.isSelected() for b in page.blocks)
    # An element placed far away: the canvas grows to hold it, with room beyond it.
    page.items[b].moveBy(3000, 2000)
    page._refresh_arrows()
    assert page.scene.sceneRect().contains(page.items[b].mapRectToScene(page.items[b].rect()).adjusted(-500, -500,
                                                                                                    500, 500))
    page.close()


def test_the_canvas_is_zoomed_from_its_menu_and_the_keys(app, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMenu

    p, d, f, *_ = build(tmp_path)
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid, f[(6, 4)].uuid]))
    page.resize(1200, 700)
    page.show()
    app.processEvents()
    canvas = page.canvas
    # From the menu: zoom in around the point clicked, which stays where it was.
    at = QPoint(300, 200)
    fixed = canvas.mapToScene(at)
    menu = QMenu()
    canvas.zoom_actions(menu, at)
    texts = [a.text() for a in menu.actions()]
    assert texts[0].startswith("Zoom avanti") and texts[1].startswith("Zoom indietro") and "100%" in texts[2]
    menu.actions()[0].trigger()
    assert canvas.transform().m11() == pytest.approx(canvas.ZOOM_STEP)
    assert (canvas.mapFromScene(fixed) - at).manhattanLength() <= 2
    menu.actions()[1].trigger()
    assert canvas.transform().m11() == pytest.approx(1)
    # The keys; never beyond its limits; Ctrl+0 back to the real size; fitted, every element in sight.
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key_Minus, Qt.ControlModifier)
    assert canvas.transform().m11() == pytest.approx(1 / canvas.ZOOM_STEP)
    for _ in range(30):
        canvas.zoom(canvas.ZOOM_STEP)
    assert canvas.transform().m11() == pytest.approx(canvas.ZOOM_RANGE[1])
    QTest.keyClick(canvas, Qt.Key_0, Qt.ControlModifier)
    assert canvas.transform().m11() == pytest.approx(1)
    canvas.zoom_fit()
    items = canvas.mapFromScene(page.scene.itemsBoundingRect()).boundingRect()
    assert canvas.viewport().rect().contains(items) and canvas.transform().m11() <= 1
    page.close()
    # The views of SA-1 and SA-2 too.
    sa2 = BreakdownPage(p, functions=True)
    sa2.canvas.zoom(2)
    assert sa2.canvas.transform().m11() == pytest.approx(2)


def test_a_block_dragged_is_aligned_to_the_blocks_nearby(app, tmp_path):
    from PySide6.QtCore import QRectF
    from arcadia_tool.ui.diagrams import SNAP, snap_offset

    # Its top 5 px below that of the other: aligned on the tops, with a horizontal guide; far: left as it is.
    dx, dy, guides = snap_offset(QRectF(400, 105, 200, 100), [QRectF(0, 100, 200, 150)])
    assert (dx, dy) == (0, -5) and guides == [(0, 100, 600, 100)]
    assert snap_offset(QRectF(400, 300, 200, 100), [QRectF(0, 100, 200, 150)])[:2] == (0, 0)
    assert snap_offset(QRectF(400, 250 + SNAP + 1, 200, 100), [QRectF(0, 100, 200, 150)])[1] == 0  # beyond SNAP
    # The nearest wins: centre 3 px away rather than an edge 6 px away.
    others = [QRectF(0, 0, 400, 50), QRectF(309, 100, 10, 10)]
    assert snap_offset(QRectF(103, 400, 200, 50), others)[0] == -3  # the centres, not the right edge (6 px)
    # In the view: the block of DF02 dragged near the height of DF06 lands aligned, the guides shown and then gone.
    p, d, f, *_ = build(tmp_path)
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid, f[(6, 4)].uuid]))
    df02 = next(b for b in page.blocks if b.key == d[2].uuid)
    df06 = next(b for b in page.blocks if b.key == d[6].uuid)
    start = df02.rect().center()
    wanted = df06.rect().top() - df02.rect().top() + 4  # 4 px off the top of DF06
    df02.mousePressEvent(_Drag(start.x(), start.y()))
    df02.mouseMoveEvent(_Drag(start.x() + 37, start.y() + wanted))
    assert df02.rect().top() == df06.rect().top() and page._guides  # aligned, guide shown
    assert page.canvas.show_grid  # the dots, while it moves
    df02.mouseReleaseEvent(_Drag(start.x() + 37, start.y() + wanted))
    assert not page._guides and page.dirty and not page.canvas.show_grid
    # Far from the others: on the dots of the grid.
    from arcadia_tool.ui.diagrams import GRID
    start = df02.rect().center()
    df02.mousePressEvent(_Drag(start.x(), start.y()))
    df02.mouseMoveEvent(_Drag(start.x() + 13, start.y() + 607))
    df02.mouseReleaseEvent(_Drag(start.x() + 13, start.y() + 607))
    assert df02.rect().left() % GRID == 0 and df02.rect().top() % GRID == 0
    page.scene.clearSelection()
    # Several blocks selected: dragging one moves them all, by the same step.
    df02.setSelected(True)
    df06.setSelected(True)
    assert all(m.isSelected() for m in df02.members + df06.members)  # their functions with them
    tops = [df02.rect().top(), df06.rect().top()]
    start = df02.rect().center()
    df02.mousePressEvent(_Drag(start.x(), start.y()))
    df02.mouseMoveEvent(_Drag(start.x(), start.y() + 300))
    df02.mouseReleaseEvent(_Drag(start.x(), start.y() + 300))
    assert [df02.rect().top() - tops[0], df06.rect().top() - tops[1]] == [300, 300]
    # A click on a block not selected: that one only.
    page.scene.clearSelection()
    df06.setSelected(True)
    start = df02.rect().center()
    df02.mousePressEvent(_Drag(start.x(), start.y()))
    assert df02.isSelected() and not df06.isSelected()
    df02.mouseReleaseEvent(_Drag(start.x(), start.y()))
    df06.mousePressEvent(_Drag(df06.rect().center().x(), df06.rect().center().y(), Qt.ControlModifier))
    assert df02.isSelected() and df06.isSelected()  # Ctrl + click: added
    df06.mouseReleaseEvent(_Drag(0, 0))


def test_the_positions_are_stored_as_text_and_the_deleted_elements_go_away(tmp_path):
    p, d, f, *_ = build(tmp_path)
    v = view(p, DIAGRAM_DATAFLOW, [f[(5, 1)].uuid, f[(6, 4)].uuid])
    dg.set_positions(v, {f[(6, 4)].uuid: (10.4, 20.6), f[(5, 1)].uuid: None})
    assert v.get("layout") == dict(sorted({f[(6, 4)].uuid: "10,21", f[(5, 1)].uuid: ""}.items()))
    assert dg.positions(v) == {f[(5, 1)].uuid: None, f[(6, 4)].uuid: (10.0, 21.0)}  # None: not placed yet
    p.delete_element(f[(5, 1)].uuid)
    assert dg.missing(p.model, v) == [f[(5, 1)].uuid]
    # A view does not count as a reference to its elements: deleting them does not warn about it.
    assert v not in p.model.referencing([f[(6, 4)].uuid])


def test_a_chain_marks_the_return_to_a_domain_already_passed(tmp_path):
    p, d, f, x, chain, *_ = build(tmp_path)
    v = view(p, DIAGRAM_CHAIN, chain=chain)
    steps = dg.shown_steps(p.model, v)
    assert [s.domain_ident for s in steps] == ["DF05", "DF06", "DF11", "DF06"]
    assert [s.bounce for s in steps] == [False, False, False, True]  # back to DF06 after DF11 (D4)
    v.set("level", dg.BY_FUNCTION)
    assert not any(s.bounce for s in dg.shown_steps(p.model, v))  # function by function: no return
    # A step taken out of the view can be added again from the list.
    layout = dict(v.get("layout"))
    layout.pop(dg.step_key(2))
    v.set("layout", layout)
    assert [a.key for a in dg.addable(p.model, v)] == [dg.step_key(2)]


def test_a_scenario_has_a_lifeline_for_each_domain_and_the_exchanges_in_order(tmp_path):
    p, d, f, x, chain, *_ = build(tmp_path)
    v = view(p, DIAGRAM_SCENARIO, chain=chain)
    sc = dg.scenario(p.model, v)
    assert [l.ident for l in sc.lifelines] == ["DF05", "DF06", "DF11"]
    assert [(m.label, m.ident, m.cycle) for m in sc.messages][:3] == [
        ("Richiesta di frenatura", "FE-DF05-DF06-01", "1"), ("Comando dei freni", "FE-DF06-DF11-01", "1"),
        ("Ingressi dal treno", "FE-DF11-DF06-01", "2")]
    last = sc.messages[-1]  # the last step has no exchange and no next step: it stays on its lifeline
    assert last.source == last.target == d[6].uuid and last.label == "Standstill"
    v.set("level", dg.BY_FUNCTION)  # the brake command reaches SF-DF11-01, the inputs come from SF-DF11-02
    assert [l.ident for l in dg.scenario(p.model, v).lifelines] == [
        "SF-DF05-01", "SF-DF06-06", "SF-DF11-01", "SF-DF11-02", "SF-DF06-04"]


def test_the_bar_of_icons_chooses_the_tab_and_closes_and_opens_the_panel(app, tmp_path):
    from PySide6.QtCore import QSettings
    from arcadia_tool.ui import main_window as mw

    p, *_ = build(tmp_path)
    p.save()
    window = mw.MainWindow()
    window._set_project(p)
    window.resize(1400, 800)
    window.show()
    app.processEvents()
    bar, tree = window.activity, window.tree
    model, views = bar.buttons
    assert model.isChecked() and not views.isChecked() and tree.caption.text() == "MODELLO"
    views.click()  # the other tab
    assert tree.tabs.currentIndex() == model_tree.VIEWS_TAB and views.isChecked() and not tree.isHidden()
    assert tree.caption.text() == "VISTE GRAFICHE"
    views.click()  # the tab shown: the panel goes away to the left, the icons stay
    assert tree.isHidden() and not views.isChecked() and not bar.isHidden()
    assert str(QSettings(QSettings.IniFormat, QSettings.UserScope, "RFI", "ARCADIA Tool")
               .value("panel/collapsed")).lower() == "true"
    model.click()  # closed: open again, on that tab, as wide as it was
    assert not tree.isHidden() and tree.tabs.currentIndex() == model_tree.MODEL_TAB and model.isChecked()
    assert bar.splitter.sizes()[0] > 100
    bar.toggle()  # Ctrl+Shift+B
    assert tree.isHidden()
    bar.toggle()
    assert not tree.isHidden()
    bar.splitter.moveSplitter(0, 1)  # the divider dragged to the left edge: closed
    bar._moved(0, 1)
    assert tree.isHidden() and not model.isChecked()
    # The next window starts as the panel was left.
    again = mw.MainWindow()
    assert again.tree.isHidden()
    again.activity.expand()
    window.close()
    again.close()


def test_the_left_panel_has_the_elements_and_the_views_in_two_tabs(app, tmp_path):
    p, d, f, x, chain, *_ = build(tmp_path)
    flow = view(p, DIAGRAM_DATAFLOW, [f[(5, 1)].uuid], name="Comando dei freni")
    view(p, DIAGRAM_SCENARIO, chain=chain, name="Frenatura")
    tree = model_tree.ModelTree()
    tree.set_project(p)
    assert [tree.tabs.tabText(i) for i in range(tree.tabs.count())] == ["Modello", "Viste grafiche"]
    # «Modello»: only the elements, directly under their kind; the views are not there.
    assert "diagram" not in tree._kind_items and flow.uuid not in tree._items
    domains = tree._kind_items["domain"]
    assert domains.childCount() == 4 and domains.child(0).data(0, model_tree.UUID_ROLE) == d[2].uuid
    # «Viste grafiche»: a group for each type with its SA; first in SA-1 and SA-2, the view of the whole model.
    from arcadia_tool.model.schema import DIAGRAM_BREAKDOWN, DIAGRAM_FUNCTIONS
    mine = view(p, DIAGRAM_BREAKDOWN, [d[6].uuid], name="Solo DF06")
    functions = view(p, DIAGRAM_FUNCTIONS, [d[5].uuid], name="Funzioni di DF05")
    tree.reload()
    groups = [tree.views.topLevelItem(i) for i in range(tree.views.topLevelItemCount())]
    assert [g.text(0) for g in groups] == ["SA-1 Domini funzionali", "SA-2 Funzioni per dominio",
                                           "SA-5 Dataflow funzionali", "SA-7 Catene funzionali",
                                           "SA-7 Scenari di scambio"]
    assert [groups[0].child(i).text(0) for i in range(2)] == ["Vista complessiva", "Solo DF06"]
    assert [groups[1].child(i).text(0) for i in range(2)] == ["Vista complessiva", "Funzioni di DF05"]
    assert groups[0].child(1).data(0, model_tree.UUID_ROLE) == mine.uuid and groups[0].text(1) == "1"
    assert groups[1].child(1).data(0, model_tree.UUID_ROLE) == functions.uuid
    groups = groups[:1] + groups[2:]  # below: SA-1, then the dataflows, the chains and the scenarios
    assert groups[1].child(0).text(0) == "Comando dei freni" and groups[1].text(1) == "1"
    assert "nessuna vista" in groups[2].child(0).text(0)
    assert groups[3].child(0).text(0) == "Frenatura"
    # A click on the breakdown asks for it; a click on a view selects it as an element (it opens its page).
    asked, selected = [], []
    tree.breakdown_requested.connect(asked.append)
    tree.element_selected.connect(selected.append)
    tree.views.setCurrentItem(groups[0].child(0))
    tree.views.setCurrentItem(groups[1].child(0))
    assert asked == ["domain"] and selected == [flow]
    # Selecting a view shows its tab; each tab searches its own items.
    tree.tabs.setCurrentIndex(0)
    tree.select(flow.uuid)
    assert tree.tabs.currentIndex() == 1 and tree.pages.currentIndex() == 1
    tree.views_filter.setText("fren")  # «Comando dei freni», «Frenatura»
    assert not groups[1].isHidden() and groups[2].isHidden() and not groups[3].isHidden()
    tree.filter.setText("freni")
    assert not tree._kind_items["domain"].isHidden()  # the kinds stay, their elements are filtered


def test_a_view_is_composed_with_the_elements_of_the_model_and_saved(app, tmp_path):
    p, d, f, x, chain, rbc, _ = build(tmp_path)
    v = view(p, DIAGRAM_DATAFLOW)
    p.save()
    page = DiagramPage(p, v)
    assert not page.dirty and page.items == {}
    keys = {page.elements.topLevelItem(i).text(0) for i in range(page.elements.topLevelItemCount())}
    assert {"Attori esterni", "Domini funzionali", "DF06 · Dominio 6"} <= keys
    page.add(f[(6, 6)].uuid, QPointF(400, 200))  # dropped from the list
    page.add(f[(5, 1)].uuid)  # double click: in a free place
    page.add(rbc.uuid)
    page.add("not-an-element")
    assert page.dirty and set(page.placed) == {f[(6, 6)].uuid, f[(5, 1)].uuid, rbc.uuid}
    assert page.placed[f[(6, 6)].uuid] == (400 - dg.NODE_W / 2, 200 - dg.NODE_H / 2)
    assert len(page.arrows) == 2  # RBC → MRSP, MRSP → braking
    assert v.get("layout") in (None, {})  # nothing in the model until «Salva vista»
    saved = []
    page.saved.connect(lambda: saved.append(1))
    page.save_view()
    assert saved and not page.dirty and set(v.get("layout")) == set(page.placed)
    page.remove([rbc.uuid])
    assert page.dirty and rbc.uuid not in page.placed
    page.discard_changes()  # «Annulla modifiche»: the view as saved
    assert rbc.uuid in page.placed and not page.dirty
    p.save()
    reopened = Project.open(tmp_path / "p")
    assert set(reopened.model.get(v.uuid).get("layout")) == set(page.placed)


def test_a_view_shows_that_a_deleted_element_went_away(app, tmp_path):
    p, d, f, *_ = build(tmp_path)
    v = view(p, DIAGRAM_DATAFLOW, [f[(5, 1)].uuid, f[(6, 6)].uuid])
    page = DiagramPage(p, v)
    p.delete_element(f[(5, 1)].uuid)
    page.refresh()
    assert page.dirty and f[(5, 1)].uuid not in page.placed and "non più nel modello" in page.notice.text()


def test_the_breakdown_opens_a_domain_on_its_functions(app, tmp_path):
    p, d, f, *_ = build(tmp_path)
    sa1 = BreakdownPage(p)  # only the names of the domains: a click does not open them
    sa1.blocks[d[6].uuid].mouseReleaseEvent(_Click(30, 10))
    assert not sa1.blocks[d[6].uuid].expandable and not sa1._timer.isActive()
    assert sa1.blocks[d[6].uuid].h >= CELL_H and sa1.blocks[d[6].uuid].w == CELL_W  # as a closed one of SA-2
    d[6].set("name", "Supervisionare la marcia del treno e comandare la frenatura di servizio e di emergenza")
    sa1.refresh()
    tall = sa1.blocks[d[6].uuid]
    assert tall.w == CELL_W and tall.h > CELL_H  # the whole name, on more lines
    assert sa1.blocks[d[5].uuid].h == tall.h  # the row as high as its highest name
    page = BreakdownPage(p, functions=True)
    assert page.opened == {d[n].uuid for n in (2, 5, 6, 11)}  # SA-2: every domain open
    page.close_all()
    page.blocks[d[6].uuid].mouseReleaseEvent(_Click(30, TITLE_H + 10))  # under the title bar: not opened
    assert not page._timer.isActive()
    page.blocks[d[6].uuid].mouseReleaseEvent(_Click(CELL_W - 20, 20))  # its chevron
    assert page._timer.isActive()
    page.cancel_toggle()
    page.toggle(d[6].uuid)
    block = page.blocks[d[6].uuid]
    assert block.opened and block.w == page.blocks[d[2].uuid].w and block.h > page.blocks[d[2].uuid].h
    opened = []
    page.open_requested.connect(opened.append)
    function = block.function_at(QPointF(30, 80))
    assert function.ident == "SF-DF06-04"


class _Click:
    def __init__(self, x, y):
        self._pos = QPointF(x, y)

    def pos(self):
        return self._pos

    def button(self):
        return Qt.LeftButton

    def accept(self):
        pass


def test_a_click_on_a_function_selects_it_and_the_domain_stays_open(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import main_window as mw

    p, d, f, *_ = build(tmp_path)
    p.save()
    window = mw.MainWindow()
    window._set_project(p)
    window.open_breakdown("system_function")
    page = window.pages.currentWidget()
    page.close_all()
    page.toggle(d[6].uuid)
    block = page.blocks[d[6].uuid]
    block.mousePressEvent(_Click(30, 80))
    block.mouseReleaseEvent(_Click(30, 80))
    assert page.selected_function == f[(6, 4)].uuid and not page._timer.isActive()  # not closed
    block.mousePressEvent(_Click(30, 10))  # on the header: the domain closes, the function is no more selected
    block.mouseReleaseEvent(_Click(30, 10))
    assert page.selected_function is None and page._timer.isActive()
    page.cancel_toggle()
    # «Elimina la funzione…» from its right click: out of the model, the view stays shown.
    from arcadia_tool.ui import diagrams as ui
    monkeypatch.setattr(ui, "ask_deletion", lambda parent, model, uuids, in_view: ("model", uuids))
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Yes)
    page.delete_requested.emit(f[(6, 4)].uuid)
    assert p.model.get(f[(6, 4)].uuid) is None and window.pages.currentWidget() is page
    assert [x.ident for x in page.blocks[d[6].uuid].domain.functions] == ["SF-DF06-06"]


def test_a_function_is_deleted_from_a_view_only_or_from_the_model_too(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from arcadia_tool.model.schema import DIAGRAM_FUNCTIONS
    from arcadia_tool.ui import diagrams as ui

    p, d, f, x, *_ = build(tmp_path)
    answers = []
    monkeypatch.setattr(ui, "ask_deletion",
                        lambda parent, model, uuids, in_view: answers.append((uuids, in_view)) or (choice[0], uuids))
    shown = []

    class Menu(QMenu):
        def exec(self, *_args):
            shown.append([a.text() for a in self.actions()])

    monkeypatch.setattr(ui, "QMenu", Menu)
    # A dataflow: the right click on a function of a domain block.
    a, b = f[(2, 1)].uuid, f[(6, 4)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b]))
    page._box_menu(page.items[b], None)
    assert "Elimina la funzione…" in shown[-1]
    choice = [None]  # cancelled: nothing changes
    assert page.delete_function(b) is None and b in page.placed
    choice = ["view"]  # only from the view: still in the model
    assert page.delete_function(b) == "view"
    assert b not in page.placed and b not in page.items and p.model.get(b) is not None and page.dirty
    assert answers[-1] == ([b], True)
    page.undo()
    assert b in page.items
    choice = ["model"]  # from the model too: out of the catalogue, Ctrl+Z puts it back
    edited = []
    page.model_edited.connect(edited.append)
    assert page.delete_function(b) == "model"
    assert p.model.get(b) is None and b not in page.items and not page.notice.isVisibleTo(page) and edited
    page.undo()
    assert p.model.get(b) is not None and b in page.items
    # A view of SA-2 with the whole domain: only from the view, the domain keeps its other functions.
    sa2 = DiagramPage(p, view(p, DIAGRAM_FUNCTIONS, [d[6].uuid]))
    choice = ["view"]
    sa2.delete_function(b)
    assert d[6].uuid not in sa2.placed and set(sa2.placed) == {f[(6, 6)].uuid}
    assert p.model.get(b) is not None
    sa2.undo()
    assert set(sa2.placed) == {d[6].uuid}


def test_a_right_click_on_a_domain_shows_what_can_be_done_and_canc_deletes_it(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from arcadia_tool.model.schema import DIAGRAM_FUNCTIONS
    from arcadia_tool.ui import diagrams as ui

    p, d, f, x, *_ = build(tmp_path)
    shown = []

    class Menu(QMenu):
        def exec(self, *_args):
            texts = []
            for a in self.actions():
                texts.append(a.text())
                if a.menu():
                    texts += [f"  {s.text()}" for s in a.menu().actions()]
            shown.append(texts)

    monkeypatch.setattr(ui, "QMenu", Menu)
    asked = []
    choice = ["view"]
    monkeypatch.setattr(ui, "ask_deletion",
                        lambda parent, model, uuids, in_view: asked.append((uuids, in_view)) or (choice[0], uuids))
    # A dataflow: the block of DF06 with one of its two functions.
    a, b = f[(2, 1)].uuid, f[(6, 4)].uuid
    page = DiagramPage(p, view(p, DIAGRAM_DATAFLOW, [a, b]))
    page.domain_menu(d[6].uuid, None)
    menu = shown[-1]
    for text in ("Apri la scheda", "Aggiungi alla vista una funzione del dominio", "Nuova funzione di sistema in DF06…",
                 "Nuovo dominio funzionale…", "Elimina il dominio…"):
        assert text in menu
    assert any("SF-DF06-06" in t for t in menu)  # the function of DF06 not in the view
    page.add_all([f[(6, 6)].uuid])
    assert f[(6, 6)].uuid in page.placed
    # Canc on the block: asked for the domain (not for each of its functions, selected with it).
    block = next(bl for bl in page.blocks if bl.key == d[6].uuid)
    block.setSelected(True)
    page.delete_selected()
    assert asked[-1] == ([d[6].uuid], True)
    assert b not in page.placed and f[(6, 6)].uuid not in page.placed and a in page.placed  # only out of the view
    assert p.model.get(d[6].uuid) is not None
    page.undo()
    # From the model too: the domain goes, its functions stay (without a domain) unless asked.
    choice = ["model"]
    page.domain_menu(d[6].uuid, None)
    assert page.delete_elements([d[6].uuid]) == "model"
    assert p.model.get(d[6].uuid) is None and p.model.get(b) is not None
    page.undo()
    assert p.model.get(d[6].uuid) is not None
    # A view of SA-2 with only a function of DF06: all of them shown from the menu of the domain.
    choice = ["view"]
    sa2 = DiagramPage(p, view(p, DIAGRAM_FUNCTIONS, [b]))
    sa2.domain_menu(d[6].uuid, None)
    assert "Mostra tutte le funzioni del dominio" in shown[-1]
    sa2.show_whole_domain(d[6].uuid)
    assert set(sa2.placed) == {d[6].uuid}
    sa2.domain_menu(d[6].uuid, None)
    assert "Chiudi il dominio" in shown[-1] and "Elimina il dominio…" in shown[-1]
    # Canc on the function selected in the block: asked.
    sa2.select_function(f[(6, 6)].uuid)
    sa2.delete_selected()
    assert asked[-1] == ([f[(6, 6)].uuid], True) and set(sa2.placed) == {b}
    # The overview of SA-2: the domain opened and closed, deleted only from the model (asked); Canc on a function.
    overview = BreakdownPage(p, functions=True)
    overview.domain_menu(d[6].uuid, None)
    assert "Chiudi il dominio" in shown[-1] and "Elimina il dominio…" in shown[-1]
    choice = [None]
    overview.select_function(b)
    overview.delete_selected()
    assert asked[-1] == ([b], False) and p.model.get(b) is not None


def test_the_deletion_of_a_domain_can_take_its_functions_too(app, tmp_path):
    from arcadia_tool.ui.diagrams import DeletionDialog

    p, d, f, *_ = build(tmp_path)
    dialog = DeletionDialog(p.model, [d[6].uuid], in_view=True)
    assert not dialog.with_functions.isHidden() and dialog.targets == [d[6].uuid]
    groups = [dialog.impacts.topLevelItem(i).text(0) for i in range(dialog.impacts.topLevelItemCount())]
    assert any(g.startswith("Riferimenti") for g in groups)  # its functions refer to it
    dialog.with_functions.setChecked(True)
    assert set(dialog.targets) == {d[6].uuid, f[(6, 4)].uuid, f[(6, 6)].uuid}
    groups = [dialog.impacts.topLevelItem(i).text(0) for i in range(dialog.impacts.topLevelItemCount())]
    assert "Da eliminare (3)" in groups


def test_the_deletion_of_a_function_shows_the_elements_impacted(app, tmp_path):
    from arcadia_tool.model.schema import DIAGRAM_FUNCTIONS
    from arcadia_tool.ui.diagrams import DeletionDialog

    p, d, f, x, *_ = build(tmp_path)
    b = f[(6, 4)].uuid
    view(p, DIAGRAM_DATAFLOW, [b], name="Frenatura")
    view(p, DIAGRAM_FUNCTIONS, [d[6].uuid], name="Funzioni DF06")  # with its whole domain
    view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid], name="Altro")
    dialog = DeletionDialog(p.model, [b], in_view=True)
    groups = {dialog.impacts.topLevelItem(i).text(0): [dialog.impacts.topLevelItem(i).child(j).text(0)
                                                         for j in range(dialog.impacts.topLevelItem(i).childCount())]
              for i in range(dialog.impacts.topLevelItemCount())}
    references = next(v for k, v in groups.items() if k.startswith("Riferimenti"))
    assert any("FE-DF02-DF06-01" in r for r in references) and any("FE-DF11-DF06-01" in r for r in references)
    assert next(v for k, v in groups.items() if k.startswith("Viste")) == ["Frenatura", "Funzioni DF06"]
    texts = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "Solo dalla vista" in texts and "Elimina anche dal modello" in texts
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Elimina anche dal modello").click()
    assert dialog.choice == "model"
    overview = DeletionDialog(p.model, [b], in_view=False)  # SA-2 «Vista complessiva»: only from the model
    texts = [b.text() for b in overview.findChildren(QPushButton)]
    assert "Solo dalla vista" not in texts and "Elimina dal modello" in texts


def test_the_main_window_opens_creates_and_saves_the_views(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import main_window as mw
    from arcadia_tool.ui.diagrams import NewViewDialog

    p, d, f, x, chain, *_ = build(tmp_path)
    p.save()
    window = mw.MainWindow()
    window._set_project(p)
    window.open_breakdown("domain")
    assert isinstance(window.pages.currentWidget(), BreakdownPage)

    def create(dialog):
        dialog.type.setCurrentText(DIAGRAM_CHAIN)
        dialog.name.setText("Frenatura")
        return True

    monkeypatch.setattr(NewViewDialog, "exec", create)
    created = window.tree.create_view()  # «+ Nuova vista…»: the type is chosen in the window
    assert created.get("diagram_type") == DIAGRAM_CHAIN and created.get("chain") == chain.uuid
    assert not p.is_modified  # created and saved with the project
    page = window.pages.currentWidget()
    assert isinstance(page, DiagramPage) and page.view is created and len(page.items) == 4
    assert window.tree._view_items[created.uuid].text(0) == "Frenatura"
    assert window.tree.tabs.currentIndex() == 1  # the new view is shown in «Viste grafiche»
    page.remove([dg.step_key(0)])
    assert window.pages.tabText(window.pages.indexOf(page)).startswith("●")
    # Closing it with changes not saved asks first: cancelled, it stays.
    monkeypatch.setattr(mw, "resolve_unsaved_view", lambda page, parent: False)
    window._close_page(window.pages.indexOf(page))
    assert window.pages.indexOf(page) >= 0
    assert p.is_modified is False and window.save_action.isEnabled()  # the changes of the tab: Ctrl+S works
    window.save_action.trigger()  # Ctrl+S on a view: «Salva vista»
    assert not page.dirty and dg.step_key(0) not in created.get("layout") and not p.is_modified
    assert not window.save_action.isEnabled()
    assert not window.pages.tabText(window.pages.indexOf(page)).startswith("●")
    # The view deleted from the tree: its tab closes.
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Yes)
    window.tree.delete_element(created)
    assert created.uuid not in window.diagram_pages


def test_a_right_click_on_a_tab_closes_it_the_others_or_all(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from arcadia_tool.ui import main_window as mw

    p, d, f, *_ = build(tmp_path)
    v = view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid])
    p.save()
    window = mw.MainWindow()
    window._set_project(p)
    window.open_breakdown("domain")
    window.open_breakdown("system_function")
    window.open_diagram(v)
    pages = window.pages

    menus = []  # alive while their actions are used

    def actions(index):
        menu = QMenu()
        menus.append(menu)
        window.tab_actions(menu, index)
        return {a.text(): a for a in menu.actions()}

    assert list(actions(0)) == ["Chiudi", "Chiudi le altre", "Chiudi tutte"]
    middle = pages.widget(1)
    actions(1)["Chiudi le altre"].trigger()
    assert pages.count() == 1 and pages.widget(0) is middle
    assert not actions(0)["Chiudi le altre"].isEnabled()
    window.open_diagram(v)
    page = window.diagram_pages[v.uuid]
    page.remove([f[(2, 1)].uuid])  # changes not saved: asked, cancelled, its tab stays
    monkeypatch.setattr(mw, "resolve_unsaved_view", lambda page, parent: False)
    actions(0)["Chiudi tutte"].trigger()
    assert pages.count() == 1 and pages.widget(0) is page
    monkeypatch.setattr(mw, "resolve_unsaved_view", lambda page, parent: True)
    actions(0)["Chiudi"].trigger()
    assert pages.count() == 0


def test_the_save_of_a_page_writes_only_its_changes_and_the_toolbar_saves_everything(app, tmp_path):
    from arcadia_tool.ui import main_window as mw

    p, d, f, *_ = build(tmp_path)
    v = view(p, DIAGRAM_DATAFLOW, [f[(2, 1)].uuid, f[(6, 4)].uuid])
    p.save()
    window = mw.MainWindow()
    window._set_project(p)
    elsewhere = p.new_element("team", name="Radio")  # a change made elsewhere, not saved yet
    # The sheet of a domain: changed and saved with its «Salva» (Ctrl+S on its tab): only it is written.
    window._select(d[2])
    editor = window.editor
    editor.start_editing()
    editor.widgets["name"].setText("Odometria")
    editor.flush()
    window.save_tab()
    assert not editor.dirty and d[2].uuid not in p.changes_since(0) and elsewhere.uuid in p.changes_since(0)
    # A view: «Salva vista» writes the view only.
    window.open_diagram(v)
    page = window.diagram_pages[v.uuid]
    page.remove([f[(2, 1)].uuid])
    window.save_tab()  # Ctrl+S on the view
    assert not page.dirty and v.uuid not in p.changes_since(0) and p.is_modified
    # «Salva» of the toolbar: everything, the sheets and the views with changes included.
    page.remove([f[(6, 4)].uuid])
    window._select(d[5])
    window.editor.start_editing()
    window.editor.widgets["name"].setText("Supervisione")
    window.editor.flush()
    assert window.save_action.isEnabled() and window.save_action.shortcut().toString() == "Ctrl+Shift+S"
    window.save_action.trigger()
    assert not p.is_modified and not page.dirty and not window.editor.dirty
    assert p.model.get(d[5].uuid).get("name") == "Supervisione" and not v.get("layout")
    assert not window.save_action.isEnabled()
