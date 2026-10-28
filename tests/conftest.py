import os
import sys

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

_exit_status = None


def pytest_sessionfinish(session, exitstatus):
    """The windows left by the tests are destroyed while Qt is still whole (not closed: a main window would ask
    whether to save, with a real message box)."""
    global _exit_status
    _exit_status = int(exitstatus)
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is not None:
        for widget in QApplication.topLevelWidgets():
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """Out with the status of the tests, after the report, without the final cleanup of PySide: on Linux it may
    destroy in the wrong order the objects still alive and crash the process after the tests have passed."""
    from PySide6.QtCore import QCoreApplication
    if _exit_status is not None and QCoreApplication.instance() is not None:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_status)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory):
    """Keep tests from touching the user's real settings (recent projects, author)."""
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings")))


@pytest.fixture(autouse=True)
def memory_credentials(monkeypatch):
    """Git passwords of the accounts in memory: tests never touch the credential store of the system."""
    import arcadia_tool.accounts as accounts
    secrets = {}
    monkeypatch.setattr(accounts, "git_secret", lambda account, host: secrets.get((account.id, host), ""))
    monkeypatch.setattr(accounts, "set_git_secret",
                        lambda account, host, secret: secrets.__setitem__((account.id, host), secret))
    return secrets


@pytest.fixture(autouse=True)
def no_modal_message_boxes(monkeypatch):
    """A message box would block an unattended test run: record it instead (critical ones fail the test)."""
    shown = []

    def record(kind, answer):
        def box(*args, **kwargs):
            shown.append((kind, args[2] if len(args) > 2 else ""))
            return answer
        return box

    monkeypatch.setattr(QMessageBox, "information", record("information", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", record("warning", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", record("question", QMessageBox.No))
    monkeypatch.setattr(QMessageBox, "critical", record("critical", QMessageBox.Ok))
    yield shown
    critical = [text for kind, text in shown if kind == "critical"]
    assert not critical, f"messaggio di errore mostrato durante il test: {critical}"


@pytest.fixture(autouse=True)
def deferred_deletes():
    """The widgets destroyed later (deleteLater, e.g. a page rebuilt from one of its signals) are destroyed after
    the test, as the event loop of the application does: they don't pile up until Python exits."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
