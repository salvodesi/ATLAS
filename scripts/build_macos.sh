#!/usr/bin/env sh
# Crea l'app macOS (Apple Silicon) con PyInstaller e lo zip da distribuire.
#   ./scripts/build_macos.sh   -> dist/ATLAS.app + dist/ATLAS-<versione>-macos-arm64.zip (+ .sha256)
# PYTHON sceglie l'interprete (default: il venv di sviluppo). Va eseguito su un Mac Apple Silicon (o dal workflow
# di GitHub, su macos-14). L'app non è firmata: al primo avvio macOS chiede conferma (vedi le note della release).
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
python="${PYTHON:-$root/.venv/bin/python}"
cd "$root"

version="$("$python" -c "import sys; sys.path.insert(0, 'src'); import arcadia_tool; print(arcadia_tool.__version__)")"

# The icon of the app: PyInstaller turns the PNG into an .icns (with Pillow installed).
"$python" -m PyInstaller --noconfirm --clean --windowed \
    --name "ATLAS" \
    --target-architecture arm64 \
    --osx-bundle-identifier "it.rfi.atlas" \
    --icon src/arcadia_tool/resources/icon_256.png \
    --paths src \
    --add-data "Templates:Templates" \
    --add-data "src/arcadia_tool/resources:arcadia_tool/resources" \
    --add-data "CHANGELOG.md:." \
    src/arcadia_tool/__main__.py

# The version shown by macOS (Finder › Informazioni).
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" dist/ATLAS.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $version" dist/ATLAS.app/Contents/Info.plist

archive="ATLAS-$version-macos-arm64.zip"
rm -f "dist/$archive"
# ditto keeps the links and the permissions of the bundle (zip would break them).
(cd dist && ditto -c -k --sequesterRsrc --keepParent ATLAS.app "$archive")
# The SHA-256 fingerprint, attached to the release next to the archive: ATLAS checks it before updating itself.
(cd dist && shasum -a 256 "$archive" > "$archive.sha256")
echo "dist/$archive"
