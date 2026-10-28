<p align="center">
  <img src="src/arcadia_tool/resources/logo_vertical_1100x1120.png" alt="ATLAS – Arcadia Traceability, Logical Architecture Software" width="320">
</p>

<p align="center">
  <b>Arcadia Traceability, Logical Architecture Software</b><br>
  Strumento desktop di modellazione ARCADIA per l'EVC ERTMS di bordo<br>
  <sub>RFI - Ricerca e Sviluppo - Sviluppo Sistemi · versione 0.4.0</sub>
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
- **Elementi trasversali**:
  - team (EPBS-1), con referente e membri. Un solo team può essere la **Design Authority**: solo i suoi membri
    creano e modificano i team e assegnano i domini ai team. La DA aggiunge ogni membro con l'**ID del suo
    account locale**, che la persona le comunica: ATLAS la riconosce come membro, anche nelle versioni che
    pubblica. Il progetto si apre solo agli account che sono tra i membri dei team;
  - decisioni architetturali (X-1) e richieste di chiarimento (X-2), ciascuna con un elenco in tabella (doppio
    clic sul nodo dell'albero) da cui crearle, aprirle ed eliminarle.
- Le richieste di chiarimento sono indirizzate alla Design Authority o a un team, scelto alla creazione. La clausola
  si sceglie con una finestra a spunta.
- Negli ADR le voci SRS interessate si scelgono a spunta e «Superata da» da un elenco con ricerca.
- Le ADR hanno un **tipo** (nuovo dominio, fusione, scissione, eliminazione, ridefinizione dello scopo,
  riallocazione di una sezione, spostamento di una funzione, deroga…), scelto alla creazione: la scheda ha i campi
  propri di quel tipo, già compilati con ciò che si sa dall'elemento selezionato. Per ogni tipo c'è anche il
  template Excel corrispondente in `Templates/` (`Template_X-1.nn_ADR_<tipo>.xlsx`), con gli stessi campi della
  scheda; si rigenerano con `scripts/make_adr_templates.py` quando i campi cambiano.
- I tipi di ADR sono raggruppati per ambito (domini SA; voci SRS, funzioni e scambi SA; LA; generali). I dati che
  ATLAS conosce già (la missione attuale, i domini di una voce, il dominio di una funzione, i produttori di
  un'informazione) sono letti dal modello e non si riscrivono. La data della decisione la imposta ATLAS.
- La Design Authority approva un'ADR di nuovo dominio con «Approva e crea il dominio»: ATLAS crea il dominio con
  il primo ID libero e gli alloca le sezioni indicate.
- «Esporta ADR aperte…» nell'elenco X-1 salva in Excel le ADR non ancora decise (ID, descrizione, team
  proponente, stato); lo stesso registro è anche un template (`Template_X-1.00_Registro_ADR_aperte.xlsx`).
- I campi collegati tra schede diverse restano allineati: per esempio il team assegnato a un dominio compare tra i
  domini del team, e viceversa.
- Campi di testo libero con editor formattato (grassetto, corsivo, elenchi), salvati in Markdown, che si
  allungano con il contenuto.
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
- Il catalogo delle voci SRS si apre anche in una finestra separata (pulsante o menu contestuale dell'albero).
  Dalle righe si allocano le sezioni ai domini e le clausole alle funzioni di sistema, e si derivano uno o più
  requisiti da una clausola.

**Versioni e collaborazione**
- Pubblicazione delle versioni su un repository Git remoto, via HTTPS o SSH. Va bene qualsiasi servizio (GitLab,
  GitHub, server interno…).
- Download di un progetto esistente, con scelta del ramo di sviluppo, e invio delle versioni locali.
- Ricezione delle versioni dei colleghi, con integrazione semantica a tre vie: le schede e i campi cambiati da
  una sola parte si integrano da soli, quelli cambiati in modo diverso si scelgono nella finestra di ricezione.
  Gli identificativi automatici in conflitto vengono rinumerati.
- Rami: elenco dei rami di questo PC e del repository, nuovo ramo da una versione scelta, cambio di ramo. Si può
  pubblicare sul ramo attuale o su un nuovo ramo creato al momento della pubblicazione.
- Cronologia e dettaglio di ogni versione pubblicata, di qualsiasi ramo.
- Confronto semantico tra versioni e tra rami (anche del repository e con lo stato attuale), anche limitato a ciò
  che un ramo ha cambiato dal punto di partenza comune.
- Migrazione della storia del progetto da un server Git a un altro.
- Account locali obbligatori: ogni modifica pubblicata è associata a un utente. Le credenziali Git restano
  nell'account sul PC (Gestione credenziali di Windows), mai nel progetto o nel repository.
- Anche le sole impostazioni condivise del progetto (per esempio le verifiche) si possono pubblicare.

**Verifiche del modello**
- 171 controlli ricavati dalla metodologia:
  - regole D1–D10, attività A4–A6 e B1–B7;
  - checklist dei template SA-1…LA-4, EPBS-1, X-1, X-2;
  - relazioni tra i campi di schede diverse, per esempio voce → funzione di sistema → funzione logica →
    componente, scambi, chain.
- I controlli sono divisi per scheda: controlli generali, matrice A4, SA-1…SA-7 e LA-1…LA-4, Team, ADR e CQ,
  indicatori di revisione, confronto con l'ultima versione pubblicata.
- Si scelgono in *Progetto › Impostazioni › Verifiche*, di default nessuno è attivo:
  - **profili** di verifiche (per esempio uno per ogni revisione di fase); il profilo attivo si sceglie anche
    dalla barra in alto;
  - per ogni controllo: **parametri** (soglie, formati degli ID, domini di codifica…), **gravità** e **ambito**,
    cioè lo stato e i domini delle schede controllate;
  - «Ripristina valori della metodologia» annulla le personalizzazioni di un controllo.
- Profili, profilo attivo ed eccezioni sono salvati nel progetto (`checks.yaml`) e pubblicati per tutto il team.
- *Verifica modello* (F7, o il pulsante sotto l'albero) mostra l'avanzamento, controllo per controllo, e si può
  interrompere. Il pannello delle segnalazioni resta ridotto in fondo alla finestra finché non c'è una verifica, e
  si può fissare aperto.
- Ogni segnalazione indica la scheda che viola il controllo e le altre schede coinvolte. Il doppio clic apre la
  scheda sul campo con il problema; ogni scheda mostra in cima le proprie segnalazioni.
- La Design Authority può accettare una segnalazione come **eccezione**, con una motivazione obbligatoria. L'eccezione
  vale finché la scheda non cambia e si può revocare.
- Gli errori non bloccano la pubblicazione: la finestra *Pubblica* ne mostra il riepilogo.

**Affidabilità**
- Ripristino delle modifiche non salvate dopo un'interruzione imprevista.
- Cache locale per aprire velocemente anche progetti con migliaia di voci SRS.

## Prossimi sviluppi

- **Diagrammi delle fasi SA e LA a ogni livello**:
  - diagrammi di System Analysis per domini, funzioni di sistema, attori, scambi funzionali e functional chain;
  - diagrammi di Logical Architecture per funzioni logiche, componenti, allocazioni e component exchange;
  - diagrammi a ogni livello di scomposizione, generati dal modello e coerenti con esso.
- **Generazione dei documenti** di progetto dal modello, ad esempio registri di tracciamento e schede delle fasi.
- **Integrazione dei rami di attività in `main`** fatta dalla Design Authority direttamente in ATLAS, con le
  verifiche del modello.
- **Effetti delle altre ADR all'approvazione** (fusione, scissione, spostamento di funzione…), come già per il
  nuovo dominio.

## Il progetto su disco

Un progetto ATLAS è una cartella:

| Percorso | Contenuto | Versionato |
|---|---|---|
| `project.yaml` | nome, baseline, descrizione, URL del repository remoto | sì |
| `checks.yaml` | profili delle verifiche, profilo attivo ed eccezioni della Design Authority | sì |
| `model/<tipo>/<uuid>.yaml` | un file per ogni elemento del modello | sì |
| `.arcadia/` | cache, file di ripristino, stato locale del ramo | no |

I dati degli utenti (account, chiavi SSH, impostazioni) sono nella cartella `RFI/ARCADIA Tool`:

- su Windows in `%APPDATA%\RFI\ARCADIA Tool`;
- su Linux in `~/.config/RFI/ARCADIA Tool`.

Il nome della cartella è quello delle prime versioni ed è rimasto invariato per compatibilità.

## Installazione e avvio

Le versioni compilate sono nelle [Release](https://github.com/salvodesi/ATLAS/releases) del progetto. Le
novità di ogni versione sono nel [CHANGELOG](CHANGELOG.md).

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
| `src/arcadia_tool/checks/` | verifiche del modello secondo la metodologia |
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

Il workflow GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) esegue i test su Linux e
compila l'archivio Linux a ogni push su `main`. Sui tag di versione (`v<versione>`) allega l'archivio alla release
del tag, accanto all'installer Windows. Per un tag già pubblicato si lancia a mano da *Actions › CI › Run
workflow*, indicando il tag. La pipeline GitLab ([.gitlab-ci.yml](.gitlab-ci.yml)) resta per chi usa ancora
il repository GitLab.

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
