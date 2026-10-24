# Changelog

Le modifiche rilevanti di ogni versione di ATLAS. Le versioni seguono il [versionamento semantico](https://semver.org/lang/it/):
finché ATLAS è in sviluppo (versioni 0.x), il formato dei progetti e l'interfaccia possono cambiare tra una versione e
l'altra.

## [0.3.0] - 2026-10-24

### Aggiunto

**Verifiche del modello**
- 171 controlli ricavati dalla metodologia:
  - regole D1–D10, attività A4–A6 e B1–B7;
  - checklist dei template;
  - relazioni tra campi di schede diverse.

  Sono divisi per scheda e di default nessuno è attivo.
- *Verifica modello* (F7, o il pulsante blu sotto l'albero del modello):
  - mostra l'avanzamento controllo per controllo;
  - si può interrompere;
  - resta aperta con l'esito fino a «Chiudi».
- Pannello delle segnalazioni in fondo alla finestra:
  - ridotto finché non si esegue una verifica, si può fissare aperto;
  - filtri per gravità e ricerca;
  - il doppio clic apre la scheda sul campo con il problema;
  - ogni scheda mostra in cima le proprie segnalazioni.
- Personalizzazione dei controlli in *Progetto › Impostazioni › Verifiche*:
  - **profili** di verifiche, con il profilo attivo scelto anche dalla barra in alto;
  - per ogni controllo **parametri** (soglie, formati degli ID, domini di codifica, dominio delle procedure…),
    **gravità** e **ambito** (stato e domini delle schede controllate);
  - «Ripristina valori della metodologia».
- **Eccezioni**: la Design Authority può accettare una segnalazione con una motivazione obbligatoria, registrata con
  autore e data. L'eccezione vale finché la scheda non cambia e si può revocare. Le eccezioni non sono contate negli
  errori.
- Il riepilogo delle verifiche è nella finestra *Pubblica*. Gli errori non bloccano la pubblicazione.

**Team e Design Authority**
- Un team (EPBS-1) può essere indicato come Design Authority, uno solo per progetto.
- I membri sono riconosciuti da nome e cognome dell'account e il ruolo è indicato nella barra di stato.

**Schede e modello**
- I campi collegati tra schede diverse restano allineati, per esempio dominio ↔ team e team ↔ domini.
- Editor formattato (grassetto, corsivo, elenchi) per tutti i campi di testo libero, salvato in Markdown. L'editor
  si allunga con il contenuto.
- Elenco in tabella delle richieste di chiarimento (X-2), con doppio clic sul nodo dell'albero:
  - colonne ID, destinatario e stato;
  - creazione, apertura ed eliminazione dall'elenco.
- Elenco in tabella degli ADR (X-1):
  - colonne ID, titolo, data e decisore, stato;
  - creazione ed eliminazione dall'elenco.
- Il destinatario di una CQ è la Design Authority o un team, scelto alla creazione. La clausola si sceglie a spunta.
- ADR:
  - voci SRS interessate scelte a spunta;
  - «Superata da» scelta da un elenco con ricerca;
  - sezione «Relazioni» prima di «Descrizione».

**Voci SRS**
- Il catalogo delle voci si apre anche in una finestra separata, con un pulsante o con «Apri in altra finestra» dal
  menu contestuale dell'albero.
- Azioni sulle righe:
  - le sezioni si allocano ai domini;
  - le clausole si allocano alle funzioni di sistema;
  - da una clausola si derivano uno o più requisiti (l'ID è mostrato subito, l'obbligo si scrive in un riquadro
    dedicato).

**Progetto**
- Nuovo file `checks.yaml`, versionato con il modello, con profili, profilo attivo ed eccezioni.
- Si possono pubblicare anche le sole impostazioni condivise del progetto, senza modifiche al modello.

### Modificato
- Nell'albero del modello «Attori esterni» viene prima di SA-1.
- Sotto l'albero il pulsante «Verifica modello» sostituisce «Nuovo» ed «Elimina», che restano nel menu contestuale.
- Le richieste di chiarimento del formato precedente, con il destinatario come testo, vengono convertite
  all'apertura del progetto:
  - un testo che nomina un team o la Design Authority diventa quel team;
  - un testo diverso resta come «Destinatario (testo)».
- I riferimenti alle voci SRS scritti nel testo degli ADR diventano voci SRS interessate.

### Aggiornamento dalla 0.2.0
- I progetti della 0.2.0 si aprono senza interventi.
- Le impostazioni delle verifiche delle prime versioni, se presenti in `project.yaml`, vengono lette e spostate in
  `checks.yaml` al primo salvataggio delle impostazioni.
- Dopo la pubblicazione delle verifiche con la 0.3.0, chi usa ancora la 0.2.0 non le vede: tutto il team deve
  aggiornare ATLAS.

## [0.2.0] - 2026-10-23

Prima versione pubblicata su GitLab.

### Aggiunto
- Modello ARCADIA secondo i template della metodologia:
  - System Analysis (SA-1…SA-7, attori esterni);
  - Logical Architecture (LA-1…LA-4);
  - team (EPBS-1), ADR (X-1) e richieste di chiarimento (X-2).
- Import delle voci SRS dai PDF del SUBSET-026, con testo, tabelle e figure, e lettore delle voci per capitolo.
- Registro di tracciamento (SA-3), requisiti derivati (SA-4) e finestre di tracciatura a spunta verso domini,
  funzioni di sistema e funzioni logiche.
- Versioni su repository Git remoto (HTTPS o SSH):
  - pubblicazione, download di un progetto e invio delle versioni;
  - cronologia e confronto semantico;
  - migrazione della storia tra server.
- Account locali obbligatori. Le credenziali Git sono salvate solo nel portachiavi del sistema.
- Ripristino delle modifiche non salvate e cache locale per i progetti grandi.
- Nome ATLAS (Arcadia Traceability, Logical Architecture Software), icona e logo.
- Installer Windows e archivio Linux. La pipeline GitLab esegue i test e compila la versione Linux.

[0.3.0]: https://gitlab.com/salvatoredesi/atlas/-/compare/v0.2.0...v0.3.0
[0.2.0]: https://gitlab.com/salvatoredesi/atlas/-/releases/v0.2.0
