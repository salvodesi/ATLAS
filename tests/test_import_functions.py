"""«Importa funzioni da Excel SA-2…» of a system function sheet: the catalogue of the functions of the teams."""
import openpyxl
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from arcadia_tool.model.srs_sections import parse_clauses, resolve
from arcadia_tool.storage.function_sheets import read_function_sheets
from arcadia_tool.storage.project import Project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


HEADINGS = ["ID", "Nome (verbo + oggetto)", "Clausole SRS", "Componente Logico proposto", "Stato Sezione", "Stato"]


DF01_ROWS = [["SF-DF01-01", "Gestire comandi di frenatura", "3.4.1.1, 3.4.1.2; 3.4.1.2 b) f)",
               "Da non compilare ora", "Nuova", "Proposto"],
              ["SF-DF01-02", "Proteggere dal Roll Away\n", "3.4.1.1\n9.9.9.9\nSUBSET-027", None,
               "Presente in Tab 4.5.2.1", "Proposto", "Valutare spostamento"],
              ["SF-DF01-03", "Determinare il modo", None, None, "Nuova", "Proposto"],  # no clauses yet
              ["SF-DF01-04", "Monitorare la velocità", "3.4.1.1, 3.4.1.2", None, None, None],
              ["SF-DF01-05", None, None, None, None, None]]  # an empty row of the template


def workbook(path, df01=DF01_ROWS):
    wb = openpyxl.Workbook()
    index = wb.active
    index.title = "Indice"
    index.append(["ID", "Domain"])
    for title, rows in (
            ("DF01", df01),
            ("DF09", [["SF-DF09-01", "Funzione di un dominio assente", "3.4.1.1", None, None, None]])):
        ws = wb.create_sheet(title)
        ws.append(["Catalogo Funzionale di dominio"])
        ws.append(["Template", "SA-2"])
        ws.append(HEADINGS)
        for row in rows:
            ws.append(row)
        ws.append(["Checklist di compilazione di SA-2"])
        ws.append(["☐", "Ogni funzione ha almeno una voce di bordo tracciata"])
    wb.save(path)
    return path


def project(tmp_path):
    p = Project.create(tmp_path / "p", "Prova")
    d1 = p.new_element("domain", id="DF01", name="Frenatura")
    items = {}
    s1 = p.new_element("requirement", id="3.4.1", item_type="Sezione", sequence=1)
    for n, ident in enumerate(("3.4.1.1", "3.4.1.2"), 2):
        items[ident] = p.new_element("requirement", id=ident, item_type="Requisito", parent=s1.uuid, sequence=n)
    for n, ident in enumerate(("3.4.1.2 b)", "3.4.1.2 f)"), 5):
        p.new_element("requirement", id=ident, item_type="Voce", parent=items["3.4.1.2"].uuid, sequence=n)
    # Already in the domain with the same name: completed with the clauses it does not trace.
    existing = p.new_element("system_function", name="Monitorare la  velocità", domain=d1.uuid,
                             sections=[items["3.4.1.1"].uuid])
    p.save()
    return p, d1, items, existing


def test_the_clauses_of_a_row_and_their_list_items():
    refs = resolve(parse_clauses("3.5.2.4; 3.5.3.4 b) f)\n3.6.2.2.2 a) a), SUBSET-027, 4.8.1–4.8.3"))
    assert [(r.text, r.ids, r.sub_items, r.external) for r in refs] == [
        ("3.5.2.4", ["3.5.2.4"], "", False), ("3.5.3.4 b) f)", ["3.5.3.4"], "b) f)", False),
        ("3.6.2.2.2 a) a)", ["3.6.2.2.2"], "a) a)", False), ("SUBSET-027", [], "", True),
        ("4.8.1–4.8.3", ["4.8.1", "4.8.2", "4.8.3"], "", False)]


def test_the_functions_are_read_from_the_sheets_of_the_domains(tmp_path):
    functions = read_function_sheets(workbook(tmp_path / "sa2.xlsx"))
    assert [(f.sheet, f.ident, f.name) for f in functions] == [
        ("DF01", "SF-DF01-01", "Gestire comandi di frenatura"), ("DF01", "SF-DF01-02", "Proteggere dal Roll Away"),
        ("DF01", "SF-DF01-03", "Determinare il modo"), ("DF01", "SF-DF01-04", "Monitorare la velocità"),
        ("DF09", "SF-DF09-01", "Funzione di un dominio assente")]
    second = functions[1]
    assert second.origin == "Presente in Tab 4.5.2.1" and second.status == "Proposto"
    assert second.notes == ["Valutare spostamento"]


