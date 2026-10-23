#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Same AppId as the versions called «ARCADIA Tool»: installing ATLAS replaces them, it does not add a second copy.
AppId={{6B1F3C2E-8D4A-4E7B-9A51-3F0C2D7E8A41}
AppName=ATLAS
AppVerName=ATLAS {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=RFI - Ricerca e Sviluppo - Sviluppo Sistemi
AppComments=Arcadia Traceability, Logical Architecture Software
DefaultDirName={autopf}\ATLAS
DefaultGroupName=ATLAS
; The folder and the Start menu group of the earlier versions are not reused (see [InstallDelete]).
UsePreviousAppDir=no
UsePreviousGroup=no
UninstallDisplayName=ATLAS
UninstallDisplayIcon={app}\ATLAS.exe
SetupIconFile=..\src\arcadia_tool\resources\atlas.ico
OutputDir=..\dist\installer
OutputBaseFilename=ATLAS-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[InstallDelete]
; What the versions called «ARCADIA Tool» installed: their program folder and their shortcuts. The data of the
; users (%APPDATA%\RFI\ARCADIA Tool: accounts, keys, settings) are not touched.
Type: filesandordirs; Name: "{autopf}\ARCADIA Tool"
Type: filesandordirs; Name: "{autoprograms}\ARCADIA Tool"
Type: files; Name: "{autodesktop}\ARCADIA Tool.lnk"

[Files]
Source: "..\dist\ATLAS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\ATLAS"; Filename: "{app}\ATLAS.exe"; Comment: "Arcadia Traceability, Logical Architecture Software"
Name: "{autodesktop}\ATLAS"; Filename: "{app}\ATLAS.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; Flags: unchecked

[Run]
Filename: "{app}\ATLAS.exe"; Description: "Avvia ATLAS"; Flags: nowait postinstall skipifsilent
