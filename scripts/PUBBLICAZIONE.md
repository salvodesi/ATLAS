# Pubblicare una nuova versione di ATLAS

Tutti i comandi sono per **PowerShell su Windows** e si lanciano dalla cartella del progetto. Negli esempi la nuova
versione è `0.9.5`.

## Cosa serve

- L'ambiente Python del progetto in `.venv`.
- [Inno Setup 6](https://jrsoftware.org/isinfo.php), per l'installer Windows.
- La chiave SSH per GitHub: `%APPDATA%\RFI\ARCADIA Tool\keys\sa.desimone_ed25519`.
- Un token GitHub *fine-grained* per `salvodesi/ATLAS`, con **Contents** e **Actions** in lettura e scrittura. Lo chiede
  una finestra durante la release e non viene salvato.

## 1. Aggiorna versione e CHANGELOG

Scrivi il numero in questi tre punti:

| File | Riga |
|---|---|
| `pyproject.toml` | `version = "0.9.5"` |
| `src/arcadia_tool/__init__.py` | `__version__ = "0.9.5"` |
| `README.md` | `versione 0.9.5</sub>` |

In `CHANGELOG.md`:

1. Sotto `## [Non rilasciato]` aggiungi l'intestazione `## [0.9.5] - AAAA-MM-GG`, sopra le voci da rilasciare, e lascia
   vuota la sezione «Non rilasciato».
2. In fondo al file, aggiorna i collegamenti:

   ```text
   [Non rilasciato]: https://github.com/salvodesi/ATLAS/compare/v0.9.5...main
   [0.9.5]: https://github.com/salvodesi/ATLAS/compare/v0.9.4...v0.9.5
   ```

## 2. Esegui i test

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider -o faulthandler_timeout=120 -o faulthandler_exit_on_timeout=true
```

Richiede circa 5-10 minuti. Se un test fallisce, fermati e correggi prima di proseguire.

## 3. Crea l'installer

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
```

Alla fine in `dist\installer` trovi `ATLAS-Setup-0.9.5.exe` e `ATLAS-Setup-0.9.5.exe.sha256`.

## 4. Fai commit e tag

Controlla prima cosa c'è da includere:

```powershell
git status --short
```

`src/arcadia_tool/storage/trace_sheets.py` è un lavoro non finito e **non va incluso**: il comando qui sotto lo toglie.
`Metodologia/` e `import/` sono già esclusi da Git. Se hai aggiunto test nuovi, `git add tests` li comprende.

```powershell
git add CHANGELOG.md README.md pyproject.toml src/arcadia_tool scripts tests
git reset -q src/arcadia_tool/storage/trace_sheets.py
git -c user.name="Salvatore De Simone" -c user.email="sa.desimone@rfi.it" commit -m "ATLAS 0.9.5: descrizione breve"
git -c user.name="Salvatore De Simone" -c user.email="sa.desimone@rfi.it" tag -a v0.9.5 -m "ATLAS 0.9.5"
```

## 5. Invia a GitHub

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\github_push.py "$env:APPDATA\RFI\ARCADIA Tool\keys\sa.desimone_ed25519"
```

Invia `main` e tutti i tag, senza forzare. Con il push del tag parte da solo il workflow di GitHub che esegue i test e
costruisce il pacchetto Linux e l'app macOS (Apple Silicon, `scripts/build_macos.sh`), allegandoli alla release.

## 6. Pubblica la release

```powershell
.\.venv\Scripts\python.exe scripts\github_release.py 0.9.5
```

Si apre la finestra per il token. Lo script crea la release con le istruzioni di installazione e la sezione del
CHANGELOG, e allega l'installer Windows e il suo `.sha256`.

Per aggiungere alle note un avviso valido solo per questa versione, scrivilo in un file e passalo come secondo argomento:

```powershell
.\.venv\Scripts\python.exe scripts\github_release.py 0.9.5 note_0.9.5.md
```

## 7. Controlla il risultato

Il pacchetto Linux arriva dopo qualche minuto. Controlla su
<https://github.com/salvodesi/ATLAS/actions> che il workflow sia riuscito, e nella pagina della release che ci siano
quattro file:

- `ATLAS-Setup-0.9.5.exe` e `ATLAS-Setup-0.9.5.exe.sha256`
- `ATLAS-0.9.5-linux-x86_64.tar.gz` e `ATLAS-0.9.5-linux-x86_64.tar.gz.sha256`

L'aggiornamento automatico cerca i file con esattamente questi nomi: gli utenti dalla 0.7.0 in poi ricevono la nuova
versione solo quando la release è pubblicata e l'installer è allegato.

## Se qualcosa va storto

- **Il push è rifiutato:** su GitHub ci sono commit che non hai in locale. Allineati prima di riprovare, senza forzare.
- **La release si interrompe:** rilancia lo stesso comando. Aggiorna la release esistente e allega solo i file mancanti.
- **Hai rifatto l'installer dopo la release:** rilancia il comando della release. Sostituisce il file se la dimensione è
  cambiata.
- **Il tag è sbagliato e già inviato:** non spostarlo. Conviene pubblicare una nuova versione.
