; ============================================================
; 씨제이씨협동조합 OSMU 워크벤치 — Windows 설치 프로그램 (Inno Setup 6)
;   .github/workflows/flet-windows-build.yml이 flet build windows 결과(stage\build\windows)를 묶어
;   OSMU-CJC-Setup-{버전}.exe를 만든다. 만든 setup.exe를 직접 고치지 말고 이 파일을 고친다.
;
; 재설치·업데이트 규칙
;   - AppId가 고정이라 다시 설치하면 같은 폴더(Program Files)에 덮어쓰고, '설치된 앱' 목록에도 1개만 남는다.
;   - 설치 전에 실행 중인 앱(과 앱이 띄운 네이버 게시용 Chrome 창)을 닫고, 설치 폴더의 이전 버전 파일을
;     모두 지운 뒤 새로 깐다. (flet 빌드는 app·site-packages·Lib 폴더와 dll로 이뤄진다. 옛 버전 모듈이 남아
;     새 버전과 섞이면 앱이 시작되지 않거나 엉뚱하게 동작할 수 있다)
;   - 사용자 데이터(브랜드 킷·글·사진·암호화된 API 키·네이버 로그인)는 설치 폴더가 아니라
;     %APPDATA%\OSMU_CJC에 있다(core/db.py의 _default_data_dir). 설치·재설치·제거 어느 것도
;     그 폴더를 건드리지 않는다 — [InstallDelete]·[UninstallDelete]는 {app}만 지운다.
;
; 이 파일은 한글이 있어 UTF-8(BOM)으로 저장해야 한다.
; ============================================================

; 빌드할 때 /D 옵션으로 넘긴다 (없으면 아래 기본값)
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef AppExe
  #define AppExe "osmu-cjc-flet.exe"
#endif
#ifndef SourceDir
  #define SourceDir "..\stage\build\windows"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "씨제이씨협동조합 OSMU 워크벤치"
; 바로가기용 아이콘 파일 이름 — 버전마다 다르게 ([Files] 참고)
#define AppIconName "osmu-cjc-" + AppVersion + ".ico"

[Setup]
; 절대 바꾸지 않는다 — 바꾸면 기존 설치를 다른 앱으로 보고 두 번 설치된다.
AppId={{34EEB406-6A85-453A-B114-1F82B055A174}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=씨제이씨협동조합
; 경로는 영문으로 짧게 둔다(Windows 260자 경로 제한 — site-packages 안 경로가 길다)
DefaultDirName={autopf}\OSMU CJC
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
; Program Files에 설치하므로 관리자 권한을 묻는다.
; 관리자 권한을 받을 수 없는 PC는 명령줄에서 setup.exe /CURRENTUSER 로 사용자 폴더에 설치할 수 있다.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 실행 중인 앱을 닫고 설치한다
CloseApplications=force
RestartApplications=no
OutputDir={#OutputDir}
OutputBaseFilename=OSMU-CJC-Setup-{#AppVersion}
#ifdef IconFile
SetupIconFile={#IconFile}
#endif
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
#ifdef IconFile
UninstallDisplayIcon={app}\{#AppIconName}
#else
UninstallDisplayIcon={app}\{#AppExe}
#endif
; 설치 끝에 탐색기에 아이콘을 다시 읽으라고 알린다(SHChangeNotify). 없으면 재설치해도 바탕화면·시작 메뉴에
; 예전 아이콘이 캐시로 남는다(2026-10-24 확인: 창 왼쪽 위 아이콘만 바뀌고 바로가기는 그대로).
ChangesAssociations=yes
SetupLogging=yes

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\Korean.isl")
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[InstallDelete]
; 설치 폴더를 비우고 새로 깐다(설치 단계 맨 처음에 실행). 설치 폴더에는 이 앱의 프로그램 파일만 있다.
; 사용자 데이터는 %APPDATA%\OSMU_CJC에 있어 지워지지 않는다. 제거 프로그램(unins000.*)은 설치 끝에 다시 만들어진다.
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef IconFile
; 바로가기 아이콘 파일. 이름에 버전을 넣어 버전마다 경로가 달라지게 한다 — Windows 아이콘 캐시는 경로로
; 찾으므로, 같은 exe 경로를 가리키는 바로가기는 아이콘을 바꿔도 예전 그림을 계속 보여 준다.
Source: "{#IconFile}"; DestDir: "{app}"; DestName: "{#AppIconName}"; Flags: ignoreversion
#endif

[Icons]
; 시작 메뉴와 바탕화면에 항상 아이콘을 만든다(재설치하면 다시 만든다). 제거하면 함께 지워진다.
#ifdef IconFile
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppIconName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppIconName}"
#else
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
#endif

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 실행 중에 생긴 파일까지 설치 폴더를 통째로 지운다. %APPDATA%\OSMU_CJC(사용자 데이터)는 넣지 않는다.
Type: filesandordirs; Name: "{app}"

[Code]
procedure CloseRunningApp();
var
  ResultCode: Integer;
begin
  { Restart Manager가 닫지 못한 경우를 위한 보조 수단. 실행 중이 아니면 아무 일도 하지 않는다.
    /T는 앱이 띄운 자식 프로세스(Playwright 드라이버와 네이버 게시용 Chrome 창)까지 닫는다 —
    사용자가 따로 켠 Chrome은 이 앱의 자식이 아니라 건드리지 않는다. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM "{#AppExe}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  CloseRunningApp();
  Result := True;
end;
