; Ruby Assistant installer (Inno Setup 6). Build it with: installer\build.ps1 -Version 1.0.0
; It packages the dist\Ruby folder produced by PyInstaller (see ruby.spec). Per-user install: no administrator rights needed.
; Keep this file saved as UTF-8 WITH a BOM, otherwise Inno Setup misreads the accented characters.

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
; the wizard language follows Windows (English when Windows is neither English nor French)
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
french.StartWithWindows=Lancer Ruby à l'ouverture de la session Windows
english.SettingsShortcut=Ruby settings
french.SettingsShortcut=Réglages de Ruby
english.LaunchRuby=Launch Ruby
french.LaunchRuby=Lancer Ruby
english.OpenSettings=Open Ruby settings
french.OpenSettings=Ouvrir les réglages de Ruby

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
; Start with Windows: the same entry as the "Start Ruby with Windows" switch in the settings (config.set_autostart)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Ruby"; ValueData: """{app}\Ruby.exe"""; Flags: uninsdeletevalue; Tasks: startup
; a previous "Disable" from the Task Manager would make Windows ignore the entry
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"; ValueName: "Ruby"; Flags: deletevalue; Tasks: startup

[Run]
Filename: "{app}\Ruby.exe"; Description: "{cm:LaunchRuby}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Ruby.exe"; Parameters: "--settings"; Description: "{cm:OpenSettings}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Ruby runs in the background: stop it before replacing or removing its files (--quit is a clean stop, then taskkill for the settings window).
// The user's settings, enrolled voice and models (%APPDATA%\Ruby, Hugging Face cache...) are NEVER deleted.
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
    // start-with-Windows enabled from Ruby's settings (not from the installer) is removed too
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Ruby');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', 'Ruby');
  end;
end;
