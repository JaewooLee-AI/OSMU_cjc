# CLAUDE.md — 씨제이씨협동조합 OSMU 워크벤치 개발 문서

이 저장소는 **씨제이씨협동조합(브랜드 '키노피스') 전용** 앱입니다. 다른 회사가 clone해서 자기 브랜드로
바꾸는 템플릿 용도(예전 "온보딩" 절차)는 더 이상 지원하지 않습니다. 같은 엔진을 쓰는 다른 저장소와
구조를 맞출 필요도 없으므로, 필요하면 DB 스키마·아키텍처도 바꿉니다 — 단 아래 규칙을 지킵니다.

작업 계획: `docs/작업계획_멀티브랜드킷.md`(진행 규칙·멀티 브랜드 킷), `docs/작업계획_기능보완_v2.md`
(대시보드·캘린더·비용 환산·원고 서식 — 가능/조건부/불가 판단과 "로컬 검증 필요" 목록), `docs/작업계획_데이터옮기기.md`
(📦 담당자 PC 사이 데이터 옮기기 — 표별 결정과 "로컬 검증 필요" 목록).

## 반드시 지킬 것

1. **공개 저장소입니다.** API 키·고객 데이터·고객과 주고받은 메시지·실제 DB 파일은 어떤 파일에도 쓰거나
   커밋하지 않습니다. 회사 원본 문서(`company_info/`, `etc/`)와 `data/`는 `.gitignore`로 제외돼 있습니다.
2. **API 키는 파일에 하드코딩하지 않습니다.** LLM·네이버 API 키는 앱 ⚙️ 설정에서 사용자가 직접 입력하고,
   AES-256-GCM으로 암호화되어 DB에 저장됩니다(`core/crypto_utils.py`). 키를 대신 채우지 말고 화면에서 입력하도록 안내합니다.
3. **`git commit`·`push`는 사용자가 요청할 때만 합니다.** 작업은 브랜치에서 합니다.
   **`main`에 push하면 고객용 GitHub Release가 자동 게시됩니다**(`.github/workflows/flet-windows-build.yml`).
   브랜치 push는 exe 빌드(Actions artifact)만 하고 Release는 만들지 않으므로, 확인용 exe는 브랜치 빌드에서 받습니다.
4. **실제 LLM 호출이나 Windows 전용 동작**(클립보드, 네이버 게시 자동화, 설치 프로그램 실행)이 필요한 검증은
   클라우드에서 하지 않고, 작업 계획의 "로컬 검증 필요" 목록에 남깁니다.
5. **사실을 지어내지 않습니다.** 브랜드 킷의 핵심 팩트·가격·인증 수치는 회사 자료나 사용자가 알려준 것만 씁니다.

## 실행

```bash
pip install -r requirements.txt
playwright install chromium   # 네이버 게시 자동화용 (선택)
python flet_app/main.py
```

`flet_app/main.py`가 저장소 루트를 `sys.path`에 넣어 `core/`·`ai_workers/`를 import합니다.
`.env`는 전부 선택 사항이고(`.env.example`), 앱은 `.env`가 없어도 정상 동작해야 합니다.

## 구조

| 폴더 | 내용 |
|---|---|
| `flet_app/` | 데스크톱 앱(유일한 UI). `main.py` 진입점, `views/` 7개 화면(📅 캘린더 포함), `simulators/` 4채널 미리보기, `components/`, `theme.py` |
| `core/` | `db.py` SQLite 스키마·마이그레이션, `repo.py` 데이터 접근 계층, `storage.py` 사진 저장, `crypto_utils.py` 키 암호화, `brand_seed.py` 첫 실행 시드, `transfer.py` 📦 데이터 옮기기 |
| `ai_workers/` | 생성 파이프라인(`content_writer.py`), LLM 라우팅(`multi_llm_router.py`), 사진 분석(`vision.py`), 컴플라이언스(`guardrail.py`), 원고 서식(`formatting.py`), 자동 작성 예약(`auto_scheduler.py`), SEO·키워드, 네이버 게시 자동화 |
| `tests/` | pytest(LLM 없이, 임시 데이터 폴더) · `live_gemini_check.py`(실제 Gemini 호출, 데이터 복사본으로 수동 실행) |
| `docs/` | 사용자 매뉴얼 pptx와 생성 스크립트, 작업 계획, 고객 테스트 문서 |

