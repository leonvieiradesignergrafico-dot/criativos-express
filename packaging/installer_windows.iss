; ============================================================================
;  Ads Express — instalador Windows (Inno Setup 6)
;  Compilar (a partir da RAIZ do projeto), depois de rodar packaging\build.ps1:
;      iscc packaging\installer_windows.iss
;  (iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" — instale o Inno Setup
;   em https://jrsoftware.org/isdl.php se ainda não tiver.)
;
;  Instala PER-USER em %LOCALAPPDATA%\Programs\Ads Express (sem exigir admin), para
;  que config\ e gerados\ — que ficam AO LADO do executável — sejam graváveis.
;  Isso casa com workspace.py: quando congelado, ROOT = pasta do .exe.
; ============================================================================

#define AppName "Ads Express"
#define AppVersion "1.0.0"
#define AppPublisher "Ads Express"
#define AppExe "Ads Express.exe"

[Setup]
AppId={{7F3B2E14-4C9A-4E2D-9B1F-ADS0EXPRESS001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Instalação por usuário (sem UAC). config\ e gerados\ ficam graváveis ao lado do app.
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=AdsExpress-Setup-{#AppVersion}
SetupIconFile=icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; O app (one-folder do PyInstaller: dist\Ads Express\).
Source: "..\dist\Ads Express\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; O assistente de Setup (one-folder) num subdiretório próprio (evita colidir com o _internal do app).
Source: "..\dist\Setup Ads Express\*"; DestDir: "{app}\setup"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
; Pastas de dados GRAVÁVEIS do usuário, ao lado do executável.
; config\ = entradas; entregas\ = saídas geradas (imagens e vídeos).
Name: "{app}\config"
Name: "{app}\entregas\gerados"
Name: "{app}\entregas\videos"

[Icons]
; Atalhos "Ads Express" (Menu Iniciar + Área de Trabalho) com o ícone do app.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Setup / Reparar {#AppName}"; Filename: "{app}\setup\Setup Ads Express.exe"; IconFilename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Ao final, oferece rodar o assistente de Setup (instala Node/CLIs e faz os logins).
Filename: "{app}\setup\Setup Ads Express.exe"; Description: "Preparar dependências agora (Node.js, Claude, Codex, logins)"; Flags: postinstall skipifsilent
; E oferece abrir o app.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; NÃO apagamos config\ nem entregas\ (dados do usuário) — só o que o instalador trouxe.
Type: dirifempty; Name: "{app}"
