#define AppName "NetBreak"
#define AppVersion "2.0.0"
#define AppPublisher "5evenTeam"
#define AppId "{{8F2A6C31-4D5E-4B7A-9C1D-2E3F4A5B6C7D}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/5evenTeam/NetBreak
AppSupportURL=https://github.com/5evenTeam/NetBreak
AppUpdatesURL=https://github.com/5evenTeam/NetBreak
DefaultDirName={autopf}\NetBreak
DefaultGroupName=NetBreak
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=NetBreak-Setup-2.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\netbreak.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "engines"; Description: "Install the native scan engines (Go and C++)"; GroupDescription: "Components:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create desktop shortcuts"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\netbreak.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\netbreak-gui.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\engines\go\bin\netbreak-engine.exe"; DestDir: "{app}\engines"; Flags: ignoreversion skipifsourcedoesntexist; Tasks: engines
Source: "..\engines\cpp\bin\netbreak-native.exe"; DestDir: "{app}\engines"; Flags: ignoreversion skipifsourcedoesntexist; Tasks: engines

[Icons]
Name: "{autoprograms}\NetBreak\NetBreak (Terminal UI)"; Filename: "{app}\netbreak.exe"; WorkingDir: "{%USERPROFILE}"; Comment: "NetBreak terminal user interface"
Name: "{autoprograms}\NetBreak\NetBreak Desktop"; Filename: "{app}\netbreak-gui.exe"; WorkingDir: "{%USERPROFILE}"; Comment: "NetBreak desktop interface"
Name: "{autodesktop}\NetBreak (Terminal UI)"; Filename: "{app}\netbreak.exe"; WorkingDir: "{%USERPROFILE}"; Comment: "NetBreak terminal user interface"; Tasks: desktopicon
Name: "{autodesktop}\NetBreak Desktop"; Filename: "{app}\netbreak-gui.exe"; WorkingDir: "{%USERPROFILE}"; Comment: "NetBreak desktop interface"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: string; ValueName: "NETBREAK_ENGINE_DIR"; ValueData: "{app}\engines"; Flags: uninsdeletevalue; Tasks: engines

[UninstallDelete]
Type: filesandordirs; Name: "{app}\engines"

[Run]
Filename: "{app}\netbreak.exe"; Description: "Launch NetBreak (Terminal UI)"; Flags: postinstall nowait skipifsilent
