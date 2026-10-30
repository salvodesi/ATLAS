"""The updates of ATLAS: the latest release published on GitHub, its file for this system downloaded and checked
with its SHA-256 fingerprint, then installed in place of the running version (the installer on Windows, the archive
on Linux). Without network nothing happens: ATLAS works offline as before."""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from arcadia_tool import __version__

REPOSITORY = "salvodesi/ATLAS"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
TIMEOUT = 15  # seconds, for each request
CHUNK = 256 * 1024


class UpdateError(Exception):
    """The update could not be checked, downloaded or installed (the message is for the user)."""


@dataclass
class Release:
    version: str  # "0.7.0"
    notes: str  # Markdown: the notes of the release (installation and the changes of the version)
    page: str  # its page on GitHub
    asset: str = ""  # the file for this system, "" if the release has none
    url: str = ""
    size: int = 0
    sha256: str = ""  # "" if GitHub gives no fingerprint: read from the file «<asset>.sha256» of the release
    sha256_url: str = ""


def parse_version(text):
    """(0, 7, 0) from "v0.7.0" or "0.7.0"; None if it is not a version."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(n) for n in match.group(1).split(".")) if match else None


def is_newer(version, than=__version__):
    a, b = parse_version(version), parse_version(than)
    return a is not None and b is not None and a > b


def asset_name(version, platform=None):
    """The file of the release for the system: the installer on Windows, the archive on Linux, else None."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        return f"ATLAS-Setup-{version}.exe"
    if platform.startswith("linux"):
        return f"ATLAS-{version}-linux-x86_64.tar.gz"
    return None


def _open(url, accept="application/json"):
    request = urllib.request.Request(url, headers={"User-Agent": f"ATLAS/{__version__}", "Accept": accept})
    return urllib.request.urlopen(request, timeout=TIMEOUT)  # the proxy of the system (urllib reads it)


def _fetch_json(url):
    with _open(url, "application/vnd.github+json") as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url):
    with _open(url, "application/octet-stream") as response:
        return response.read().decode("utf-8", "replace")


def latest_release(fetch=_fetch_json, platform=None):
    """The latest release published (drafts and pre-releases are not «latest» on GitHub)."""
    try:
        data = fetch(LATEST_URL)
    except OSError as exc:  # no network, proxy, GitHub not reachable
        raise UpdateError(f"Impossibile contattare GitHub: {getattr(exc, 'reason', exc)}") from exc
    except ValueError as exc:
        raise UpdateError("Risposta di GitHub non leggibile") from exc
    version = (data.get("tag_name") or "").lstrip("v")
    if parse_version(version) is None:
        raise UpdateError(f"Versione dell'ultima release non riconosciuta: «{data.get('tag_name')}»")
    release = Release(version=version, notes=data.get("body") or "", page=data.get("html_url") or RELEASES_PAGE)
    assets = {a.get("name"): a for a in data.get("assets") or []}
    name = asset_name(version, platform)
    if name in assets:
        asset = assets[name]
        release.asset, release.url, release.size = name, asset.get("browser_download_url") or "", asset.get("size") or 0
        digest = asset.get("digest") or ""  # "sha256:…", given by GitHub for the files of the releases
        if digest.startswith("sha256:"):
            release.sha256 = digest.split(":", 1)[1].lower()
        elif f"{name}.sha256" in assets:
            release.sha256_url = assets[f"{name}.sha256"].get("browser_download_url") or ""
    return release


def expected_sha256(release, fetch_text=_fetch_text):
    if release.sha256:
        return release.sha256
    if release.sha256_url:
        try:
            text = fetch_text(release.sha256_url)
        except OSError as exc:
            raise UpdateError(f"Impronta del file non scaricata: {getattr(exc, 'reason', exc)}") from exc
        match = re.search(r"\b[0-9a-fA-F]{64}\b", text)
        if match:
            return match.group(0).lower()
    raise UpdateError("La release non ha l'impronta SHA-256 del file: l'aggiornamento non è installato senza "
                      "poterne verificare l'integrità. Scaricalo dalla pagina della release.")