파이프라인 단계 순서와 설계 이유는 `README.md`에 있습니다.

## 데이터 폴더

`core/db.py`의 `_default_data_dir`이 정합니다 (`.env`의 `OSMU_DATA_DIR`이 있으면 그것이 우선).

1. 소스에서 실행(`python flet_app/main.py`)하고 저장소 루트(`PROJECT_ROOT`)에 `data/`가 이미 있으면 그 폴더
2. 그 밖에는 사용자별 폴더 — Windows `%APPDATA%\OSMU_CJC`, macOS `~/Library/Application Support/OSMU_CJC`,
   그 밖 `~/.local/share/OSMU_CJC`

안에는 `osmu.db`(SQLite), `assets/`(사진), `.master_key`(API 키 암호화 키), `naver_state.json`(네이버 로그인 세션),
`backups/`(📦 데이터 옮기기로 가져오기 직전의 DB 사본, 최근 5개)가 있습니다.
패키징된 exe(Flet이 `FLET_APP_STORAGE_DATA`를 넣어 줌)는 `PROJECT_ROOT/data`를 **절대 쓰지 않습니다** — 설치형의 `PROJECT_ROOT`는
`C:\Program Files\OSMU CJC\app`(쓰기 금지, 재설치 때 비워짐)입니다. 배포된 앱 사용자의 데이터는 `%APPDATA%\OSMU_CJC`에 있으며,
새 버전 설치·재설치·제거로 지워지면 안 됩니다. 앱이 설치 폴더에 파일을 쓰는 코드를 넣지 않습니다(로그·캐시·임시 파일은 데이터 폴더나 임시 폴더로).

DB 스키마를 바꿀 때는 `core/db.py`의 기존 방식(앱 시작 시 한 번 실행되는 마이그레이션 — 컬럼 추가는 `_ADDED_COLUMNS`,
테이블을 다시 만들어야 하면 `_migrate_single_brand_kit`처럼 한 트랜잭션으로)을 따르고,
**여러 번 실행돼도 안전하게**(이미 적용된 변경은 건너뛰게) 만듭니다. 기존 사용자 데이터가 보존되는지
실제 데이터 복사본으로 확인하는 일은 "로컬 검증 필요"에 남깁니다.

## 브랜드 킷

브랜드 킷은 사업 분야별로 **여러 개**이고, 글마다 어느 킷으로 쓸지 고릅니다. 값이 세 테이블에 나뉩니다 (`core/db.py`):

| 테이블 | 값 | 행 |
|---|---|---|
| `brand_kit` | 이름·업종·페르소나·톤앤매너·핵심 팩트·샘플·용어집·SEO 키워드·전환 가중치·검색 타깃 제외·기본 콘텐츠 모드 | 킷마다 한 줄 |
| `company_profile` | 기업명·브랜드명·홈페이지·블로그 ID·인스타·금기어 사전·가드레일 | 한 줄 (회사 공통) |
| `app_settings` | 기본 생성 모델·사진 분석 모델/품질/사용·생성 채널 | 한 줄 (앱 설정) |

- `repo.get_brand_kit(kit_id)`는 셋을 **합친 dict**를 돌려줍니다(`kit_id=None`이면 기본 킷 = 목록 맨 앞의 삭제되지 않은 킷).
  생성 파이프라인은 `repo.get_campaign_brand_kit(campaign)`으로 **글에 연결된 킷**을 씁니다. 킷 없이 `get_brand_kit()`을 부르는
  새 코드를 파이프라인에 넣지 않습니다 — 다른 분야 킷 내용이 섞이는 원인이 됩니다.
- `save_brand_kit(kit_id, **fields)`는 값마다 맞는 테이블로 나눠 저장합니다. 회사 공통·앱 설정만 고칠 때는
  `save_company_profile`·`save_app_settings`를 씁니다.
