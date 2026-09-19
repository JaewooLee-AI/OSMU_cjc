"""씨제이씨협동조합 / 키노피스 Brand Kit — seeded from ../cjc_blog_v2/.

Everything here is lifted from the cooperative's own documents rather than
invented, so the generated drafts cite facts the cooperative can actually
stand behind:

- ../cjc_blog_v2/config.json
  (persona_guide.system_persona, few_shot_samples, fact_database.company_facts,
  compliance.whitelist_seo/blacklist_map, naver_settings.naver_blog_id)
- ../cjc_blog_v2/AI 블로그 자동화 시스템 기획.md
  (2014 founding, certifications, ATUM specs, KOTITI thresholds, 7~10-day
  delivery, ESG process, market size)
- https://atumkorea.com/ (company/ · atum/ · kinopiece/ · certificate/ —
  설립 취지, ATUM 측정 방식·스펙, 키노피스 품목, 인증·특허 목록,
  주소·대표·연락처)
- ../cjc_blog_v2/README.md, AGENTS.md (domain context, compliance rules)

One deliberate alignment with OSMU_admin's Brand Kit: the compliance
guardrail there was written for 의료법/표시광고법, and CJC sells custom wigs
and scalp-care-adjacent services — so its real legal exposure is **medical
efficacy overstatement** (탈모 완치·치료 등) under 의료법 제56조 and
표시·광고의 공정화에 관한 법률. The blacklist and the auditor prompt
(ai_workers/guardrail.py) are built around that instead of the greenwashing
criteria used for the previous (upcycling) tenant.

`seed_if_empty()` runs once on first launch; after that the Brand Kit page is
the source of truth and this file is never re-applied, so admin edits are
never clobbered.
"""
from __future__ import annotations

from core import repo

# --- visual identity --------------------------------------------------------
# CJC 제안 팔레트 (네이비 신뢰 + 골드 포인트). assets/custom.css의 CSS 변수와 1:1 대응됩니다.
BRAND_COLORS = {
    "primary": "#1B3A5C",      # 딥 네이비 — 신뢰·전문성
    "primary_dark": "#122A44",
    "secondary": "#2F6B7A",    # 틸 — 청결·케어
    "accent": "#C9A227",       # 골드 — 포인트
    "mint": "#7FB5A8",         # 민트 — 보조
    "bg": "#F7F5F0",           # 웜 페이퍼
    "text": "#23262B",
    "text_muted": "#7A828E",
}

BRAND_NAME = "씨제이씨협동조합"
SUB_BRAND = "키노피스"
HOMEPAGE = "https://atumkorea.com/"
NAVER_BLOG_ID = "jwl1722"
INSTAGRAM_HANDLE = ""
INDUSTRY = "맞춤가발·항암가발 제조 (스마트팩토리) · 가발/두피 창업 교육서비스 (협동조합·사회적기업)"

PERSONA = (
    "60년 가발 산업의 혁신을 이끄는 씨제이씨협동조합의 수석 컨설턴트이자 비즈니스 교육 디렉터의 목소리로 이야기합니다. "
    "탈모·두피 고민 고객에게는 따뜻한 위로와 공감을 먼저 전하고, ATUM 3D 두상측정기의 정밀함과 친환경 공정, "
    "KOTITI 인증 키노피스의 안전성을 알기 쉽게 설명합니다. "
    "창업 희망자·소상공인·교육 수강생에게는 조합의 상생 철학과 디지털 대전환 비전을 논리적이고 자신감 있게 전하고, "
    "마케팅·국비학원·공장 연동 지원망을 확신시킵니다. "
    "과장된 홍보나 의학적 치료를 약속하는 표현은 철저히 배제하고, 부드러운 경어체(해요체/하십시오체 혼용)를 씁니다."
)

TONE_AND_MANNER = """- 부드러운 경어체(해요체/하십시오체 혼용)를 씁니다. 문장은 2~3줄 안에서 끊습니다.
- 고객의 고민에 공감하는 서론으로 시작하고, 해결책으로 ATUM·키노피스 팩트를 자연스럽게 연결합니다.
- 의학적 치료 효과(완치·치료·재생 등)를 약속하거나 암시하는 표현을 절대 쓰지 않습니다.
- 수치와 인증은 확인된 것만 씁니다. 24개 센서·10분 스캔·7~10일·KOTITI 수치 등 팩트 DB 범위를 벗어나지 않습니다.
- B2C 글은 따뜻하고 안심시키는 말투로, B2B·공지 글은 격식 있고 힘 있는 전문가 말투로 씁니다.
- 출처(원문 기사 링크)는 글末에 양식화해 표기합니다.
- 매 글 끝에 가까운 조합 가맹점 방문·창업 교육 문의·ATUM 체험으로 이어지는 부드러운 한 문장을 남깁니다."""