def download_folder():
    return Path(tempfile.gettempdir()) / "ATLAS-update"


def download(release, progress=None, cancelled=lambda: False, opener=_open, fetch_text=_fetch_text, folder=None):
    """The file of the release in the download folder, checked with its fingerprint (else deleted, UpdateError).
    progress(done, total) after each piece; cancelled() True stops the download (None returned)."""
    if not release.url:
        raise UpdateError("La release non ha il file per questo sistema")
    expected = expected_sha256(release, fetch_text)
    folder = Path(folder or download_folder())
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():  # what earlier updates left
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    target, partial = folder / release.asset, folder / f"{release.asset}.part"
    digest, done = hashlib.sha256(), 0
    try:
        with opener(release.url, "application/octet-stream") as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or release.size or 0)
            while True:
                if cancelled():
                    break
                piece = response.read(CHUNK)
                if not piece:
                    break
                out.write(piece)
                digest.update(piece)
                done += len(piece)
                if progress:
                    progress(done, total)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Download interrotto: {getattr(exc, 'reason', exc)}") from exc
    if cancelled():
        partial.unlink(missing_ok=True)
        return None
    if digest.hexdigest() != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError("Il file scaricato non corrisponde all'impronta della release (scaricato male o "
                          "alterato): non è installato.")
    partial.replace(target)
    return target


# --- installing ----------------------------------------------------------------------------------------------


def app_folder():
    """The folder of the installed executable, None when ATLAS runs from the source code (development)."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None


def can_install(platform=None):
    """Why this copy cannot update itself (it runs from the source code, or its folder cannot be written), or None."""
    platform = platform or sys.platform
    folder = app_folder()
    if folder is None:
        return "ATLAS è in esecuzione dal codice sorgente: aggiorna il codice con git."
    if asset_name("0", platform) is None:
        return "Aggiornamento automatico non disponibile per questo sistema."
    if platform.startswith("linux") and not os.access(folder.parent, os.W_OK):
        return f"La cartella di ATLAS ({folder}) non è modificabile dall'utente."
    return None


def installer_command(path):
    """Windows: the installer, silent, for the user, closing ATLAS if still open and starting it again at the end."""
    return [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]


def linux_script(archive, folder, pid):
    """Shell script: waits for ATLAS (pid) to close, puts the folder of the archive in place of the installed one
    (the old one kept until the new one is there), starts ATLAS again."""
    folder = Path(folder)
    new, old = folder.parent / f".{folder.name}.new", folder.parent / f".{folder.name}.old"
    q = shlex.quote
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
rm -rf {q(str(new))} {q(str(old))}
mkdir -p {q(str(new))} && tar -xzf {q(str(archive))} -C {q(str(new))} || exit 1
mv {q(str(folder))} {q(str(old))} && mv {q(str(new / 'ATLAS'))} {q(str(folder))} || {{ mv {q(str(old))} {q(str(folder))}; exit 1; }}
rm -rf {q(str(new))} {q(str(old))} {q(str(archive))}
nohup {q(str(folder / 'ATLAS'))} >/dev/null 2>&1 &
"""


def check_archive(archive):
    """The archive holds the folder ATLAS with its executable, and nothing outside it."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
    except (OSError, tarfile.TarError) as exc:
        raise UpdateError(f"Archivio non leggibile: {exc}") from exc
    if "ATLAS/ATLAS" not in names or any((n != "ATLAS" and not n.startswith("ATLAS/")) or ".." in n.split("/")
                                         for n in names):
        raise UpdateError("L'archivio non contiene la cartella di ATLAS attesa")


def start_install(path, platform=None, popen=subprocess.Popen):
    """Starts the installation of the file downloaded; ATLAS must close right after (the installer, or the script,
    waits for it)."""
    platform = platform or sys.platform
    try:
        if platform.startswith("win"):
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            popen(installer_command(path), creationflags=flags, close_fds=True)
        else:
            check_archive(path)
            script = Path(path).with_name("install.sh")
            script.write_text(linux_script(path, app_folder(), os.getpid()), encoding="utf-8")
            popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise UpdateError(f"Installazione non avviata: {exc}") from exc
