import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from arcadia_tool import accounts
from arcadia_tool.accounts import HTTPS, SSH, Account, AccountStore, GitAccess, git_host
from arcadia_tool.storage.project import Project
from arcadia_tool.storage.repository import remote_branches


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def person(**values):
    data = dict(first_name="Mario", last_name="Rossi", username="mrossi", email="mario.rossi@example.com")
    data.update(values)
    return Account(**data)


def test_accounts_are_stored_with_a_password_hash_only(tmp_path):
    store = AccountStore(tmp_path)
    account = person()
    assert accounts.validate(account, store, "segreta123", new=True) == []
    account.set_password("segreta123")
    store.add(account)
    text = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "segreta123" not in text and account.password_hash in text  # salted hash, never the password
    again = AccountStore(tmp_path)  # read back from the file
    assert again.login("MROSSI", "segreta123").id == account.id  # username not case sensitive
    assert again.login("mrossi", "sbagliata") is None and again.login("altro", "segreta123") is None
    assert len(account.id) == 32 and account.author == "Mario Rossi <mario.rossi@example.com>"
    twin = person(email="altro@example.com")
    problems = accounts.validate(twin, again, "corta", new=True)
    assert any("già usato" in p for p in problems) and any("almeno 8" in p for p in problems)


def test_server_of_a_git_url():
    assert git_host("https://gitlab.example.com/evc/modello.git") == "gitlab.example.com"
    assert git_host("https://mrossi@git.rfi.it:8443/evc/modello.git") == "git.rfi.it:8443"
    assert git_host("git@github.com:evc/modello.git") == "github.com"
    assert git_host("ssh://git@git.rfi.it:2222/evc/modello.git") == "git.rfi.it:2222"
    assert git_host(r"C:\Repo\modello") == "" and git_host("file:///C:/Repo/modello") == ""  # no server


def test_git_access_is_kept_per_server_in_the_account(tmp_path, memory_credentials):
    account = person()
    https = GitAccess(HTTPS, "mrossi")
    assert accounts.validate_git_access(https) == []
    assert accounts.validate_git_access(GitAccess(HTTPS, "")) and accounts.validate_git_access(GitAccess(SSH))
    account.set_git_access("gitlab.example.com", https)
    accounts.set_git_secret(account, "gitlab.example.com", "token-xyz")
    key = accounts.generate_ssh_key(account, tmp_path / "keys")
    account.set_git_access("github.com", GitAccess(SSH, ssh_key=key))
    store = AccountStore(tmp_path)
    store.add(account)
    assert "token-xyz" not in (tmp_path / "accounts.json").read_text(encoding="utf-8")
    saved = AccountStore(tmp_path).get("mrossi")
    assert accounts.git_credentials(saved, "https://gitlab.example.com/evc/modello.git") == {
        "username": "mrossi", "password": "token-xyz"}
    ssh = accounts.git_credentials(saved, "git@github.com:evc/modello.git")
    assert ssh["key_filename"] == key and "BatchMode=yes" in ssh["ssh_command"]
    assert accounts.git_credentials(saved, str(tmp_path)) == {}  # a local path needs none


def test_ssh_key_generated_for_the_account(tmp_path):
    account = person()
    key = accounts.generate_ssh_key(account, tmp_path / "keys")
    public = accounts.public_key(key)
    assert public.startswith("ssh-ed25519 ") and public.endswith("mario.rossi@example.com")
    assert accounts.check_ssh_key(key) is None
    assert "senza «.pub»" in accounts.check_ssh_key(f"{key}.pub")  # the public key is not a private key


def test_remote_branches_of_any_git_repository(tmp_path):
    """The check of the connection only needs Git: here a repository reached by its path."""
    p = Project.create(tmp_path / "remote", "Remoto")
    p.new_element("domain", name="Odometria")
    p.publish("v1", "Mario Rossi <mario.rossi@example.com>")
    p.close()
    assert remote_branches(str(tmp_path / "remote")) == ["master"]
    with pytest.raises(Exception):
        remote_branches(str(tmp_path / "missing"))


def test_first_start_creates_the_account_and_then_asks_to_log_in(app, tmp_path, monkeypatch):
    from arcadia_tool.ui import accounts as ui

    store = AccountStore(tmp_path / "accounts")
    monkeypatch.setattr(ui, "account_store", lambda: store)

    def fill(dialog):  # the user fills in the first account (no Git access here: it is in the project)
        dialog.first_name.setText("Mario")
        dialog.last_name.setText("Rossi")
        dialog.username.setText("mrossi")
        dialog.email.setText("mario.rossi@example.com")
        dialog.password.setText("segreta123")
        dialog.confirm.setText("segreta123")
        dialog._save()
        return dialog.result()
    monkeypatch.setattr(ui.AccountDialog, "exec", fill)
    account = ui.require_login()
    assert account is not None and store.get("mrossi") is account

    def log_in(dialog, password):
        dialog.password.setText(password)
        dialog._login()
        return dialog.result()
    monkeypatch.setattr(ui.LoginDialog, "exec", lambda d: log_in(d, "sbagliata"))
    assert ui.require_login() is None  # wrong password: no access
    monkeypatch.setattr(ui.LoginDialog, "exec", lambda d: log_in(d, "segreta123"))
    assert ui.require_login().id == account.id


