<p align="center">
  <img src="src/arcadia_tool/resources/logo_vertical_1100x1120.png" alt="ATLAS – Arcadia Traceability, Logical Architecture Software" width="320">
</p>

<p align="center">
  <b>Arcadia Traceability, Logical Architecture Software</b><br>
  Strumento desktop di modellazione ARCADIA per l'EVC ERTMS di bordo<br>
  <sub>RFI - Ricerca e Sviluppo - Sviluppo Sistemi · versione 0.2.0</sub>
</p>

> [!WARNING]
> **ATLAS è ancora in corso di sviluppo.** Le funzionalità, il formato dei progetti e l'interfaccia possono
> cambiare tra una versione e l'altra. Alcune parti della metodologia non sono ancora coperte: vedi
> [Prossimi sviluppi](#prossimi-sviluppi).

---

ATLAS guida la modellazione ARCADIA del progetto EVC secondo i template della metodologia (cartella `Templates/`).
Importa le voci SRS dal SUBSET-026, ne gestisce la tracciabilità verso domini funzionali, funzioni e componenti,
e permette ai team di condividere il modello tramite un qualsiasi repository Git remoto. Funziona offline: il
repository serve solo per scaricare e pubblicare le versioni.

## Cosa è supportato oggi

<img src="src/arcadia_tool/resources/symbol_256.png" alt="" width="72" align="right">

**Modello ARCADIA**
- **System Analysis**: domini funzionali (SA-1), funzioni di sistema (SA-2), attori esterni, exchange item (SA-6),
  scambi funzionali (SA-5) e functional chain (SA-7).
- **Logical Architecture**: funzioni logiche (LA-2), componenti logici (LA-1), component exchange (LA-3) e
  realizzazioni delle chain (LA-4).
- **Elementi trasversali**: team (EPBS-1), con membri e referente; decisioni architetturali (X-1) e richieste di
  chiarimento (X-2).
- Identificativi automatici, una tab per ogni elemento aperto, schede in sola lettura finché non si passa in
  modalità modifica, con salvataggio o annullamento esplicito.

**Requisiti e tracciabilità**
- Import delle voci SRS dai PDF del SUBSET-026, con testo, tabelle e figure, e lettore delle voci diviso per
  capitolo.
- Registro di tracciamento (SA-3) e requisiti derivati (SA-4), con motivazione della derivazione e domanda B5.
- Finestre di tracciatura a spunta, con ricerca, filtro per categoria (bordo, terra, definizioni, informative) e
  testo completo della voce con doppio clic:
  - domini → sezioni e clausole, come principale o contributore;
  - funzioni di sistema → sezioni e clausole;
  - funzioni logiche → sezioni, clausole e requisiti derivati.

**Versioni e collaborazione**
- Pubblicazione delle versioni su un repository Git remoto, via HTTPS o SSH. Va bene qualsiasi servizio (GitLab,
  GitHub, server interno…).
- Download di un progetto esistente, con scelta del ramo di sviluppo, e invio delle versioni locali.
- Cronologia e dettaglio di ogni versione pubblicata.
- Confronto semantico tra versioni.
- Migrazione della storia del progetto da un server Git a un altro.
- Account locali obbligatori: ogni modifica pubblicata è associata a un utente. Le credenziali Git restano
  nell'account sul PC (Gestione credenziali di Windows), mai nel progetto o nel repository.

**Affidabilità**
- Ripristino delle modifiche non salvate dopo un'interruzione imprevista.
- Cache locale per aprire velocemente anche progetti con migliaia di voci SRS.

## Prossimi sviluppi

- **Diagrammi delle fasi SA e LA a ogni livello**:
  - diagrammi di System Analysis per domini, funzioni di sistema, attori, scambi funzionali e functional chain;
  - diagrammi di Logical Architecture per funzioni logiche, componenti, allocazioni e component exchange;
  - diagrammi a ogni livello di scomposizione, generati dal modello e coerenti con esso.
- **Verifiche di coerenza del modello** secondo le regole della metodologia, ad esempio voci SRS non tracciate,
  funzioni non allocate e scambi incompleti.
- **Generazione dei documenti** di progetto dal modello, ad esempio registri di tracciamento e schede delle fasi.
- **Aggiornamento da Git**: ricezione delle versioni pubblicate dagli altri team e gestione delle modifiche in
  conflitto.
- **Cambio del ramo di sviluppo** in un progetto già scaricato.

## Il progetto su disco

Un progetto ATLAS è una cartella:

| Percorso | Contenuto | Versionato |
|---|---|---|
| `project.yaml` | nome, baseline, descrizione, URL del repository remoto | sì |
| `model/<tipo>/<uuid>.yaml` | un file per ogni elemento del modello | sì |
| `.arcadia/` | cache, file di ripristino, stato locale del ramo | no |

I dati degli utenti (account, chiavi SSH, impostazioni) sono nella cartella `RFI/ARCADIA Tool`:

- su Windows in `%APPDATA%\RFI\ARCADIA Tool`;
- su Linux in `~/.config/RFI/ARCADIA Tool`.

Il nome della cartella è quello delle prime versioni ed è rimasto invariato per compatibilità.

## Installazione e avvio

Le versioni compilate sono nelle [Release](https://gitlab.com/salvatoredesi/atlas/-/releases) del progetto.

### Windows (10/11, 64 bit)

1. Scaricare ed eseguire `ATLAS-Setup-<versione>.exe`. L'installazione per il solo utente non richiede
   privilegi di amministratore.
2. Avviare **ATLAS** dal menu Start, oppure dall'icona sul desktop se scelta durante l'installazione.

Installato sopra una versione precedente («ARCADIA Tool»), la sostituisce e mantiene i dati degli utenti. Si
disinstalla da *Impostazioni → App*.

### Linux (x86_64)

Serve una distribuzione con glibc 2.36 o successiva, ad esempio Ubuntu 24.04, Debian 12 o Fedora 37 e
successive.

```sh
tar -xzf ATLAS-<versione>-linux-x86_64.tar.gz      # crea la cartella ATLAS/
./ATLAS/ATLAS
```

Note:

- **Librerie grafiche**: l'eseguibile contiene Qt. Se il sistema non le ha già, servono le librerie X11/xcb, ad
  esempio su Ubuntu e Debian:
  ```sh
  sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1
  ```
- **Credenziali Git**: sono salvate nel portachiavi del desktop (GNOME Keyring o KWallet, tramite Secret
  Service).
- **Collegamento nel menu delle applicazioni**: è facoltativo. L'icona `atlas.png` è nella cartella `ATLAS/`:
  ```sh
  cat > ~/.local/share/applications/atlas.desktop <<EOF
  [Desktop Entry]
  Type=Application
  Name=ATLAS
  Comment=Arcadia Traceability, Logical Architecture Software
  Exec=$PWD/ATLAS/ATLAS
  Icon=$PWD/ATLAS/atlas.png
  Categories=Development;
  EOF
  ```

## Sviluppo

Requisiti: Python 3.14 (va bene anche dalla 3.12 in poi), su Windows o Linux.

```powershell
# Windows
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

```sh
# Linux
python3.14 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Stack:
- PySide6 per l'interfaccia;
- dulwich per Git (in puro Python);
- pdfplumber e pypdfium2 per l'import SRS;
- PyYAML per i file del modello;
- keyring e cryptography per credenziali e chiavi SSH;
- qtawesome per le icone.

Il codice è nel pacchetto `arcadia_tool`, nome interno rimasto quello delle prime versioni:

| Cartella | Contenuto |
|---|---|
| `src/arcadia_tool/model/` | schema degli elementi ARCADIA |
| `src/arcadia_tool/importers/` | import delle voci SRS dai PDF |
| `src/arcadia_tool/diff/` | confronto semantico tra versioni |
| `src/arcadia_tool/storage/` | progetto, repository Git, cache, ripristino |
| `src/arcadia_tool/ui/` | finestre e tema dell'interfaccia |
| `src/arcadia_tool/resources/` | icona, simbolo e logo, installati con l'applicazione |

### Avvio dai sorgenti

```powershell
# Windows
.\scripts\run.ps1
# oppure
.\.venv\Scripts\python.exe -m arcadia_tool
```

```sh
# Linux
sh scripts/run.sh
# oppure
.venv/bin/python -m arcadia_tool
```

### Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests      # Windows
```

```sh
.venv/bin/python -m pytest tests                # Linux
```

Il test sui PDF reali del SUBSET-026 (non inclusi nel repository) si attiva indicando la cartella dei PDF nella
variabile `ARCADIA_SRS_PDF_DIR`. I test non toccano le impostazioni né il portachiavi reali.

### Eseguibile e installer

**Windows**: va compilato su un PC Windows.

```powershell
.\scripts\build.ps1               # dist\ATLAS\ + installer (se Inno Setup 6 è installato)
.\scripts\build.ps1 -NoInstaller  # solo dist\ATLAS\ATLAS.exe
```

L'installer richiede [Inno Setup 6](https://jrsoftware.org/isinfo.php) e viene scritto in
`dist\installer\ATLAS-Setup-<versione>.exe`.

**Linux**: richiede `binutils`.

```sh
sh scripts/build.sh               # dist/ATLAS/ + dist/ATLAS-<versione>-linux-x86_64.tar.gz
```

La pipeline GitLab ([.gitlab-ci.yml](.gitlab-ci.yml)) esegue i test su Linux e compila l'archivio Linux a
ogni push su `main`. Sui tag di versione (`v<versione>`) carica l'archivio tra i pacchetti del progetto, accanto
all'installer Windows della release.

## Logo

<img src="src/arcadia_tool/resources/icon_128.png" alt="Icona di ATLAS" width="64">&nbsp;&nbsp;
<img src="src/arcadia_tool/resources/symbol_256.png" alt="Simbolo di ATLAS" width="64">

Le immagini usate dall'applicazione sono in `src/arcadia_tool/resources/`:

| File | Uso |
|---|---|
| `atlas.ico`, `icon_*.png` | icona dell'eseguibile, dell'installer e delle finestre |
| `symbol_*.png` | finestra di accesso e pagina di selezione del progetto |
| `logo_vertical_*.png` | area di lavoro senza schede aperte |

Gli originali sono in `images/`.

---

<p align="center"><sub>© RFI - Ricerca e Sviluppo - Sviluppo Sistemi</sub></p>