- 킷 삭제는 **보관**(`is_archived = 1`)입니다. 글에 `brand_kit_id`와 생성 당시 이름 `brand_kit_name`이 남으므로 행을 지우지 않습니다.
  삭제되지 않은 마지막 킷은 삭제할 수 없습니다(`repo.archive_brand_kit`).
- 키워드 화면 진행 상태는 킷마다 따로입니다: `app_state`의 `sweep:{킷 ID}`·`category_sweep:{킷 ID}` (`repo.kit_state_key`).
  키워드 측정 캐시(`keyword_cache`)와 제목 이력(`title_history`)은 킷끼리 공유합니다(같은 블로그·같은 유료 호출).

`core/brand_seed.py`의 값은 **DB가 비어 있을 때 첫 실행에서 한 번만** '기본' 킷과 회사 공통 값으로 들어갑니다(`seed_if_empty()`).
그 뒤로는 앱의 🧵 브랜드 킷 화면이 원본이며, 이 파일을 고쳐도 기존 설치에는 반영되지 않습니다.
이미 저장된 문구를 한 번만 고쳐야 할 때는 `SEED_FIXES`(`apply_seed_fixes()` — 모든 킷의 톤앤매너에 적용)를 씁니다.

## 원고 서식 · AI 비용 · 캘린더 (기능 보완 v2)

- **본문(`campaigns.content`)에 서식 기호를 남기지 않습니다.** 굵게·형광·소제목·인용구·구분선·요약 박스·사진 자리는
  `campaigns.content_format`(JSON, `ai_workers/formatting.py`)에 따로 둡니다. 검수·SEO·교정·글자 수·SNS 단계가 평문을
  전제로 돌기 때문입니다. 초안 호출에서 받은 서식 표시는 `formatting.extract`로 바로 떼고, 마지막에 `formatting.finalize`로
  최종 본문 기준으로 정리합니다. 본문을 새로 받는 경로(직접 편집 저장·수정 반영)도 `has_markup`이면 같은 방식으로 옮깁니다.
- 네이버에는 서식을 **붙여넣는 HTML에만** 담습니다(`formatting.naver_segments`). 에디터 툴바를 자동으로 누르는 코드를
  넣지 않습니다(작업계획_멀티브랜드킷.md 결정 3). [서식 적용]은 본문 글자를 바꾸지 않습니다 — 응답의 구절이 본문에
  그대로 없으면 버립니다.
- LLM 호출은 `multi_llm_router.generate_text`(또는 `vision`)를 거쳐 `repo.log_usage`로 기록되고, 금액은 **호출 시점**
  `model_prices` 단가로 `usage_log.cost_usd`에 저장됩니다. 단가가 없으면 null('단가 미등록') — 0으로 채우지 않습니다.
  가격 기본값을 코드에 넣지 않습니다(사실을 지어내지 않음). 글 하나에 묶이는 작업은 `@_attributed`(= `repo.usage_scope`)로
  감싸고, 그 안에서 스레드풀을 쓰면 `content_writer._submit`으로 넘깁니다(컨텍스트 전달).
- 📅 캘린더: `campaigns.scheduled_date`·`series_name`·`auto_generate_at`·`published_url`·`published_at`, 주제 목록 `topics`,
  반복 규칙 `schedule_rules`. 글을 지울 때는 `repo.delete_campaign`을 써야 주제 연결이 끊깁니다. 자동 작성은 앱이 켜져 있을
  때만(`auto_scheduler`) 돌고, 발행은 하지 않습니다.
- 시험: `python -m pytest tests` (LLM·실제 데이터 폴더를 쓰지 않음). 실제 호출 확인은
  `python tests/live_gemini_check.py <데이터 폴더> <빈 결과 폴더>` — 데이터를 복사본으로 옮겨 돌립니다.

## 📦 데이터 옮기기 (담당자 PC 사이)

`core/transfer.py` — ⚙️ 설정 → 📦 데이터 옮기기. 고른 항목(브랜드 킷·회사 공통·앱 설정·API 키·AI 비용 설정·키워드 측정값·
제목 이력)만 `.osmu` 파일(JSON, 형식 이름 `osmu-cjc-transfer`)로 내보내고 가져옵니다. 설계와 표별 결정은
`docs/작업계획_데이터옮기기.md`에 있습니다.

