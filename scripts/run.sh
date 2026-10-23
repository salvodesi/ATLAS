#!/usr/bin/env sh
# Avvia l'applicazione dal venv di sviluppo (Linux).
root="$(cd "$(dirname "$0")/.." && pwd)"
exec "$root/.venv/bin/python" -m arcadia_tool "$@"
