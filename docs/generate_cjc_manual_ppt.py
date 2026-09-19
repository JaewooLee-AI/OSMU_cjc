# -*- coding: utf-8 -*-
"""씨제이씨협동조합 OSMU 워크벤치 — 관리자·사용자 매뉴얼 PPT 생성기.

대상: 조합 실무자·매장 담당자 (비개발자 포함).
범위: LLM/네이버 API 키 등록 → 씨앗 키워드·키워드 갱신 → 일상 사용법 → 주의사항·FAQ.
모든 수치는 코드에서 확인한 실제 값입니다 (모델명, 캐시 30일, 상한 기본값 등).

실행: python3 docs/generate_cjc_manual_ppt.py
출력: docs/CJC_OSMU_사용자_매뉴얼.pptx
"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# ---------- palette (core/brand_seed.py BRAND_COLORS — CJC 네이비·골드) ----------
PRIMARY      = RGBColor(0x1B, 0x3A, 0x5C)
PRIMARY_DARK = RGBColor(0x12, 0x2A, 0x44)
SECONDARY    = RGBColor(0x2F, 0x6B, 0x7A)
ACCENT       = RGBColor(0xC9, 0xA2, 0x27)
MINT         = RGBColor(0x7F, 0xB5, 0xA8)
BG           = RGBColor(0xF7, 0xF5, 0xF0)
TEXT         = RGBColor(0x23, 0x26, 0x2B)
TEXT_MUTED   = RGBColor(0x7A, 0x82, 0x8E)
WHITE        = RGBColor(0xFF, 0xFF, 0xFF)
CARD_GOLD    = RGBColor(0xF5, 0xED, 0xD7)
CARD_BLUE    = RGBColor(0xE4, 0xEC, 0xEF)
ROW_ALT      = RGBColor(0xEF, 0xEB, 0xE2)
WARN         = RGBColor(0xC0, 0x39, 0x2B)
GOOD         = RGBColor(0x2E, 0x8B, 0x57)
FREE_TAG     = RGBColor(0x2E, 0x8B, 0x57)
PAID_TAG     = RGBColor(0xC0, 0x39, 0x2B)

FONT = "맑은 고딕"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = prs.slide_width, prs.slide_height

PAGE = {"n": 0}


def next_page():
    PAGE["n"] += 1
    return PAGE["n"]


def set_bg(slide, color):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def add_rect(slide, x, y, w, h, color, line=False, round_=False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    if line:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def add_text(slide, x, y, w, h, text, size=18, color=TEXT, bold=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font=FONT,
             line_spacing=1.0, italic=False):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.alignment = align
        p.line_spacing = line_spacing
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.color.rgb = color
            r.font.bold = bold
            r.font.italic = italic
            r.font.name = font
    return tb


def add_bullets(slide, x, y, w, h, items, size=14, color=TEXT, font=FONT,
                space_after=8, line_spacing=1.15, muted=TEXT_MUTED):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    first = True
    for level, text, bold in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        prefix = "▪ " if level == 0 else "－ "
        p.text = ("     " if level == 1 else "") + prefix + text
        p.space_after = Pt(space_after)
        p.line_spacing = line_spacing
        for r in p.runs:
            r.font.size = Pt(size if level == 0 else size - 1)
            r.font.color.rgb = color if level == 0 else muted
            r.font.bold = bold
            r.font.name = font
    return tb


def header_bar(slide, kicker, title, accent=PRIMARY):
    add_rect(slide, 0, 0, SW, Inches(1.15), PRIMARY_DARK)
    add_rect(slide, 0, Inches(1.15), SW, Pt(3), accent)
    add_text(slide, Inches(0.55), Inches(0.12), Inches(9.5), Inches(0.32), kicker,
             size=12, color=accent, bold=True)
    add_text(slide, Inches(0.5), Inches(0.38), Inches(11.5), Inches(0.68), title,
             size=24, color=WHITE, bold=True)
    add_text(slide, Inches(0.5), SH - Inches(0.4), Inches(9), Inches(0.3),
             "씨제이씨협동조합 OSMU 워크벤치 · 관리자·사용자 매뉴얼", size=9, color=TEXT_MUTED)
    add_text(slide, SW - Inches(1.2), SH - Inches(0.4), Inches(0.8), Inches(0.3),
             f"{next_page():02d}", size=9, color=TEXT_MUTED, align=PP_ALIGN.RIGHT)


def new_slide(bg=BG):
    s = prs.slides.add_slide(BLANK)
    set_bg(s, bg)
    return s


def tag(slide, x, y, w, h, text, color):
    add_rect(slide, x, y, w, h, color, round_=True)
    add_text(slide, x, y, w, h, text, size=10.5, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def style_table(table, header_color=PRIMARY_DARK, col_widths=None, header_size=12.5, body_size=11.5):
    n_rows, n_cols = len(table.rows), len(table.columns)
    if col_widths:
        for i, w in enumerate(col_widths):
            table.columns[i].width = w
    for ci in range(n_cols):
        cell = table.cell(0, ci)
        cell.fill.solid()
        cell.fill.fore_color.rgb = header_color
        for p in cell.text_frame.paragraphs:
            p.alignment = PP_ALIGN.CENTER
            for r in p.runs:
                r.font.bold = True
                r.font.size = Pt(header_size)
                r.font.color.rgb = WHITE
                r.font.name = FONT
    for ri in range(1, n_rows):
        for ci in range(n_cols):
            cell = table.cell(ri, ci)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if ri % 2 == 1 else ROW_ALT
            for p in cell.text_frame.paragraphs:
                p.alignment = PP_ALIGN.LEFT
                for r in p.runs:
                    r.font.size = Pt(body_size)
                    r.font.color.rgb = TEXT
                    r.font.name = FONT
            cell.margin_left = Pt(8)
            cell.margin_right = Pt(8)
            cell.margin_top = Pt(4)
            cell.margin_bottom = Pt(4)


def section_divider(kicker, title, sub, color=PRIMARY):
    s = new_slide(color)
    next_page()
    add_rect(s, 0, 0, Inches(0.22), SH, ACCENT)
    add_text(s, Inches(0.9), Inches(2.7), Inches(11), Inches(0.5), kicker,
             size=16, color=ACCENT, bold=True)
    add_text(s, Inches(0.85), Inches(3.15), Inches(11.5), Inches(1.2), title,
             size=34, color=WHITE, bold=True)
    add_text(s, Inches(0.9), Inches(4.25), Inches(10.5), Inches(0.9), sub,
             size=15, color=RGBColor(0xF5, 0xED, 0xD7),
             line_spacing=1.3)
    return s


def step_box(slide, x, y, w, h, num, title, desc, color=PRIMARY, num_w=Inches(0.55),
             title_size=13.5, desc_size=11.5):
    add_rect(slide, x, y, num_w, h, color)
    add_text(slide, x, y, num_w, h, str(num), size=19, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    add_rect(slide, x + num_w, y, w - num_w, h, WHITE)
    add_text(slide, x + num_w + Inches(0.2), y + Inches(0.08), w - num_w - Inches(0.4), Inches(0.35),
             title, size=title_size, color=TEXT, bold=True)
    add_text(slide, x + num_w + Inches(0.2), y + Inches(0.42), w - num_w - Inches(0.4), h - Inches(0.5),
             desc, size=desc_size, color=TEXT_MUTED, line_spacing=1.2)


def warn_box(slide, y, title, desc, h=Inches(1.15)):
    add_rect(slide, Inches(0.55), y, Inches(12.2), h, WHITE)
    add_rect(slide, Inches(0.55), y, Inches(0.12), h, WARN)
    add_text(slide, Inches(0.9), y + Inches(0.1), Inches(11.6), Inches(0.4), title,
             size=13.5, color=TEXT, bold=True)
    add_text(slide, Inches(0.9), y + Inches(0.52), Inches(11.6), h - Inches(0.6), desc,
             size=11.5, color=TEXT_MUTED, line_spacing=1.25)


# ============================================================
# 1. 표지
# ============================================================
s = new_slide(PRIMARY_DARK)
add_rect(s, 0, 0, Inches(0.22), SH, ACCENT)
add_text(s, Inches(0.9), Inches(1.9), Inches(10), Inches(0.5),
         "CJC COOPERATIVE · KINOPIECE — ADMIN & USER MANUAL", size=14, color=ACCENT, bold=True)
add_text(s, Inches(0.85), Inches(2.4), Inches(11.5), Inches(1.7),
         "씨제이씨협동조합 OSMU 워크벤치\n관리자·사용자 매뉴얼", size=38, color=WHITE, bold=True, line_spacing=1.15)
add_text(s, Inches(0.9), Inches(4.15), Inches(10.5), Inches(0.9),
         "API 키 등록부터 씨앗 키워드·키워드 갱신, 일상 사용법과 주의사항까지",
         size=17, color=RGBColor(0xF5, 0xED, 0xD7))
add_rect(s, Inches(0.9), Inches(5.15), Inches(1.1), Pt(4), ACCENT)
add_text(s, Inches(0.9), Inches(5.5), Inches(10.5), Inches(0.9),
         "홈페이지 atumkorea.com · 네이버 블로그 jwl1722 · 대표 02-6396-3388",
         size=13, color=RGBColor(0xF5, 0xED, 0xD7))
add_text(s, Inches(0.9), Inches(6.6), Inches(9), Inches(0.5),
         "앱 실행: streamlit run app.py → http://localhost:8501",
         size=12, color=TEXT_MUTED)

# ============================================================
# 2. 목차
# ============================================================
s = new_slide()
header_bar(s, "CONTENTS", "목차")
parts = [
    ("준비", "① 초기 설정 — 키 3종 등록", "LLM 1개 + 네이버 API 2개. 한 번만 하면 됩니다", ACCENT),
    ("핵심", "② 씨앗 키워드와 키워드 갱신", "이 매뉴얼의 심장부: 씨앗→발굴→측정→판정→적용", PRIMARY),
    ("일상", "③ 매일 쓰는 법", "워크벤치·뉴스·브랜드 킷·네이버 게시", PRIMARY),
    ("안전", "④ 컴플라이언스·비용·주의사항", "의료법 검수, 과금 지점, 함정 모음, FAQ", SECONDARY),
]
y = Inches(1.4)
for tag_txt, title, desc, color in parts:
    add_rect(s, Inches(0.55), y, Inches(12.2), Inches(1.25), WHITE)
    add_rect(s, Inches(0.55), y, Inches(0.12), Inches(1.25), color)
    tag(s, Inches(0.85), y + Inches(0.4), Inches(1.1), Inches(0.44), tag_txt, color)
    add_text(s, Inches(2.2), y + Inches(0.12), Inches(9.6), Inches(0.4), title, size=16.5, color=TEXT, bold=True)
    add_text(s, Inches(2.2), y + Inches(0.6), Inches(9.6), Inches(0.5), desc, size=11.5, color=TEXT_MUTED)
    y += Inches(1.4)

# ============================================================
# 3. 시스템 개요
# ============================================================
s = new_slide()
header_bar(s, "개요", "이 시스템은 무엇을 하나요")
boxes = [
    ("① 한 번 쓰고 네 채널로", "담당자 메모 + 사진만 넣으면 네이버 블로그·인스타 캡션·X 스레드·쇼츠 자막을 AI가 한 번에 만듭니다.", PRIMARY),
    ("② 의료법 자동 검수", "맞춤가발 업종 기준(치료·완치 약속 금지)으로 금기어 자동 치환 + AI 법무 검토를 모든 초안에 적용합니다.", SECONDARY),
    ("③ 내 컴퓨터에만 저장", "클라우드 없이 로컬 SQLite에 저장됩니다. API 키는 AES-256-GCM 암호화, 데이터는 이 PC를 떠나지 않습니다.", MINT),
]
x = Inches(0.55)
for title, desc, color in boxes:
    add_rect(s, x, Inches(1.7), Inches(3.95), Inches(2.9), CARD_GOLD if color != MINT else CARD_BLUE)
    add_rect(s, x, Inches(1.7), Inches(3.95), Inches(0.08), color)
    add_text(s, x + Inches(0.25), Inches(2.0), Inches(3.45), Inches(0.55), title, size=15, color=TEXT, bold=True)
    add_text(s, x + Inches(0.25), Inches(2.6), Inches(3.5), Inches(1.9), desc, size=12.5, color=TEXT, line_spacing=1.3)
    x += Inches(4.2)
add_rect(s, Inches(0.55), Inches(4.9), Inches(12.2), Inches(1.7), WHITE)
add_text(s, Inches(0.85), Inches(5.05), Inches(11.6), Inches(0.4), "이미 채워져 있는 조합 데이터 (🧵 브랜드 킷 화면 기준)", size=13.5, color=TEXT, bold=True)
add_text(s, Inches(0.85), Inches(5.5), Inches(11.6), Inches(1.0),
         "핵심 팩트 14개(2014년 설립·ATUM 24개 센서·10분 스캔·7~10일 배송·KOTITI 수치 등) · "
         "SEO 키워드 14개 · 금기어 12쌍 · 우수 글 샘플 2개 · 네이비·골드 테마",
         size=12, color=TEXT, line_spacing=1.3)

# ============================================================
# 4. 전체 흐름
# ============================================================
s = new_slide()
header_bar(s, "개요", "전체 사용 흐름 — 1회 설정 + 반복 루틴")
rows = [
    ("구분", "할 일", "주기"),
    ("⚙️ 초기 설정 (1회)", "LLM 키 1개 + 네이버 API 키 2개 등록 · 기본 생성 모델 확인", "최초 1회 (약 30분)"),
    ("🔑 키워드 갱신", "[🔄 숫자만 새로 재기]로 만료 지표 갱신", "매월 1회 (5분)"),
    ("🔎 키워드 교체", "씨앗→발굴→측정→판정→적용 4단계로 SEO 키워드 교체", "분기 1회 (30분)"),
    ("✍️ 일상", "메모+사진 → 초안 생성 → 검수 → 네이버 게시", "수시"),
]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.55), Inches(1.55), Inches(12.2), Inches(3.6)).table
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        tbl.cell(r, c).text = val
style_table(tbl, col_widths=[Inches(3.0), Inches(6.4), Inches(2.8)])
add_rect(s, Inches(0.55), Inches(5.4), Inches(12.2), Inches(1.2), CARD_BLUE)
add_text(s, Inches(0.85), Inches(5.55), Inches(11.6), Inches(0.9),
         "키 없이도 글쓰기·게시는 전부 됩니다. 키가 필요한 것은 '어떤 키워드로 써야 검색에 잘 걸릴지'를 "
         "데이터로 판단하는 키워드 갱신뿐입니다.",
         size=12.5, color=SECONDARY, bold=True, line_spacing=1.3)

# ============================================================
# 5. LLM 벤더 등록
# ============================================================
s = new_slide()
header_bar(s, "① 초기 설정 · LLM", "LLM 벤더 등록 — 글쓰기 AI 연결하기")
add_text(s, Inches(0.55), Inches(1.35), Inches(12.2), Inches(0.4),
         "⚙️ 설정 → 🔑 LLM 벤더 탭. 카드 3종 중 쓰는 것 하나만 등록하면 됩니다.",
         size=13, color=TEXT_MUTED)
rows = [
    ("벤더", "기본 모델명", "특징"),
    ("✨ Google Gemini", "gemini-2.5-flash", "이미지 분석 기본 벤더 — 사진 토큰 단가가 가장 낮음"),
    ("🤖 OpenAI", "gpt-4o-mini", "범용, 안정적"),
    ("🧠 Anthropic", "claude-sonnet-4-5", "장문·톤앤매너 반영에 강함"),
]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.55), Inches(1.9), Inches(12.2), Inches(2.4)).table
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        tbl.cell(r, c).text = val
style_table(tbl, col_widths=[Inches(3.0), Inches(3.4), Inches(5.8)])
steps = [
    ("1", "모델명 확인", "기본값 그대로 두면 됩니다. 바꾸려면 카드의 모델명 칸을 고치세요."),
    ("2", "[연결 테스트 · 저장] 클릭", "실제로 모델을 한 번 호출해보고, 성공하면 그 자리에서 암호화 저장됩니다."),
    ("3", "기본 생성 모델 자동 지정", "테스트에 성공한 벤더가 바로 기본값이 됩니다. 별도 지정 버튼은 없습니다."),
]
y = Inches(4.55)
for num, t, d in steps:
    step_box(s, Inches(0.55), y, Inches(12.2), Inches(0.85), num, t, d)
    y += Inches(0.93)

# ============================================================
# 6. 저장 확인법
# ============================================================
s = new_slide()
header_bar(s, "① 초기 설정 · LLM", "저장됐는지 확인하는 법 — 꼭 읽어주세요")
add_rect(s, Inches(0.55), Inches(1.5), Inches(12.2), Inches(1.15), WHITE)
add_text(s, Inches(0.85), Inches(1.62), Inches(11.6), Inches(0.4),
         "정상 저장 시 카드에 이렇게 표시됩니다", size=13.5, color=GOOD, bold=True)
add_text(s, Inches(0.85), Inches(2.02), Inches(11.6), Inches(0.5),
         "✅ 등록됨 ****9999 · 2026-09-18 11:21 저장",
         size=14, color=TEXT, bold=True)
add_bullets(s, Inches(0.55), Inches(2.9), Inches(12.2), Inches(3.4), [
    (0, "비밀번호 입력칸은 보안상 저장 후에도 항상 비어 보입니다 — 비어 있는 게 정상입니다.", True),
    (0, "판정은 배지로 하세요: '✅ 등록됨 + 키 끝 4자리 + 저장 시각'이 보이면 저장된 것입니다.", False),
    (0, "같은 배지가 네이버 API HUB·검색광고 API 칸에도 뜹니다.", False),
    (0, "저장은 DB 라운드트립으로 검증済 — 배지가 보이면 다음날 와도 그대로 있습니다.", False),
    (0, "키를 바꾸려면 새 키를 입력하고 [연결 테스트 · 저장]을 다시 누르면 덮어씁니다.", False),
    (0, "[🗑️]는 키 삭제입니다. 기본 모델이던 벤더를 지우면 남은 벤더로 자동 승계됩니다.", False),
], size=12.5, space_after=9, line_spacing=1.25)

# ============================================================
# 7. NAVER API HUB 발급
# ============================================================
s = new_slide()
header_bar(s, "① 초기 설정 · 네이버 ①", "NAVER API HUB 발급 — 경쟁도 조사용 (유료)", accent=SECONDARY)
add_text(s, Inches(0.55), Inches(1.35), Inches(12.2), Inches(0.4),
         "용도: 특정 키워드로 이미 올라온 블로그 글이 몇 개인지 세는 '경쟁도 조사'에만 씁니다.",
         size=13, color=TEXT_MUTED)
steps3 = [
    "console.ncloud.com 로그인 (네이버 클라우드 플랫폼 계정 — 없으면 새로 가입)",
    "Menu > All Services > Application Services > NAVER API HUB > Subscription → 약관 동의 (종량제라 결제수단 등록 필요)",
    "Application > [Application 등록] — API 카테고리에서 검색(블로그·뉴스·카페)과 Data Lab을 모두 선택",
    "목록에서 [인증 정보] → X-NCP-APIGW-API-KEY-ID(Client ID), X-NCP-APIGW-API-KEY(Client Secret) 복사",
    "[한도 및 알림]에서 일·월 상한과 70%/90% 알림 설정 (권장) + 앱의 일일 호출 상한(기본 500회)도 방어선",
]
y = Inches(1.9)
for i, txt in enumerate(steps3, start=1):
    add_rect(s, Inches(0.55), y, Inches(0.5), Inches(0.5), SECONDARY, round_=True)
    add_text(s, Inches(0.55), y, Inches(0.5), Inches(0.5), str(i), size=16, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, Inches(1.25), y + Inches(0.02), Inches(11.5), Inches(0.45), txt, size=12, color=TEXT, line_spacing=1.15)
    y += Inches(0.6)
add_rect(s, Inches(0.55), Inches(5.15), Inches(12.2), Inches(0.75), CARD_BLUE)
add_text(s, Inches(0.85), Inches(5.27), Inches(11.6), Inches(0.5),
         "⚠️ developers.naver.com의 키는 여기서 동작하지 않습니다 (인증 헤더가 다른 별개 서비스). 반드시 위 절차로 새로 발급하세요.",
         size=11.5, color=WARN, bold=True, line_spacing=1.2)
add_text(s, Inches(0.55), Inches(6.05), Inches(12.2), Inches(0.6),
         "💡 \"요청한 API가 이 Application에서 활성화되어 있지 않습니다\" 오류 → 3번의 API 선택이 빠진 것. 콘솔에서 [Application 수정]으로 검색·Data Lab을 체크하세요.",
         size=11, color=TEXT_MUTED, line_spacing=1.2)

# ============================================================
# 8. 검색광고 API 발급
# ============================================================
s = new_slide()
header_bar(s, "① 초기 설정 · 네이버 ②", "검색광고 API 발급 — 검색량·연관키워드용 (무료)", accent=SECONDARY)
add_text(s, Inches(0.55), Inches(1.35), Inches(12.2), Inches(0.4),
         "용도: 정확한 월간 검색량 조회 + 연관키워드 대량 발굴. 완전 무료, 호출 상한과 무관합니다.",
         size=13, color=TEXT_MUTED)
steps4 = [
    "searchad.naver.com 회원가입 — 개인·개인사업자·법인 모두 가능, 광고 집행 불필요",
    "로그인 후 우측 상단 [광고시스템] 클릭 → manage.searchad.naver.com 진입 (메인 화면엔 '도구' 탭이 없음)",
    "상단 도구 > API 사용 관리",
    "[네이버 검색광고 API 서비스 신청] 클릭 — 심사 없이 약관 동의만으로 즉시 발급",
    "CUSTOMER_ID(7자리 숫자) · 액세스라이선스(01000000...) · 비밀키(AQAAAA...) 세 값 복사",
]
y = Inches(1.9)
for i, txt in enumerate(steps4, start=1):
    add_rect(s, Inches(0.55), y, Inches(0.5), Inches(0.5), SECONDARY, round_=True)
    add_text(s, Inches(0.55), y, Inches(0.5), Inches(0.5), str(i), size=16, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, Inches(1.25), y + Inches(0.02), Inches(11.5), Inches(0.45), txt, size=12, color=TEXT, line_spacing=1.15)
    y += Inches(0.6)
add_rect(s, Inches(0.55), Inches(5.15), Inches(12.2), Inches(0.75), CARD_BLUE)
add_text(s, Inches(0.85), Inches(5.27), Inches(11.6), Inches(0.5),
         "💡 계정 책임자(마스터) 계정으로 로그인해야 키가 보입니다. 키가 안 보이면 아직 서비스 신청 전(4번)인 경우가 많습니다.",
         size=11.5, color=SECONDARY, bold=True, line_spacing=1.2)
add_text(s, Inches(0.55), Inches(6.05), Inches(12.2), Inches(0.6),
         "앱 입력 위치: ⚙️ 설정 → 🔍 네이버 API 탭 하단 '검색광고 API (광고주센터)' → 세 칸 입력 후 [연결 테스트 · 저장]",
         size=11, color=TEXT_MUTED, line_spacing=1.2)

# ============================================================
# 9. 키 등록 후 확인
# ============================================================
s = new_slide()
header_bar(s, "① 초기 설정 · 확인", "두 키를 등록하면 열리는 것들", accent=SECONDARY)
add_bullets(s, Inches(0.55), Inches(1.5), Inches(6.0), Inches(4.5), [
    (0, "🔑 키워드 갱신 전체가 활성화됩니다.", True),
    (0, "키가 없을 때는 경고 한 줄만 보이고 [숫자 재기]·[1~4단계] 버튼이 잠겨 있습니다.", False),
    (0, "등록 후에는 버튼이 활성화되고, 오늘 호출·남은 호출·캐시 통계 카드가 표시됩니다.", False),
    (0, "[🪄 브랜드에서 추천]은 LLM 키가 있어야 동작합니다 (네이버 키와 별개).", False),
], size=12.5, space_after=10, line_spacing=1.25)
add_rect(s, Inches(6.85), Inches(1.5), Inches(5.9), Inches(4.5), WHITE)
add_text(s, Inches(7.1), Inches(1.65), Inches(5.4), Inches(0.4), "키 없이도 되는 것", size=14, color=GOOD, bold=True)
add_bullets(s, Inches(7.1), Inches(2.1), Inches(5.4), Inches(3.7), [
    (0, "초안 생성·4채널 카피·컴플라이언스 검수 (LLM 키만 있으면)", False),
    (0, "뉴스 큐레이션 — API 없이 직접 조회라 완전 무료", False),
    (0, "네이버 게시 — 로그인 세션 방식이라 API 키 불필요", False),
    (0, "브랜드 킷 편집 — 수동으로 키워드 입력 가능", False),
], size=12, space_after=10, line_spacing=1.25)

# ============================================================
# 10. 씨앗 키워드
# ============================================================
s = new_slide()
header_bar(s, "② 키워드 갱신 · 씨앗", "씨앗 키워드란 — 그물의 첫 한 땀")
add_bullets(s, Inches(0.55), Inches(1.5), Inches(12.2), Inches(2.4), [
    (0, "씨앗은 그 자체로 쓸 키워드가 아니라, 연관검색어를 최대한 많이 끌어오기 위한 '그물'입니다.", True),
    (0, "넓을수록 좋습니다. 누구나 아는 순수 카테고리 이름 한 단어, 2~5글자가 적당합니다.", False),
    (0, "우리 사업의 서로 다른 축에서 5개를 고르세요. 한 축에 몰면 그 축의 연관어만 나옵니다.", False),
], size=13, space_after=11, line_spacing=1.3)
colw = Inches(5.95)
add_rect(s, Inches(0.55), Inches(4.1), colw, Inches(2.5), WHITE)
add_text(s, Inches(0.8), Inches(4.25), colw - Inches(0.5), Inches(0.4), "좋은 씨앗 (예시)", size=14, color=GOOD, bold=True)
add_text(s, Inches(0.8), Inches(4.7), colw - Inches(0.5), Inches(1.9),
         "'가발' '탈모' '두피케어' '항암' '창업교육'\n수식어 없는 카테고리 이름 그대로",
         size=13, color=TEXT, line_spacing=1.4)
add_rect(s, Inches(6.85), Inches(4.1), colw, Inches(2.5), WHITE)
add_text(s, Inches(7.1), Inches(4.25), colw - Inches(0.5), Inches(0.4), "나쁜 씨앗 (예시)", size=14, color=WARN, bold=True)
add_text(s, Inches(7.1), Inches(4.7), colw - Inches(0.5), Inches(1.9),
         "'친환경 가발공정' 'ATUM 3D측정' '키노피스'\n수식어·브랜드명·전문용어 → 결과가 비어버림",
         size=13, color=TEXT, line_spacing=1.4)

# ============================================================
# 11. 추천 + 4단계 파이프라인
# ============================================================
s = new_slide()
header_bar(s, "② 키워드 갱신 · 실행", "[🪄 추천]과 4단계 파이프라인")
add_rect(s, Inches(0.55), Inches(1.5), Inches(12.2), Inches(1.15), CARD_GOLD)
add_text(s, Inches(0.85), Inches(1.62), Inches(11.6), Inches(0.4),
         "🪄 브랜드에서 추천 — 씨앗 5개를 AI가 대신 골라줍니다", size=13.5, color=TEXT, bold=True)
add_text(s, Inches(0.85), Inches(2.02), Inches(11.6), Inches(0.5),
         "LLM(기본 생성 모델)을 씁니다. 실패 메시지가 뜨면 그대로 읽으세요 — "
         "예: '기본 생성 모델이 지정되지 않았습니다' → LLM 탭에서 먼저 등록해야 합니다.",
         size=11.5, color=TEXT, line_spacing=1.25)
steps5 = [
    ("1. 후보 찾기", FREE_TAG, "검색광고 API", "연관검색어 대량 발굴 → 검색량 구간 필터 (무료)"),
    ("2. 경쟁도 조사", PAID_TAG, "API HUB", "후보마다 블로그 문서 수 측정 — 유일한 유료 단계"),
    ("3. 브랜드 판정", TEXT_MUTED, "LLM (API 없음)", "우리 브랜드에 맞는 것만 AI가 판정"),
    ("4. 적용", PAID_TAG, "API HUB", "승인 시 브랜드 킷 반영 + 최종 측정까지 완료"),
]
y = Inches(2.9)
for t, tagcolor, tagtxt, d in steps5:
    add_rect(s, Inches(0.55), y, Inches(12.2), Inches(0.95), WHITE)
    add_rect(s, Inches(0.55), y, Inches(0.12), Inches(0.95), SECONDARY)
    add_text(s, Inches(0.9), y + Inches(0.1), Inches(2.8), Inches(0.35), t, size=13, color=TEXT, bold=True)
    tag(s, Inches(3.9), y + Inches(0.26), Inches(2.1), Inches(0.42), tagtxt, tagcolor)
    add_text(s, Inches(6.3), y + Inches(0.14), Inches(6.1), Inches(0.65), d, size=11.5, color=TEXT_MUTED, line_spacing=1.2)
    y += Inches(1.03)

# ============================================================
# 12. 평소/분기 루틴 + 캐시
# ============================================================
s = new_slide()
header_bar(s, "② 키워드 갱신 · 유지", "평소 달 5분 · 분기 30분 · 캐시 30일")
colw = Inches(5.95)
add_rect(s, Inches(0.55), Inches(1.5), colw, Inches(3.2), WHITE)
add_text(s, Inches(0.8), Inches(1.65), colw - Inches(0.5), Inches(0.4), "매월 — [🔄 숫자만 새로 재기]", size=14, color=PRIMARY, bold=True)
add_text(s, Inches(0.8), Inches(2.1), colw - Inches(0.5), Inches(2.4),
         "키워드 목록은 그대로 두고 만료된 검색량·경쟁도만 다시 잽니다. "
         "살아 있는 값은 캐시에서 읽어 호출 0회 — 과금되는 것은 만료분뿐입니다.",
         size=12, color=TEXT, line_spacing=1.35)
add_rect(s, Inches(6.85), Inches(1.5), colw, Inches(3.2), WHITE)
add_text(s, Inches(7.1), Inches(1.65), colw - Inches(0.5), Inches(0.4), "분기 — 4단계 전체", size=14, color=PRIMARY, bold=True)
add_text(s, Inches(7.1), Inches(2.1), colw - Inches(0.5), Inches(2.4),
         "씨앗부터 다시 발굴해 키워드 목록 자체를 교체합니다. "
         "조사할 후보 수(기본 100개)가 곧 최대 유료 호출 수 — 넓힐수록 좋은 키워드를 찾을 확률이 오릅니다.",
         size=12, color=TEXT, line_spacing=1.35)
add_rect(s, Inches(0.55), Inches(4.95), Inches(12.2), Inches(1.75), CARD_GOLD)
add_text(s, Inches(0.85), Inches(5.1), Inches(11.6), Inches(0.4), "⚠️ 만료는 조용히 일어납니다", size=14, color=WARN, bold=True)
add_text(s, Inches(0.85), Inches(5.52), Inches(11.6), Inches(1.0),
         "에러도 멈춤도 없이 '전환 가중치'가 꺼지고 단순 등장 횟수로만 순위가 매겨집니다. "
         "브랜드 킷·설정 화면에 '경쟁도 측정 만료' 경고가 뜨면 [숫자만 새로 재기]를 눌러주세요.",
         size=12, color=TEXT, line_spacing=1.3)

# ============================================================
# 13. 워크벤치
# ============================================================
s = new_slide()
header_bar(s, "③ 매일 쓰는 법 · 워크벤치", "새 콘텐츠 만들기 — 5단계")
steps = [
    ("➕ 새 콘텐츠", "빈 초안이 만들어집니다. 빈 초안이 이미 있으면 새로 만들지 않고 재사용합니다."),
    ("담당자 메모 작성", "'초안의 씨앗'. 현장 일화·고객 반응을 자유롭게 — 예: '가발창업교육 5기 모집, ATUM 시연에 40대 관심 집중'."),
    ("공지·제품 정보 입력", "날짜·가격·주문 방법처럼 AI가 지어내면 안 되는 값은 별도 칸에. 예: 장소 '서초 본점', 문의 '02-6396-3388'."),
    ("사진 첨부 → 🪄 초안 생성", "네이버 본문·인스타 캡션·X 스레드·쇼츠 자막이 한 번에 생성됩니다. 같은 사진 재사용은 분석 토큰 0."),
    ("편집 → 시뮬레이터 확인", "4개 탭에서 직접 고치고, 우측에서 실제 레이아웃(인스타 125자 절단선·쇼츠 데드존 등)으로 검증."),
]
y = Inches(1.5)
for i, (t, d) in enumerate(steps, start=1):
    step_box(s, Inches(0.55), y, Inches(12.2), Inches(1.0), i, t, d)
    y += Inches(1.08)

# ============================================================
# 14. 뉴스 + 게시
# ============================================================
s = new_slide()
header_bar(s, "③ 매일 쓰는 법 · 뉴스와 게시", "뉴스 큐레이션 & 네이버 게시")
add_text(s, Inches(0.55), Inches(1.4), Inches(5.9), Inches(0.4), "📰 뉴스 큐레이션", size=15, color=PRIMARY, bold=True)
add_bullets(s, Inches(0.55), Inches(1.85), Inches(5.9), Inches(2.8), [
    (0, "브랜드 키워드로 관련 기사를 찾아 [워크벤치로 전달]합니다.", False),
    (0, "Google 뉴스 RSS + 네이버 뉴스 직접 조회 — API 키 없이 완전 무료입니다.", True),
    (0, "뉴스 기반 글은 본문 끝에 원문 링크가 자동으로 붙습니다.", False),
    (0, "추가 검색어 예시: '탈모 관리, 항암가발 지원, 소상공인 창업교육'.", False),
], size=12, space_after=9, line_spacing=1.25)
add_text(s, Inches(6.85), Inches(1.4), Inches(5.9), Inches(0.4), "🚀 네이버 게시 (반자동)", size=15, color=PRIMARY, bold=True)
add_bullets(s, Inches(6.85), Inches(1.85), Inches(5.9), Inches(2.8), [
    (0, "① [네이버 로그인]으로 세션 저장 → ② [지금 게시] → Chrome 자동 입력.", False),
    (0, "③ 마지막 [발행] 클릭은 항상 사람이 직접 — 봇 차단을 피하기 위한 설계입니다.", True),
    (0, "직접 붙여넣어 발행했다면 [✅ 수동으로 완료]로 목록을 정리하세요.", False),
    (0, "인스타/X/쇼츠는 자동 게시가 없어 [📄 콘텐츠 보기]에서 복사해 직접 올립니다.", False),
], size=12, space_after=9, line_spacing=1.25)
add_rect(s, Inches(0.55), Inches(5.0), Inches(12.2), Inches(1.5), CARD_GOLD)
add_text(s, Inches(0.85), Inches(5.2), Inches(11.6), Inches(0.4), "게시 대상 블로그", size=13.5, color=TEXT, bold=True)
add_text(s, Inches(0.85), Inches(5.6), Inches(11.6), Inches(0.75),
         "현재 blog.naver.com/jwl1722 로 연결됩니다. 바꾸려면 🧵 브랜드 킷의 '네이버 블로그 아이디'를 고치세요.",
         size=12, color=TEXT, line_spacing=1.25)

# ============================================================
# 15. 브랜드 킷
# ============================================================
s = new_slide()
header_bar(s, "③ 매일 쓰는 법 · 브랜드 킷", "🧵 브랜드 킷 — AI의 두뇌를 직접 관리")
rows = [
    ("섹션", "무엇을 하나"),
    ("🏢 기업·채널", "조합명·키노피스·업종·홈페이지·블로그 ID — 글의 톤과 게시 대상에 반영"),
    ("🛡️ 가드레일 토글", "끄면 검수 없이 발행. 끌 이유는 거의 없음"),
    ("🏭 핵심 팩트", "초안마다 2개 이상 자동 인용. 여기 없는 수치·인증은 AI가 지어내지 않음"),
    ("📖 용어집", "키노피스·ATUM 등 표기 통일 + 교정 보호"),
    ("🎚️ 기본 콘텐츠 모드", "따로 지정 안 한 글의 기본값 (검색 최적화 ↔ 내용 우선)"),
    ("🔍 SEO 키워드", "제목·본문 배치 대상 + 전환 가중치 + 검색 타깃 여부"),
    ("🚫 금기어 사전", "발행 전 100% 자동 치환되는 치료·완치 표현 목록"),
]
tbl = s.shapes.add_table(len(rows), 2, Inches(0.55), Inches(1.55), Inches(12.2), Inches(5.0)).table
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        tbl.cell(r, c).text = val
style_table(tbl, col_widths=[Inches(3.0), Inches(9.2)], body_size=11)

# ============================================================
# 16. 컴플라이언스
# ============================================================
s = new_slide()
header_bar(s, "④ 안전 · 컴플라이언스", "의료법 제56조 + 표시·광고법 — 치료 약속 금지")
add_text(s, Inches(0.55), Inches(1.35), Inches(12.2), Inches(0.5),
         "조합은 의료기관·의약품이 아닙니다. 가발은 '스타일 보완 수단'으로만 서술해야 합니다. 2단 방어:",
         size=13, color=TEXT_MUTED)
add_bullets(s, Inches(0.55), Inches(1.9), Inches(5.6), Inches(2.2), [
    (0, "1단 — 금기어 사전이 발행 전 100% 자동 치환합니다.", True),
    (0, "2단 — LLM 법무 검토관이 맥락 위반을 잡아 점수·지적·교정본을 냅니다.", False),
    (0, "인스타·X도 별개 텍스트라 같은 감사를 거칩니다.", False),
], size=12, space_after=9, line_spacing=1.25)
rows = [
    ("금기어", "자동 치환어"),
    ("탈모 완치", "두피 환경 개선 및 스타일 보완"),
    ("탈모 치료", "맞춤가발 스타일 보완"),
    ("모발 영구 재생", "건강한 두피 관리"),
    ("부작용 제로", "안전성 검증 완료"),
    ("병원 치료 대체", "전문 케어 및 스타일링"),
    ("+ 외 7쌍", "브랜드 킷 화면에서 전체 확인"),
]
tbl = s.shapes.add_table(len(rows), 2, Inches(6.5), Inches(1.9), Inches(6.2), Inches(4.3)).table
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        tbl.cell(r, c).text = val
style_table(tbl, col_widths=[Inches(2.9), Inches(3.3)], body_size=11)
add_text(s, Inches(0.55), Inches(4.5), Inches(5.6), Inches(1.6),
         "⚠️ 실제 서비스 전 법무 검토를 권장합니다.\n가드레일은 템플릿이지 법률 자문이 아닙니다.",
         size=12, color=WARN, bold=True, line_spacing=1.35)

# ============================================================
# 17. 비용 관리
# ============================================================
s = new_slide()
header_bar(s, "④ 안전 · 비용", "어디서 돈이 나가나 — 과금 지점 정리")
rows = [
    ("지점", "비용", "방어선"),
    ("LLM 초안·감사·추천", "선택한 벤더 요금제 종량", "필요한 호출만 — 실패는 재시도 전 확인"),
    ("경쟁도 조사 (API HUB)", "유료 종량 (유일한 네이버 과금점)", "앱 일일 상한 기본 500회 + NCP 콘솔 알림"),
    ("검색량·연관키워드 (검색광고)", "무료", "없음 — 몇 번을 눌러도 과금 0"),
    ("뉴스·게시·사진 재사용", "무료", "사진 캐시로 재분석 토큰 0"),
]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.55), Inches(1.55), Inches(12.2), Inches(3.4)).table
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        tbl.cell(r, c).text = val
style_table(tbl, col_widths=[Inches(4.2), Inches(3.4), Inches(4.6)])
add_rect(s, Inches(0.55), Inches(5.2), Inches(12.2), Inches(1.4), CARD_BLUE)
add_text(s, Inches(0.85), Inches(5.35), Inches(11.6), Inches(1.1),
         "⚙️ 설정 → 📈 사용량 탭에서 실제 usage(프로바이더 응답값) 기준으로 쓴 만큼만 확인됩니다. "
         "네이버 호출 수·남은 호출·캐시 현황은 🔍 네이버 API 탭의 통계 카드에서 봅니다.",
         size=12, color=SECONDARY, bold=True, line_spacing=1.3)

# ============================================================
# 18. 함정 모음
# ============================================================
s = new_slide()
header_bar(s, "④ 안전 · 주의사항", "함정 모음 — 먼저 알면 안 헷갈립니다")
warn_items = [
    ("비밀번호 칸이 비어 보여도 저장된 게 맞다", "보안상 키는 절대 다시 보여주지 않습니다. '✅ 등록됨 ****뒷4자리 · 저장 시각' 배지로 확인하세요."),
    ("키 없이 눌렀을 때 증상 3종", "'기본 생성 모델이 지정되지 않았습니다'(🪄 추천) · 키워드 갱신 버튼 잠김 · 경쟁도 만료 경고 — 모두 키 등록으로 해결."),
    ("만료는 조용히 일어난다", "에러 없이 전환 가중치만 꺼집니다. '경쟁도 측정 만료' 문구가 보이면 [숫자만 새로 재기]."),
    ("[발행]은 사람이 직접", "자동으로 발행까지 가지 않는 것은 고장이 아니라 네이버 차단 회피 설계입니다."),
    ("data/ 폴더를 함부로 지우지 말기", "DB·사진·마스터키가 전부 안에 있습니다. 브랜드 킷을 처음부터 다시 채울 때만 삭제 후 재시작하세요."),
]
y = Inches(1.55)
for t, d in warn_items:
    h = Inches(1.08)
    add_rect(s, Inches(0.55), y, Inches(12.2), h, WHITE)
    add_rect(s, Inches(0.55), y, Inches(0.12), h, WARN)
    add_text(s, Inches(0.9), y + Inches(0.08), Inches(11.6), Inches(0.38), t, size=13, color=TEXT, bold=True)
    add_text(s, Inches(0.9), y + Inches(0.48), Inches(11.6), Inches(0.55), d, size=11.5, color=TEXT_MUTED, line_spacing=1.25)
    y += h + Inches(0.1)

# ============================================================
# 19. FAQ
# ============================================================
s = new_slide()
header_bar(s, "④ 안전 · FAQ", "자주 묻는 질문")
faqs2 = [
    ("[🪄 브랜드에서 추천]이 실패해요", "'추천 실패: ...' 뒤의 메시지가 원인입니다. 대부분 LLM 미등록 → LLM 탭에서 키 등록 후 기본 모델 확인."),
    ("키를 저장했는데 칸이 비어 있어요", "정상입니다. 배지(✅ 등록됨 ****...)로 확인하세요. 바꾸려면 새 키 입력 후 다시 [연결 테스트 · 저장]."),
    ("키워드 갱신 아래가 안 보여요", "구버전 증상 — 최신 버전에서는 키가 없어도 기능 목록이 보이고 버튼만 잠깁니다. 새로고침 후 확인하세요."),
    ("경쟁도 만료 경고가 떠요", "[🔄 숫자만 새로 재기]를 누르세요. 캐시가 살아있는 값은 재과금되지 않습니다."),
    ("브랜드 킷을 고쳤는데 앱에 안 바껴요", "🧵 브랜드 킷 하단 [저장]을 눌렀는지 확인하세요. 저장은 즉시 모든 생성에 반영됩니다."),
]
y = Inches(1.55)
for q, a in faqs2:
    add_rect(s, Inches(0.55), y, Inches(12.2), Inches(1.08), WHITE)
    add_text(s, Inches(0.8), y + Inches(0.08), Inches(11.6), Inches(0.4), f"Q. {q}", size=12.5, color=PRIMARY_DARK, bold=True)
    add_text(s, Inches(0.8), y + Inches(0.5), Inches(11.6), Inches(0.5), f"A. {a}", size=11, color=TEXT, line_spacing=1.2)
    y += Inches(1.16)

# ============================================================
# 20. 마무리
# ============================================================
s = new_slide(PRIMARY_DARK)
next_page()
add_rect(s, 0, 0, Inches(0.22), SH, ACCENT)
add_text(s, Inches(0.9), Inches(2.4), Inches(11), Inches(0.5), "더 알아보기", size=16, color=ACCENT, bold=True)
add_text(s, Inches(0.85), Inches(2.85), Inches(11.5), Inches(1.1), "참고 문서", size=32, color=WHITE, bold=True)
add_bullets(s, Inches(0.9), Inches(4.0), Inches(11.2), Inches(2.4), [
    (0, "README.md — 아키텍처와 설계 이유", False),
    (0, "CLAUDE.md — 다른 회사용으로 바꿀 때의 절차", False),
    (0, "HANDOFF.md — 구축 보고 (앱 📋 구축 보고서 페이지에서도 열람)", False),
    (0, "문의: 씨제이씨협동조합 02-6396-3388 · cjc@cjccoop.com", False),
], size=15, color=RGBColor(0xF5, 0xED, 0xD7), space_after=14, muted=RGBColor(0xD8, 0xC6, 0xCE))

out_path = "/Users/jwlee/project/OSMU_cjc/docs/CJC_OSMU_사용자_매뉴얼.pptx"
prs.save(out_path)
print("Saved:", out_path, "| slides:", len(prs.slides._sldIdLst))
