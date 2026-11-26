; Installateur de Ruby (Inno Setup 6). Compiler: installer\build.ps1 -Version 1.0.0
; Il emballe le dossier dist\Ruby fabriqué par PyInstaller (voir ruby.spec). Installation par utilisateur: pas besoin d'être administrateur.
; Ce fichier est enregistré en UTF-8 AVEC BOM (sinon Inno Setup lit les accents de travers).

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{1E28E4B2-7175-4D78-8CB2-967EA7BF8300}
AppName=Ruby
AppVersion={#AppVersion}
AppPublisher=Ruby
DefaultDirName={autopf}\Ruby
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Ruby-Setup-{#AppVersion}
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\Ruby.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; la langue de l'assistant suit celle de Windows (English si Windows n'est ni en anglais ni en français)
ShowLanguageDialog=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
english.StartupGroup=Startup
french.StartupGroup=Démarrage
english.StartWithWindows=Start Ruby when I sign in to Windows
french.StartWithWindows=Lancer Ruby à l'ouverture de ma session Windows
english.SettingsShortcut=Ruby settings
french.SettingsShortcut=Réglages de Ruby
english.LaunchRuby=Launch Ruby
french.LaunchRuby=Lancer Ruby
english.OpenSettings=Open Ruby settings (to teach it your voice)
french.OpenSettings=Ouvrir les réglages de Ruby (pour lui apprendre ta voix)

[Tasks]
Name: "startup"; Description: "{cm:StartWithWindows}"; GroupDescription: "{cm:StartupGroup}"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Ruby\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Ruby"; Filename: "{app}\Ruby.exe"
Name: "{autoprograms}\{cm:SettingsShortcut}"; Filename: "{app}\Ruby.exe"; Parameters: "--settings"
Name: "{autodesktop}\Ruby"; Filename: "{app}\Ruby.exe"; Tasks: desktopicon

[Registry]
; Lancer avec Windows: la même entrée que l'interrupteur « Lancer Ruby avec Windows » des réglages (config.set_autostart)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Ruby"; ValueData: """{app}\Ruby.exe"""; Flags: uninsdeletevalue; Tasks: startup
; un ancien « Désactiver » du Gestionnaire des tâches ferait ignorer l'entrée
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"; ValueName: "Ruby"; Flags: deletevalue; Tasks: startup

[Run]
Filename: "{app}\Ruby.exe"; Description: "{cm:LaunchRuby}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Ruby.exe"; Parameters: "--settings"; Description: "{cm:OpenSettings}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Ruby tourne en arrière-plan: on l'arrête avant de remplacer ou de supprimer ses fichiers (--quit = arrêt propre, puis taskkill pour la fenêtre de réglages).
// Tes réglages, ta voix apprise et tes modèles (dossier %APPDATA%\Ruby, caches Hugging Face…) ne sont JAMAIS supprimés.
procedure StopRuby();
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\Ruby.exe')) then
    Exec(ExpandConstant('{app}\Ruby.exe'), '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1500);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Ruby.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRuby();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRuby();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // le lancement avec Windows activé depuis les réglages de Ruby (pas depuis l'installateur) est lui aussi retiré
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Ruby');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', 'Ruby');
  end;
end;
