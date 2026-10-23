# Avvia l'applicazione dal venv di sviluppo.
$root = Split-Path -Parent $PSScriptRoot
& "$root\.venv\Scripts\python.exe" -m arcadia_tool
