"""The updates of ATLAS: the latest release on GitHub, its file downloaded and checked with its SHA-256 fingerprint,
the installation started and ATLAS closed. No request reaches the network: GitHub is simulated."""
import hashlib
import io
import tarfile
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from arcadia_tool import __version__, updates
from arcadia_tool.ui import updates as updates_ui
from arcadia_tool.ui.dialogs import settings

PAYLOAD = b"installer di prova" * 1000
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def github(version="99.0.0", digest=True, files=("win32", "linux")):
    assets = []
    for platform in files:
        name = updates.asset_name(version, platform)
        asset = {"name": name, "browser_download_url": f"https://example.invalid/{name}", "size": len(PAYLOAD)}
        if digest:
            asset["digest"] = f"sha256:{SHA}"
        else:
            assets.append({"name": f"{name}.sha256", "browser_download_url": f"https://example.invalid/{name}.sha256"})
        assets.append(asset)
    return {"tag_name": f"v{version}", "body": "## Novità\n- tutto", "html_url": "https://example.invalid/rel",
            "assets": assets}


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_versions_are_compared_as_numbers():
    assert updates.parse_version("v0.10.0") == (0, 10, 0)
    assert updates.is_newer("0.10.0", "0.9.3") and not updates.is_newer("0.6.0", "0.6.0")
    assert not updates.is_newer("nightly", "0.6.0") and updates.parse_version("x1") is None


def test_the_latest_release_and_its_file_for_the_system():
    release = updates.latest_release(lambda url: github(), platform="win32")
    assert (release.version, release.asset, release.sha256) == ("99.0.0", "ATLAS-Setup-99.0.0.exe", SHA)
    linux = updates.latest_release(lambda url: github(), platform="linux")
    assert linux.asset == "ATLAS-99.0.0-linux-x86_64.tar.gz"
    none = updates.latest_release(lambda url: github(files=("linux",)), platform="win32")
    assert none.url == ""  # the release has no installer: only its page is offered
    side = updates.latest_release(lambda url: github(digest=False), platform="win32")
    assert side.sha256 == "" and side.sha256_url.endswith(".exe.sha256")  # the fingerprint in a file of its own
    assert updates.expected_sha256(side, lambda url: f"{SHA.upper()}  ATLAS-Setup-99.0.0.exe\n") == SHA

    def offline(url):
        raise OSError("rete assente")
    with pytest.raises(updates.UpdateError, match="Impossibile contattare GitHub"):
        updates.latest_release(offline)


def test_the_download_is_checked_with_the_fingerprint(tmp_path):
    release = updates.latest_release(lambda url: github(), platform="win32")
    seen = []
    path = updates.download(release, lambda d, t: seen.append((d, t)), opener=lambda url, accept: Response(PAYLOAD),
                            folder=tmp_path)
    assert path.read_bytes() == PAYLOAD and seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    # Altered (or downloaded badly): not kept.
    with pytest.raises(updates.UpdateError, match="non corrisponde all'impronta"):
        updates.download(release, opener=lambda url, accept: Response(PAYLOAD + b"!"), folder=tmp_path)
    assert not list(tmp_path.iterdir())
    # Without a fingerprint nothing is downloaded.
    release.sha256 = ""
    with pytest.raises(updates.UpdateError, match="impronta SHA-256"):
        updates.download(release, opener=lambda url, accept: Response(PAYLOAD), folder=tmp_path)
    # Cancelled: nothing left.
    release.sha256 = SHA
    assert updates.download(release, cancelled=lambda: True, opener=lambda url, accept: Response(PAYLOAD),
                            folder=tmp_path) is None
    assert not list(tmp_path.iterdir())


