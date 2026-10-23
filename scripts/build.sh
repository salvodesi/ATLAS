#!/usr/bin/env sh
# Crea l'eseguibile Linux con PyInstaller e l'archivio da distribuire.
#   ./scripts/build.sh   -> dist/ATLAS/ATLAS + dist/ATLAS-<versione>-linux-x86_64.tar.gz
# PYTHON sceglie l'interprete (default: il venv di sviluppo).
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
python="${PYTHON:-$root/.venv/bin/python}"
cd "$root"

"$python" -m PyInstaller --noconfirm --clean --windowed \
    --name "ATLAS" \
    --paths src \
    --add-data "Templates:Templates" \
    --add-data "src/arcadia_tool/resources:arcadia_tool/resources" \
    src/arcadia_tool/__main__.py

version="$("$python" -c "import sys; sys.path.insert(0, 'src'); import arcadia_tool; print(arcadia_tool.__version__)")"
cp src/arcadia_tool/resources/icon_256.png dist/ATLAS/atlas.png
tar -czf "dist/ATLAS-$version-linux-x86_64.tar.gz" -C dist ATLAS
echo "dist/ATLAS-$version-linux-x86_64.tar.gz"
