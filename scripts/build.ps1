# Crea l'eseguibile con PyInstaller e, se Inno Setup e' installato, l'installer Windows.
#   .\scripts\build.ps1            -> dist\ATLAS\ATLAS.exe (+ installer dist\installer\ATLAS-Setup-<versione>.exe)
#   .\scripts\build.ps1 -NoInstaller
param([switch]$NoInstaller)

$root = Split-Path -Parent $PSScriptRoot
$python = "$root\.venv\Scripts\python.exe"
Set-Location $root

& $python -m PyInstaller --noconfirm --clean --windowed `
    --name "ATLAS" `
    --icon src\arcadia_tool\resources\atlas.ico `
    --paths src `
    --add-data "Templates;Templates" `
    --add-data "src\arcadia_tool\resources;arcadia_tool\resources" `
    src\arcadia_tool\__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallito" }

if ($NoInstaller) { return }

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Warning "Inno Setup 6 non trovato: creato solo dist\ATLAS. Installare Inno Setup per generare l'installer."
    return
}

$version = & $python -c "import sys; sys.path.insert(0, 'src'); import arcadia_tool; print(arcadia_tool.__version__)"
& $iscc "/DAppVersion=$version" "installer\atlas.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallito" }
