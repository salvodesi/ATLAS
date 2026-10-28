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
CHECKS_FILE = "checks.yaml"  # settings of the checks of the methodology: profiles, parameters, exceptions
TRACKED_FILES = (PROJECT_FILE, CHECKS_FILE, ".gitignore")
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


def _version(commit):
    return Version(
        sha=commit.id.decode(),
        message=commit.message.decode("utf-8", "replace").strip(),
        author=commit.author.decode("utf-8", "replace"),
        timestamp=datetime.fromtimestamp(commit.commit_time, timezone.utc).astimezone(),
    )


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


def keep_line_endings(repo):
    """The files are written as they are in the versions (LF), whatever the Git installed on the computer says
    (Git for Windows sets core.autocrlf=true for the whole system): else every downloaded file would differ from
    its version and the project would always look changed."""
    config = repo.get_config()
    try:
        if config.get((b"core",), b"autocrlf") == b"false":
            return
    except KeyError:
        pass
    config.set((b"core",), b"autocrlf", b"false")
    config.write_to_path()


class Repository:
    def __init__(self, path):
        self.path = path
        self._repo = Repo(str(path))
        keep_line_endings(self._repo)
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

    def save_version(self, message, author, files, merged=None, working=None):
        """Record `files` ({relative path: bytes}, the whole project content) as a new version. merged: the
        version integrated with it (a second parent: the versions received from the remote). working: the
        content on disk, if it is not `files` (see _write_index)."""
        entries = self._entries(files)
        tree = self._build_tree(entries, store_blobs=True)
        head = self.head()
        if tree == self._head_tree() and merged is None:
            raise NothingToSave()
        now = int(time.time())
        offset = time.localtime(now).tm_gmtoff
        commit = Commit()
        commit.tree = tree
        commit.parents = ([head.encode()] if head else []) + ([merged.encode()] if merged else [])
        commit.author = commit.committer = author.encode("utf-8")
        commit.author_time = commit.commit_time = now
        commit.author_timezone = commit.commit_timezone = offset
        commit.encoding = b"UTF-8"
        commit.message = message.encode("utf-8")
        self._repo.object_store.add_object(commit)
        self._repo.refs[b"HEAD"] = commit.id
        self._write_index(entries, working)
        return commit.id.decode()

    def _write_index(self, entries, working=None):
        """Keep the Git index in sync with the new version, so external git tools see a clean tree. working:
        the content of the files on disk when it may differ from the version (only the files equal to it are
        recorded as unchanged)."""
        index = self._repo.open_index()
        for path in list(index):
            del index[path]
        for rel, blob in entries:
            file = self.path / rel.decode("utf-8")
            if working is not None and working.get(rel.decode("utf-8")) != blob.data:
                continue
            if file.exists():
                index[rel] = index_entry_from_stat(os.stat(file), blob.id, FILE_MODE)
        index.write()
        self._index = None

    # --- versions of other PCs: receiving and merging --------------------------------------------------------

    def files_at(self, sha):
        """The whole project content of a version: {relative path: bytes}."""
        if not sha:
            return {}
        store = self._repo.object_store
        return {e.path.decode("utf-8"): store[e.sha].data
                for e in iter_tree_contents(store, self._repo[sha.encode()].tree)}

    def merge_base(self, a, b):
        """The last version two versions both come from, or None (unrelated histories)."""
        from dulwich.graph import find_merge_base

        found = find_merge_base(self._repo, [a.encode(), b.encode()])
        return found[0].decode() if found else None

    def is_ancestor(self, a, b):
        """The version `a` is in the history of `b` (or is `b`)."""
        return a == b or self.merge_base(a, b) == a

    def versions_between(self, since, until):
        """The versions in the history of `until` that are not in that of `since` (a version, or a list of them),
        newest first."""
        since = [since] if isinstance(since, str) else list(since or [])
        walker = self._repo.get_walker(include=[until.encode()], exclude=[s.encode() for s in since if s] or None)
        return [_version(entry.commit) for entry in walker]

    def move_to(self, sha, working):
        """The local branch moves to the version `sha` (e.g. received from the remote) without touching the
        files on disk, whose content is `working`: the files different from the version are changes to
        publish."""
        self._repo.refs[b"HEAD"] = sha.encode()
        self._write_index(self._entries(self.files_at(sha)), working)

    def set_remote_head(self, branch, sha):
        self._repo.refs[f"refs/remotes/origin/{branch}".encode()] = sha.encode()

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

    def history(self, limit=None, start=None):
        """The versions of the local branch (or of the version `start`, e.g. the head of another branch), newest
        first."""
        start = start or self.head()
        if start is None:
            return []
        return [_version(entry.commit)
                for entry in self._repo.get_walker(include=[start.encode()], max_entries=limit)]

    def version(self, sha):
        return _version(self._repo[sha.encode()])

    def parents(self, sha):
        """The versions a version comes from: one, two for an integration of versions received, none for the
        first one."""
        return [p.decode() for p in self._repo[sha.encode()].parents]

    # --- branches -----------------------------------------------------------------------------------------

    def _heads(self, prefix):
        prefix = prefix.encode()
        return {ref[len(prefix):].decode("utf-8"): self._repo.refs[ref].decode()
                for ref in self._repo.refs.keys() if ref.startswith(prefix) and ref[len(prefix):] != b"HEAD"}

    def local_heads(self):
        """{branch: last version} of the branches of this PC."""
        return self._heads("refs/heads/")

    def remote_heads(self):
        """{branch: last version} of the branches of the remote, as known at the last download."""
        return self._heads("refs/remotes/origin/")

    def set_remote_heads(self, heads):
        """The branches of the remote just downloaded (those no longer there are forgotten)."""
        for branch in set(self.remote_heads()) - set(heads):
            del self._repo.refs[f"refs/remotes/origin/{branch}".encode()]
        for branch, sha in heads.items():
            self.set_remote_head(branch, sha)

    def start_branch(self, branch):
        """A new local branch at the current version, which becomes the one in use; the files do not change (the
        next version is recorded on it)."""
        ref = f"refs/heads/{branch}".encode()
        head = self.head()
        if head is not None:
            self._repo.refs[ref] = head.encode()
        self._repo.refs.set_symbolic_ref(b"HEAD", ref)

    def delete_branch(self, branch):
        """Remove a local branch (not the one in use)."""
        ref = f"refs/heads/{branch}".encode()
        if branch != self.local_branch() and ref in self._repo.refs:
            del self._repo.refs[ref]

    def checkout(self, branch, sha, working):
        """The local branch becomes `branch` at the version `sha` (created if missing); `working` is the content
        written on disk (the files of the version, see Project.switch_branch)."""
        ref = f"refs/heads/{branch}".encode()
        self._repo.refs[ref] = sha.encode()
        self._repo.refs.set_symbolic_ref(b"HEAD", ref)
        self._write_index(self._entries(self.files_at(sha)), working)

    def model_at(self, sha):
        store = self._repo.object_store
        tree = self._repo[sha.encode()].tree
        prefix = MODEL_DIR.encode() + b"/"
        elements = []
        for entry in iter_tree_contents(store, tree):
            if entry.path.startswith(prefix) and entry.path.endswith(b".yaml"):
                elements.append(loads(store[entry.sha].data.decode("utf-8")))
        return Model(elements)
