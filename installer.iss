; Inno Setup script for MotoTRBO TTS with built-in English voices.
; Built by the GitHub workflow (or build.bat) after PyInstaller and fetch_voices.py:
;   dist\MotoTRBO-TTS\   app folder from PyInstaller --onedir
;   voices\              voice models from fetch_voices.py
;
; Voices are compressed with LZMA2 inside the installer and unpacked during setup.
; Because all English voices together are several GB, the installer is split into
; parts under 2 GB (MotoTRBO-TTS-Setup.exe + MotoTRBO-TTS-Setup-1.bin, -2.bin, ...).
; Keep all parts in the same folder and run the .exe.

#define AppName "MotoTRBO TTS"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6B1E7A52-3C0F-4E9B-9C7E-2F4D8A1B5E30}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=MotoTRBO TTS
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\MotoTRBO-TTS.exe
SetupIconFile=icon.ico
LicenseFile=LICENSE
OutputDir=installer-output
OutputBaseFilename=MotoTRBO-TTS-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
; Compression: LZMA2, non-solid so each voice is compressed on its own (keeps memory use sane)
Compression=lzma2/max
SolidCompression=no
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
; Split into parts small enough for GitHub Releases (2 GB per file limit)
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
ReserveBytes=0

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\MotoTRBO-TTS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "voices\*.onnx"; DestDir: "{app}\voices"; Flags: ignoreversion
Source: "voices\*.onnx.json"; DestDir: "{app}\voices"; Flags: ignoreversion
Source: "voices\voices.json"; DestDir: "{app}\voices"; Flags: ignoreversion
Source: "phrases.lst"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\MotoTRBO-TTS.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\MotoTRBO-TTS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MotoTRBO-TTS.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
