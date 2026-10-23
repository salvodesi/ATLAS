"""Git history of a project: published versions, timeline and model snapshots.

Versions are written with low-level dulwich calls: the tree is built directly from the project files
(hashing a few thousand small files is fast) instead of going through `porcelain.add`, which is
too slow on projects with thousands of SRS items.
"""
import io
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from dulwich import client as dulwich_client
from dulwich import porcelain
from dulwich.index import commit_tree, index_entry_from_stat
from dulwich.object_store import MemoryObjectStore, iter_tree_contents
from dulwich.objects import Blob, Commit
from dulwich.repo import Repo

from arcadia_tool.model.element import Model
from arcadia_tool.model.serialization import loads

MODEL_DIR = "model"
PROJECT_FILE = "project.yaml"
TRACKED_FILES = (PROJECT_FILE, ".gitignore")
FILE_MODE = 0o100644


class NothingToSave(Exception):
    pass


class PushRefused(Exception):
    """The remote refused the versions sent (usually: it has versions of colleagues not received yet)."""


class _WindowlessSSHVendor(dulwich_client.SubprocessSSHVendor):
    """The ssh client of the system, started without a console window: in the tool (a windowed program) every
    Git operation over SSH would otherwise flash a black window. Same arguments as dulwich's own vendor."""

    def run_command(self, host, command, username=None, port=None, password=None, key_filename=None,
                    ssh_command=None, protocol_version=None):
        if password is not None:
            raise NotImplementedError("Password SSH non supportata: usa una chiave.")
        args = [*shlex.split(ssh_command, posix=False), "-x"] if ssh_command else ["ssh", "-x"]
        if port:
            args += ["-p", str(port)]
        if key_filename:
            args += ["-i", str(key_filename)]
        if protocol_version is None:
            protocol_version = dulwich_client.DEFAULT_GIT_PROTOCOL_VERSION_FETCH
        if protocol_version > 0:
            args += ["-o", f"SetEnv GIT_PROTOCOL=version={protocol_version}"]
        if username:
            host = f"{username}@{host}"
        if host.startswith("-"):
            raise dulwich_client.StrangeHostname(hostname=host)
        proc = subprocess.Popen([*args, host, command], bufsize=0, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return dulwich_client.SubprocessWrapper(proc)


if sys.platform == "win32":
    dulwich_client.get_ssh_vendor = _WindowlessSSHVendor


def remote_branches(url, **credentials):
    """Branches (development trees) of a remote repository (any Git server, HTTP/HTTPS or SSH, or a local
    path), sorted; see remote_branches_and_default for the default one."""
    return remote_branches_and_default(url, **credentials)[0]


def remote_branches_and_default(url, **credentials):
    """(branches, default branch or None) of a remote repository.

    credentials: username/password, or key_filename/ssh_command (see accounts.git_credentials).
    Raises an exception with the reason when the server cannot be reached or refuses the access."""
    result = porcelain.ls_remote(url, **credentials)
    refs = getattr(result, "refs", result)  # LsRemoteResult in recent dulwich, a plain dict before
    prefix = b"refs/heads/"
    branches = sorted(name[len(prefix):].decode("utf-8") for name in refs if name.startswith(prefix))
    head = (getattr(result, "symrefs", None) or {}).get(b"HEAD", b"")  # e.g. refs/heads/main
    default = head[len(prefix):].decode("utf-8") if head.startswith(prefix) else None
    if default is None and refs.get(b"HEAD"):  # no symref announced: the branch at the same commit as HEAD
        default = next((n[len(prefix):].decode("utf-8") for n, sha in refs.items()
                        if n.startswith(prefix) and sha == refs[b"HEAD"]), None)
    return branches, default if default in branches else None


@dataclass(frozen=True)
class Version:
    sha: str
    message: str
    author: str
    timestamp: datetime

    @property
    def short(self):
        return self.sha[:8]

    @property
    def title(self):
        return self.message.splitlines()[0] if self.message else ""


class Repository:
    def __init__(self, path):
        self.path = path
        self._repo = Repo(str(path))
        self._index = None

    @classmethod
    def init(cls, path):
        porcelain.init(str(path)).close()
        return cls(path)

    def close(self):
        self._repo.close()

    # --- remote (any Git server: the standard «origin» of .git/config) -------------------------------------

    def remote_url(self):
        try:
            return self._repo.get_config().get((b"remote", b"origin"), b"url").decode("utf-8")
        except KeyError:
            return ""

    def set_remote_url(self, url):
        config = self._repo.get_config()
        if url:
            config.set((b"remote", b"origin"), b"url", url.encode("utf-8"))
            config.set((b"remote", b"origin"), b"fetch", b"+refs/heads/*:refs/remotes/origin/*")
        elif (b"remote", b"origin") in config:
            del config[(b"remote", b"origin")]
        config.write_to_path()

    def head(self):
        try:
            return self._repo.head().decode()
        except KeyError:
            return None

    def local_branch(self):
        """Name of the local branch the versions are recorded on (e.g. «master»)."""
        try:
            ref = self._repo.refs.read_ref(b"HEAD") or b""
        except KeyError:
            ref = b""
        prefix = b"ref: refs/heads/"
        return ref[len(prefix):].decode("utf-8") if ref.startswith(prefix) else "master"

    def fetch(self, url, **credentials):
        """Download every branch of the remote `url`, with its whole history, into the local object store.
        Returns {branch: last version (sha)}; the local branches and files are not changed."""
        result = porcelain.fetch(self._repo, url, outstream=io.StringIO(), errstream=io.BytesIO(), **credentials)
        refs = getattr(result, "refs", None) or {}
        prefix = b"refs/heads/"
        return {name[len(prefix):].decode("utf-8"): sha.decode() for name, sha in refs.items()
                if name.startswith(prefix) and sha}

    def switch_to(self, branch, sha):
        """The local branch becomes `branch` at the version `sha` (downloaded), with its files: what was there
        before stays in the history of the folder but is no longer on the branch."""
        ref = f"refs/heads/{branch}".encode()
        self._repo.refs[ref] = sha.encode()
        self._repo.refs.set_symbolic_ref(b"HEAD", ref)
        self._repo.refs[f"refs/remotes/origin/{branch}".encode()] = sha.encode()
        porcelain.reset(self._repo, "hard", sha.encode())
        self._index = None

    def send_branch(self, url, sha, branch, **credentials):
        """Send the version `sha` (with its history) as `branch` of the remote `url` (e.g. the migration of a
        branch downloaded from another remote). Raises an exception if the remote refuses it."""
        temporary = f"refs/arcadia-migration/{branch}".encode()
        self._repo.refs[temporary] = sha.encode()
        try:
            result = porcelain.push(self._repo, url, temporary + f":refs/heads/{branch}".encode(),
                                    outstream=io.BytesIO(), errstream=io.BytesIO(), **credentials)
            refused = {r: s for r, s in (getattr(result, "ref_status", None) or {}).items() if s}
            if refused:
                raise PushRefused("; ".join(f"{r.decode()}: {s}" for r, s in refused.items()))
        finally:
            del self._repo.refs[temporary]

    def remote_branch_head(self, branch):
        """Last version of `branch` known to be on the remote (written by a download or a push), or None."""
        try:
            return self._repo.refs[f"refs/remotes/origin/{branch}".encode()].decode()
        except KeyError:
            return None

    def push(self, url, branch, **credentials):
        """Send the published versions of the local branch to `branch` of the remote `url` (created if missing).

        credentials: see accounts.git_credentials. Raises an exception with the reason if the remote refuses
        (e.g. it has versions that are not here: they must be received first)."""
        local = self.local_branch()
        result = porcelain.push(self._repo, url, f"refs/heads/{local}:refs/heads/{branch}".encode(),
                                outstream=io.BytesIO(), errstream=io.BytesIO(), **credentials)
        refused = {ref: status for ref, status in (getattr(result, "ref_status", None) or {}).items() if status}
        if refused:
            raise PushRefused("; ".join(f"{ref.decode()}: {status}" for ref, status in refused.items()))
        self._repo.refs[f"refs/remotes/origin/{branch}".encode()] = self._repo.head()
        return self.head()

    @staticmethod
    def _entries(files):
        """files: {relative posix path: content bytes} → [(path bytes, Blob)] sorted by path."""
        return [(rel.encode("utf-8"), Blob.from_string(data)) for rel, data in sorted(files.items())]

    def _head_tree(self):
        head = self.head()
        return self._repo[head.encode()].tree if head else None

    def _head_blobs(self):
        tree = self._head_tree()
        return {e.sha for e in iter_tree_contents(self._repo.object_store, tree)} if tree else set()

    def _build_tree(self, entries, store_blobs):
        blobs = [(rel, blob.id, FILE_MODE) for rel, blob in entries]
        if not store_blobs:
            return commit_tree(MemoryObjectStore(), blobs)
        store = self._repo.object_store
        known = self._head_blobs()
        missing = [(blob, None) for _, blob in entries if blob.id not in known]
        if missing:
            store.add_objects(missing)
        return commit_tree(store, blobs)

    def has_unsaved_changes(self, files):
        """True if `files` (the project content) differ from the last published version."""
        return self._build_tree(self._entries(files), store_blobs=False) != self._head_tree()

    def save_version(self, message, author, files):
        """Record `files` ({relative path: bytes}, the whole project content) as a new version."""
        entries = self._entries(files)
        tree = self._build_tree(entries, store_blobs=True)
        head = self.head()
        if tree == self._head_tree():
            raise NothingToSave()
        now = int(time.time())
        offset = time.localtime(now).tm_gmtoff
        commit = Commit()
        commit.tree = tree
        commit.parents = [head.encode()] if head else []
        commit.author = commit.committer = author.encode("utf-8")
        commit.author_time = commit.commit_time = now
        commit.author_timezone = commit.commit_timezone = offset
        commit.encoding = b"UTF-8"
        commit.message = message.encode("utf-8")
        self._repo.object_store.add_object(commit)
        self._repo.refs[b"HEAD"] = commit.id
        self._write_index(entries)
        return commit.id.decode()

    def _write_index(self, entries):
        """Keep the Git index in sync with the new version, so external git tools see a clean tree."""
        index = self._repo.open_index()
        for path in list(index):
            del index[path]
        for rel, blob in entries:
            file = self.path / rel.decode("utf-8")
            if file.exists():
                index[rel] = index_entry_from_stat(os.stat(file), blob.id, FILE_MODE)
        index.write()
        self._index = None

    def unchanged_content(self, rel, stat):
        """Content of a working file taken from the object store if the index says it is unchanged.

        Like git, a file whose size and modification time match its index entry is assumed unchanged:
        reading it from the (single) pack file avoids opening thousands of small files.
        """
        if self._index is None:
            self._index = self._repo.open_index()
        try:
            entry = self._index[rel.encode("utf-8")]
        except KeyError:
            return None
        mtime = entry.mtime if isinstance(entry.mtime, tuple) else (int(entry.mtime), 0)
        if entry.size != stat.st_size or mtime != divmod(stat.st_mtime_ns, 1_000_000_000):
            return None
        try:
            return self._repo.object_store[entry.sha].data
        except KeyError:
            return None

    def history(self, limit=None):
        if self.head() is None:
            return []
        versions = []
        for entry in self._repo.get_walker(max_entries=limit):
            c = entry.commit
            versions.append(Version(
                sha=c.id.decode(),
                message=c.message.decode("utf-8", "replace").strip(),
                author=c.author.decode("utf-8", "replace"),
                timestamp=datetime.fromtimestamp(c.commit_time, timezone.utc).astimezone(),
            ))
        return versions

    def model_at(self, sha):
        store = self._repo.object_store
        tree = self._repo[sha.encode()].tree
        prefix = MODEL_DIR.encode() + b"/"
        elements = []
        for entry in iter_tree_contents(store, tree):
            if entry.path.startswith(prefix) and entry.path.endswith(b".yaml"):
                elements.append(loads(store[entry.sha].data.decode("utf-8")))
        return Model(elements)
