"""A project on disk: one YAML file per element under model/<folder>/, versioned with Git."""
import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import yaml
from dulwich import porcelain

from arcadia_tool.model.element import Element, Model, natural_key
from arcadia_tool.model.identifiers import compute_id, is_automatic, matches_context
from arcadia_tool.model.links import keep_in_step
from arcadia_tool.model.teams import member_rows
from arcadia_tool.model.schema import B5_QUESTIONS, KINDS, KINDS_BY_NAME, derived_value
from arcadia_tool.model.serialization import dumps, loads
from arcadia_tool.storage.repository import (CHECKS_FILE, MODEL_DIR, PROJECT_FILE, TRACKED_FILES, Repository,
                                             keep_line_endings, remote_branches_and_default)

FORMAT_VERSION = 1
ASSETS_DIR = "assets"
GITIGNORE = ".arcadia/\n"


class ProjectError(Exception):
    pass


def describe_project(path):
    """What a project folder contains, read without loading the model: name, remote, versions published,
    versions not yet sent to the remote (to warn before deleting it)."""
    path = Path(path)
    settings = yaml.safe_load((path / PROJECT_FILE).read_text(encoding="utf-8")) or {}
    try:
        local = json.loads((path / LOCAL_SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        local = {}
    info = {"name": settings.get("name", path.name), "remote": settings.get("remote", ""), "versions": 0,
            "unsent": 0}
    if (path / ".git").exists():
        repository = Repository(path)
        try:
            info["remote"] = repository.remote_url() or info["remote"]
            versions = repository.history()
            branch = local.get("branch") or repository.local_branch()
            info["versions"] = len(versions)
            info["unsent"] = len(_unsent(versions, local.get("sent") or repository.remote_branch_head(branch)))
        finally:
            repository.close()
    return info


def reload_project(path, url, branch=None, **credentials):
    """The project at `path` (closed in the tool) replaced by `branch` of the remote `url`, e.g. after its
    address changed: download, then the local branch and files become those of the remote. Without a branch:
    the default one of the remote. Returns the branch. What was there before stays in the Git history."""
    path = Path(path)
    repository = Repository(path)
    try:
        heads = repository.fetch(url, **credentials)
        if not heads:
            raise ProjectError("Il repository è vuoto: non c'è un progetto da caricare (puoi inviare il tuo con "
                               "Versioni › Invia al repository).")
        if not branch:
            branch = remote_branches_and_default(url, **credentials)[1] or sorted(heads)[0]
        if branch not in heads:
            raise ProjectError(f"Il ramo «{branch}» non esiste nel repository. Rami disponibili: "
                               f"{', '.join(sorted(heads))}.")
        repository.switch_to(branch, heads[branch])
        repository.set_remote_url(url)
    finally:
        repository.close()
    if not (path / PROJECT_FILE).exists():
        raise ProjectError("Il ramo scaricato non contiene un progetto ARCADIA (manca project.yaml).")
    local = {}
    try:
        local = json.loads((path / LOCAL_SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    local.update(branch=branch, sent=heads[branch])
    _write_text(path / LOCAL_SETTINGS, json.dumps(local, indent=2))
    return branch


def migrate_repository(path, source, target, branches, source_credentials=None, target_credentials=None,
                       progress=None):
    """Copy branches of the remote `source`, each with its whole history, to the remote `target` (e.g. the move
    of the project to another Git server). progress(branch, outcome) after each branch. Returns
    {branch: None if sent, else the reason it was not}. A branch that exists on the target with another history
    is not overwritten."""
    repository = Repository(Path(path))
    results = {}
    try:
        heads = repository.fetch(source, **(source_credentials or {}))
        for branch in branches:
            if branch not in heads:
                results[branch] = "il ramo non esiste nel repository di origine"
            else:
                try:
                    repository.send_branch(target, heads[branch], branch, **(target_credentials or {}))
                    results[branch] = None
                except Exception as exc:
                    diverged = exc.__class__.__name__ in ("DivergedBranches", "PushRefused")
                    results[branch] = ("esiste già nella destinazione con una storia diversa: non sovrascritto"
                                       if diverged else str(exc) or exc.__class__.__name__)
            if progress:
                progress(branch, results[branch])
    finally:
        repository.close()
    return results


def _unsent(versions, sent):
    """The versions (newest first) after the one known to be on the remote; all of them if none is known."""
    index = next((i for i, v in enumerate(versions) if v.sha == sent), None)
    return versions if index is None else versions[:index]


def clone_project(url, target, branch=None, **credentials):
    """Download a project from a Git remote (any server) into the folder `target`, new or empty.

    credentials: see accounts.git_credentials. Returns the path of the project. The folder is removed again if
    the download fails or the repository does not contain an ARCADIA project."""
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise ProjectError(f"La cartella {target} non è vuota.")
    created = not target.exists()
    try:
        # The files are written after the configuration of the line endings (see keep_line_endings).
        with porcelain.clone(url, str(target), checkout=False, branch=branch or None, errstream=io.BytesIO(),
                             **credentials) as cloned:
            keep_line_endings(cloned)
            if b"HEAD" in cloned.refs:
                porcelain.reset(cloned, "hard", cloned.head())
        if not (target / PROJECT_FILE).exists():
            raise ProjectError("Il repository non contiene un progetto ARCADIA (manca project.yaml): verifica "
                               "l'URL e il ramo.")
    except Exception:
        _remove_folder(target, keep=not created)
        raise
    # The working branch, and the version downloaded: it is on the remote already (nothing to send).
    repository = Repository(target)
    local = {"branch": branch or repository.local_branch(), "sent": repository.head()}
    repository.close()
    _write_text(target / LOCAL_SETTINGS, json.dumps(local, indent=2))
    return target


def _remove_folder(target, keep):
    """Undo a failed download: the folder, or (if it existed already, empty) its content."""
    if not target.exists():
        return
    if not keep:
        shutil.rmtree(target, ignore_errors=True)
        return
    for child in target.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Nothing to protect: write directly (much faster when importing thousands of items).
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _document_key(element):
    """Specification order of SRS items: position in the document when imported, else the clause number."""
    sequence = element.get("sequence")
    return sequence is None, sequence or 0, natural_key(element.get("id") or "")


RECOVERY_NAME = ".arcadia/recovery.zip"
LOCAL_SETTINGS = ".arcadia/local.json"
RECOVERY_INFO = "recovery.json"


def recovery_file(path):
    return Path(path) / RECOVERY_NAME


def read_recovery_info(path):
    """Edits left by a session that ended unexpectedly ({saved_at, modified, deleted}), or None."""
    try:
        with zipfile.ZipFile(recovery_file(path)) as z:
            return json.loads(z.read(RECOVERY_INFO))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def _remove_temporary_files(path):
    """Half-written files of an interrupted save («x.yaml.tmp», «model-cache.tmp»)."""
    for folder in (path / MODEL_DIR, path / ".arcadia"):
        if folder.exists():
            for file in folder.rglob("*.tmp"):
                file.unlink(missing_ok=True)


class ModelCache:
    """Local copy of the saved model files in one file (.arcadia/, not versioned).

    Opening thousands of small files is slow on Windows (each one is scanned by the antivirus): a file whose
    size and modification time match the cache is read from it instead, like git does with its index.
    """
    NAME = ".arcadia/model-cache.zip"
    STATS = "stats.json"

    def __init__(self, path):
        self.stats, self._zip = {}, None
        try:
            self._zip = zipfile.ZipFile(path / self.NAME)
            self.stats = json.loads(self._zip.read(self.STATS))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            self.close()

    def content(self, rel, stat):
        if self.stats.get(rel) != [stat.st_size, stat.st_mtime_ns]:
            return None
        try:
            return self._zip.read(rel)
        except (KeyError, zipfile.BadZipFile):
            return None

    def stale(self, saved):
        return set(self.stats) != set(saved)

    def close(self):
        if self._zip is not None:
            self._zip.close()
        self._zip, self.stats = None, {}

    @classmethod
    def write(cls, path, saved):
        """saved: {relative path: content as on disk}. A failure only makes the next opening slower."""
        target = path / cls.NAME
        tmp = target.with_suffix(".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            stats = {}
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
                for rel, data in saved.items():
                    stat = (path / rel).stat()
                    if stat.st_size == len(data):
                        stats[rel] = [stat.st_size, stat.st_mtime_ns]
                        z.writestr(rel, data)
                z.writestr(cls.STATS, json.dumps(stats))
            os.replace(tmp, target)
        except OSError:
            tmp.unlink(missing_ok=True)


MAIN_BRANCHES = ("main", "master")
BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class Branch:
    """A branch of the project: its last version on this PC (local) and on the remote (as last downloaded)."""

    def __init__(self, name, local=None, remote=None, current=False, main=False):
        self.name, self.local, self.remote, self.current, self.main = name, local, remote, current, main
        self.last = None  # the Version of its head
        self.ahead = self.behind = None  # versions it has that main has not, and the other way round

    @property
    def head(self):
        return self.local or self.remote

    @property
    def where(self):
        if self.local and self.remote:
            return "su questo PC e nel repository" if self.local == self.remote else (
                "su questo PC e nel repository (diversi)")
        return "solo su questo PC" if self.local else "solo nel repository"


class Receive:
    """How the versions of the working branch of the remote are received (Versioni › Ricevi dal repository).

    - UP_TO_DATE: nothing new on the remote; NO_BRANCH: the branch is not on the remote yet.
    - FAST_FORWARD: only the remote has new versions: the project takes them, and the changes saved here but not
      yet published are merged on top of them (still to publish).
    - MERGE: both have published versions: they are merged into a new version, to send then.
    - PUBLISH_FIRST: both have published versions, and there are changes here not yet published: they are
      published first (the merge is a version, it must not publish them unasked).
    """
    UP_TO_DATE, NO_BRANCH, FAST_FORWARD, MERGE, PUBLISH_FIRST = (
        "up_to_date", "no_branch", "fast_forward", "merge", "publish_first")

    def __init__(self, state, branch, theirs=None, incoming=(), base=None, ours=None, theirs_files=None):
        self.state, self.branch, self.theirs = state, branch, theirs
        self.incoming = list(incoming)  # the versions received, newest first
        self.base, self.ours, self.theirs_files = base or {}, ours or {}, theirs_files or {}
        self.result = None

    def merge(self, choices=None):
        from arcadia_tool.storage.merge import merge_files, renumber_ids

        result = merge_files(self.base, self.ours, self.theirs_files, choices)
        if result.resolved:
            renumber_ids(result, self.base, self.theirs_files)
        return result


class Project:
    """Edits are kept in memory until save(); publish() saves and records a version in the history."""

    def __init__(self, path, settings, repository, model, saved=None):
        self.path = Path(path)
        self.settings = settings
        self.repository = repository
        self.model = model
        self.checks = self._read_checks()
        self._modified = set()
        self._deleted = {}
        # Content of the model files as saved on disk ({relative path: bytes}), so that publishing does
        # not have to read thousands of files back.
        self._saved = saved or {}
        self._pending_assets = {}

    @property
    def name(self):
        return self.settings.get("name", self.path.name)

    @property
    def baseline(self):
        return self.settings.get("baseline", "")

    @property
    def description(self):
        return self.settings.get("description", "")

    def update_settings(self, **values):
        """Settings shared with the team (project.yaml, versioned): name, baseline, description."""
        for name, value in values.items():
            if value:
                self.settings[name] = value
            else:
                self.settings.pop(name, None)
        _write_text(self.path / PROJECT_FILE, yaml.safe_dump(self.settings, sort_keys=False, allow_unicode=True))

    def _read_checks(self):
        """Settings of the checks (checks.yaml); those of the first versions were in project.yaml («checks»)."""
        from arcadia_tool.checks.config import ChecksConfig

        file = self.path / CHECKS_FILE
        if file.exists():
            try:
                return ChecksConfig.from_data(yaml.safe_load(file.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError):
                return None  # not readable: «Verifica modello» says so (see checks.problems)
        return ChecksConfig.from_project_settings(self.settings)

    def update_checks(self, config):
        """Save the settings of the checks (checks.yaml, versioned and shared with the team): the profiles, with
        their settings, and the active one."""
        self.checks = config.copy()
        _write_text(self.path / CHECKS_FILE, config.dumps())
        if "checks" in self.settings:  # moved from project.yaml
            self.settings.pop("checks")
            self.update_settings()

    def choose_checks_profile(self, name):
        """The profile «Verifica modello» runs: saved in checks.yaml, so it is published for the whole team."""
        if self.checks is not None and name in self.checks.profiles and name != self.checks.active:
            config = self.checks.copy()
            config.active = name
            self.update_checks(config)

    def local_settings(self):
        """Settings of this PC only (.arcadia/, not versioned): e.g. the working branch of the remote."""
        try:
            return json.loads((self.path / LOCAL_SETTINGS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_local_settings(self, **values):
        data = {**self.local_settings(), **values}
        _write_text(self.path / LOCAL_SETTINGS, json.dumps({k: v for k, v in data.items() if v}, indent=2))

    # --- remote Git repository ------------------------------------------------------------------------

    def remote(self):
        """URL of the remote repository: the «origin» of the local Git, else the one shared in project.yaml."""
        return self.repository.remote_url() or self.settings.get("remote", "")

    def push_branch(self):
        """Branch of the remote the versions are sent to: the working branch, else the local one."""
        return self.local_settings().get("branch") or self.repository.local_branch()

    def unsent_versions(self):
        """Published versions not yet sent to the remote: those after the last one sent from here, or after the
        last one Git knows is on the remote (e.g. a downloaded project); else (e.g. a new branch) those that are on
        no branch of the remote; all of them if the remote is not known."""
        sent = self.local_settings().get("sent") or self.repository.remote_branch_head(self.push_branch())
        if sent:
            return _unsent(self.versions(), sent)
        head = self.repository.head()
        return self.repository.versions_between(list(self.repository.remote_heads().values()), head) if head else []

    def branch_on_remote(self):
        """The working branch is on the remote (as last known): a new branch is not, until it is sent."""
        return self.push_branch() in self.repository.remote_heads()

    def push(self, **credentials):
        """Send the published versions to the working branch of the remote. Returns the branch."""
        branch = self.push_branch()
        sha = self.repository.push(self.remote(), branch, **credentials)
        self.set_local_settings(sent=sha, branch=branch)
        return branch

    def rebuild_cache(self):
        """Rewrite the local copy of the saved model (see ModelCache) from the files on disk."""
        ModelCache.write(self.path, {self._relative(f): f.read_bytes()
                                     for f in sorted((self.path / MODEL_DIR).rglob("*.yaml"))})

    @classmethod
    def create(cls, path, name, baseline="SUBSET-026 v3.6.0"):
        path = Path(path)
        if (path / PROJECT_FILE).exists():
            raise ProjectError(f"Esiste già un progetto in {path}")
        path.mkdir(parents=True, exist_ok=True)
        settings = {"name": name, "baseline": baseline, "format_version": FORMAT_VERSION}
        _write_text(path / PROJECT_FILE, yaml.safe_dump(settings, sort_keys=False, allow_unicode=True))
        _write_text(path / ".gitignore", GITIGNORE)
        (path / MODEL_DIR).mkdir(exist_ok=True)
        repository = Repository.init(path)
        return cls(path, settings, repository, Model())

    @classmethod
    def open(cls, path, progress=None):
        path = Path(path)
        if not (path / PROJECT_FILE).exists():
            raise ProjectError(f"{path} non contiene un progetto ({PROJECT_FILE} mancante)")
        settings = yaml.safe_load((path / PROJECT_FILE).read_text(encoding="utf-8")) or {}
        if settings.get("format_version", FORMAT_VERSION) > FORMAT_VERSION:
            raise ProjectError("Il progetto è stato creato con una versione più recente dello strumento")
        if not (path / ".git").exists():
            Repository.init(path).close()
        repository = Repository(path)
        _remove_temporary_files(path)
        model, saved = cls._load_model(path, repository, progress)
        project = cls(path, settings, repository, model, saved)
        project._migrate()
        return project

    def _migrate(self):
        """Data written by earlier versions of the tool: migrated in memory (saved with the next save).

        - A logical function listed its derived requirements («derived_requirements»): the derived requirement
          now has one logical function, its «Funzione logica».
        - The recipient of a request for clarification (X-2) was a text: now it is the Design Authority or a
          team. A text naming a team (its ID or name, or «DA»/«Design Authority») becomes that team; another one
          is kept as «Destinatario (testo)».
        - The SRS items an ADR is about were written in its text «Voci SRS ed elementi interessati»: the items
          cited by number become «Voci SRS interessate» (chosen with ticks); the text stays as it is.
        - The members of a team were a list of names: each becomes a member (a row) without the ID of the
          account, recognized by name until the DA writes it (see model.teams).
        - An ADR had «Data e decisore» (a text): its date becomes «Data della decisione»; the decider is always
          the Design Authority."""
        by_id = {}
        for item in self.model.of_kind("requirement"):
            by_id.setdefault(item.get("id"), item.uuid)
        for adr in self.model.of_kind("adr"):
            text = adr.values.get("affected")
            if not text or adr.values.get("srs_items"):
                continue
            cited = [by_id[t] for t in re.findall(r"[A-Z]?\d+(?:\.\d+)+(?:-[A-Z]\d+)?", text) if t in by_id]
            if cited:
                adr.set("srs_items", list(dict.fromkeys(cited)))
                self.update(adr)
        for adr in self.model.of_kind("adr"):  # «Data e decisore» (a text): its date, the decider is the DA
            text = adr.values.get("date_decider")
            if text is None:
                continue
            found = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", str(text))
            if found and not adr.values.get("decision_date"):
                adr.values["decision_date"] = f"{int(found[1]):02d}/{int(found[2]):02d}/{found[3]}"
            adr.values.pop("date_decider")
            self.update(adr)
        teams = self.model.of_kind("team")
        for team in teams:  # members of the first versions (only names): rows, to which the DA adds the ID
            members = team.values.get("members") or []
            if any(not isinstance(m, dict) or "code" in m for m in members):
                team.set("members", [{k: v for k, v in m.items() if k != "code"} for m in member_rows(team)])
                self.update(team)
        for request in self.model.of_kind("clarification"):
            text = request.values.get("recipient")
            if not text or self.model.get(text) is not None:
                continue
            key = " ".join(str(text).casefold().split())
            team = next((t for t in teams if key in {(t.get("id") or "").casefold(), (t.get("name") or "").casefold()}),
                        None)
            if team is None and key in ("da", "design authority"):
                team = next((t for t in teams if t.get("design_authority")), None)
            request.set("recipient", team.uuid if team is not None else None)
            if team is None:
                request.set("recipient_text", str(text))
            self.update(request)
        for function in self.model.of_kind("logical_function"):
            refined = function.values.get("derived_requirements")
            if refined is None:
                continue
            for uuid in refined:
                derived = self.model.get(uuid)
                if derived is not None and not derived.get("function"):
                    derived.set("function", function.uuid)
                    self.update(derived)
            function.values.pop("derived_requirements")
            self.update(function)

    @staticmethod
    def _load_model(path, repository, progress=None):
        """progress(action, done, total), called every few files."""
        def report(action, done, total):
            if progress:
                progress(action, done, total)

        report("Ricerca dei file del modello", 0, 0)
        files = sorted((path / MODEL_DIR).rglob("*.yaml"))
        report("Lettura della cache locale", 0, len(files))
        cache = ModelCache(path)
        elements, saved, from_disk = [], {}, 0
        for i, file in enumerate(files, 1):
            if i % 100 == 0:
                report("Lettura degli elementi del modello", i, len(files))
            rel = file.relative_to(path).as_posix()
            stat = file.stat()
            data = cache.content(rel, stat)
            if data is None:
                data = repository.unchanged_content(rel, stat)
            if data is None:
                data = file.read_bytes()  # slow on Windows (antivirus): the cache avoids it next time
                from_disk += 1
            elements.append(loads(data.decode("utf-8")))
            saved[rel] = data
        stale = cache.stale(saved)
        cache.close()  # before rewriting it
        report("Indicizzazione del modello", len(files), len(files))
        model = Model(elements)
        if from_disk or stale:
            report("Aggiornamento della cache locale", len(files), len(files))
            ModelCache.write(path, saved)
        return model, saved

    def _relative(self, file):
        return file.relative_to(self.path).as_posix()

    def close(self):
        self.repository.close()

    def element_file(self, element):
        return self.path / MODEL_DIR / KINDS_BY_NAME[element.kind].folder / f"{element.uuid}.yaml"

    def is_new(self, element):
        """True for an element never saved to disk (e.g. just created)."""
        return self._relative(self.element_file(element)) not in self._saved

    def new_element(self, kind, **values):
        element = Element(kind)
        for name, value in values.items():
            element.set(name, value)
        self.update(element)
        return element

    def update(self, element, previous=None):
        """Record a change of an element (previous: the element before it, when known). Returns the other
        elements changed with it: the fields of other sheets kept in step (see model.links, e.g. the domains of a
        team when its team is assigned in a domain sheet) and those copied from it (e.g. the referent)."""
        self.model.add(element)
        self._modified.add(element.uuid)
        self._deleted.pop(element.uuid, None)
        if element.kind == "adr":  # the date of the decision: set when it is decided (see model.adr)
            from arcadia_tool.model.adr import decision_date_of
            element.set("decision_date", decision_date_of(element))
        if is_automatic(element.kind) and not element.get("id"):
            element.set("id", compute_id(element, self.model))
        changed = {}
        for other in keep_in_step(self.model, element, previous):
            self._modified.add(other.uuid)
            changed[other.uuid] = other
        for source in [element, *list(changed.values())]:
            for other in self._sync_derived(source):
                if other.uuid != element.uuid:
                    changed[other.uuid] = other
        return list(changed.values())

    def _sync_derived(self, element):
        """Fields copied from a referenced element (the referent of a domain from its team), both ways. Returns the
        other elements changed."""
        changed = []
        for f in element.schema.fields:
            if f.derived_from and f.stored:
                element.set(f.name, derived_value(self.model, element, f))
        for kind in KINDS:
            for f in kind.fields:
                if not f.derived_from or not f.stored or element.kind not in kind.field(f.derived_from[0]).ref_kinds:
                    continue
                for other in self.model.of_kind(kind.name):
                    if other.get(f.derived_from[0]) == element.uuid:
                        value = derived_value(self.model, other, f)
                        if (other.get(f.name) or None) != (value or None):
                            other.set(f.name, value)
                            self._modified.add(other.uuid)
                            changed.append(other)
        return changed

    def trace_srs(self, domain, principal, contributing):
        """Matrix sections × domains (A4) seen from a domain: the SRS items (uuids) of which it is the principal
        domain and those to which it contributes. Returns the SRS items changed."""
        changed = []
        for item in self.model.of_kind("requirement"):
            primary = item.get("primary_domain")
            others = [d for d in item.get("contributing_domains") or [] if d != domain.uuid]
            if item.uuid in principal:
                primary = domain.uuid
            elif primary == domain.uuid:
                primary = None
            if item.uuid in contributing and item.uuid not in principal:
                others.append(domain.uuid)
            if primary != item.get("primary_domain") or others != list(item.get("contributing_domains") or []):
                item.set("primary_domain", primary)
                item.set("contributing_domains", others)
                self.update(item)
                changed.append(item)
        return changed

    def allocate_item(self, item, principal, contributing):
        """Matrix A4 from an SRS item (a section): its principal domain and the contributing ones (uuids).
        Returns the elements changed."""
        before = item.copy()
        item.set("primary_domain", principal)
        item.set("contributing_domains", [d for d in contributing if d != principal])
        if before.values == item.values:
            return []
        return [item, *self.update(item, before)]

    def trace_item_to_functions(self, item, functions):
        """The system functions (uuids) that trace an SRS clause directly; the others no longer do (those that
        trace a section containing it are not changed). Returns the elements changed."""
        changed = []
        for sf in self.model.of_kind("system_function"):
            traced = list(sf.get("sections") or [])
            if (sf.uuid in functions) == (item.uuid in traced):
                continue
            before = sf.copy()
            sf.set("sections", traced + [item.uuid] if sf.uuid in functions else
                   [u for u in traced if u != item.uuid])
            changed.append(sf)
            changed.extend(e for e in self.update(sf, before) if all(e.uuid != c.uuid for c in changed))
        return changed

    def derive_requirements(self, item, obligations, decompose=True):
        """Derived requirements (SA-4) of an SRS clause, one per (name, obligation); with decompose, the SA-3
        record of the clause says «Scomposta in requisiti derivati» (question B5 4). Returns (created, changed)."""
        created = [self.new_element("derived_requirement", parent=item.uuid, name=name or None, obligation=text)
                   for name, text in obligations if (text or "").strip()]
        changed = []
        if decompose and created:
            records = [r for r in self.model.of_kind("trace_record") if r.get("requirement") == item.uuid]
            record = records[0] if records else self.new_element("trace_record", requirement=item.uuid)
            before = record.copy()
            record.set("b5_question", B5_QUESTIONS[3])
            record.set("outcome", "Scomposta in requisiti derivati")
            changed = [record, *self.update(record, before)]
        return created, changed

    def clean(self, keep_srs=False):
        """Remove every element, or every element but the imported SRS items (whose analysis data, e.g. the
        allocation to the removed domains, is cleared). Returns the number of elements removed."""
        removed = [e.uuid for e in self.model if not (keep_srs and e.kind == "requirement")]
        self.delete_elements(removed)
        if keep_srs:
            for item in self.model.of_kind("requirement"):
                analysis = [f.name for f in item.schema.fields if f.analysis and item.get(f.name)]
                for name in analysis:
                    item.set(name, None)
                if analysis:
                    self.update(item)
        return len(removed)

    def allocate_function(self, function, srs, derived, shown=None):
        """A system function (SA-2) or a logical function (LA-2): the SRS sections and clauses (uuids) it is
        allocated to and, for a logical function, the derived requirements (SA-4) allocated to it (their
        «Funzione logica», one per requirement). shown: the items offered for the choice; the other ones already
        referenced (e.g. a list item) are kept. Returns the elements changed."""
        changed = []
        field = "sections" if function.kind == "system_function" else "detail_requirements"
        current = list(function.get(field) or [])
        kept = [u for u in current if shown is not None and u not in shown]
        chosen = [e.uuid for e in sorted((self.model.get(u) for u in srs), key=_document_key)]
        sections = kept + [u for u in chosen if u not in kept]
        if sections != current:
            function.set(field, sections)
            self.update(function)
            changed.append(function)
        if function.kind != "logical_function":
            return changed
        for item in self.model.of_kind("derived_requirement"):
            value = function.uuid if item.uuid in derived else (
                None if item.get("function") == function.uuid else item.get("function"))
            if value != item.get("function"):
                item.set("function", value)
                self.update(item)
                changed.append(item)
        return changed

    def renumber(self, element):
        """Reassign the identifier if it no longer matches the element's context. Returns True if changed."""
        if not is_automatic(element.kind) or matches_context(element, self.model):
            return False
        new_id = compute_id(element, self.model)
        if not new_id or new_id == element.get("id"):
            return False
        element.set("id", new_id)
        self.update(element)
        return True

    def delete_element(self, uuid):
        element = self.model.get(uuid)
        if element is None:
            return
        self.model.remove(uuid)
        self._modified.discard(uuid)
        self._deleted[uuid] = self.element_file(element)

    def discard_new(self, uuid):
        """Forget an element created and never saved (e.g. «Nuovo» in the tree, then «Annulla»): unlike a deletion
        there is no file to remove, so nothing is left to save."""
        element = self.model.get(uuid)
        if element is None or not self.is_new(element):
            return False
        self.model.remove(uuid)
        self._modified.discard(uuid)
        self._deleted.pop(uuid, None)
        return True

    def delete_elements(self, uuids):
        for uuid in list(uuids):
            self.delete_element(uuid)

    @property
    def is_modified(self):
        """True when there are edits not yet written to disk (cheap: no Git access)."""
        return bool(self._modified or self._deleted)

    @property
    def pending_count(self):
        return len(self._modified) + len(self._deleted)

    # --- assets (images of figures and tables) --------------------------------------------------------

    def set_asset(self, rel, data):
        """Store a binary file of the project (e.g. a figure image) at the next save."""
        self._pending_assets[rel] = data

    def asset_data(self, rel):
        if rel in self._pending_assets:
            return self._pending_assets[rel]
        file = self.path / rel
        return file.read_bytes() if rel and file.is_file() else None

    def _referenced_assets(self):
        return {e.values.get("figure") for e in self.model if e.values.get("figure")}

    def _asset_files(self):
        folder = self.path / ASSETS_DIR
        return sorted(f for f in folder.rglob("*") if f.is_file()) if folder.exists() else []

    def _save_assets(self):
        referenced = self._referenced_assets()
        for rel, data in self._pending_assets.items():
            if rel in referenced:
                file = self.path / rel
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
        self._pending_assets.clear()
        for file in self._asset_files():  # images no longer used by any element
            if self._relative(file) not in referenced:
                file.unlink()

    def save(self, progress=None):
        total = len(self._modified)
        for i, uuid in enumerate(self._modified, 1):
            if progress and i % 50 == 0:
                progress(i, total)
            element = self.model.get(uuid)
            if element is not None:
                file = self.element_file(element)
                text = dumps(element)
                _write_text(file, text)
                self._saved[self._relative(file)] = text.encode("utf-8")
        for file in self._deleted.values():
            file.unlink(missing_ok=True)
            self._saved.pop(self._relative(file), None)
        changed = bool(self._modified or self._deleted)
        self._modified.clear()
        self._deleted.clear()
        self._save_assets()
        if changed:
            ModelCache.write(self.path, self._saved)
        self.discard_recovery()

    # --- recovery after an unexpected interruption ------------------------------------------------------

    def write_recovery(self):
        """Copy of the unsaved edits, written periodically; removed by save() and by a normal close."""
        if not self.is_modified and not self._pending_assets:
            self.discard_recovery()
            return
        target = recovery_file(self.path)
        tmp = target.with_suffix(".tmp")
        target.parent.mkdir(parents=True, exist_ok=True)
        info = {"saved_at": datetime.now().isoformat(timespec="seconds"),
                "modified": len(self._modified), "deleted": sorted(self._deleted)}
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for uuid in self._modified:
                element = self.model.get(uuid)
                if element is not None:
                    z.writestr(f"elements/{uuid}.yaml", dumps(element))
            for rel, data in self._pending_assets.items():
                z.writestr(f"assets/{rel}", data)
            z.writestr(RECOVERY_INFO, json.dumps(info))
        os.replace(tmp, target)

    def recovery_info(self):
        """{saved_at, modified, deleted} of edits left by an interrupted session, or None."""
        return read_recovery_info(self.path)

    def restore_recovery(self):
        """Apply the recovered edits as unsaved changes. Returns the number of restored changes."""
        with zipfile.ZipFile(recovery_file(self.path)) as z:
            info = json.loads(z.read(RECOVERY_INFO))
            names = z.namelist()
            for name in names:
                if name.startswith("elements/"):
                    self.model.add(loads(z.read(name).decode("utf-8")))
                    self._modified.add(name.removeprefix("elements/").removesuffix(".yaml"))
                elif name.startswith("assets/"):
                    self._pending_assets[name.removeprefix("assets/")] = z.read(name)
        for uuid in info.get("deleted", []):
            self.delete_element(uuid)
        return len(self._modified) + len(info.get("deleted", []))

    def discard_recovery(self):
        recovery_file(self.path).unlink(missing_ok=True)

    def _version_files(self):
        """Whole project content as it is saved on disk: settings files plus every model file."""
        files = {name: (self.path / name).read_bytes() for name in TRACKED_FILES if (self.path / name).exists()}
        files.update(self._saved)
        for file in self._asset_files():
            files[self._relative(file)] = file.read_bytes()
        return files

    def has_unpublished_changes(self):
        """True if the saved project differs from the last published version (computes hashes)."""
        return self.repository.has_unsaved_changes(self._version_files())

    def publish(self, message, author):
        """Save to disk and record a published version (a Git commit)."""
        self.save()
        sha = self.repository.save_version(message, author, self._version_files())
        return sha

    # --- branches --------------------------------------------------------------------------------------

    def current_branch(self):
        return self.repository.local_branch()

    def fetch_branches(self, **credentials):
        """Download every branch of the remote (the project is not changed). Returns {branch: last version}."""
        url = self.remote()
        if not url:
            raise ProjectError("Nessun repository remoto: indicalo in Progetto › Impostazioni › Repository Git.")
        heads = self.repository.fetch(url, **credentials)
        self.repository.set_remote_heads(heads)
        self.set_local_settings(fetched=datetime.now().isoformat(timespec="minutes"))
        return heads

    def fetched_at(self):
        """When the branches of the remote were downloaded the last time (text, e.g. «2026-10-26T10:30»), or ""."""
        return self.local_settings().get("fetched", "")

    def main_branch(self):
        """The branch the Design Authority integrates into: «main» (or «master»), on this PC or on the remote."""
        names = set(self.repository.local_heads()) | set(self.repository.remote_heads())
        return next((n for n in MAIN_BRANCHES if n in names), None)

    def branches(self):
        """The branches of this PC and of the remote (as last downloaded): Branch, the main one first."""
        local, remote = self.repository.local_heads(), self.repository.remote_heads()
        current, main = self.current_branch(), self.main_branch()
        main_sha = remote.get(main) or local.get(main) if main else None
        result = []
        for name in sorted(set(local) | set(remote), key=lambda n: (n != main, n.lower())):
            b = Branch(name, local.get(name), remote.get(name), name == current, name == main)
            head = b.head
            b.last = self.repository.version(head)
            if main_sha and not b.main:
                b.ahead = len(self.repository.versions_between(main_sha, head))
                b.behind = len(self.repository.versions_between(head, main_sha))
            result.append(b)
        return result

    def branch_versions(self, sha, limit=None):
        """The versions of a branch, from its last one (`sha`), newest first."""
        return self.repository.history(limit, start=sha)

    def check_branch_name(self, name):
        """What is wrong in the name of a new branch, or None."""
        name = (name or "").strip()
        if not name:
            return "Indica il nome del ramo."
        if not BRANCH_NAME.match(name) or ".." in name or name.endswith((".", "/", ".lock")) or "//" in name:
            return ("Il nome può contenere lettere, cifre, «-», «_», «.» e «/» (es. att/T2-odometria), senza spazi "
                    "e senza iniziare o finire con «/» o «.».")
        if name in self.repository.local_heads() or name in self.repository.remote_heads():
            return f"Il ramo «{name}» esiste già."
        return None

    def publish_on_new_branch(self, name, message, author):
        """Publish the changes as the first version of a new branch, which starts from the current version and
        becomes the one in use (to send then)."""
        problem = self.check_branch_name(name)
        if problem:
            raise ProjectError(problem)
        self.save()
        previous, settings = self.current_branch(), self.local_settings()
        self.repository.start_branch(name)
        self.set_local_settings(branch=name, sent="")
        try:
            return self.publish(message, author)
        except Exception:  # not published: back on the branch it was on
            self.repository.start_branch(previous)
            self.repository.delete_branch(name)
            self.set_local_settings(branch=settings.get("branch", ""), sent=settings.get("sent", ""))
            raise

    def switch_branch(self, name, sha=None):
        """The project moves to the branch `name`: created at the version `sha` if given (a new branch, still to
        send), else at its last version on this PC, or on the remote if it is not here yet. The changes saved and
        not published are lost (published first, or discarded, by the caller). The project must then be opened
        again."""
        self.save()
        local, remote = self.repository.local_heads(), self.repository.remote_heads()
        target = sha or local.get(name) or remote.get(name)
        if target is None:
            raise ProjectError(f"Il ramo «{name}» non esiste né su questo PC né nel repository.")
        working = self._version_files()
        files = self.repository.files_at(target)
        self._write_files(files, working)
        self.repository.checkout(name, target, files)
        self.set_local_settings(branch=name, sent=remote.get(name) or "")
        self.discard_recovery()
        return target

    # --- receiving the versions of the others ----------------------------------------------------------

    def prepare_receive(self, **credentials):
        """Download the working branch of the remote and work out how to receive it (see Receive). Saves the
        edits first. Nothing changes in the project until apply_receive."""
        self.save()
        branch, url = self.push_branch(), self.remote()
        if not url:
            raise ProjectError("Nessun repository remoto: indicalo in Progetto › Impostazioni › Repository Git.")
        heads = self.repository.fetch(url, **credentials)
        theirs = heads.get(branch)
        if theirs is None:
            return Receive(Receive.NO_BRANCH, branch)
        self.repository.set_remote_head(branch, theirs)
        head = self.repository.head()
        if head is not None and self.repository.is_ancestor(theirs, head):
            return Receive(Receive.UP_TO_DATE, branch, theirs)
        incoming = self.repository.versions_between(head, theirs)
        working = self._version_files()
        theirs_files = self.repository.files_at(theirs)
        if head is None or self.repository.is_ancestor(head, theirs):
            # Only the remote has new versions: they are received, the changes not yet published stay on top.
            receive = Receive(Receive.FAST_FORWARD, branch, theirs, incoming=incoming,
                              base=self.repository.files_at(head), ours=working, theirs_files=theirs_files)
        else:
            # Both have published versions: they are merged into a new version (then sent).
            head_files = self.repository.files_at(head)
            if working != head_files:
                return Receive(Receive.PUBLISH_FIRST, branch, theirs, incoming=incoming)
            base = self.repository.merge_base(head, theirs)
            receive = Receive(Receive.MERGE, branch, theirs, incoming=incoming,
                              base=self.repository.files_at(base), ours=head_files, theirs_files=theirs_files)
        receive.result = receive.merge()
        return receive

    def apply_receive(self, receive, choices=None, author=None):
        """Receive the versions as prepared, with the choices for the conflicts ({conflict key: ours/theirs}).
        Writes the project on disk: the project must then be opened again. Returns the MergeResult (with the
        conflicts still unresolved if the choices miss some: then nothing is written)."""
        result = receive.merge(choices)
        if not result.resolved:
            return result
        self._write_files(result.files, receive.ours)
        if receive.state == Receive.FAST_FORWARD:
            self.repository.move_to(receive.theirs, result.files)
        else:
            count = len(receive.incoming)
            message = (f"Integrazione di {count} {'versione ricevuta' if count == 1 else 'versioni ricevute'} "
                       f"dal ramo «{receive.branch}»")
            self.repository.save_version(message, author or "ATLAS <atlas@localhost>", result.files,
                                         merged=receive.theirs)
        self.set_local_settings(sent=receive.theirs, branch=receive.branch)
        self.discard_recovery()
        return result

    def _write_files(self, files, current):
        """The project on disk becomes `files` (current: what is on disk now)."""
        for rel, data in files.items():
            if current.get(rel) != data:
                target = self.path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, target)
        for rel in set(current) - set(files):
            (self.path / rel).unlink(missing_ok=True)

    def versions(self):
        return self.repository.history()

    def published_model(self, sha=None):
        sha = sha or self.repository.head()
        return self.repository.model_at(sha) if sha else Model()
