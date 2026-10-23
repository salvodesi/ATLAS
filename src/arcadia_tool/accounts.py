"""Local user accounts: who works with the tool on this PC, and their credentials for the Git servers.

Accounts are kept in the user folder of the tool (never in a project or on Git). The account password is
stored only as a salted PBKDF2 hash. The access to a Git server is set in the project settings (where the URL
of the remote is) but kept in the account, one per server («gitlab.example.com»): the kind of authentication,
the Git user and the SSH key file; the Git password or token is in the credential store of the operating
system (Windows Credential Manager, through keyring).
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

HTTPS, SSH = "https", "ssh"
AUTH_LABELS = {HTTPS: "Utente e password/token (HTTP/HTTPS)", SSH: "Chiave SSH"}
PBKDF2_ROUNDS = 240_000
MIN_PASSWORD = 8
KEYRING_SERVICE = "ARCADIA Tool - Git"  # name of the first versions: the Git passwords already saved are kept
USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Options of the ssh client used for the Git remote: no question on the terminal (the tool has none), and the
# key of a new server is accepted the first time and checked the following ones.
SSH_OPTIONS = "-o BatchMode=yes -o StrictHostKeyChecking=accept-new"


class AccountError(Exception):
    pass


@dataclass
class GitAccess:
    """How an account reaches one Git server."""
    auth: str = HTTPS
    username: str = ""  # HTTP/HTTPS (the password or token is in the credential store)
    ssh_key: str = ""  # SSH: path of the private key


@dataclass
class Account:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)  # unique, never changes
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    email: str = ""
    git: dict = field(default_factory=dict)  # server («host[:port]») → GitAccess as a dict
    password_hash: str = ""
    salt: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    # Written by the first version (one access for every server): the default for a server not set yet.
    auth: str = HTTPS
    git_username: str = ""
    ssh_key: str = ""

    def git_access(self, host):
        known = self.git.get(host)
        if known:
            return GitAccess(**{k: v for k, v in known.items() if k in GitAccess.__dataclass_fields__})
        return GitAccess(self.auth, self.git_username, self.ssh_key)

    def set_git_access(self, host, access):
        self.git[host] = asdict(access)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def author(self):
        """Author of the published versions (Git commits)."""
        return f"{self.full_name} <{self.email}>"

    def set_password(self, password):
        if len(password) < MIN_PASSWORD:
            raise AccountError(f"La password deve avere almeno {MIN_PASSWORD} caratteri.")
        self.salt = secrets.token_hex(16)
        self.password_hash = _hash(password, self.salt)

    def check_password(self, password):
        return bool(self.password_hash) and hmac.compare_digest(self.password_hash, _hash(password, self.salt))


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def validate(account, store, password=None, new=False):
    """Problems of an account before it is saved (empty list: valid)."""
    problems = []
    if not account.first_name.strip() or not account.last_name.strip():
        problems.append("Indica nome e cognome.")
    if not USERNAME.match(account.username):
        problems.append("Lo username deve avere da 3 a 32 caratteri tra lettere, cifre, punto, trattino e _.")
    elif any(a.username.lower() == account.username.lower() and a.id != account.id for a in store.accounts):
        problems.append(f"Lo username «{account.username}» è già usato da un altro account.")
    if not EMAIL.match(account.email):
        problems.append("Indica un indirizzo e-mail valido (è l'autore delle versioni pubblicate).")
    if new and not password:
        problems.append("Scegli la password dell'account.")
    if password is not None and password and len(password) < MIN_PASSWORD:
        problems.append(f"La password deve avere almeno {MIN_PASSWORD} caratteri.")
    return problems


def validate_git_access(access):
    """Problems of the access to a Git server (empty list: valid)."""
    if access.auth == HTTPS and not access.username.strip():
        return ["Indica l'utente Git per l'accesso HTTP/HTTPS."]
    if access.auth == SSH and not (access.ssh_key and Path(access.ssh_key).is_file()):
        return ["Genera una chiave SSH o carica una chiave esistente."]
    return []


def git_host(url):
    """Server of a Git URL, the key of its access in the account: «host» or «host:port»; "" for a local path.

    https://user@server:8443/group/project.git → server:8443; git@server:group/project.git → server;
    ssh://git@server:2222/group/project.git → server:2222."""
    url = (url or "").strip()
    if url.lower().startswith("file:"):
        return ""
    if "://" in url:
        match = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::(\d+))?", url, re.IGNORECASE)
        if not match:
            return ""
        return f"{match.group(1)}:{match.group(2)}" if match.group(2) else match.group(1)
    match = re.match(r"^(?:[^@/]+@)?([^/:]+):(?!\\)", url)  # scp-like syntax of ssh (not «C:\…»)
    if match and len(match.group(1)) > 1:
        return match.group(1)
    return ""


