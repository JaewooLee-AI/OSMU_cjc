"""The one content pipeline: source material -> 4-channel OSMU output.

OSMU_admin had two near-identical pipelines (news_scraper.run_newsjacking_pipeline
and manual_content_writer.run_manual_content_pipeline) that differed only in
where the seed text came from and whether a source-link footer was appended.
They're one function here, with `source_type` selecting those two differences.

Runs **synchronously inside Streamlit**, which is the main structural change
from the original architecture. The async Supabase queue + `worker_runner.py`
polling loop existed to route around Vercel's 10-second serverless timeout;
with the frontend and the engine in the same Python process there is no
timeout to route around, and a queue whose producer and consumer are the same
process is pure overhead. `progress` is a callback so the caller can drive a
`st.status` panel instead of the marketer staring at a spinner for 90 seconds.

Stage order, and why:
  1. caption photos      — cached/batched (ai_workers/vision.py)
  2. draft the body      — the only call that sees memo + article + captions
  3. compliance guardrail— rewrites, so it must run before density checks
  4. SEO rebalance       — verifies what stage 2 was merely *instructed* to do
  5. dictionary re-sweep — stages 3~4 are fresh LLM output; re-run the cheap
                           deterministic substitution over them
  6. image-tag backstops — nothing may silently drop an attached photo
  7. secondary channels  — Instagram / X / Shorts / Naver tags, best-effort
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from ai_workers import content_mode
from ai_workers.guardrail import (
    apply_blacklist_dictionary,
    apply_guardrail_if_enabled,
    check_certification_scope,
)
from ai_workers.instagram_caption_writer import write_instagram_caption
from ai_workers.multi_llm_router import generate_text, get_configured_vendor
from ai_workers.naver_hashtag_writer import write_naver_hashtags
from ai_workers.news_scraper import scrape_article
from ai_workers.photo_placement import (
    caption_attachments,
    ensure_all_photos_tagged,
    ensure_image_tags_preserved,
    strip_unresolvable_image_tags,
)
from ai_workers.prompt_builder import (
    SUBJECT_INSTRUCTION,
    build_blog_system_prompt,
    photo_context,
    photo_instruction,
)
from ai_workers import search_intent
from ai_workers.proofreader import proofread
from ai_workers.seo_optimizer import (
    check_keyword_density,
    rebalance_keywords,
    rewrite_title_for_keyword,
    select_target_keywords,
    title_candidates,
    title_keyword_coverage,
)
from ai_workers.shorts_writer import write_shorts_script
from ai_workers.sns_validator import validate_instagram, validate_tweets
from ai_workers.title_variety import (
    SIMILARITY_THRESHOLD,
    avoidance_instruction,
    closest_previous,
    rewrite_for_variety,
)
from ai_workers.x_thread_writer import write_x_thread
from core import repo

def _title_generation_instruction(seo_keywords: List[str], source_title: str = "") -> str:
    """Asks the LLM to draft the title alongside the body in the same call
    (see module docstring on why title+body aren't split across two calls).
    When SEO keywords are configured, the instruction front-loads keyword
    inclusion here — cheaper than fixing it after the fact — and
    `rewrite_title_for_keyword` below is the verify/correct backstop for
    when the model ignores it anyway."""
    keyword_line = ""
    if seo_keywords:
        keyword_line = (
            f" 다음 타깃 키워드 중 최소 1개를 제목에 자연스럽게 포함하세요: {', '.join(seo_keywords)}."
        )
    if source_title:
        # Newsjacking: the value is the brand's angle on the news, not the
        # news itself. Naver pools blog and news for duplicate detection, so
        # echoing the publisher's headline gets the post dropped in favour of
        # the original — and a reader searching that headline wants the
        # article, not a product post.
        keyword_line += (
            f"\n원본 기사 제목은 «{source_title}» 입니다. 이 제목을 그대로 쓰거나 살짝 바꿔 "
            "쓰지 마세요 — 네이버는 블로그와 뉴스를 같은 유사문서 판정 대상으로 보기 때문에 "
            "기사 제목을 따라 쓰면 원본 기사에 밀려 검색에서 제외됩니다. "
            "뉴스의 핵심 소재나 수치는 가져오되, 제목은 '우리 브랜드가 이 뉴스를 어떻게 "
            "해석했는가'가 드러나도록 새로 지으세요."
        )
    return (
        "\n\n[제목 자동 생성 안내] 담당자가 제목을 입력하지 않았습니다. 본문보다 먼저, 첫 줄에 "
        "정확히 `[TITLE: 생성한 제목]` 형식으로 이 포스트에 어울리는 제목을 **25자 이내로** 출력한 "
        "뒤, 줄바꿈하고 그 다음부터 본문을 이어서 작성하세요. 부제목이나 설명을 덧붙이지 말고 "
        f"제목 하나만 짧게 쓰세요.{keyword_line}"
    )

_TITLE_MARKER_RE = re.compile(r"^\s*\[TITLE:\s*(.+?)\]\s*\n+", re.IGNORECASE)

Progress = Optional[Callable[[str], None]]


def _extract_generated_title(draft: str):
    """Pulls a leading `[TITLE: ...]` marker off the draft, if present.
    Returns (title_or_None, remaining_draft)."""
    match = _TITLE_MARKER_RE.match(draft)
    if not match:
        return None, draft
    return match.group(1).strip(), draft[match.end():]


def _recommendation(report: Dict) -> Dict:
    """A deterministic verdict from fields the pipeline already computed —
    not another LLM call — so the marketer gets an instant, reproducible
    answer to "should I regenerate this?" instead of having to read every
    sub-section of the report and weigh it themselves."""
    reasons = []
    if report.get("compliance_pass") is False:
        reasons.append(f"컴플라이언스 미해결 이슈 {len(report.get('llm_issues') or [])}건")

    density = report.get("seo_density") or {}
    conflicts = report.get("seo_conflicts") or []
    # In '내용 우선' the density numbers are reported for information only —
    # the marketer chose not to enforce them, so being under the floor is the
    # requested outcome, not a defect to regenerate over.
    if density.get("enforced") is not False:
        # Missing keywords the guardrail stripped are excluded here: another
        # run can't satisfy them, so listing them as a reason to regenerate
        # would send the marketer into a loop.
        fixable_missing = [kw for kw in density.get("missing") or [] if kw not in conflicts]
        if fixable_missing:
            reasons.append(f"SEO 키워드 부족: {', '.join(fixable_missing)}")
        if density.get("overused"):
            reasons.append(f"SEO 키워드 과다: {', '.join(density['overused'])}")

    # No target at all is not a failure of this draft — it means the post's
    # subject has no matching keyword in the brand pool (see
    # select_target_keywords). Regenerating cannot fix that; adding a keyword
    # for that line of business can, so it routes to 'settings'.
    #
    # Not reported in '내용 우선': that mode never shows the model the pool,
    # so an empty target list is the mode working as asked, not a gap in the
    # keyword list.
    no_targets = (
        report.get("seo_targets") == []
        and bool(report.get("seo_pool"))
        and report.get("content_mode") != "rich"
    )

    if reasons:
        verdict = "regenerate"
    elif conflicts:
        verdict = "settings"
    elif no_targets:
        verdict = "settings"
    else:
        verdict = "ok"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "conflicts": conflicts,
        "no_targets": bool(no_targets),
    }


def _report(progress: Progress, message: str) -> None:
    print(f"[content_writer] {message}")
    if progress:
        progress(message)


def _quality_pass(
    draft: str,
    final_title: str,
    target_keywords: List[str],
    skipped_keywords: List[str],
    brand_kit: dict,
    vendor: str,
    storage_file_paths: List[str],
    is_news: bool,
    source_url: Optional[str],
    progress: Progress,
    mode: Optional[dict] = None,
):
    """Stages 3~6c: compliance, SEO density, and the deterministic backstops.

    Shared by the from-scratch pipeline and `revise_content`, because a
    revision is fresh LLM output making the same brand claims — it needs the
    identical audit, not a lighter one. Returns (final_content, report).
    """
    profile = mode or content_mode.resolve(None, brand_kit)
    # --- stage 2d: search-intent coverage ---
    # Read-only: reports what a searcher for the target keyword expects and
    # the draft doesn't answer. Deliberately does not write the answers —
    # see search_intent's module docstring.
    _report(progress, "검색 의도 충족 점검 중…")
    intent_report = search_intent.run(final_title, draft, target_keywords, vendor)

    # --- stage 3: compliance guardrail ---
    if brand_kit.get("guardrail_enabled", True):
        _report(progress, "환경성 표시·광고 컴플라이언스 검수 중…")
    report = apply_guardrail_if_enabled(draft, brand_kit, vendor)
    report["search_intent"] = intent_report
    report["final_text"] = ensure_image_tags_preserved(draft, report["final_text"])

    # --- stage 4: SEO keyword density ---
    _report(progress, "네이버 SEO 키워드 밀도 확인 중…")
    final_content, density_report = rebalance_keywords(
        final_title, report["final_text"], target_keywords, vendor,
        minimum=profile.get("density_min", 2), maximum=profile.get("density_max", 6),
        enforce=profile.get("enforce_density", True),
    )
    report["seo_density"] = density_report

    # --- stage 4b: guard against SEO rebalancing undoing the guardrail ---
    # rebalance_keywords optimizes purely for keyword counts; if a target SEO
    # keyword happens to be a phrase the guardrail just rewrote out (e.g. the
    # admin's keyword list still has a greenwashing-flagged term), the LLM can
    # reinsert it verbatim while chasing density. Only re-run the guardrail —
    # one more LLM call — when that regression is actually detected.
    flagged_phrases = list(report.get("issue_phrases", {}).values())
    regressed = [p for p in flagged_phrases if p and p.lower() in final_content.lower()]
    if regressed:
        _report(progress, "SEO 보정이 되살린 컴플라이언스 문구 재검수 중…")
        reguard = apply_guardrail_if_enabled(final_content, brand_kit, vendor)
        final_content = ensure_image_tags_preserved(final_content, reguard["final_text"])
        report["llm_issues"] = list(dict.fromkeys((report.get("llm_issues") or []) + reguard["llm_issues"]))
        report["issue_phrases"] = {**report.get("issue_phrases", {}), **reguard.get("issue_phrases", {})}
        report["seo_regression_fixed"] = regressed

    # --- stage 4c: spelling / spacing ---
    # Runs on every generation, not just on revisions: the marketer's typed
    # edits reach here through revise_content, and the guardrail and SEO
    # rewrites above are themselves fresh LLM output that can introduce
    # errors. Placed before the deterministic backstops so those still have
    # the last word on image tags and banned terms.
    _report(progress, "맞춤법·오탈자 교정 중…")
    final_content, applied_fixes, rejected_fixes = proofread(final_content, brand_kit, vendor)
    report["proofread"] = {"applied": applied_fixes, "rejected": rejected_fixes}

    # --- stages 5~6: deterministic backstops ---
    final_content = ensure_image_tags_preserved(report["final_text"], final_content)
    final_content, _ = apply_blacklist_dictionary(final_content, brand_kit.get("blacklist_map", {}))
    final_content = ensure_all_photos_tagged(final_content, storage_file_paths)
    final_content = strip_unresolvable_image_tags(final_content, storage_file_paths)

    if is_news and source_url:
        # Deterministic append, after every rewrite pass — a citation footer
        # shouldn't have to survive multiple LLM rewrites the way `[IMAGE:]`
        # tags do (and those have a backstop for exactly that).
        final_content = f"{final_content.rstrip()}\n\n[원문 기사 출처: {source_url}]"

    # --- stage 6b: resolve issues already fixed in the text that ships ---
    # `llm_issues` records what each guardrail pass found in *its own* input —
    # not what's still in the text after every later rewrite. A phrase whose
    # corrected_text already dropped it (or that stage 4b fixed) isn't a live
    # problem just because it was quoted earlier; checking against the text
    # that actually ships is what makes compliance_pass trustworthy.
    phrase_map = report.get("issue_phrases", {})
    still_open, resolved_issues = [], []
    for issue in report.get("llm_issues") or []:
        phrase = phrase_map.get(issue)
        if phrase and phrase.lower() not in final_content.lower():
            resolved_issues.append(issue)
        else:
            still_open.append(issue)
    # The certification-scope finding quotes a whole sentence, so any later
    # rewrite (SEO rebalance, proofread) changes the string and the check
    # above would call it resolved without the over-claim having gone. It is
    # deterministic and cheap, so re-run it on the text that actually ships
    # rather than trying to track the sentence through every pass.
    cert_issues = check_certification_scope(final_content, brand_kit)
    for finding in cert_issues:
        display = f"'{finding['phrase']}' — {finding['note']}"
        if display not in still_open:
            still_open.append(display)
        report.setdefault("issue_phrases", {})[display] = finding["phrase"]
    report["cert_scope_issues"] = [f["phrase"] for f in cert_issues]

    report["llm_issues"] = still_open
    report["resolved_issues"] = [i for i in resolved_issues if i not in still_open]
    report["compliance_pass"] = not still_open

    # --- stage 6c: re-measure density on the text that actually ships ---
    # Stage 4's density was measured on the rebalanced draft, before stage 4b's
    # re-audit and the deterministic passes above could strip words back out.
    report["seo_density"] = check_keyword_density(
        final_title, final_content, target_keywords,
        profile.get("density_min", 2), profile.get("density_max", 6),
    )
    if not profile.get("enforce_density", True):
        report["seo_density"]["enforced"] = False
    report["seo_targets"] = target_keywords
    report["seo_skipped"] = skipped_keywords
    report["seo_pool"] = list(brand_kit.get("seo_keywords") or [])
    report["content_mode"] = profile["key"]

    # A keyword the compliance guardrail is obliged to remove can never reach
    # its density target — regenerating just replays the same tug-of-war.
    stripped = {p.lower() for p in report.get("issue_phrases", {}).values() if p}
    stripped.update(p.lower() for p in report.get("seo_regression_fixed") or [])
    report["seo_conflicts"] = [
        kw for kw in report["seo_density"].get("missing") or []
        if any(kw.lower() in s or s in kw.lower() for s in stripped)
    ]

    report["recommendation"] = _recommendation(report)
    return final_content, report


def run_pipeline(campaign_id: str, progress: Progress = None) -> Dict:
    """Generates all four channels for a campaign and persists the result.

    Raises on a failure that leaves nothing usable; the campaign row is
    flipped to 'failed' with the error in `publish_error` first, so the
    dashboard shows what happened instead of a silently stuck row.
    """
    repo.update_campaign(campaign_id, status="processing", publish_error=None)
    try:
        vendor = get_configured_vendor()
        campaign = repo.get_campaign(campaign_id)
        if not campaign:
            raise RuntimeError(f"campaign {campaign_id} not found")

        brand_kit = repo.get_brand_kit()
        storage_file_paths = campaign.get("storage_file_paths") or []
        memo = (campaign.get("memo") or "").strip()
        given_title = (campaign.get("title") or "").strip()
        source_url = campaign.get("source_url")
        is_news = campaign.get("source_type") == "news"
        seo_keywords = brand_kit.get("seo_keywords") or []
        mode = content_mode.resolve(campaign.get("content_mode"), brand_kit)
        _report(progress, f"콘텐츠 모드: {mode['icon']} {mode['label']}")

        # --- stage 0: news article (news track only) ---
        article_text = ""
        source_title = (campaign.get("source_title") or "").strip()
        if is_news and source_url:
            _report(progress, "뉴스 기사를 읽는 중…")
            # Raises ArticleTooThin when the URL yields no usable body. That
            # propagates: run_pipeline's except clause writes it to
            # publish_error and flips the row to 'failed', which is the point
            # — a newsjacking post whose article never loaded used to finish
            # "successfully" as a generic brand post carrying a citation to
            # an article it had not read.
            article = scrape_article(source_url)
            article_text = article.body
            # Keyword-search results already carry the publisher's real title
            # from the RSS metadata; the scraped <title> for a Google News
            # link often lands on Google's redirect page instead.
            source_title = source_title or article.title
            # Cite (and remember) the outlet, not the aggregator. Persisting
            # it also keeps the news-search dedup working on the resolved URL.
            if article.url and article.url != source_url:
                repo.update_campaign(campaign_id, source_url=article.url)
                source_url = article.url
            # The headline is context for the writer, never the post's title.
            # Reusing it makes the post a 유사문서 in Naver's eyes (blog and
            # news share one duplicate-detection space), so it loses to the
            # original article — and it also skipped every title stage below,
            # since a pre-filled title means `needs_title` is False.

        # --- stage 1: photo captions (cached + batched) ---
        _report(progress, f"사진 {len(storage_file_paths)}장 분석 중…" if storage_file_paths else "첨부 사진 없음")
        captions = caption_attachments(storage_file_paths)

        # --- stage 2: the draft ---
        _report(progress, "블로그 본문 초안 작성 중…")
        needs_title = not given_title
        # Read from title_history, not from campaigns: the marketer prunes
        # campaigns down to a handful, and titles of deleted posts still need
        # to be avoided (core/db.py explains why they're stored separately).
        title_history = repo.recent_titles() if needs_title else []
        seed_blocks = []
        if is_news and article_text:
            seed_blocks.append(f"[뉴스 원문]\n{article_text[:3000]}")
            if memo:
                seed_blocks.append(f"[담당자 메모 — 이 뉴스와 엮고 싶은 자사 맥락]\n{memo}")
            seed_blocks.append(
                "위 뉴스를 우리 브랜드의 관점에서 재해석한 네이버 블로그 포스트 본문을 작성하세요. "
                "뉴스를 그대로 요약하지 말고, 독자가 우리 제품/활동과 연결지어 읽을 수 있게 쓰되, "
                "기사의 구체적인 내용(무엇이 왜 화제인지)이 글에 분명히 남아 있어야 합니다. "
                + SUBJECT_INSTRUCTION
            )
        else:
            seed_blocks.append(f"[담당자가 작성한 메모 — 이 글의 소재]\n{memo}")
            seed_blocks.append(
                "위 메모를 자연스럽게 확장한 네이버 블로그 포스트 본문을 작성하세요. "
                + SUBJECT_INSTRUCTION
            )

        prompt = "\n\n".join(
            seed_blocks
            + [
                f"[첨부 사진 및 설명 — 아래 목록의 사진만 사용 가능. 총 {len(captions)}장]\n"
                + photo_context(captions),
                photo_instruction(captions),
            ]
            + (
                [
                    _title_generation_instruction(
                        title_candidates(seo_keywords, brand_kit.get("keyword_weights")),
                        source_title,
                    )
                    + avoidance_instruction(title_history)
                ]
                if needs_title
                else [f"[제목]\n{given_title}"]
            )
        )

        draft = generate_text(
            vendor=vendor,
            prompt=prompt,
            system=build_blog_system_prompt(brand_kit, mode),
            # '내용 우선' asks for a longer piece, so the ceiling has to move
            # with it — Korean runs ~2 characters per token.
            max_tokens=max(2500, int((mode.get("length_hint") or 0) / 2) + 1200),
            note=f"blog-draft:{mode['key']}",
        )

        generated_title = None
        if needs_title:
            generated_title, draft = _extract_generated_title(draft)
        final_title = given_title or (generated_title or "").strip() or "제목 미정"

        # --- stage 2a: pick this post's target keywords ---
        # Every later SEO stage measures against these, not the whole brand
        # pool — see select_target_keywords for why enforcing the full list
        # produced stuffed drafts.
        target_keywords = select_target_keywords(
            final_title, draft, seo_keywords, limit=mode["max_targets"],
            weights=brand_kit.get("keyword_weights"), min_mentions=mode["min_mentions"],
        )
        skipped_keywords = [kw for kw in seo_keywords if kw not in target_keywords]

        # --- stage 2b: title keyword verification ---
        # Only applies to AI-generated titles — a title the marketer typed
        # themselves is never rewritten out from under them (same rule
        # `rebalance_keywords` already follows for the body-density pass).
        title_missing_keywords: List[str] = []
        # Demoted keywords are targets for the body but never for the title —
        # see seo_optimizer.title_candidates. Without this the backstop puts
        # back exactly what the generation instruction was just stopped from
        # asking for.
        title_eligible = title_candidates(target_keywords, brand_kit.get("keyword_weights"))
        if needs_title and title_eligible and mode["rewrite_title"]:
            title_missing_keywords = title_keyword_coverage(final_title, title_eligible)
            if title_missing_keywords:
                _report(progress, "제목에 SEO 키워드 보강 중…")
                # History is passed so the candidate scorer can reject a
                # keyword-bearing title that repeats a past headline, instead
                # of leaving that entirely to the separate variety pass below.
                final_title = rewrite_title_for_keyword(
                    final_title, draft[:300], title_missing_keywords, vendor, title_history
                )

        # --- stage 2c: title variety against past titles ---
        # Runs after 2b because forcing a keyword in can itself push the title
        # back toward the shape of every other keyword-bearing title.
        title_variety = {"checked": bool(needs_title and title_history), "rewritten": False}
        if needs_title and title_history:
            # Brand name and target keywords are required to repeat, so they
            # are excluded from the comparison — see title_variety.py.
            ignore_terms = list(seo_keywords) + [brand_kit.get("brand_name") or ""]
            similar_to, score = closest_previous(final_title, title_history, ignore_terms)
            title_variety["score"] = round(score, 2)
            if similar_to and score >= SIMILARITY_THRESHOLD:
                _report(progress, "과거 제목과 유사해 제목을 다시 짓는 중…")
                candidate = rewrite_for_variety(
                    final_title, similar_to, title_missing_keywords or title_eligible[:1],
                    vendor, title_history,
                )
                # Keep the rewrite only if it still carries a target keyword —
                # variety must not cost the SEO coverage stage 2b just secured.
                # Measured against the title-eligible set, not every target: a
                # demoted keyword was never allowed in the title, so its
                # absence must not veto a rewrite.
                if not title_eligible or title_keyword_coverage(candidate, title_eligible) != title_eligible:
                    final_title = candidate
                    title_variety["rewritten"] = True
                    title_variety["similar_to"] = similar_to

        # --- stage 2d: the title gets the banned-term dictionary too ---
        # It never did. Every guardrail layer ran on the body only, so
        # "DDP 전시로 감상하는 더봄봄 한복 리사이클링의 미학" shipped with a
        # compliance-relevant term — 새활용(upcycling) mislabelled as
        # 리사이클링(recycling) — in the single most visible line of the post.
        # Deterministic substitution only: rewriting a title with an LLM here
        # would undo the keyword and variety work just done above.
        final_title, title_dict_hits = apply_blacklist_dictionary(
            final_title, brand_kit.get("blacklist_map", {})
        )

        final_content, report = _quality_pass(
            draft, final_title, target_keywords, skipped_keywords, brand_kit, vendor,
            storage_file_paths, is_news, source_url, progress, mode,
        )
        report["title_dictionary_hits"] = title_dict_hits
        report["title_seo"] = {
            "checked": bool(needs_title and seo_keywords),
            "fixed": bool(needs_title and title_missing_keywords),
        }
        report["title_variety"] = title_variety

        # --- stage 7: secondary channels ---
        caption_values = list(captions.values())
        seed_note = memo or (article_text[:800] if article_text else final_title)

        instagram = _safe(
            progress, "인스타그램 캡션 생성 중…",
            lambda: _guarded_instagram(seed_note, caption_values, brand_kit, vendor),
            {"caption": "", "hashtags": []},
        )
        x_result = _safe(
            progress, "X 스레드 생성 중…",
            lambda: _guarded_x(seed_note, caption_values, brand_kit, vendor),
            {"tweets": [], "hashtags": []},
        )
        shorts = _safe(
            progress, "쇼츠 구성안 생성 중…",
            lambda: write_shorts_script(seed_note, caption_values, brand_kit, vendor),
            {"title": "", "hook": "", "scenes": [], "hashtags": []},
        )
        naver_hashtags = _safe(
            progress, "네이버 발행 태그 생성 중…",
            lambda: write_naver_hashtags(final_title, final_content, brand_kit, vendor),
            [],
        )

        # --- stage 7b: platform format checks ---
        # The writers are only *told* about the 240-character tweet ceiling and
        # the 125-character Instagram fold. Verify it: an over-long tweet is
        # rejected by X outright, which is a harder failure than any SEO miss.
        _report(progress, "SNS 형식 검증 중…")
        x_result["tweets"], x_issues = validate_tweets(x_result["tweets"])
        instagram["caption"], instagram["hashtags"], ig_issues = validate_instagram(
            instagram["caption"], instagram["hashtags"]
        )
        report["sns_checks"] = {"x": x_issues, "instagram": ig_issues}

        repo.update_campaign(
            campaign_id,
            status="draft",
            title=final_title,
            source_title=source_title or None,
            content=final_content,
            guardrail_passed=report["compliance_pass"],
            guardrail_report=report,
            instagram_caption=instagram["caption"],
            instagram_hashtags=instagram["hashtags"],
            x_content=x_result["tweets"],
            x_hashtags=x_result["hashtags"],
            naver_hashtags=naver_hashtags,
            shorts_script=shorts,
        )
        # Outlives this campaign on purpose, so a future run still avoids this
        # title after the marketer prunes the campaign list (core/db.py).
        repo.record_title(final_title, campaign_id)
        _report(progress, "완료")
        return repo.get_campaign(campaign_id)

    except Exception as exc:
        repo.update_campaign(campaign_id, status="failed", publish_error=str(exc))
        raise


LENGTH_MODES = {
    "keep": {"label": "그대로", "ratio": None},
    "longer": {"label": "20% 길게", "ratio": 1.2},
    "shorter": {"label": "20% 짧게", "ratio": 0.8},
}

REVISION_SYSTEM_PROMPT = (
    "당신은 네이버 블로그 편집자입니다. 아래 본문을 담당자의 요청에 따라 고쳐 쓰세요. "
    "요청과 무관한 부분은 원문의 문장과 표현을 그대로 유지하고, 요청된 부분만 바꿉니다. "
    "새로운 사실이나 수치를 지어내지 마세요. "
    "`[IMAGE: 경로]` 형식의 태그는 사진이 삽입될 위치 마크업이므로 삭제·수정하지 말고, "
    "개수와 순서를 그대로 유지한 채 문맥에 맞는 자리에 남겨두세요. "
    "고쳐 쓴 본문 전체만 출력하고 다른 설명은 절대 덧붙이지 마세요."
)


def revise_content(
    campaign_id: str,
    instruction: str = "",
    length_mode: str = "keep",
    progress: Progress = None,
) -> Dict:
    """Rewrites the *current* body — including the marketer's manual edits —
    instead of regenerating from the memo the way `run_pipeline` does.

    `run_pipeline` always starts from the memo, so it throws away whatever the
    marketer typed into the editor. That makes it the wrong tool for "make
    this bit warmer" or "trim it a bit", which is most of the real editing
    loop. The revision output is fresh LLM text making brand claims, so it
    goes through the same `_quality_pass` audit rather than a lighter one.

    Instagram/X/쇼츠 are deliberately not regenerated: they are written from
    the memo and photo captions, not from this body, so re-running them would
    spend four LLM calls to produce the same text. Naver tags are refreshed
    because they are derived from the body.
    """
    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        raise RuntimeError(f"campaign {campaign_id} not found")

    base_content = (campaign.get("content") or "").strip()
    if not base_content:
        raise RuntimeError("수정할 본문이 없습니다. 먼저 초안을 생성하세요.")

    instruction = (instruction or "").strip()
    ratio = LENGTH_MODES.get(length_mode, LENGTH_MODES["keep"])["ratio"]

    repo.update_campaign(campaign_id, status="processing", publish_error=None)
    try:
        vendor = get_configured_vendor()
        brand_kit = repo.get_brand_kit()
        seo_keywords = brand_kit.get("seo_keywords") or []
        final_title = (campaign.get("title") or "").strip() or "제목 미정"
        storage_file_paths = campaign.get("storage_file_paths") or []

        requests = []
        if instruction:
            requests.append(f"[담당자 수정 요청]\n{instruction}")
        if ratio:
            # An explicit character target is far more reliable than "조금 더
            # 길게" — the model has no sense of the current length otherwise.
            target = int(len(base_content) * ratio)
            direction = "늘려" if ratio > 1 else "줄여"
            requests.append(
                f"[분량 조정]\n현재 본문은 약 {len(base_content)}자입니다. "
                f"내용을 {direction} 약 {target}자 내외로 다시 쓰세요. "
                + (
                    "새로운 사실을 지어내지 말고, 기존 내용의 묘사와 설명을 더 구체적으로 풀어 쓰세요."
                    if ratio > 1
                    else "핵심 메시지와 사진 태그는 유지하고 군더더기 표현을 덜어내세요."
                )
            )

        if requests:
            _report(progress, "수정 요청 반영 중…")
            revised = generate_text(
                vendor=vendor,
                prompt=f"[현재 본문]\n{base_content}\n\n" + "\n\n".join(requests),
                system=REVISION_SYSTEM_PROMPT,
                # Headroom for the longer case: Korean runs ~2 characters/token.
                max_tokens=max(2500, int(len(base_content) * (ratio or 1) / 2) + 800),
                note=f"revision:{length_mode}",
            )
            revised = ensure_image_tags_preserved(base_content, revised.strip() or base_content)
        else:
            # No instruction and no length change: the marketer just wants
            # their edits checked. _quality_pass still proofreads and re-audits,
            # so skipping the rewrite call costs nothing but tokens saved.
            revised = base_content

        # Re-select targets from the revised text: a length change can drop a
        # keyword the previous target set relied on.
        mode = content_mode.resolve(campaign.get("content_mode"), brand_kit)
        target_keywords = select_target_keywords(
            final_title, revised, seo_keywords, limit=mode["max_targets"],
            weights=brand_kit.get("keyword_weights"), min_mentions=mode["min_mentions"],
        )
        skipped_keywords = [kw for kw in seo_keywords if kw not in target_keywords]

        final_content, report = _quality_pass(
            revised, final_title, target_keywords, skipped_keywords, brand_kit, vendor,
            storage_file_paths, campaign.get("source_type") == "news",
            campaign.get("source_url"), progress, mode,
        )
        report["revision"] = {
            "instruction": instruction,
            "length_mode": length_mode,
            "before_chars": len(base_content),
            "after_chars": len(final_content),
        }

        naver_hashtags = _safe(
            progress, "네이버 발행 태그 갱신 중…",
            lambda: write_naver_hashtags(final_title, final_content, brand_kit, vendor),
            campaign.get("naver_hashtags") or [],
        )

        repo.update_campaign(
            campaign_id,
            status="draft",
            content=final_content,
            guardrail_passed=report["compliance_pass"],
            guardrail_report=report,
            naver_hashtags=naver_hashtags,
        )
        _report(progress, "완료")
        return repo.get_campaign(campaign_id)

    except Exception as exc:
        repo.update_campaign(campaign_id, status="failed", publish_error=str(exc))
        raise


def _safe(progress: Progress, message: str, fn: Callable, fallback):
    """Secondary channels are best-effort: the Naver draft is the primary
    deliverable and a caption failure must never discard it."""
    _report(progress, message)
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        print(f"[content_writer] {message} failed: {exc}")
        return fallback


def _guarded_instagram(note: str, caption_values: List[str], brand_kit: dict, vendor: str) -> dict:
    """The caption goes through the same compliance guardrail as the Naver
    body — it's separately generated text making its own claims about the
    brand, not a derivative of the audited body, so skipping it would leave a
    real compliance gap."""
    result = write_instagram_caption(note, caption_values, brand_kit, vendor)
    guarded = apply_guardrail_if_enabled(result["caption"], brand_kit, vendor)
    result["caption"] = guarded["final_text"]
    return result


_TWEET_DELIMITER = "\n<<<TWEET>>>\n"


def _guarded_x(note: str, caption_values: List[str], brand_kit: dict, vendor: str) -> dict:
    """Same reasoning as the Instagram block: X gets its own generated text
    making brand claims, so it gets the same audit.

    The whole thread is audited in **one** call rather than one per tweet.
    The audit system prompt is ~500 tokens, so a 5-tweet thread was paying
    2,500 tokens of instructions to review maybe 300 tokens of content — and
    a tweet reviewed in isolation is also worse-informed than one reviewed
    alongside the rest of its thread. If the model doesn't return the
    delimiter structure intact, fall back to the deterministic dictionary
    pass: the hard guarantee (no banned term survives) is preserved either
    way, and a mangled thread is worse than an unaudited-by-LLM one.
    """
    result = write_x_thread(note, caption_values, brand_kit, vendor)
    tweets = result["tweets"]
    if not tweets or not brand_kit.get("guardrail_enabled", True):
        return result

    joined = _TWEET_DELIMITER.join(tweets)
    guarded = apply_guardrail_if_enabled(joined, brand_kit, vendor)["final_text"]
    parts = [p.strip() for p in guarded.split(_TWEET_DELIMITER.strip())]
    parts = [p for p in parts if p]

    if len(parts) == len(tweets):
        result["tweets"] = parts
    else:
        print(
            f"[content_writer] X guardrail returned {len(parts)} segments for {len(tweets)} "
            "tweets — keeping originals with dictionary substitution only."
        )
        result["tweets"] = [
            apply_blacklist_dictionary(t, brand_kit.get("blacklist_map", {}))[0] for t in tweets
        ]
    return result