def test_the_summary_and_the_import_of_the_functions(app, tmp_path):
    from arcadia_tool.ui.import_functions import (FOUND, MISSING, NEW, NO_DOMAIN, SUB_ITEM, TICK, UPDATED,
                                                  ImportFunctionsDialog)

    p, d1, items, existing = project(tmp_path)
    dialog = ImportFunctionsDialog(p, workbook(tmp_path / "sa2.xlsx"))
    outcomes = [(x.source.name, x.outcome) for x in dialog.planned]
    assert outcomes == [("Gestire comandi di frenatura", NEW), ("Proteggere dal Roll Away", NEW),
                        ("Determinare il modo", NEW), ("Monitorare la velocità", UPDATED),
                        ("Funzione di un dominio assente", NO_DOMAIN)]
    first = dialog.planned[0]
    assert [(o, w) for o, w, _i in first.clauses] == [(FOUND, "3.4.1.1"), (FOUND, "3.4.1.2"),
                                                      (SUB_ITEM, "3.4.1.2 b) f)")]
    assert [i.get("id") for i in first.traced] == ["3.4.1.1", "3.4.1.2"]  # the list items: with their clause
    assert [o for o, _w, _i in dialog.planned[1].clauses] == [FOUND, MISSING, "external"]
    # Every function to import has its tick, on at first; the one of a domain not in the model has none.
    rows = [row for _p, row in dialog.entries]
    assert [r.data(TICK, Qt.CheckStateRole) is not None for r in rows] == [True, True, True, True, False]
    assert "3 nuove, 1 aggiornate, 0 eliminate · allocazioni: +4 −0" in dialog.counts.text()
    assert "clausole non trovate: 1" in dialog.counts.text()
    assert "domini non presenti nel modello: DF09" in dialog.counts.text()
    rows[1].setCheckState(TICK, Qt.Unchecked)  # not imported
    assert "2 nuove" in dialog.counts.text()
    dialog.import_functions()
    created = {f.get("name"): f for f in dialog.created}
    assert set(created) == {"Gestire comandi di frenatura", "Determinare il modo"}
    brake = created["Gestire comandi di frenatura"]
    assert brake.get("domain") == d1.uuid and brake.get("id", "").startswith("SF-DF01-")  # the ID of ATLAS
    assert brake.get("sections") == [items["3.4.1.1"].uuid, items["3.4.1.2"].uuid]
    assert brake.get("is_new") is True and brake.get("status") == "Proposta"
    assert not created["Determinare il modo"].get("sections")  # imported also without clauses
    assert existing.get("sections") == [items["3.4.1.1"].uuid, items["3.4.1.2"].uuid] and existing in dialog.changed
    assert not any(f.get("name") == "Proteggere dal Roll Away" for f in p.model.of_kind("system_function"))