- **테이블을 새로 만들면 `transfer.TABLE_PARTS`에 옮길지(항목 이름) 말지(None) 넣습니다.** 넣지 않으면
  `tests/test_transfer.py`가 실패합니다. 브랜드 킷·회사 공통·앱 설정에 칸을 더하면 `repo.BRAND_KIT_FIELDS`·
  `_COMPANY_COLUMNS`·`_APP_SETTINGS_COLUMNS`를 따라 자동으로 옮겨집니다. 옮길 `app_state` 키는 `transfer.APP_STATE_PARTS`에 둡니다.
- 브랜드 킷은 **이름으로** 맞춥니다. 킷 ID는 PC마다 다르므로 파일에 넣지 않습니다(글·주제·반복 규칙이 받는 PC의 킷 ID를 들고 있음).
- API 키는 평문으로 파일에 쓰지 않습니다 — 비밀번호로 암호화하고, `.master_key`는 절대 옮기지 않습니다.
- 가져오기는 한 트랜잭션이고 직전에 데이터 폴더의 `backups/`에 DB를 복사합니다. 설치 폴더에는 쓰지 않습니다.

## 컴플라이언스 감사

`ai_workers/guardrail.py`의 `AUDIT_SYSTEM_PROMPT`는 의료법 제56조·표시광고법(치료·완치 약속 금지) 기준입니다.
검토 기준 문구는 고칠 수 있지만, **프롬프트 뒷부분의 출력 형식(`issues` 항목마다 `phrase`·`note`·`replacement`를
담는 JSON)은 `run_llm_audit`이 그대로 파싱하므로 바꾸지 않습니다.** 형식이 깨지면 감사가 '검수 미완료'로 처리됩니다.
법률 기준을 바꿀 때는 실제 서비스 전 법무 검토가 필요하다고 사용자에게 알립니다.

## 빌드 (Windows exe)

- `.github/workflows/flet-windows-build.yml`이 `stage/`에 `core/`·`ai_workers/`·`flet_app/`를 나란히 복사하고
  `flet build windows stage`로 빌드합니다(`flet build`는 앱 경로 안의 파일만 묶기 때문).
- 빌드 결과는 Inno Setup(`installer/osmu-cjc.iss`)으로 `OSMU-CJC-Setup-{버전}.exe`를 만들고, 그 setup.exe 하나를 zip으로 감싸
  Release에 올립니다(카카오톡 전달용). **`AppId` GUID는 절대 바꾸지 않습니다** — 바꾸면 재설치가 기존 설치를 덮지 못하고 두 번 설치됩니다.
  워크플로가 러너에서 설치·재설치·제거를 실제로 돌려 확인합니다(앱 창 실행은 러너에서 불가 — 로컬 검증).
- 앱·바로가기·설치 프로그램 아이콘은 `flet_app/assets/icon.png`(보라색 둥근 사각형에 씨제이씨 로고·'씨제이씨협동조합 OSMU' 글자, 모서리 밖은 투명, 512×512) 하나에서 만듭니다.
  `flet build`가 exe 아이콘으로 쓰고, 워크플로가 같은 파일로 설치 프로그램용 `.ico`를 만듭니다.
- flet은 `1.0.2`로 고정합니다. 올릴 때는 flet·flet-cli·flet-desktop이 모두 같은 버전으로 PyPI에 올라와 있는지 확인합니다.
- **`flet_app/pyproject.toml`의 `jni_flutter = "1.0.3"` 고정을 유지합니다.** 1.0.4 이상은 flet 1.0.2 템플릿(jni 1.0.0)과
  맞지 않아 Dart 컴파일이 "Constant evaluation error"로 깨집니다. flet을 jni 1.1을 쓰는 버전으로 올릴 때만 이 고정을 같이 풉니다.
  같은 이유로 `shared_preferences_android = "2.4.28"`도 고정합니다(2.5.0부터 jni ^1.1). 빌드가 다시 이 오류로 깨지면
  로그에서 오류가 난 패키지를 찾아, pub.dev에서 jni 1.1을 요구하기 직전 버전으로 같은 자리에 고정합니다.
