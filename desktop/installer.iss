; Inno Setup script for Browser Guardian
; Download Inno Setup from: https://jrsoftware.org/isinfo.php
; Then open this file in Inno Setup and click Build > Compile

#define AppName "Browser Guardian"
#define AppVersion "1.0"
#define AppPublisher "Parent"
#define AppExeName "BrowserGuardian.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\BrowserGuardian
DefaultGroupName={#AppName}
OutputDir=installer_output
OutputBaseFilename=BrowserGuardianSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Include all files from the PyInstaller output folder
Source: "dist\BrowserGuardian\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Browser Guardian"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall Browser Guardian"; Filename: "{uninstallexe}"

[Run]
; Launch the app after install
Filename: "{app}\{#AppExeName}"; Description: "Start Browser Guardian now"; Flags: nowait postinstall skipifsilent

[Registry]
; Add to Windows startup automatically
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "BrowserGuardian"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletevalue

[UninstallRun]
; Remove from startup on uninstall
Filename: "reg"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v BrowserGuardian /f"; Flags: runhidden; RunOnceId: "RemoveStartup"