def test_the_function_sheet_imports_and_its_save_writes_them(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import element_editor, import_functions as ui
    from arcadia_tool.ui.main_window import MainWindow

    p, d1, items, existing = project(tmp_path)
    path = workbook(tmp_path / "sa2.xlsx")
    window = MainWindow()
    window._set_project(p)
    window._select(existing)
    editor = window.editor
    texts = [b.text() for b in editor.widget().findChildren(QPushButton)]
    assert "Alloca a sezioni e clausole SRS…" in texts and "Importa funzioni da Excel SA-2…" in texts
    monkeypatch.setattr(ui.ImportFunctionsDialog, "exec", lambda dialog: dialog.import_functions())
    told = []
    monkeypatch.setattr(element_editor.QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    created, changed, deleted = editor._import_functions(path)
    assert len(created) == 3 and existing in changed and told and "Funzioni create: 3" in told[0]
    assert all(f.uuid in window.tree._items for f in created)  # in the model tree
    window.save_tab()  # Ctrl+S on the sheet: the functions imported are written
    assert not {f.uuid for f in created} & p.pending() and existing.uuid not in p.pending()
    window._set_project(None)
    window.close()


def test_the_menu_of_sa2_in_the_model_tree_imports(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import import_functions as ui, model_tree
    from arcadia_tool.ui.main_window import MainWindow

    p, d1, items, existing = project(tmp_path)
    path = workbook(tmp_path / "sa2.xlsx")
    window = MainWindow()
    window._set_project(p)
    window.show()
    menus = []

    class RecordedMenu(model_tree.QMenu):
        def exec(self, *args):  # not shown: its entries are recorded
            menus.append({a.text(): a for a in self.actions()})
    monkeypatch.setattr(model_tree, "QMenu", RecordedMenu)
    chosen = []
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileName", lambda *a, **k: (chosen.append(True), (str(path), ""))[1])
    monkeypatch.setattr(ui.ImportFunctionsDialog, "exec", lambda dialog: dialog.import_functions())
    tree = window.tree
    node = tree._kind_items["system_function"]
    parent = node.parent()
    while parent is not None:
        parent.setExpanded(True)
        parent = parent.parent()
    app.processEvents()
    tree._context_menu(tree.tree.visualItemRect(node).center())
    assert "Importa funzioni…" in menus[-1]
    menus[-1]["Importa funzioni…"].trigger()  # the choice of the file, then the summary
    created = [f for f in p.model.of_kind("system_function") if f is not existing]
    assert chosen and len(created) == 3 and all(f.uuid in tree._items for f in created)
    assert "Funzioni create: 3 · aggiornate nelle clausole: 1" in window.statusBar().currentMessage()
    window.save()  # «Salva» of the toolbar
    assert not {f.uuid for f in created} & p.pending()
    # Only on the group: not on a single function.
    row = tree._items[existing.uuid]
    parent = row.parent()
    while parent is not None:
        parent.setExpanded(True)
        parent = parent.parent()
    app.processEvents()
    tree._context_menu(tree.tree.visualItemRect(row).center())
    assert "Importa funzioni…" not in menus[-1]
    window._set_project(None)
    window.close()


def test_the_same_workbook_imported_again_aligns_the_model(app, tmp_path):
    from arcadia_tool.ui.import_functions import DELETED, NEW, PRESENT, REMOVED, TICK, UPDATED, ImportFunctionsDialog

    p, d1, items, existing = project(tmp_path)
    first = ImportFunctionsDialog(p, workbook(tmp_path / "sa2.xlsx"))
    first.import_functions()
    p.save()
    brake = next(f for f in first.created if f.get("name") == "Gestire comandi di frenatura")
    assert brake.get("catalogue_id") == "SF-DF01-01"
    brake.set("description", "Scritta in ATLAS")
    brake.set("status", "Rivista")
    p.update(brake)
    manual = p.new_element("system_function", name="Creata a mano", domain=d1.uuid)  # never in the workbook
    p.save()
    # The teams changed the workbook: a clause less for one, a function gone, a new one.
    rows = [list(r) for r in DF01_ROWS]
    rows[0][2] = "3.4.1.2"  # 3.4.1.1 no longer there
    del rows[2]  # «Determinare il modo»
    rows.insert(0, ["SF-DF01-06", "Gestire la riserva", "3.4.1.1", None, "Nuova", "Proposto"])
    again = ImportFunctionsDialog(p, workbook(tmp_path / "sa2-bis.xlsx", rows))
    outcomes = {(x.source.name if x.source else x.existing.get("name")): x.outcome for x in again.planned}
    assert outcomes == {"Gestire la riserva": NEW, "Gestire comandi di frenatura": UPDATED,
                        "Proteggere dal Roll Away": PRESENT, "Monitorare la velocità": PRESENT,
                        "Funzione di un dominio assente": "no_domain", "Determinare il modo": DELETED,
                        "Creata a mano": DELETED}
    entries = {(x.source.name if x.source else x.existing.get("name")): (x, row) for x, row in again.entries}
    planned, row = entries["Gestire comandi di frenatura"]
    assert planned.removed == [items["3.4.1.1"].uuid] and not planned.added
    assert any(row.child(i).text(1) == "3.4.1.1" and "Non più nel file" in row.child(i).text(5)
               for i in range(row.childCount()))
    assert "si tolgono 1 clausola" in row.text(5)
    # Deleted at first only if it came from the workbook; one created in ATLAS only if ticked.
    assert entries["Determinare il modo"][1].checkState(TICK) == Qt.Checked
    assert entries["Creata a mano"][1].checkState(TICK) == Qt.Unchecked
    assert "1 nuove, 1 aggiornate, 1 eliminate · allocazioni: +1 −1 · 2 senza modifiche" in again.counts.text()
    again.import_functions()
    names = {f.get("name") for f in p.model.of_kind("system_function")}
    assert names == {"Gestire comandi di frenatura", "Proteggere dal Roll Away", "Monitorare la  velocità",
                     "Gestire la riserva", "Creata a mano"}
    assert p.model.get(manual.uuid) is manual
    # The function already there is not overwritten: only its clauses follow the workbook.
    assert brake.get("sections") == [items["3.4.1.2"].uuid]
    assert brake.get("description") == "Scritta in ATLAS" and brake.get("status") == "Rivista"
    assert [e.get("name") for e in again.deleted] == ["Determinare il modo"] and REMOVED
