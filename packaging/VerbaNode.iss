#define MyAppName "VerbaNode"
#ifndef MyAppVersion
  #define MyAppVersion "0.12.6"
#endif
#define MyAppPublisher "Sari Teknologi"
#define MyAppExeName "VerbaNode.exe"

[Setup]
AppId={{914EFF97-CD2A-477F-9CBD-BF62FEA8A0C7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VerbaNode
DefaultGroupName=VerbaNode
UsePreviousAppDir=yes
DirExistsWarning=auto
DisableProgramGroupPage=yes
PrivilegesRequired=admin
SetupArchitecture=x64
WizardStyle=modern
OutputDir=..\dist-installer
OutputBaseFilename=VerbaNode-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
SetupIconFile=assets\VerbaNode.ico
UninstallDisplayName=VerbaNode
UninstallDisplayIcon={app}\VerbaNode.ico
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=VerbaNode Windows Online Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Files]
Source: "..\dist\VerbaNode\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Install the final VerbaNode icon as a standalone file as well. Shortcuts
; reference this explicitly so Explorer does not need to infer/cached-read the EXE icon.
Source: "assets\VerbaNode.ico"; DestDir: "{app}"; DestName: "VerbaNode.ico"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Windows integration:"; Flags: unchecked
Name: "startup"; Description: "Start VerbaNode automatically with Windows"; GroupDescription: "Windows integration:"; Flags: unchecked

[InstallDelete]
; Remove any shortcut created by an older installer so Windows is forced to
; recreate it with the explicit final icon instead of retaining a cached icon.
Type: files; Name: "{group}\VerbaNode.lnk"
Type: files; Name: "{autodesktop}\VerbaNode.lnk"
Type: files; Name: "{commonstartup}\VerbaNode.lnk"

[Icons]
Name: "{group}\VerbaNode"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\VerbaNode.ico"; IconIndex: 0
Name: "{autodesktop}\VerbaNode"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\VerbaNode.ico"; IconIndex: 0; Tasks: desktopicon
; Use the common Startup folder for the elevated Program Files installer.
Name: "{commonstartup}\VerbaNode"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\VerbaNode.ico"; IconIndex: 0; Tasks: startup

[Run]
; Keep the firewall rule scoped to this executable and Private networks only.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VerbaNode"" program=""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""VerbaNode"" dir=in action=allow program=""{app}\{#MyAppExeName}"" enable=yes profile=private"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch VerbaNode"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser; Check: ShouldLaunchVerbaNode

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VerbaNode"" program=""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated; RunOnceId: "VerbaNodeFirewallRemove"

[Code]
const
  VerbaNodeUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{914EFF97-CD2A-477F-9CBD-BF62FEA8A0C7}_is1';

var
  ModePage: TInputOptionWizardPage;
  LanguagePage: TInputOptionWizardPage;
  WhisperPage: TInputOptionWizardPage;
  FeaturePage: TInputOptionWizardPage;
  OllamaModelPage: TInputQueryWizardPage;
  SetupProgressPage: TOutputMarqueeProgressWizardPage;
  DownloadPage: TDownloadWizardPage;
  EssentialSetupOK: Boolean;
  SetupWarnings: String;
  ExistingInstall: Boolean;
  InstalledVersion: String;

procedure AppendWarning(const Text: String);
begin
  if SetupWarnings <> '' then
    SetupWarnings := SetupWarnings + #13#10 + #13#10;
  SetupWarnings := SetupWarnings + Text;
end;

function DetectExistingInstall(): Boolean;
begin
  InstalledVersion := '';
  Result := RegQueryStringValue(HKLM64, VerbaNodeUninstallKey, 'DisplayVersion', InstalledVersion);
  if not Result then
    Result := RegQueryStringValue(HKLM32, VerbaNodeUninstallKey, 'DisplayVersion', InstalledVersion);

  if not Result then
  begin
    Result := FileExists(ExpandConstant('{autopf}\VerbaNode\{#MyAppExeName}'));
    if Result then
      InstalledVersion := 'existing version';
  end;
end;

function ShouldConfigureComponents(): Boolean;
begin
  Result := (not ExistingInstall) or (ModePage.SelectedValueIndex = 1);
end;

procedure InitializeWizard();
begin
  EssentialSetupOK := True;
  SetupWarnings := '';
  ExistingInstall := DetectExistingInstall();

  ModePage := CreateInputOptionPage(
    wpSelectDir,
    'Existing VerbaNode installation detected',
    'VerbaNode ' + InstalledVersion + ' is already installed.',
    'Choose how Setup should handle this run. Persistent agents, scripts, Information, settings, plugins, certificates and downloaded model caches are always preserved.',
    True,
    False
  );
  ModePage.Add('Update application only (recommended) - keep current AI models and components');
  ModePage.Add('Update application and review/add AI components');
  ModePage.SelectedValueIndex := 0;

  LanguagePage := CreateInputOptionPage(
    ModePage.ID,
    'Language support',
    'Choose which speech-recognition models Setup should prepare.',
    'Setup checks the existing user caches first. Selected AI models are downloaded only when missing; already-installed models are never downloaded again.',
    False,
    False
  );
  LanguagePage.Add('English - prepare SenseVoiceSmall');
  LanguagePage.Add('Bahasa Indonesia - prepare OpenAI Whisper through FunASR');
  LanguagePage.Values[0] := True;
  LanguagePage.Values[1] := True;

  WhisperPage := CreateInputOptionPage(
    LanguagePage.ID,
    'Indonesian speech recognition',
    'Choose the Whisper checkpoint to prepare.',
    'Base is faster and smaller. Small is more accurate but heavier. You can install both.',
    True,
    False
  );
  WhisperPage.Add('Whisper Base - faster CPU option');
  WhisperPage.Add('Whisper Small - higher accuracy option');
  WhisperPage.Add('Whisper Base + Small');
  WhisperPage.SelectedValueIndex := 0;

  FeaturePage := CreateInputOptionPage(
    WhisperPage.ID,
    'Optional local components',
    'Choose additional components to prepare.',
    'Edge TTS is already part of VerbaNode. Existing Kokoro, Ollama and Ollama models are detected and reused instead of reinstalled.',
    False,
    False
  );
  FeaturePage.Add('Download Kokoro local TTS model');
  FeaturePage.Add('Install/configure Ollama local LLM runtime');
  FeaturePage.Values[0] := False;
  FeaturePage.Values[1] := True;

  OllamaModelPage := CreateInputQueryPage(
    FeaturePage.ID,
    'Ollama model',
    'Choose the local model VerbaNode should pre-download.',
    'The default matches the built-in Ropi agent. You can change models later from VerbaNode settings.'
  );
  OllamaModelPage.Add('Model:', False);
  OllamaModelPage.Values[0] := 'qwen3.5:0.8b';

  SetupProgressPage := CreateOutputMarqueeProgressPage(
    'Preparing VerbaNode',
    'VerbaNode is initializing persistent data and selected AI components.'
  );
  DownloadPage := CreateDownloadPage(
    'Downloading component',
    'Setup is downloading a selected external component.',
    nil
  );
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = ModePage.ID then
    Result := not ExistingInstall
  else if (PageID = LanguagePage.ID) or (PageID = FeaturePage.ID) then
    Result := not ShouldConfigureComponents()
  else if PageID = WhisperPage.ID then
    Result := (not ShouldConfigureComponents()) or (not LanguagePage.Values[1])
  else if PageID = OllamaModelPage.ID then
    Result := (not ShouldConfigureComponents()) or (not FeaturePage.Values[1]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ModelName: String;
begin
  Result := True;
  if CurPageID = OllamaModelPage.ID then
  begin
    ModelName := Trim(OllamaModelPage.Values[0]);
    if ModelName = '' then
    begin
      MsgBox('Enter an Ollama model name or go Back and disable Ollama setup.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function RunSetupCommand(const Params, TitleText, DetailText: String): Boolean;
var
  ResultCode: Integer;
begin
  SetupProgressPage.SetText(TitleText, DetailText);
  Result := ExecAsOriginalUser(
    ExpandConstant('{app}\{#MyAppExeName}'),
    Params,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  if Result then
    Result := ResultCode = 0;
end;

function CheckOllamaInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := ExecAsOriginalUser(
    ExpandConstant('{app}\{#MyAppExeName}'),
    '--setup-ollama-status',
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  Result := Result and (ResultCode = 0);
end;

function InstallOllama(): Boolean;
var
  ResultCode: Integer;
  InstallerPath: String;
begin
  Result := False;
  DownloadPage.Clear;
  DownloadPage.Add(
    'https://ollama.com/download/OllamaSetup.exe',
    'OllamaSetup.exe',
    ''
  );
  DownloadPage.Show;
  try
    DownloadPage.Download;
  except
    AppendWarning('Ollama could not be downloaded: ' + GetExceptionMessage);
    Exit;
  finally
    DownloadPage.Hide;
  end;

  InstallerPath := ExpandConstant('{tmp}\OllamaSetup.exe');
  Result := ExecAsOriginalUser(
    InstallerPath,
    '/SILENT',
    ExpandConstant('{tmp}'),
    SW_SHOWNORMAL,
    ewWaitUntilTerminated,
    ResultCode
  );
  Result := Result and (ResultCode = 0);
end;

procedure PrepareSelectedComponents();
var
  WhisperSelection: String;
  OllamaModel: String;
begin
  SetupProgressPage.Show;
  try
    if not RunSetupCommand(
      '--setup-database',
      'Preparing database',
      'Creating or migrating the VerbaNode database. Existing data is backed up and preserved.'
    ) then
    begin
      EssentialSetupOK := False;
      AppendWarning('Database initialization failed. VerbaNode will not be launched automatically.');
    end;

    if not RunSetupCommand(
      '--setup-https',
      'Preparing HTTPS',
      'Checking or generating the local HTTPS certificate used by the dashboard and browser microphone.'
    ) then
    begin
      EssentialSetupOK := False;
      AppendWarning('HTTPS initialization failed. VerbaNode will not be launched automatically.');
    end;

    if not ShouldConfigureComponents() then
      Exit;

    if LanguagePage.Values[0] then
      if not RunSetupCommand(
        '--setup-download-sensevoice',
        'Preparing English speech recognition',
        'Downloading SenseVoiceSmall if it is not already cached. This can take several minutes.'
      ) then
        AppendWarning('SenseVoiceSmall setup failed. English STT can be downloaded later from the source helper or on first use.');

    if LanguagePage.Values[1] then
    begin
      case WhisperPage.SelectedValueIndex of
        1: WhisperSelection := 'small';
        2: WhisperSelection := 'both';
      else
        WhisperSelection := 'base';
      end;
      if not RunSetupCommand(
        '--setup-download-whisper ' + WhisperSelection,
        'Preparing Indonesian speech recognition',
        'Downloading the selected Whisper checkpoint if it is not already cached.'
      ) then
        AppendWarning('Whisper ' + WhisperSelection + ' setup failed. Indonesian STT can be downloaded later.');
    end;

    if FeaturePage.Values[0] then
      if not RunSetupCommand(
        '--setup-download-kokoro',
        'Preparing Kokoro local TTS',
        'Downloading and extracting the Kokoro local TTS model if it is missing.'
      ) then
        AppendWarning('Kokoro setup failed. Edge TTS remains available.');
  finally
    SetupProgressPage.Hide;
  end;

  if FeaturePage.Values[1] then
  begin
    if not CheckOllamaInstalled() then
    begin
      if not InstallOllama() then
      begin
        AppendWarning('Ollama installation failed. Install Ollama manually and then pull the configured model.');
        Exit;
      end;
    end;

    OllamaModel := Trim(OllamaModelPage.Values[0]);
    SetupProgressPage.Show;
    try
      if not RunSetupCommand(
        '--setup-ollama-pull "' + OllamaModel + '"',
        'Preparing local LLM',
        'Starting Ollama if needed and downloading ' + OllamaModel + '. Large models can take a long time.'
      ) then
        AppendWarning('Ollama is installed, but model ' + OllamaModel + ' could not be downloaded.');
    finally
      SetupProgressPage.Hide;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    PrepareSelectedComponents();
    if SetupWarnings <> '' then
      MsgBox(
        'VerbaNode was installed, but some setup actions need attention:' + #13#10 + #13#10 + SetupWarnings,
        mbInformation,
        MB_OK
      );
  end;
end;

function ShouldLaunchVerbaNode(): Boolean;
begin
  Result := EssentialSetupOK;
end;
