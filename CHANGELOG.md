# Changelog

Le modifiche rilevanti di ogni versione di ATLAS. Le versioni seguono il [versionamento semantico](https://semver.org/lang/it/):
finché ATLAS è in sviluppo (versioni 0.x), il formato dei progetti e l'interfaccia possono cambiare tra una versione e
l'altra.

## [0.4.0] - 2026-10-28

### Aggiunto
- *Versioni › Ricevi dal repository*: riceve le versioni pubblicate dai colleghi sul ramo di lavoro.
  - Se solo il repository ha versioni nuove, il progetto le prende; le modifiche salvate e non ancora pubblicate
    restano da pubblicare.
  - Se anche questo PC ha pubblicato versioni nuove, le due storie vengono integrate in una nuova versione, da
    inviare poi al repository. Se ci sono anche modifiche non pubblicate, ATLAS chiede di pubblicarle prima.
- Integrazione semantica a tre vie:
  - le schede cambiate da una sola parte prendono quella modifica;
  - le schede cambiate da entrambe le parti si integrano campo per campo; nei riferimenti ad altre schede
    (per esempio le voci tracciate) si tengono le aggiunte e le rimozioni di entrambi;
  - le impostazioni del progetto e delle verifiche si integrano voce per voce;
  - lo stesso campo cambiato in modo diverso, o una scheda eliminata da una parte e modificata dall'altra, si
    sceglie riga per riga (o tutte insieme) nella finestra di ricezione.
- Gli identificativi automatici dati qui e già usati nelle versioni ricevute (per esempio due `SF-DF06-03`)
  vengono rinumerati automaticamente, insieme a quelli che ne dipendono (le funzioni logiche della funzione
  rinumerata). La scheda ricevuta mantiene il proprio identificativo.
- Quando l'invio viene rifiutato perché il repository ha versioni non ancora ricevute, la finestra di invio
  propone «Ricevi ora».
- **Tipi di decisione architetturale (ADR, X-1)**: creando un'ADR si sceglie prima il tipo, con l'anteprima dei
  campi del suo modello; la scheda ha i campi comuni (contesto, voci SRS, opzioni, decisione, motivazione,
  conseguenze…) più la sezione «Dettagli» propria del tipo. Tipi: nuovo dominio funzionale, eliminazione di
  dominio, fusione di domini, scissione di dominio, ridefinizione dello scopo del dominio (estensione, riduzione o
  cambio totale), riallocazione di sezione o clausola, spostamento di una funzione tra domini, proprietà di
  un'informazione / confine, scelta lasciata all'implementazione, opzione di prodotto, decisione di architettura
  logica, deroga a una regola della metodologia, altro.
  - L'ADR nasce già compilata con ciò che si sa dall'elemento selezionato (es. dal dominio: dominio e missione
    attuale; dalla sezione: voce, principale e contributori attuali), con stato «Proposta».
  - Cambiando tipo, i campi del tipo precedente vengono svuotati dopo una conferma.
  - L'ADR di un **nuovo dominio funzionale** ha solo l'identificazione e i suoi dettagli: dominio proposto,
    missione proposta, perché si propone il nuovo dominio, vantaggi della proposta,
    **sezioni allocate al dominio** (scelte con le spunte, solo sezioni a tre numeri) e team proposto; niente
    relazioni, descrizione, opzioni, informazioni principali, criteri A2 o tabelle di sezioni e funzioni che
    cambiano dominio.
  - La finestra dei tipi si apre con la lista dall'inizio; senza un elemento selezionato propone il primo tipo.
  - L'ADR di **fusione di domini** ha solo l'identificazione e i dettagli: domini da fondere, nome del dominio
    risultante (l'ID sarà quello del dominio che resta, o assegnato dal tool), dominio che resta, missione
    proposta, team e le **voci SRS attribuite al dominio risultante**, calcolate dal tool come quelle dei domini
    fusi (principali o contributori) e aggiornate cambiando i domini.
  - L'ADR di **scissione di un dominio** è la duale della fusione: dominio da scindere, domini risultanti (per
    ciascuno nome, missione e team proposti, e quale mantiene l'ID del dominio scisso; gli altri ID li assegna il
    tool) e la **ripartizione delle voci SRS**: per ogni riga si sceglie una voce del dominio da scindere e uno dei
    domini risultanti scritti sopra, da elenchi che si aggiornano mentre si compila la scheda. Niente descrizione,
    opzioni o altri campi.
  - L'ADR di **ridefinizione dello scopo di un dominio** ha solo l'identificazione e i dettagli: dominio
    interessato, natura della modifica, missione attuale (letta dalla scheda del dominio), missione proposta,
    motivazione della modifica, sezioni acquisite e sezioni cedute (scelte con le spunte, solo sezioni).
  - L'ADR di **riallocazione di sezione o clausola** ha solo l'identificazione e i dettagli: la voce da
    riallocare (scelta con le spunte), il dominio principale e i contributori attuali (letti dalla voce), il
    dominio principale e i contributori proposti, la motivazione.
  - L'ADR di **spostamento di una funzione tra domini** ha solo l'identificazione e i dettagli: la funzione, il
    dominio attuale (letto dalla funzione), il dominio proposto e la motivazione dello spostamento.
  - Anche le ADR di **proprietà di un'informazione**, **scelta lasciata all'implementazione** e **opzione di
    prodotto** hanno solo l'identificazione e i dettagli, ciascuna con la propria motivazione: i produttori attuali
    dell'informazione (letti dagli scambi), il dominio principale della voce SRS (scelta con le spunte) e il dominio
    della funzione opzionale sono calcolati dal tool.
  - I tipi sono **raggruppati per ambito**: domini funzionali (SA), voci SRS, funzioni e scambi (SA), architettura
    logica (LA), generali. Nella finestra di scelta del tipo gli ambiti sono intestazioni; l'elenco X-1 ha la
    colonna «Ambito» ed è ordinato per ambito.
  - L'ADR di **eliminazione di un dominio** ha solo l'identificazione e la descrizione, con dominio interessato,
    motivazione e osservazioni della DA.
  - Nell'ADR di un nuovo dominio si indica solo il **nome**: l'ID (DFnn) lo assegna il tool all'approvazione.
  - **«Approva e crea il dominio»** (solo per i membri della Design Authority, sull'ADR proposta): dopo una
    conferma che riassume cosa cambia, crea il dominio con l'ID assegnato dal tool, la missione e il team
    proposti, lo rende dominio principale delle sezioni allocate (le sezioni che avevano un altro principale
    passano al nuovo dominio) e porta l'ADR a «Decisa», con la data e il dominio creato.
  - **Data della decisione** al posto di «Data e decisore»: la imposta il tool quando l'ADR diventa «Decisa»
    (dall'approvazione o dallo stato), resta se l'ADR viene superata, sparisce se torna «Proposta». Il decisore
    non si indica: è sempre la Design Authority. Le ADR esistenti conservano la data che avevano scritto.
  - L'elenco X-1 ha la colonna «Tipo»; le ADR delle versioni precedenti restano senza tipo, con i soli campi comuni.
- **Rami** (*Versioni › Rami…*, anche nella barra in alto, prima di «Pubblica»):
  - un elenco a scelta mostra tutti i rami, solo quelli di questo PC o solo quelli del repository;
  - elenco dei rami di questo PC e del repository, con ultima versione, autore, dove si trovano e quante versioni
    sono avanti o indietro rispetto a `main`; «Aggiorna dal repository» scarica i rami senza cambiare il progetto;
  - **nuovo ramo da una versione scelta** di qualsiasi ramo (anche dalla Cronologia, «Crea ramo da questa
    versione…»), con il nome proposto `att/<team>-…`, inviato subito al repository se richiesto;
  - **cambio di ramo**, anche verso un ramo che è solo nel repository; le modifiche non pubblicate vengono prima
    pubblicate o scartate, a scelta;
  - il ramo in uso è indicato nella barra di stato.
- **Cronologia di qualsiasi ramo**: nella Cronologia si sceglie il ramo (di questo PC o del repository); il
  dettaglio di una versione la confronta con la versione da cui deriva.
- **Pubblicazione su un nuovo ramo**: nella finestra *Pubblica* si sceglie se pubblicare sul ramo in uso o su un
  nuovo ramo, creato in quel momento dall'ultima versione del ramo in uso; il nuovo ramo diventa quello di lavoro
  e viene inviato al repository.
- **Confronto tra rami**: in *Confronta* ogni lato è un ramo e una sua versione, o lo stato attuale. I rami sono
  distinti per provenienza, «Questo PC › …» e «Repository › …», anche quando hanno lo stesso nome: si confrontano
  locale con locale, locale con remoto, remoto con remoto. All'apertura la finestra scarica i rami del repository
  (e c'è «Aggiorna dal repository»). L'opzione «Solo ciò che ha cambiato «A» dal punto di partenza comune» mostra solo le modifiche di un
  ramo da quando è nato, senza quelle entrate nel frattempo nell'altro. Dalla finestra dei rami: «Confronta con il
  mio stato attuale» e «Cosa ha cambiato rispetto a main».
- **Membri dei team** gestiti dalla scheda del team (EPBS-1) da un membro della Design Authority:
  - «Aggiungi membro…» apre la finestra del nuovo membro: nome e cognome e **ID dell'account** (obbligatori),
    e-mail, ruolo;
  - per ogni membro: modifica dei dettagli (anche con doppio clic) e rimozione;
  - la stessa persona, o lo stesso ID, non può essere aggiunta due volte allo stesso team.
- **Riconoscimento tramite l'ID dell'account**: ogni utente ha un solo ID, generato alla creazione dell'account
  locale e mostrato (con un pulsante per copiarlo) in *Utente › Modifica account*. La persona lo comunica alla DA,
  che lo inserisce aggiungendola al team: da quel momento l'account è riconosciuto come quel membro, anche se il
  nome è scritto in modo diverso.
  - La barra di stato indica i team di cui l'utente fa parte; la Design Authority è riconosciuta dall'ID.
  - Le versioni pubblicate da un membro riportano nel messaggio nome, team e ID dell'account.
- **Accesso al progetto riservato ai membri**: un progetto si apre solo se l'ID dell'account è tra i membri di un
  team. Chi non c'è vede il motivo, con il proprio ID da copiare e inviare alla Design Authority. Finché nessun
  membro ha un ID (progetto nuovo o delle versioni precedenti) il progetto si apre per tutti, per impostare i
  team. Se cambia l'utente con un progetto aperto e il nuovo utente non ne è membro, il progetto si chiude.
  Se un membro della Design Authority rimuove per errore il proprio ID (togliendo la propria riga, cambiando il
  proprio ID o eliminando il team che lo contiene), compare subito un messaggio di errore e l'ID non viene
  rimosso: altrimenti non potrebbe più aprire il progetto.
- I membri del team sono nella scheda subito dopo la sezione «Descrizione».
- **I team si modificano solo dalla Design Authority**: creazione, modifica ed eliminazione delle schede dei team
  (membri compresi) sono riservate ai membri della DA; per gli altri la scheda resta in sola lettura e il pulsante
  «Modifica» spiega perché. Finché nessun team DA ha membri, chiunque può modificare i team, per poterla
  impostare.
  Anche il «Team assegnatario» di un dominio lo cambia solo la DA: per gli altri il campo resta bloccato nella
  scheda del dominio (che per il resto si modifica come prima).
- Un **template Excel per ogni tipo di ADR** nella cartella `Templates/` (`Template_X-1.01_ADR_Nuovo_dominio_funzionale.xlsx`
  … `Template_X-1.13_ADR_Altro_decisione_trasversale.xlsx`), numerati nell'ordine degli ambiti. Hanno lo stile e
  l'intestazione del template X-1 generale e gli stessi campi della scheda del tipo in ATLAS: le tabelle (domini
  risultanti, ripartizione delle voci, produttori candidati, opzioni) con le loro colonne, gli elenchi a tendina
  per i campi a valori fissi e l'indicazione dei campi che ATLAS compila dal modello. Li scrive
  `scripts/make_adr_templates.py` a partire dallo schema, e un test verifica che restino allineati alle schede.
- Il **registro delle ADR aperte** (`Templates/Template_X-1.00_Registro_ADR_aperte.xlsx`): ID dell'ADR, breve
  descrizione, team proponente e stato, una riga per ogni ADR non ancora decisa dalla Design Authority (lo script
  dei template lo crea solo se manca, così le modifiche fatte a mano restano). Lo stesso
  elenco, già compilato dal progetto, si salva in Excel da ATLAS con «Esporta ADR aperte…» nell'elenco X-1.

### Corretto
- Un progetto scaricato su un PC con Git per Windows installato non risulta più sempre «modificato e non
  pubblicato»: Git per Windows imposta per tutto il sistema la conversione delle fine riga (`core.autocrlf`), che
  ATLAS applicava scaricando i file. Ora ogni progetto mantiene le fine riga delle versioni.
- All'avvio non viene più proposto il «Ripristino della sessione» dopo una chiusura normale: la copia di
  sicurezza delle modifiche, se nel frattempo erano state annullate (per esempio un elemento nuovo non salvato),
  restava e sembrava una chiusura imprevista.

### Modificato
- Il repository dello strumento è ora su GitHub (<https://github.com/salvodesi/ATLAS>), con le release di tutte
  le versioni. I test su Linux e l'archivio Linux sono compilati da GitHub Actions.
- Un elemento creato con «Nuovo…» (albero, elenchi X-1 e X-2) la cui scheda non viene mai salvata sparisce
  dal modello e dall'albero: con «Annulla», chiudendone la scheda o chiudendo il progetto. Non resta nulla da
  salvare.
- «Importa SRS…» non è più nella barra in alto: è la prima voce del menu del tasto destro su «Voci SRS»
  nell'albero del modello (e resta nel menu File).
- I membri dei team non sono più un elenco di nomi: all'apertura del progetto ogni nome diventa un membro senza
  ID, riconosciuto da nome e cognome finché la DA non ne indica l'ID dell'account.
- Gli identificativi automatici prendono il primo numero libero, anche quello lasciato da una scheda eliminata
  (prima non venivano mai riusati gli identificativi già pubblicati, e il numero era sempre l'ultimo più uno).

### Aggiornamento dalla 0.3.0
- I progetti della 0.3.0 si aprono senza interventi.
- I membri dei team scritti come nomi diventano membri senza ID dell'account, riconosciuti da nome e cognome:
  la Design Authority ne indichi l'ID dalla scheda del team. Chi non è tra i membri di un team non può aprire il
  progetto, quindi conviene che la DA completi i team prima di distribuire la nuova versione.
- Le ADR già scritte mantengono i propri dati: i campi che il loro tipo non ha più restano salvati ma non sono
  mostrati nella scheda.

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

[0.4.0]: https://github.com/salvodesi/ATLAS/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/salvodesi/ATLAS/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/salvodesi/ATLAS/releases/tag/v0.2.0