def test_account_dialog_keeps_the_password_when_left_empty(app, tmp_path):
    from arcadia_tool.ui.accounts import AccountDialog

    store = AccountStore(tmp_path)
    account = person()
    account.set_password("segreta123")
    store.add(account)
    dialog = AccountDialog(store, account)
    assert dialog.ident.isReadOnly() and dialog.ident.text() == account.id
    assert not hasattr(dialog, "auth_ssh")  # the Git access is set in the project settings
    dialog.last_name.setText("Bianchi")
    dialog._save()
    saved = AccountStore(tmp_path).get("mrossi")
    assert saved.last_name == "Bianchi" and saved.check_password("segreta123")
    assert account.last_name == "Rossi"  # the dialog worked on a copy until «Salva»


def test_project_settings_set_the_git_access_kept_in_the_account(app, tmp_path, monkeypatch, memory_credentials):
    from arcadia_tool.ui import accounts as ui
    from arcadia_tool.ui.main_window import MainWindow
    from arcadia_tool.ui.project_settings import ProjectSettingsDialog, recovery_minutes
    from arcadia_tool.ui.versions import PublishDialog

    store = AccountStore(tmp_path / "accounts")
    user = person()
    user.set_password("segreta123")
    store.add(user)
    monkeypatch.setattr(ui, "account_store", lambda: AccountStore(tmp_path / "accounts"))
    import arcadia_tool.ui.project_settings as project_settings
    monkeypatch.setattr(project_settings, "account_store", lambda: AccountStore(tmp_path / "accounts"))

    remote = Project.create(tmp_path / "remote", "Remoto")
    remote.new_element("domain", name="Odometria")
    remote.publish("v1", "Mario Rossi <mario.rossi@example.com>")
    remote.close()

    window = MainWindow()
    window.set_user(user)
    window._set_project(Project.create(tmp_path / "p", "Prova"))
    assert "Mario Rossi" in window.status_user.text()  # next to the project in the status bar
    menus = [a.text() for a in window.menuBar().actions()]
    assert "&Utente" in menus
    project_menu = window.menuBar().actions()[menus.index("&Progetto")].menu()
    assert "Impostazioni…" in [a.text() for a in project_menu.actions()]

    dialog = ProjectSettingsDialog(window.project, user, window)
    dialog.name.setText("EVC bordo")
    dialog.description.setPlainText("Modello funzionale dell'EVC")
    dialog.remote.setText(str(tmp_path / "remote"))  # a local path: no credentials needed
    dialog._show_access()
    assert not dialog.access.isEnabled()
    dialog.check_connection()
    dialog.worker.wait(10000)
    for _ in range(50):
        app.processEvents()
        if dialog.check_button.isEnabled():
            break
    assert "Connessione riuscita" in dialog.check_result.text()
    assert [dialog.branch.itemText(i) for i in range(dialog.branch.count())] == ["master"]

    dialog.remote.setText("https://gitlab.example.com/evc/modello.git")  # a server: its access is asked
    dialog._show_access()
    assert dialog.access.isEnabled() and "gitlab.example.com" in dialog.access_note.text()
    dialog.access.git_username.setText("mrossi")
    dialog.access.git_secret.setText("token-xyz")
    dialog.branch.setCurrentText("develop")
    dialog.recovery.setValue(5)
    dialog._save()
    p = window.project
    assert p.name == "EVC bordo" and p.description == "Modello funzionale dell'EVC"
    assert "EVC bordo" in (p.path / "project.yaml").read_text(encoding="utf-8")  # shared with the team
    assert p.repository.remote_url() == "https://gitlab.example.com/evc/modello.git"  # .git/config origin
    assert p.settings["remote"] == "https://gitlab.example.com/evc/modello.git"  # and shared in the project
    assert "mrossi" not in (p.path / "project.yaml").read_text(encoding="utf-8")  # no credentials there
    assert p.local_settings()["branch"] == "develop" and recovery_minutes() == 5
    saved = AccountStore(tmp_path / "accounts").get("mrossi")  # the access is in the account
    assert saved.git_access("gitlab.example.com") == GitAccess(HTTPS, "mrossi")
    assert memory_credentials[(user.id, "gitlab.example.com")] == "token-xyz"

    again = ProjectSettingsDialog(p, saved, window)  # opened again: the access of the server is shown
    assert again.access.git_username.text() == "mrossi" and again.access.git_secret.text() == "token-xyz"

    publish = PublishDialog(p, window, user=user)  # the author comes from the account
    assert publish.author_name.text() == "Mario Rossi" and publish.author_name.isReadOnly()
    window.save()
    window.close()
