"""GitHub release of a version (its tag already pushed), with the Windows installer; the Linux archive is attached by the
workflow on the push of the tag. Notes: how to install, the optional notes file, the section of the version in the
CHANGELOG. The token is asked in a password field and only kept in memory.
  python scripts/github_release.py <version> [notes file]      (see scripts/PUBBLICAZIONE.md)"""
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit

REPO = "salvodesi/ATLAS"
API = f"https://api.github.com/repos/{REPO}"
ROOT = Path(__file__).resolve().parents[1]


def section(version):
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[\d)", changelog, re.S | re.M)
    if match is None:
        sys.exit(f"Nel CHANGELOG manca la sezione [{version}]")
    return match.group(1).strip()


def notes(version, installer, linux, extra, mac=None):
    sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    return f"""> **ATLAS è ancora in corso di sviluppo**: funzionalità, formato dei progetti e interfaccia possono cambiare.

## Installazione (Windows 10/11, 64 bit)

Scaricare ed eseguire **{installer.name}**. ATLAS si installa per il solo utente, senza privilegi di
amministratore, e mantiene i dati degli utenti (`%APPDATA%\\RFI\\ARCADIA Tool`).

**Aggiornamento dalla 0.7.0 in poi:** ATLAS propone la nuova versione all'avvio (al massimo una volta al giorno)
oppure da *Info › Verifica aggiornamenti…* (*Aiuto* fino alla 0.8.0): «Aggiorna ora» la scarica, la verifica e la
installa, poi riapre ATLAS. In alternativa basta scaricare ed eseguire l'installer qui sotto, che aggiorna la
versione installata.

Dalle versioni fino alla 0.6.0, installate in *Programmi*: installare questa versione, poi disinstallare quella
precedente da *Impostazioni › App* (l'installer lo ricorda).

{extra}SHA-256: `{sha}`

## Installazione (Linux x86_64)

Distribuzione con glibc 2.36 o successiva (ad esempio Ubuntu 24.04, Debian 12, Fedora 37 e successive). Scaricare
**{linux}**, poi:

```sh
tar -xzf {linux}
./ATLAS/ATLAS
```

## Installazione (macOS, Apple Silicon: M1 e successivi)

Scaricare **{mac or f"ATLAS-{version}-macos-arm64.zip"}** e aprirlo: si estrae **ATLAS.app**, da trascinare nella
cartella *Applicazioni*. I Mac con processore Intel non sono supportati.

L'app **non è firmata da Apple**: al primo avvio macOS la blocca («Impossibile aprire ATLAS» o «Apple non può
verificare…»). Per aprirla, una volta sola:

1. chiudere il messaggio;
2. aprire *Impostazioni di Sistema › Privacy e sicurezza* e, in fondo alla pagina, accanto a «ATLAS è stato
   bloccato…», premere **Apri comunque**;
3. confermare con la password del Mac.

In alternativa, dal Terminale: `xattr -dr com.apple.quarantine /Applications/ATLAS.app`. Gli aggiornamenti
successivi si installano da ATLAS (*Info › Verifica aggiornamenti…*) senza chiedere di nuovo.

## Novità della {version}

{section(version)}
"""


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    version = sys.argv[1]
    extra = Path(sys.argv[2]).read_text(encoding="utf-8").strip() + "\n\n" if len(sys.argv) > 2 else ""
    assets = ROOT / "dist" / "installer"
    installer = assets / f"ATLAS-Setup-{version}.exe"
    if not installer.is_file():
        sys.exit(f"Manca {installer}: esegui prima scripts\\build.ps1")
    linux = f"ATLAS-{version}-linux-x86_64.tar.gz"
    body_text = notes(version, installer, linux, extra)  # before the token: a mistake here asks for nothing

    app = QApplication([])  # noqa: F841 (the dialog needs it)
    token, ok = QInputDialog.getText(None, "ATLAS – Release GitHub",
                                     f"Token di GitHub per {REPO} (fine-grained: Contents e Actions in lettura e "
                                     "scrittura).\nUsato solo per questa pubblicazione, non viene salvato:",
                                     QLineEdit.Password)
    token = token.strip()
    if not ok or not token:
        sys.exit("annullato: nessun token")

    def call(method, url, data=None, content_type="application/json", missing_ok=False):
        body = json.dumps(data).encode() if isinstance(data, dict) else data
        request = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                text = response.read().decode()
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            sys.exit(f"{method} {url}: HTTP {error.code} {error.read().decode()[:400]}")

    print("repository:", call("GET", API)["full_name"])
    tag = f"v{version}"
    release = call("GET", f"{API}/releases/tags/{tag}", missing_ok=True)
    body = {"tag_name": tag, "name": f"ATLAS {version}", "body": body_text}
    if release is None:
        release = call("POST", f"{API}/releases", body)
    else:  # e.g. created empty by the workflow that attached the Linux archive
        release = call("PATCH", f"{API}/releases/{release['id']}", body)
    present = {a["name"]: a for a in release.get("assets", [])}
    for path in (installer, installer.with_name(installer.name + ".sha256")):
        old = present.get(path.name)
        if path.is_file() and old is not None and old["size"] != path.stat().st_size:  # rebuilt: replaced
            call("DELETE", f"{API}/releases/assets/{old['id']}")
            print(" ", tag, "sostituito", path.name)
            old = None
        if path.is_file() and old is None:
            upload = release["upload_url"].split("{")[0] + "?name=" + urllib.parse.quote(path.name)
            call("POST", upload, path.read_bytes(), "application/octet-stream")
            print(" ", tag, "allegato", path.name, f"{path.stat().st_size / 1e6:.1f} MB")
    print("release:", release["html_url"])


if __name__ == "__main__":
    main()