def test_the_installation_is_started_silent_and_ATLAS_opens_again(tmp_path):
    started = []
    updates.start_install(tmp_path / "ATLAS-Setup-99.0.0.exe", platform="win32",
                          popen=lambda command, **kw: started.append(command))
    assert started[0][0].endswith("ATLAS-Setup-99.0.0.exe")
    assert {"/SILENT", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"} <= set(started[0])


def test_the_linux_archive_must_hold_the_folder_of_ATLAS(tmp_path):
    def archive(name, members):
        path = tmp_path / name
        with tarfile.open(path, "w:gz") as tar:
            for member in members:
                info = tarfile.TarInfo(member)
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
        return path
    updates.check_archive(archive("ok.tar.gz", ["ATLAS/ATLAS", "ATLAS/_internal/x"]))
    for bad in (["ATLAS/other"], ["ATLAS/ATLAS", "../etc/passwd"], ["ATLAS/ATLAS", "elsewhere/x"]):
        with pytest.raises(updates.UpdateError):
            updates.check_archive(archive("bad.tar.gz", bad))
    script = updates.linux_script(tmp_path / "a.tar.gz", tmp_path / "opt" / "ATLAS", 1234)
    assert "kill -0 1234" in script and "nohup" in script  # waits for ATLAS to close, then starts it again


def test_from_the_source_code_it_cannot_install_itself():
    assert "codice sorgente" in updates.can_install()  # the tests run from the source code


def test_the_check_at_start_once_a_day_and_the_version_skipped(app, monkeypatch):
    s = settings()
    s.remove("updates")
    assert updates_ui.due_today()
    updates_ui.set_checks_at_start(False)
    assert not updates_ui.due_today()
    updates_ui.set_checks_at_start(True)
    release = updates.latest_release(lambda url: github(), platform="win32")
    shown, told = [], []
    monkeypatch.setattr(updates_ui.UpdateChecker, "show", lambda self, r: shown.append(r.version))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[2]))
    checker = updates_ui.UpdateChecker(None, lambda path: None)

    class Done:
        def wait(self):
            pass
    checker.worker = Done()
    checker._found(release)
    assert shown == ["99.0.0"] and not updates_ui.due_today()  # done today
    assert updates_ui.due_today(date(2000, 1, 1))  # another day: due again
    s.setValue(updates_ui.SKIPPED_KEY, "99.0.0")
    checker._found(release)
    assert shown == ["99.0.0"]  # skipped: not offered at the start…
    checker.manual = True
    checker._found(release)
    assert shown == ["99.0.0", "99.0.0"]  # …but asked from the menu, yes
    release.version = __version__
    checker._found(release)
    assert told and "ultima versione" in told[-1]
    s.remove("updates")


def test_the_window_downloads_and_the_main_window_closes_to_install(app, tmp_path, monkeypatch):
    from arcadia_tool.ui.main_window import MainWindow

    release = updates.latest_release(lambda url: github(), platform="win32")
    monkeypatch.setattr(updates, "can_install", lambda platform=None: None)  # as if installed
    dialog = updates_ui.UpdateDialog(release)
    assert dialog.update_button.text() == "Aggiorna ora"
    assert "Novità" in dialog.findChild(updates_ui.QTextBrowser, "releaseNotes").toPlainText()
    monkeypatch.setattr(updates, "download", lambda r, progress, cancelled: tmp_path / r.asset)
    dialog._update()
    dialog.worker.wait()
    app.processEvents()
    assert dialog.result() == QDialog.Accepted and dialog.path == tmp_path / release.asset
    # The main window: the edits asked about, the installation started, ATLAS closed.
    window = MainWindow()
    started = []
    monkeypatch.setattr(updates, "start_install", lambda path: started.append(path))
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    window.show()
    assert window.install_update(dialog.path)
    assert started == [dialog.path] and not window.isVisible()
    # Blocked (from the source code): only the page of the release.
    monkeypatch.setattr(updates, "can_install", lambda platform=None: "codice sorgente")
    assert updates_ui.UpdateDialog(release).update_button.text() == "Apri la pagina della release"
