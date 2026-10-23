import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import arcadia_tool.ui.main_window as main_window
from arcadia_tool.model.schema import KINDS_BY_NAME, enum_option
from arcadia_tool.storage.project import ModelCache, Project, recovery_file
from arcadia_tool.ui.dialogs import settings
from arcadia_tool.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def saved_project(tmp_path, n=30):
    p = Project.create(tmp_path / "p", "Prova")
    for i in range(n):
        p.new_element("requirement", id=f"3.1.{i}", item_type="Requisito", text=f"text {i}")
    p.save()
    p.close()
    return tmp_path / "p"


def test_saved_files_are_read_from_the_local_cache(tmp_path, monkeypatch):
    path = saved_project(tmp_path)
    assert (path / ModelCache.NAME).exists()
    read = []
    original = type(path).read_bytes
    monkeypatch.setattr(type(path), "read_bytes",
                        lambda self: read.append(self.name) or original(self))
    steps = []
    p = Project.open(path, progress=lambda action, done, total: steps.append(action))
    assert len(p.model) == 30 and not [r for r in read if r.endswith(".yaml")]
    assert steps[0] == "Ricerca dei file del modello" and "Indicizzazione del modello" in steps
    # A file changed outside the tool (e.g. git pull) is read from disk, not from the cache.
    element = p.model.of_kind("requirement")[0]
    file = p.element_file(element)
    file.write_text(file.read_text(encoding="utf-8").replace("text ", "changed "), encoding="utf-8")
    p.close()
    p = Project.open(path)
    assert "changed" in p.model.get(element.uuid).get("text")
    p.close()


def test_recovery_restore_and_discard(tmp_path):
    path = saved_project(tmp_path, 3)
    p = Project.open(path)
    first, second = p.model.of_kind("requirement")[:2]
    first.set("text", "edited")
    p.update(first)
    p.delete_element(second.uuid)
    added = p.new_element("domain", name="Odometria")
    p.write_recovery()
    p.close()  # interrupted: nothing saved

    p = Project.open(path)
    info = p.recovery_info()
    assert info["modified"] == 2 and info["deleted"] == [second.uuid]
    assert p.restore_recovery() == 3
    assert p.model.get(first.uuid).get("text") == "edited" and p.model.get(second.uuid) is None
    assert p.model.get(added.uuid).get("name") == "Odometria" and p.is_modified
    p.save()
    assert not recovery_file(path).exists()
    p.close()

    p = Project.open(path)
    p.new_element("domain")
    p.write_recovery()
    p.discard_recovery()
    assert p.recovery_info() is None
    p.close()


def test_open_with_loading_screen_and_recovery_question(app, tmp_path, monkeypatch):
    path = saved_project(tmp_path)
    p = Project.open(path)
    p.new_element("domain", name="Odometria")
    p.write_recovery()
    p.close()
    settings().setValue("recent", [str(path)])

    asked = []
    monkeypatch.setattr(MainWindow, "_ask_recovery", lambda self, name, info: asked.append(name) or True)
    window = MainWindow()
    window.show()
    window.check_interrupted_sessions()
    assert asked == ["p"]  # asked once, at start-up
    assert window.project is not None and len(window.project.model) == 31 and window.project.is_modified
    window.save()
    window.close()

    window = MainWindow()
    window.open_project(str(path))
    assert len(window.project.model) == 31 and asked == ["p"]  # nothing left to restore
    window.close()


def test_missing_recent_projects_are_hidden(app, tmp_path):
    path = saved_project(tmp_path)
    settings().setValue("recent", [str(tmp_path / "gone"), str(path)])
    window = MainWindow()
    assert [a.text() for a in window.recent_menu.actions()] == [str(path)]
    window.close()


def test_b5_and_b6_are_enumerations():
    b5 = KINDS_BY_NAME["trace_record"].field("b5_question")
    b6 = KINDS_BY_NAME["derived_requirement"].field("b6_scheme")
    assert b5.options[3].startswith("4 – Obblighi di domini diversi")
    assert enum_option(b5, "4") == b5.options[3]  # value stored by earlier versions
    assert b6.label == "Motivazione della derivazione"
    assert enum_option(b6, "2").startswith("2 – Una procedura chiede")
    old = "2 – La procedura (DF08) chiede un'azione al dominio proprietario"  # wording of an earlier version
    assert enum_option(b6, old) == b6.options[1] and not any("DF" in o for o in b6.options)
    assert enum_option(b6, None) is None
