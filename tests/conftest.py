import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox


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
