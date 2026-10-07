#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
[Setup]
AppId={{944EB08E-3B20-4C0B-AC3E-2C85DB5B6C2E}
AppName=Vision
AppVersion=0.4.0
AppPublisher=VisionSolver
DefaultDirName={localappdata}\Programs\VisionSolver
DefaultGroupName=Vision
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir={#OutputDir}
OutputBaseFilename=Vision
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\VisionApp.exe
SetupLogging=yes
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Vision"; Filename: "{app}\VisionApp.exe"
Name: "{autodesktop}\Vision"; Filename: "{app}\VisionApp.exe"
[Run]
Filename: "{app}\VisionApp.exe"; Description: "Запустить Vision"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\VisionApp.exe"; Parameters: "--uninstall-cleanup"; Flags: runhidden waituntilterminated; RunOnceId: "RestoreVisionPower"
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var ExitCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and not UninstallSilent then
    if MsgBox('Удалить также модели, фотографии, результаты и настройки? По умолчанию эти данные сохраняются.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      Exec(ExpandConstant('{app}\VisionApp.exe'), '--uninstall-cleanup --delete-data', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
end;
