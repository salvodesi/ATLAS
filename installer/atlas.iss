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
; For the user only (%LOCALAPPDATA%\Programs\ATLAS, no administrator rights): ATLAS updates itself without asking
; the password of an administrator (Aiuto › Verifica aggiornamenti…).
PrivilegesRequired=lowest
DefaultDirName={autopf}\ATLAS
DefaultGroupName=ATLAS
; The folder and the Start menu group of the earlier versions are not reused (see [InstallDelete]).
UsePreviousAppDir=no
UsePreviousGroup=no
; ATLAS still open during an update: closed by the installer (it closes itself before, after saving).
CloseApplications=force
UninstallDisplayName=ATLAS
UninstallDisplayIcon={app}\ATLAS.exe
SetupIconFile=..\src\arcadia_tool\resources\atlas.ico
OutputDir=..\dist\installer
OutputBaseFilename=ATLAS-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
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
; The update started by ATLAS (silent, /RELAUNCH=1): ATLAS opens again when it is installed.
Filename: "{app}\ATLAS.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[Code]
function Relaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

// The versions up to 0.6.0 could be installed for all the users (in Programmi, with administrator rights): this
// installation, for the user, does not replace them, so the user is told to uninstall them.
function InitializeSetup: Boolean;
begin
  Result := True;
  if not WizardSilent and RegKeyExists(HKLM,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6B1F3C2E-8D4A-4E7B-9A51-3F0C2D7E8A41}_is1') then
    MsgBox('Sul PC c''è una versione precedente di ATLAS installata per tutti gli utenti (in Programmi).' + #13#10 +
           'Da questa versione ATLAS si installa per il solo utente e si aggiorna da sé: dopo l''installazione ' +
           'disinstalla la versione precedente da Impostazioni › App, per non averne due copie.',
           mbInformation, MB_OK);
end;