CORE_FACTS = [
    "2014년 사단법인 대한가발협회 소속 회원들이 공동 브랜드·공동 마케팅·공동구매 수익사업을 하자는 뜻을 모아 설립한 씨제이씨협동조합(CJC Cooperative)입니다.",
    "자주적·자립적·자치적인 협동조합으로 공동마케팅·시설공동사용·원자재공동구매·공동제작을 하며, 소상공인 지원·취약계층 일자리창출·사회서비스 제공으로 지역사회에 공헌합니다.",
    "고용노동부 사회적기업 인증, 벤처기업 확인, 기업부설연구소, 공장등록을 갖추고 우수협동조합 중소벤처기업부장관상을 받은 협동조합입니다.",
    "ATUM 3D 두상측정기는 24개 초정밀 측정핀과 3D 스테레오 카메라, 내부 레이저 마커(미간 중앙 위치 기준)를 탑재해 10분 이내에 두상과 탈모 형태를 정밀 스캔합니다.",
    "측정 전 4개 카메라로 헤어라인을 촬영하고, 시뮬레이션으로 가발 모양·핏을 미리 보여주며, 측정 데이터는 저장해 다음 주문에도 재사용합니다.",
    "스캔된 3D 데이터는 작업지시서로 자동 변환되어 클라우드 ERP·MES와 실시간 연동되고, 데이터 전송에 별도 비용이 들지 않습니다.",
    "석고·비닐 본뜨기와 플라스틱 패턴이 필요 없는 3D 데이터 기반 스마트팩토리 친환경(ESG) 공정으로 제조합니다.",
    "기존 1개월 이상 걸리던 맞춤가발 제작·배송 기간을 7일~10일 수준으로 단축했습니다.",
    "유통 브랜드 '키노피스(KINO PIECE)'는 패션가발·남자맞춤가발·부분가발·인모가발·항암가발·붙임머리·쪽가발·탑피스와 샴푸·영양앰플·스켈링제 등 탈모예방 케어용품을 판매합니다.",
    "키노피스 제품은 공인시험기관 KOTITI와 협력해 접착제 내 폼알데하이드(20mg/kg 이하)·톨루엔(1,000mg/kg 이하)을 엄격히 통제합니다.",
    "가발부착법·가발모심기방법 등 관련 특허(출원 포함)와 상표(텍스트·디자인·이미지) 등록으로 ATUM의 독창성을 보호하고 있습니다.",
    "가발 제작 기초부터 심화 과정·마케팅·경영컨설팅과 가발/두피 창업 교육을 운영하며, 공장 OEM 직연동으로 소상공인 창업을 지원합니다 (예: 총 280만 원 상당 가발 실무 교육 지원 '소상공인 상생프로젝트').",
    "조합 사무실은 서울시 서초구 강남대로 18길 16-8 K&M빌딩 2층이며, 대표 CEO 이현준, 대표전화 02-6396-3388, 이메일 cjc@cjccoop.com입니다.",
    "타깃 키워드는 맞춤가발·항암가발·남성가발·탈모가발·3D두상측정·ATUM·키노피스·가발창업·두피창업교육·가발공장OEM·스마트팩토리가발 등입니다.",
]

TERMINOLOGY = {
    "씨제이씨협동조합": "사단법인 대한가발협회 주축 설립 협동조합. 영문은 CJC Cooperative. 'CJC협동조합'으로 줄여 쓸 수 있습니다.",
    "키노피스": "조합의 유통 브랜드. 영문은 KINO PIECE. 띄어 쓰지 않고 '키노피스'로 씁니다.",
    "ATUM 3D 두상측정기": "24개 초정밀 센서·3D 스테레오 카메라·레이저 마커 탑재, 10분 이내 정밀 스캔 장비. 'ATUM'은 대문자로 씁니다.",
    "KOTITI": "공인시험기관. 키노피스의 폼알데하이드·톨루엔 통제 안전 인증 주체로만 언급합니다.",
    "스마트팩토리": "3D 데이터 기반 제조·클라우드 ERP/MES 연동 생산 체계. '스마트공장'과 혼용하지 않습니다.",
    "스마트미러": "3D 스캔 데이터를 시뮬레이션해 작업지시서로 변환하는 과정의 명칭입니다.",
    "맞춤가발": "고객 두상에 맞춘 주문 제작 가발. 의학적 치료 수단이 아니므로 치료·완치 표현과 함께 쓰지 않습니다.",
    "항암가발": "항암 치료 과정의 고객을 위한 가발. 위로·보완의 관점에서만 서술합니다.",
    "두피케어": "두피 환경 관리·케어 의미로만 씁니다. '두피 치료'라고 쓰지 않습니다.",
    "가발창업": "가발 매장 창업 과정·지원을 뜻합니다.",
    "두피창업교육": "두피 관리 매장 창업 교육 과정. '두피창업 교육'으로 띄어 쓰지 않습니다.",
    "가발공장OEM": "조합 스마트팩토리와 연동한 공장 직연동 위탁생산. 'OEM'은 대문자로 씁니다.",
    "대한가발협회": "사단법인 대한가발협회. 조합 설립 주체로 언급할 때 정식 명칭을 씁니다.",
    "소상공인 상생프로젝트": "경기 불황 속 소상공인·예비 창업자 대상 교육 지원 사업 (예: 총 280만 원 상당 실무 교육 지원).",
}

