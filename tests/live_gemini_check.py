"""Gemini 실제 호출 시험 (수동 실행 — pytest가 모으지 않습니다).

실제 데이터 폴더의 **복사본**으로 돌립니다. 원본 data/는 읽기만 하고 바꾸지 않습니다.
LLM 키는 복사본 DB에 앱에서 입력해 둔 암호화된 키를 그대로 씁니다(키를 파일·화면에 출력하지 않음).

    python tests/live_gemini_check.py <원본 데이터 폴더> <결과를 쓸 빈 폴더>

확인하는 것:
1. 서식 '표준·정보형'으로 초안 생성 → 본문은 평문, 서식 레이어가 채워짐, 검수·SEO 리포트 정상
2. 비용: 이번 생성의 호출이 모두 이 글로 기록되고, 등록한 단가로 금액이 계산됨
3. 서식 '사용 안 함'으로 생성한 글에 [서식 적용] → 본문 글자는 그대로, 서식만 생김
4. [수정 반영] 뒤에도 서식이 (찾을 수 있는 만큼) 남음
5. 자동 작성 예약 실행기가 실제 파이프라인으로 초안을 만듦
6. 네이버 붙여넣기 HTML(에디터·기호 두 방식)을 파일로 남김 — 눈으로 확인용
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

SRC, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
WORK = OUT / "data"
if WORK.exists():
    raise SystemExit(f"{WORK}가 이미 있습니다 — 빈 폴더를 주세요.")
WORK.mkdir(parents=True)
for name in ("osmu.db", ".master_key"):
    shutil.copy2(SRC / name, WORK / name)
if (SRC / "assets").exists():
    shutil.copytree(SRC / "assets", WORK / "assets")
os.environ["OSMU_DATA_DIR"] = str(WORK)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai_workers import auto_scheduler, formatting  # noqa: E402
from ai_workers import content_writer as cw  # noqa: E402
from core import db, repo  # noqa: E402

assert Path(db.DATA_DIR) == WORK, "복사본이 아닌 데이터 폴더를 쓰려고 합니다"

results: dict = {}


def check(name: str, ok: bool, detail=None) -> None:
    results[name] = {"ok": bool(ok), "detail": detail}
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail is not None else ""), flush=True)


def plain_ok(text: str) -> bool:
    return not formatting.has_markup(text)


google = repo.get_llm_setting("google")
if not google:
    raise SystemExit("복사본 DB에 Google(Gemini) 키가 없습니다. 앱 ⚙️ 설정에서 먼저 등록하세요.")
model = google["model_name"]
repo.save_app_settings(default_generation_vendor="google", vision_vendor="google")
# 시험용 단가(복사본 DB에만 들어감). 금액 계산이 맞는지 보려는 값이지 실제 가격 안내가 아닙니다.
repo.save_model_price("google", model, 0.30, 2.50)
kit = repo.get_brand_kit()
repo.save_brand_kit(kit["id"], design_template="info", design_strength="standard")

# --- 1·2: 서식 포함 생성 + 비용 ---
c = repo.insert_campaign(source_type="manual", status="awaiting_media",
                         memo="맞춤가발 세척과 보관 방법. 미지근한 물, 전용 샴푸, 자연 건조, 거치대 보관. 월 1~2회 세척 권장.")
repo.update_campaign(c["id"], content_mode="balanced")
start_id = repo.last_usage_id()
t0 = time.time()
out = cw.run_pipeline(c["id"], progress=lambda m: print("  ·", m, flush=True))
sec = round(time.time() - t0)
fmt = out.get("content_format") or {}
rep = out.get("guardrail_report") or {}
check("생성 완료(초안)", out["status"] == "draft", f"{sec}초, 제목 '{out.get('title')}'")
check("본문은 평문(서식 기호 없음)", plain_ok(out.get("content") or ""))
kinds = sorted({i["type"] for i in fmt.get("items") or []})
check("서식 레이어 채워짐", len(fmt.get("items") or []) >= 3, {"items": len(fmt.get("items") or []), "kinds": kinds})
_blocks, unmatched = formatting.bind(out["content"], fmt)
check("서식이 최종 본문에 붙음(못 찾은 것 없음)", not unmatched, f"못 찾음 {len(unmatched)}")
check("검수 실행됨", rep.get("compliance_pass") is not None, {"score": rep.get("score"), "pass": rep.get("compliance_pass")})
rows = [r for r in repo.recent_usage(200) if r["id"] > start_id]
mine = [r for r in rows if r.get("campaign_id") == c["id"]]
check("이번 생성 호출이 모두 이 글로 기록", rows and len(mine) == len(rows), f"{len(mine)}/{len(rows)}")
cost = rep.get("cost") or {}
check("생성 비용 계산", cost.get("calls") == len(mine) and cost.get("cost_usd", 0) > 0 and cost.get("unpriced_calls") == 0,
      {"calls": cost.get("calls"), "usd": round(cost.get("cost_usd", 0), 6), "krw": round(cost.get("cost_krw", 0), 2)})
expected_usd = sum(((r["est_input_tokens"] - r["cached_input_tokens"]) * 0.30 + r["cached_input_tokens"] * 0.30
                    + r["est_output_tokens"] * 2.50) / 1e6 for r in mine)
check("금액 = 토큰 × 단가", abs(expected_usd - cost.get("cost_usd", 0)) < 1e-9, round(expected_usd, 6))
(OUT / "1_formatted_post.txt").write_text(
    f"{out.get('title')}\n\n{out.get('content')}\n\n--- content_format ---\n"
    + json.dumps(fmt, ensure_ascii=False, indent=1), encoding="utf-8")
for mode in ("editor", "symbol"):
    html = formatting.naver_full_html(out["content"], fmt, mode)
    (OUT / f"1_naver_paste_{mode}.html").write_text(f"<meta charset='utf-8'>{html}", encoding="utf-8")

# --- 3: 서식 없이 생성 → [서식 적용] ---
c2 = repo.insert_campaign(source_type="manual", status="awaiting_media",
                          memo="가발 처음 쓰는 분을 위한 착용 팁. 거울 앞에서 앞머리 위치 맞추기, 고정 테이프 사용.")
repo.update_campaign(c2["id"], design_strength="none")
out2 = cw.run_pipeline(c2["id"], progress=None)
check("'사용 안 함' 생성은 서식 없음", not (out2.get("content_format") or {}).get("items"))
before = out2["content"]
out2b = cw.apply_format(c2["id"], strength="standard")
fmt2 = out2b.get("content_format") or {}
check("[서식 적용] 뒤 본문 글자 그대로", out2b["content"] == before)
check("[서식 적용]으로 서식 생김", len(fmt2.get("items") or []) >= 2,
      sorted({i["type"] for i in fmt2.get("items") or []}))
fc = (out2b.get("guardrail_report") or {}).get("format_cost") or {}
check("[서식 적용] 비용 기록(1회)", fc.get("calls") == 1 and fc.get("cost_usd", 0) > 0, fc)
(OUT / "3_apply_format.txt").write_text(before + "\n\n--- format ---\n" + json.dumps(fmt2, ensure_ascii=False, indent=1),
                                        encoding="utf-8")

# --- 4: 수정 반영 뒤 서식 ---
n_before = len(fmt.get("items") or [])
out3 = cw.revise_content(c["id"], instruction="도입부를 한 문장 더 친근하게 바꿔 주세요.", length_mode="keep")
fmt3 = out3.get("content_format") or {}
check("수정 반영 뒤 본문 평문", plain_ok(out3["content"]))
check("수정 반영 뒤 서식 유지", len(fmt3.get("items") or []) >= max(1, n_before // 2), f"{n_before} → {len(fmt3.get('items') or [])}")
check("수정 비용 기록", ((out3.get("guardrail_report") or {}).get("cost") or {}).get("kind") == "revise")

# --- 5: 자동 작성 예약 ---
c4 = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="두피 건강을 위한 생활 습관 3가지. 충분한 수면, 미지근한 물 세정, 자외선 차단.")
repo.set_campaign_schedule(c4["id"], "2026-10-30", "두피 시리즈", "2026-10-01 09:00")
res = auto_scheduler.run_due()
got = repo.get_campaign(c4["id"])
check("자동 작성 예약 → 초안", res and res[0]["ok"] and got["status"] == "draft" and got["auto_generate_at"] is None,
      res[0] if res else None)
check("자동 작성 표시 남음", bool((got.get("guardrail_report") or {}).get("auto_generated")))

summary = {k: v["ok"] for k, v in results.items()}
(OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print("\nSUMMARY", json.dumps({"passed": sum(summary.values()), "total": len(summary)}, ensure_ascii=False))
print("결과 폴더:", OUT)
