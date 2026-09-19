# 스파이크 — Flet + Playwright + Windows 클립보드 검증

`docs`용이 아니라 검증용 임시 폴더입니다. 본 앱(OSMU 워크벤치) Flet 전환을 시작하기 전에,
검토 과정에서 나온 두 가지 불확실한 지점을 먼저 확인합니다.

## 확인하는 것

1. **`flet build windows`로 만든 exe 안에서 Playwright가 실제로 브라우저를 띄울 수 있는가?**
   `ai_workers/naver_publisher.py`의 `launch_browser()`와 동일하게 시스템 Chrome
   (`channel="chrome"`)을 먼저 시도합니다. Flet은 PyInstaller가 아니라 CPython을 통째로
   번들하는 방식이라(https://flet.dev/docs/updates/breaking-changes/v0-86-0/default-bundled-python-3-14),
   Playwright의 드라이버가 그 패키징 과정에서 살아남는지가 실제로 빌드해보기 전엔
   확실하지 않았습니다.
2. **Windows에서 CF_HTML 클립보드 포맷 write→read 왕복이 되는가?**
   `core/clipboard_utils.py`는 macOS(`osascript`) 전용이고, non-mac 폴백인
   `pyperclip.copy()`는 일반 텍스트만 클립보드에 넣습니다 — 그대로 두면 Windows에서
   네이버 에디터에 `<p>...</p>` 태그가 날것으로 붙여넣기됩니다. `src/clipboard_win.py`가
   `pywin32`로 직접 CF_HTML 포맷을 만들어 넣고, 다시 읽어서 검증합니다.

## 실행 방법

맥에는 Windows 빌드 환경이 없으므로 GitHub Actions(`windows-latest` 러너)로 검증합니다.
`spike_flet/` 아래 파일을 바꾸고 push하거나, Actions 탭에서
**spike-flet-playwright-windows** 워크플로우를 수동 실행(`workflow_dispatch`)하세요.

워크플로우가 하는 일:
1. `flet build windows`로 exe 빌드
2. 만들어진 exe를 실제로 실행 (창을 20초 띄웠다가 강제 종료)
3. 앱이 시작 시 두 검증을 돌리고 `results.txt`에 `PASS`/`FAIL`을 남김
4. `results.txt`에 `FAIL`이 하나라도 있으면 워크플로우 자체를 실패시킴

결과는 Actions 실행 로그의 "Run packaged exe and capture results" 스텝에서 바로 보이고,
빌드 산출물(exe 포함)은 Artifacts로도 올라갑니다.

## 결과가 나온 뒤

- **둘 다 PASS** → 본 전환 작업을 그대로 진행해도 됩니다. `clipboard_win.py`의 로직을
  `core/clipboard_utils.py`에 Windows 분기로 합치면 됩니다.
- **clipboard만 FAIL** → `_build_cf_html`의 오프셋 계산 버그일 가능성이 높습니다 —
  `results.txt`에 남는 raw CF_HTML 텍스트를 보고 헤더 숫자와 실제 바이트 위치를
  대조하세요.
- **playwright만 FAIL** → `channel="chrome"` 폴백까지 실패했다는 뜻이므로, 빌드 로그에서
  "channel=chrome failed" 라인 이후 어떤 예외가 났는지 확인하세요. GitHub 러너에
  Chrome이 없어졌거나, Flet 패키징이 Playwright 드라이버 파일을 정리(cleanup)
  설정에서 지워버렸을 가능성이 있습니다 — 후자라면 `pyproject.toml`의
  `[tool.flet.cleanup]`에서 해당 파일 패턴을 제외해야 합니다.

## 검증이 끝난 뒤

이 폴더와 워크플로우 파일은 본 전환에 필요 없어지면 통째로 삭제해도 됩니다 — 실제 앱
코드(`core/`, `ai_workers/`, `views/`)에는 아무 의존성도 걸려 있지 않습니다.