SEO_KEYWORDS = [
    "가발",
    "탈모",
    "맞춤가발",
    "항암가발",
    "남성가발",
    "탈모가발",
    "두피케어",
    "3D두상측정",
    "ATUM",
    "키노피스",
    "가발창업",
    "두피창업교육",
    "가발공장OEM",
    "스마트팩토리가발",
]

# 의료법 제56조 + 표시·광고의 공정화에 관한 법률 기준의 결정론적 치환 사전.
# ../cjc_blog_v2/config.json compliance.blacklist_map 그대로 이식.
# 여기 등록된 표현은 LLM이 무엇을 쓰든 발행 전 100% 자동 치환됩니다.
# (긴 항목이 먼저 매칭되도록 하는 처리는 ai_workers/guardrail.py에 있습니다.)
BLACKLIST_MAP = {
    "완벽한 탈모 치료": "맞춤가발을 통한 스타일 보완",
    "탈모 치료": "맞춤가발 스타일 보완",
    "완벽 치료": "스타일 개선 및 보완",
    "완벽한 치료": "스타일 개선 및 보완",
    "치료 가능": "스타일 보완 가능",
    "완치 가능": "두피 보완 가능",
    "탈모 완치": "두피 환경 개선 및 스타일 보완",
    "모발 영구 재생": "건강한 두피 관리",
    "100% 치료": "스타일 개선",
    "병원 치료 대체": "전문 케어 및 스타일링",
    "의학적 효능": "스타일링 개선 및 만족도 극대화",
    "부작용 제로": "안전성 검증 완료",
}

FEW_SHOT_SAMPLES = [
    """[씨제이씨협동조합] 10분 만에 끝나는 혁신적인 ATUM 3D 맞춤 가발 스캔 체험기

안녕하세요! 씨제이씨협동조합입니다. 기존에 석고나 비닐로 본을 뜨며 한 달 넘게 기다리셨던 맞춤가발 제작, 많이 답답하셨죠? 이제는 24개 초정밀 센서와 3D 스테레오 카메라가 탑재된 ATUM 3D 두상측정기로 단 10분 만에 정밀 스캔이 완료됩니다. KOTITI 시험인증을 거친 안전한 키노피스(KINO PIECE) 친환경 가발을 7~10일 만에 빠르게 만나보세요.""",
    """[소상공인 상생] 가발 창업 및 두피 전문 교육 5기 수강생 모집 안내

안녕하세요, 씨제이씨협동조합 조합원과 예비 창업자 여러분! 60년 정체된 가발 산업을 디지털 대전환(AX)으로 이끄는 씨제이씨협동조합에서 스마트팩토리 기반 가발창업 및 두피창업교육 수강생을 모집합니다. 공장 OEM 직연동 서비스와 독자적인 기술력으로 소상공인분들의 성공 창업을 든든하게 조력합니다.""",
]


def seed_if_empty() -> bool:
    """Populates the Brand Kit on first launch only. Returns True if seeded."""
    existing = repo.get_brand_kit()
    if existing.get("brand_name") or existing.get("persona"):
        return False

    repo.save_brand_kit(
        brand_name=BRAND_NAME,
        sub_brand=SUB_BRAND,
        industry=INDUSTRY,
        homepage=HOMEPAGE,
        naver_blog_id=NAVER_BLOG_ID,
        instagram_handle=INSTAGRAM_HANDLE,
        persona=PERSONA,
        tone_and_manner=TONE_AND_MANNER,
        core_facts=CORE_FACTS,
        terminology=TERMINOLOGY,
        seo_keywords=SEO_KEYWORDS,
        blacklist_map=BLACKLIST_MAP,
        few_shot_samples=FEW_SHOT_SAMPLES,
        guardrail_enabled=True,
        vision_enabled=True,
        vision_quality="economy",
    )
    return True