class AccountStore:
    """The accounts of this PC, in one JSON file of the tool's user folder."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.file = self.folder / "accounts.json"
        self.accounts = self._load()

    def _load(self):
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        known = Account.__dataclass_fields__
        return [Account(**{k: v for k, v in a.items() if k in known}) for a in data.get("accounts", [])]

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"accounts": [asdict(a) for a in self.accounts]}, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.file)

    def get(self, username):
        return next((a for a in self.accounts if a.username.lower() == (username or "").lower()), None)

    def by_id(self, account_id):
        return next((a for a in self.accounts if a.id == account_id), None)

    def add(self, account):
        self.accounts.append(account)
        self.save()

    def replace(self, account):
        self.accounts = [account if a.id == account.id else a for a in self.accounts]
        self.save()

    def login(self, username, password):
        account = self.get(username)
        return account if account is not None and account.check_password(password) else None

    @property
    def keys_folder(self):
        return self.folder / "keys"


# --- Git credentials ---------------------------------------------------------------------------------

def _secret_key(account, host):
    return f"{account.id}@{host}"


def git_secret(account, host):
    """Password or token for HTTP/HTTPS on a server, from the credential store of the system ("" if none)."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, _secret_key(account, host)) or ""
    except Exception:  # no usable credential store: as if no secret was saved
        return ""


def set_git_secret(account, host, secret):
    import keyring
    try:
        if secret:
            keyring.set_password(KEYRING_SERVICE, _secret_key(account, host), secret)
        elif keyring.get_password(KEYRING_SERVICE, _secret_key(account, host)) is not None:
            keyring.delete_password(KEYRING_SERVICE, _secret_key(account, host))
    except Exception as exc:
        raise AccountError(f"Impossibile salvare la password Git nel portachiavi del sistema: {exc}") from exc


def git_credentials(account, url, access=None, secret=None):
    """Keyword arguments for the dulwich client (ls_remote, fetch, push) to reach the remote `url`.

    access/secret: values being entered (not saved yet), else those kept in the account for the server."""
    host = git_host(url)
    if account is None or not host:
        return {}
    access = access or account.git_access(host)
    if access.auth == SSH:  # dulwich passes the key to ssh itself (-i)
        return {"key_filename": access.ssh_key, "ssh_command": f"ssh {SSH_OPTIONS}"}
    password = secret if secret is not None else git_secret(account, host)
    return {"username": access.username or None, "password": password or None}


# --- SSH keys --------------------------------------------------------------------------------------------

def generate_ssh_key(account, folder):
    """New Ed25519 key pair for the account (private key without passphrase, readable only by its user);
    returns the path of the private key. The public key («.pub») is to be added to the Git service."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    path = folder / f"{account.username or account.id}_ed25519"
    path.write_bytes(private)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    comment = account.email or account.username
    Path(f"{path}.pub").write_text(f"{public.decode()} {comment}\n", encoding="ascii")
    return str(path)


def public_key(private_path):
    """Public key of a private key file: its «.pub» next to it, or computed from the private key."""
    if not private_path:
        return ""
    pub = Path(f"{private_path}.pub")
    if pub.is_file():
        return pub.read_text(encoding="ascii", errors="replace").strip()
    try:
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_ssh_private_key(Path(private_path).read_bytes(), password=None)
        return key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                             serialization.PublicFormat.OpenSSH).decode()
    except Exception:
        return ""


def check_ssh_key(path):
    """Problem of an existing private key file, or None if it can be used (OpenSSH or PEM, no passphrase)."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return f"File non leggibile: {exc}"
    from cryptography.hazmat.primitives import serialization
    try:
        serialization.load_ssh_private_key(data, password=None)
        return None
    except TypeError:
        return "La chiave è protetta da una passphrase: il tool usa solo chiavi senza passphrase."
    except ValueError:
        pass
    try:
        serialization.load_pem_private_key(data, password=None)
        return None
    except TypeError:
        return "La chiave è protetta da una passphrase: il tool usa solo chiavi senza passphrase."
    except ValueError:
        return "Il file non contiene una chiave privata SSH (scegli il file senza «.pub»)."
